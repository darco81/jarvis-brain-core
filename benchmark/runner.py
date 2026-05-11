"""Benchmark runner: compare baseline (Grep/Read/Glob) vs brain MCP.

Usage:
    python benchmark/runner.py --questions benchmark/questions.json \
        --output benchmark/results/run_$(date +%F).json \
        --mode both --limit 5   # smoke: first 5 questions only
    python benchmark/runner.py --mode both         # full 50

Each question is executed twice: baseline config and brain config.
Both use the user's Claude subscription (no API keys, no per-token cost).
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import time
from pathlib import Path
from typing import Any

from claude_agent_sdk import (
    AssistantMessage,
    ClaudeAgentOptions,
    ResultMessage,
    TextBlock,
    query,
)

# Paths to the local checkouts the baseline needs read access to. Override via
# env BRAIN_BENCHMARK_ROOT to point at your own repos.
BENCHMARK_ROOT = Path(os.environ.get("BRAIN_BENCHMARK_ROOT") or (Path.home() / "dev" / "example-group"))
REPO_ROOT = BENCHMARK_ROOT / "app-core"  # primary cwd (core repo)
# Fair baseline: give access to every sibling repo in the group so cross-repo
# questions are answerable. Without this, baseline fails cross-repo questions
# by default.
SIBLING_REPOS = [
    BENCHMARK_ROOT / "app-front-a",
    BENCHMARK_ROOT / "app-front-b",
    BENCHMARK_ROOT / "app-front-c",
    BENCHMARK_ROOT / "app-front-d",
]
BRAIN_URL = os.environ.get("BRAIN_URL") or "http://localhost:8000/mcp"
BRAIN_TOKEN = os.environ.get("BRAIN_DEV_TOKEN")
if not BRAIN_TOKEN:
    raise RuntimeError(
        "Set BRAIN_DEV_TOKEN env var before running the benchmark. "
        "Educational version does not ship a default token."
    )

# Conservative iteration cap - prevents runaway loops on hard questions.
# Baseline typically needs 5-12 iterations (Grep + multiple Reads).
# Brain typically needs 2-4 (one query + one explain).
MAX_TURNS = 15

SYSTEM_PROMPT = """You are a code analysis assistant. Answer the user's question concretely and briefly.
Focus on the specific facts asked. If you find the answer, state it and stop - do not add commentary.
Cite file paths or node identifiers when relevant. Do not write code. Do not explain your reasoning steps."""


def _build_baseline_options() -> ClaudeAgentOptions:
    """Claude Code with native Grep/Read/Glob on every repo in the group (fair cross-repo)."""
    return ClaudeAgentOptions(
        cwd=str(REPO_ROOT),
        add_dirs=[str(p) for p in SIBLING_REPOS if p.exists()],
        allowed_tools=["Bash", "Grep", "Read", "Glob"],
        system_prompt=SYSTEM_PROMPT,
        max_turns=MAX_TURNS,
        permission_mode="bypassPermissions",
    )


def _build_brain_options() -> ClaudeAgentOptions:
    """Claude Code with ONLY brain MCP tools (no file access)."""
    return ClaudeAgentOptions(
        cwd=str(REPO_ROOT),
        add_dirs=[str(p) for p in SIBLING_REPOS if p.exists()],
        mcp_servers={
            "brain": {
                "type": "http",
                "url": BRAIN_URL,
                "headers": {"Authorization": f"Bearer {BRAIN_TOKEN}"},
            },
        },
        allowed_tools=[
            "mcp__brain__brain_query",
            "mcp__brain__brain_graph",
            "mcp__brain__brain_path",
            "mcp__brain__brain_explain",
            "mcp__brain__brain_ffcss",
        ],
        system_prompt=SYSTEM_PROMPT,
        max_turns=MAX_TURNS,
        permission_mode="bypassPermissions",
    )


async def run_single(question: dict[str, Any], mode: str) -> dict[str, Any]:
    """Execute one question in one mode. Return telemetry."""
    prompt = question["prompt"]
    options = _build_baseline_options() if mode == "baseline" else _build_brain_options()

    start = time.perf_counter()
    final_text = ""
    tool_calls: list[dict[str, Any]] = []
    usage: dict[str, Any] = {}
    num_turns = 0
    result_msg: ResultMessage | None = None
    error: str | None = None

    try:
        async for msg in query(prompt=prompt, options=options):
            if isinstance(msg, AssistantMessage):
                num_turns += 1
                for block in msg.content:
                    if isinstance(block, TextBlock):
                        final_text += block.text
                    elif hasattr(block, "name") and hasattr(block, "input"):
                        tool_calls.append({
                            "name": getattr(block, "name", ""),
                            "input_preview": str(getattr(block, "input", {}))[:300],
                        })
            elif isinstance(msg, ResultMessage):
                result_msg = msg
                if hasattr(msg, "usage") and msg.usage:
                    usage = msg.usage if isinstance(msg.usage, dict) else msg.usage.__dict__
    except Exception as exc:  # noqa: BLE001
        error = f"{type(exc).__name__}: {exc}"

    elapsed = time.perf_counter() - start

    return {
        "mode": mode,
        "question_id": question["id"],
        "category": question["category"],
        "answer": final_text.strip()[:2000],
        "tool_calls_count": len(tool_calls),
        "tool_calls": tool_calls[:20],  # keep first 20 for inspection
        "usage": usage,
        "num_turns": num_turns,
        "elapsed_s": round(elapsed, 2),
        "error": error,
        "result_total_cost_usd": getattr(result_msg, "total_cost_usd", None) if result_msg else None,
    }


async def run_all(
    questions: list[dict[str, Any]],
    mode: str,
    limit: int | None = None,
) -> list[dict[str, Any]]:
    """Run all questions sequentially in one mode."""
    results: list[dict[str, Any]] = []
    qs = questions[:limit] if limit else questions
    for i, q in enumerate(qs, 1):
        print(f"  [{mode}] {i}/{len(qs)} {q['id']} ({q['category']}): ", end="", flush=True)
        r = await run_single(q, mode)
        results.append(r)
        marker = "✗" if r["error"] else "✓"
        print(f"{marker} {r['elapsed_s']}s, {r['tool_calls_count']} tools, turns={r['num_turns']}")
    return results


async def main() -> None:
    parser = argparse.ArgumentParser(description="Benchmark: baseline vs brain MCP")
    parser.add_argument("--questions", default="benchmark/questions.json")
    parser.add_argument("--output", default=None)
    parser.add_argument("--mode", choices=["baseline", "brain", "both"], default="both")
    parser.add_argument("--limit", type=int, default=None, help="Run only first N questions")
    parser.add_argument("--category", default=None, help="Filter by category")
    args = parser.parse_args()

    data = json.loads(Path(args.questions).read_text())
    questions = data["questions"]

    if args.category:
        questions = [q for q in questions if q["category"] == args.category]

    print(f"Loaded {len(questions)} questions")
    print(f"Mode: {args.mode}")
    print(f"Limit: {args.limit or 'all'}")
    print(f"Max turns per run: {MAX_TURNS}")
    print(f"Repo: {REPO_ROOT}")
    print("=" * 70)

    output_path = Path(args.output) if args.output else Path(
        f"benchmark/results/run_{time.strftime('%Y-%m-%d_%H%M%S')}.json"
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)

    all_results: dict[str, list[dict[str, Any]]] = {}

    if args.mode in ("baseline", "both"):
        print("\n=== BASELINE (Grep/Read/Glob) ===")
        all_results["baseline"] = await run_all(questions, "baseline", args.limit)

    if args.mode in ("brain", "both"):
        print("\n=== BRAIN MCP ===")
        all_results["brain"] = await run_all(questions, "brain", args.limit)

    summary = {
        "metadata": data.get("metadata", {}),
        "run_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "limit": args.limit,
        "category_filter": args.category,
        "max_turns": MAX_TURNS,
        "results": all_results,
    }

    output_path.write_text(json.dumps(summary, indent=2))
    print("\n=== RESULTS SAVED ===")
    print(f"  → {output_path}")

    # Quick summary
    if "baseline" in all_results and "brain" in all_results:
        print("\n=== QUICK SUMMARY ===")
        for mode in ("baseline", "brain"):
            rs = all_results[mode]
            total_time = sum(r["elapsed_s"] for r in rs)
            total_turns = sum(r["num_turns"] for r in rs)
            total_tools = sum(r["tool_calls_count"] for r in rs)
            errors = sum(1 for r in rs if r["error"])
            print(f"  {mode:10s}: {total_time:.1f}s total, "
                  f"{total_turns} turns, {total_tools} tool calls, {errors} errors")


if __name__ == "__main__":
    asyncio.run(main())
