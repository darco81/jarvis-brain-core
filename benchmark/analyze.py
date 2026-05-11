"""Analyze benchmark results - per-category aggregates + global stats.

Usage:
    python benchmark/analyze.py benchmark/results/full_run.json

Outputs JSON summary to stdout + saves stats.json next to input.
"""
from __future__ import annotations

import argparse
import json
import statistics
from pathlib import Path
from typing import Any


def _tokens_from_usage(usage: dict[str, Any]) -> dict[str, int]:
    """Extract input/output/cache tokens from SDK usage dict."""
    return {
        "input_tokens": int(usage.get("input_tokens", 0) or 0),
        "output_tokens": int(usage.get("output_tokens", 0) or 0),
        "cache_read_input_tokens": int(usage.get("cache_read_input_tokens", 0) or 0),
        "cache_creation_input_tokens": int(usage.get("cache_creation_input_tokens", 0) or 0),
    }


def _per_run_metrics(r: dict[str, Any]) -> dict[str, float]:
    """Flatten single run into measurable metrics.

    Terminology:
      - fresh_input: uncached input tokens (new tool outputs, user prompts).
        These DO count fully against Max plan rate limits.
      - output: model-generated tokens (thinking, answers).
        These DO count fully against rate limits.
      - cache_read: input tokens served from Anthropic prompt cache.
        Heavily discounted for rate-limit accounting (~10% weight).
      - total_tokens: fresh_input + output (the rate-limit-relevant sum).
    """
    tok = _tokens_from_usage(r.get("usage", {}) or {})
    fresh_input = tok["input_tokens"]
    output = tok["output_tokens"]
    # Rate-limit-relevant: fresh input + output, NOT including cache reads.
    rate_limit_tokens = fresh_input + output
    return {
        "elapsed_s": float(r.get("elapsed_s", 0) or 0),
        "num_turns": int(r.get("num_turns", 0) or 0),
        "tool_calls": int(r.get("tool_calls_count", 0) or 0),
        "input_tokens": fresh_input,
        "output_tokens": output,
        "cache_read": tok["cache_read_input_tokens"],
        "cache_create": tok["cache_creation_input_tokens"],
        "fresh_input": fresh_input,
        "total_tokens": rate_limit_tokens,  # this is the headline metric
        "cost_usd": float(r.get("result_total_cost_usd", 0) or 0),
        "has_error": 1.0 if r.get("error") else 0.0,
    }


def _agg(values: list[float]) -> dict[str, float]:
    """Min/max/mean/median/p95 for a list of floats."""
    if not values:
        return {"min": 0, "max": 0, "mean": 0, "median": 0, "p95": 0, "sum": 0, "count": 0}
    sv = sorted(values)
    p95_idx = max(0, int(len(sv) * 0.95) - 1)
    return {
        "min": round(min(values), 3),
        "max": round(max(values), 3),
        "mean": round(statistics.mean(values), 3),
        "median": round(statistics.median(values), 3),
        "p95": round(sv[p95_idx], 3),
        "sum": round(sum(values), 3),
        "count": len(values),
    }


def analyze(data: dict[str, Any]) -> dict[str, Any]:
    """Return structured stats for a completed run."""
    results = data.get("results", {})
    baseline = results.get("baseline", [])
    brain = results.get("brain", [])

    # Align by question_id - report only questions present in BOTH modes
    baseline_by_id = {r["question_id"]: r for r in baseline}
    brain_by_id = {r["question_id"]: r for r in brain}
    common_ids = sorted(set(baseline_by_id) & set(brain_by_id))

    # Per-question comparison
    per_q: list[dict[str, Any]] = []
    for qid in common_ids:
        b = _per_run_metrics(baseline_by_id[qid])
        n = _per_run_metrics(brain_by_id[qid])
        per_q.append({
            "question_id": qid,
            "category": baseline_by_id[qid].get("category", "?"),
            "baseline": b,
            "brain": n,
            "delta": {
                "elapsed_s": round(b["elapsed_s"] - n["elapsed_s"], 2),
                "input_tokens": b["input_tokens"] - n["input_tokens"],
                "output_tokens": b["output_tokens"] - n["output_tokens"],
                "total_tokens": b["total_tokens"] - n["total_tokens"],
                "tool_calls": b["tool_calls"] - n["tool_calls"],
                "turns": b["num_turns"] - n["num_turns"],
                "cost_usd": round(b["cost_usd"] - n["cost_usd"], 4),
            },
            "ratio": {
                "input_tokens": round(b["input_tokens"] / max(1, n["input_tokens"]), 2),
                "total_tokens": round(b["total_tokens"] / max(1, n["total_tokens"]), 2),
                "cost": round(b["cost_usd"] / max(0.0001, n["cost_usd"]), 2),
            },
            "baseline_answer": baseline_by_id[qid].get("answer", "")[:300],
            "brain_answer": brain_by_id[qid].get("answer", "")[:300],
        })

    def _aggregate_mode(runs: list[dict[str, Any]]) -> dict[str, Any]:
        metrics = [_per_run_metrics(r) for r in runs]
        return {
            "elapsed_s": _agg([m["elapsed_s"] for m in metrics]),
            "input_tokens": _agg([m["input_tokens"] for m in metrics]),
            "fresh_input": _agg([m["fresh_input"] for m in metrics]),
            "output_tokens": _agg([m["output_tokens"] for m in metrics]),
            "total_tokens": _agg([m["total_tokens"] for m in metrics]),
            "cache_read": _agg([m["cache_read"] for m in metrics]),
            "cache_create": _agg([m["cache_create"] for m in metrics]),
            "cost_usd": _agg([m["cost_usd"] for m in metrics]),
            "tool_calls": _agg([m["tool_calls"] for m in metrics]),
            "num_turns": _agg([m["num_turns"] for m in metrics]),
            "errors": int(sum(m["has_error"] for m in metrics)),
        }

    global_stats = {
        "baseline": _aggregate_mode(baseline),
        "brain": _aggregate_mode(brain),
    }

    # Category breakdown
    categories = sorted({q["category"] for q in per_q})
    by_category: dict[str, Any] = {}
    for cat in categories:
        cat_qs = [q for q in per_q if q["category"] == cat]
        by_category[cat] = {
            "count": len(cat_qs),
            "baseline_mean_tokens": round(
                statistics.mean([q["baseline"]["total_tokens"] for q in cat_qs]), 1
            ),
            "brain_mean_tokens": round(
                statistics.mean([q["brain"]["total_tokens"] for q in cat_qs]), 1
            ),
            "baseline_mean_time_s": round(
                statistics.mean([q["baseline"]["elapsed_s"] for q in cat_qs]), 2
            ),
            "brain_mean_time_s": round(
                statistics.mean([q["brain"]["elapsed_s"] for q in cat_qs]), 2
            ),
            "baseline_mean_cost": round(
                statistics.mean([q["baseline"]["cost_usd"] for q in cat_qs]), 4
            ),
            "brain_mean_cost": round(
                statistics.mean([q["brain"]["cost_usd"] for q in cat_qs]), 4
            ),
            "baseline_mean_tool_calls": round(
                statistics.mean([q["baseline"]["tool_calls"] for q in cat_qs]), 2
            ),
            "brain_mean_tool_calls": round(
                statistics.mean([q["brain"]["tool_calls"] for q in cat_qs]), 2
            ),
        }

    # Headline numbers - focus on rate-limit-relevant (fresh + output)
    b_total_tokens = global_stats["baseline"]["total_tokens"]["sum"]
    n_total_tokens = global_stats["brain"]["total_tokens"]["sum"]
    b_fresh = global_stats["baseline"]["fresh_input"]["sum"]
    n_fresh = global_stats["brain"]["fresh_input"]["sum"]
    b_output = global_stats["baseline"]["output_tokens"]["sum"]
    n_output = global_stats["brain"]["output_tokens"]["sum"]
    b_cache_read = global_stats["baseline"]["cache_read"]["sum"]
    n_cache_read = global_stats["brain"]["cache_read"]["sum"]
    b_total_cost = global_stats["baseline"]["cost_usd"]["sum"]
    n_total_cost = global_stats["brain"]["cost_usd"]["sum"]
    b_total_time = global_stats["baseline"]["elapsed_s"]["sum"]
    n_total_time = global_stats["brain"]["elapsed_s"]["sum"]

    headline = {
        "total_questions": len(common_ids),
        # Rate-limit-relevant tokens (fresh_input + output)
        "tokens_baseline_total": int(b_total_tokens),
        "tokens_brain_total": int(n_total_tokens),
        "tokens_savings_pct": round(
            (1 - n_total_tokens / max(1, b_total_tokens)) * 100, 1
        ) if b_total_tokens else 0,
        "tokens_ratio": round(b_total_tokens / max(1, n_total_tokens), 2),
        # Fresh input only (the big win)
        "fresh_baseline_total": int(b_fresh),
        "fresh_brain_total": int(n_fresh),
        "fresh_savings_pct": round(
            (1 - n_fresh / max(1, b_fresh)) * 100, 1
        ) if b_fresh else 0,
        "fresh_ratio": round(b_fresh / max(1, n_fresh), 2),
        # Output tokens
        "output_baseline_total": int(b_output),
        "output_brain_total": int(n_output),
        # Cache read (cheap, mostly ignored for rate limit)
        "cache_read_baseline_total": int(b_cache_read),
        "cache_read_brain_total": int(n_cache_read),
        "cost_baseline_total_usd": round(b_total_cost, 4),
        "cost_brain_total_usd": round(n_total_cost, 4),
        "cost_savings_pct": round(
            (1 - n_total_cost / max(0.0001, b_total_cost)) * 100, 1
        ) if b_total_cost else 0,
        "time_baseline_total_s": round(b_total_time, 2),
        "time_brain_total_s": round(n_total_time, 2),
        "time_savings_pct": round(
            (1 - n_total_time / max(1, b_total_time)) * 100, 1
        ) if b_total_time else 0,
        # Projected monthly cost at 20 queries/day/dev
        "projected_monthly_cost_baseline_20qd": round(
            (b_total_cost / max(1, len(common_ids))) * 20 * 22, 2
        ),
        "projected_monthly_cost_brain_20qd": round(
            (n_total_cost / max(1, len(common_ids))) * 20 * 22, 2
        ),
    }

    return {
        "run_at": data.get("run_at"),
        "metadata": data.get("metadata", {}),
        "headline": headline,
        "global": global_stats,
        "by_category": by_category,
        "per_question": per_q,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("input_json", help="Path to runner output JSON")
    parser.add_argument("--output", help="Output stats JSON path", default=None)
    args = parser.parse_args()

    data = json.loads(Path(args.input_json).read_text())
    stats = analyze(data)

    out_path = Path(args.output) if args.output else Path(args.input_json).with_name(
        Path(args.input_json).stem + "_stats.json"
    )
    out_path.write_text(json.dumps(stats, indent=2))

    # Print headline to stdout
    h = stats["headline"]
    print("=" * 60)
    print(f"BENCHMARK RESULTS - {stats.get('run_at', '?')}")
    print("=" * 60)
    print(f"Questions executed: {h['total_questions']}")
    print()
    print("TOKENS:")
    print(f"  Baseline total: {h['tokens_baseline_total']:>10,}")
    print(f"  Brain total:    {h['tokens_brain_total']:>10,}")
    print(f"  Savings:        {h['tokens_savings_pct']:>9.1f}%  ({h['tokens_ratio']}x less)")
    print()
    print("COST (USD - Max plan users pay $0; projected pay-per-use pricing):")
    print(f"  Baseline total: ${h['cost_baseline_total_usd']:>9.4f}")
    print(f"  Brain total:    ${h['cost_brain_total_usd']:>9.4f}")
    print(f"  Savings:        {h['cost_savings_pct']:>9.1f}%")
    print("  Monthly (1 dev × 20q/day × 22d):")
    print(f"    Baseline:     ${h['projected_monthly_cost_baseline_20qd']:>9.2f}")
    print(f"    Brain:        ${h['projected_monthly_cost_brain_20qd']:>9.2f}")
    print()
    print("TIME:")
    print(f"  Baseline total: {h['time_baseline_total_s']:>7.1f}s")
    print(f"  Brain total:    {h['time_brain_total_s']:>7.1f}s")
    print(f"  Savings:        {h['time_savings_pct']:>9.1f}%")
    print()
    print("BY CATEGORY (mean tokens per question):")
    for cat, c in sorted(stats["by_category"].items()):
        ratio = c["baseline_mean_tokens"] / max(1, c["brain_mean_tokens"])
        print(f"  {cat:20s} baseline={c['baseline_mean_tokens']:>7.0f}  brain={c['brain_mean_tokens']:>7.0f}  ratio={ratio:4.2f}x")
    print()
    print(f"Stats saved: {out_path}")


if __name__ == "__main__":
    main()
