"""Deterministic FFCSS design-token extractor.

Path-B support utility: regex scan of `.scss`, `.css`, `.vue` (style blocks).
Zero LLM cost. Returns `FFCSSCandidate` instances that federation/merger
converts into `ffcss_token` nodes + `defines_token`/`uses_token` edges.

"FFCSS" is the brain-internal name for "a project-wide design-token convention
where every reusable token shares a single prefix" - e.g. `dt-` (design
tokens), `ds-`, `app-`. The default prefix is `dt-` in the educational
version; configure it per repo to match your codebase's convention.

Prefix semantics:
- non-empty (default "dt-"): only tokens whose raw name starts with prefix
  are picked up; the prefix is stripped from `token_name`.
- empty "": every CSS custom property (--NAME) and SCSS variable ($NAME) is
  picked up with `token_name = NAME` (opt-in, noisy).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class FFCSSDefinition:
    file: Path
    line: int
    syntax: str  # "css-variable" | "scss-variable"
    value: str


@dataclass
class FFCSSUsage:
    file: Path
    line: int
    syntax: str  # "css-variable" | "scss-variable"


@dataclass
class FFCSSCandidate:
    token_name: str
    token_type: str  # "css-variable" | "scss-variable" | "scss-css-bridge"
    value: str | None = None
    definitions: list[FFCSSDefinition] = field(default_factory=list)
    usages: list[FFCSSUsage] = field(default_factory=list)


_CSS_DEF_RE = re.compile(
    r"--(?P<name>[A-Za-z0-9_\-]+)\s*:\s*(?P<value>[^;{}]+);?",
)
_SCSS_DEF_RE = re.compile(
    r"\$(?P<name>[A-Za-z0-9_\-]+)\s*:\s*(?P<value>[^;{}]+);",
)
_CSS_USE_RE = re.compile(
    r"var\(\s*--(?P<name>[A-Za-z0-9_\-]+)\s*(?:,[^)]*)?\)",
)
_SCSS_USE_RE = re.compile(r"\$(?P<name>[A-Za-z0-9_\-]+)")


def _matches_prefix(name: str, prefix: str) -> tuple[bool, str]:
    if prefix == "":
        # Empty prefix: match all, but strip "dt-" if present
        if name.startswith("dt-"):
            return True, name[3:]
        return True, name
    if name.startswith(prefix):
        return True, name[len(prefix):]
    return False, name


def _line_of_offset(source: str, offset: int) -> int:
    return source.count("\n", 0, offset) + 1


def extract_from_source(
    *,
    path: Path,
    source: str,
    prefix: str = "dt-",
) -> list[FFCSSCandidate]:
    """Extract FFCSS candidate tokens from `source`.

    Does not raise on malformed input - regex doesn't depend on balanced
    braces. All state is local; idempotent.
    """
    by_name: dict[str, FFCSSCandidate] = {}

    def _get(name: str) -> FFCSSCandidate:
        if name not in by_name:
            by_name[name] = FFCSSCandidate(
                token_name=name,
                token_type="css-variable",
            )
        return by_name[name]

    for m in _CSS_DEF_RE.finditer(source):
        raw_name = m.group("name")
        ok, stripped = _matches_prefix(raw_name, prefix)
        if not ok:
            continue
        cand = _get(stripped)
        line = _line_of_offset(source, m.start())
        value = m.group("value").strip()
        cand.definitions.append(
            FFCSSDefinition(file=path, line=line, syntax="css-variable", value=value)
        )
        cand.value = cand.value or value

    for m in _SCSS_DEF_RE.finditer(source):
        raw_name = m.group("name")
        ok, stripped = _matches_prefix(raw_name, prefix)
        if not ok:
            continue
        cand = _get(stripped)
        line = _line_of_offset(source, m.start())
        value = m.group("value").strip()
        cand.definitions.append(
            FFCSSDefinition(file=path, line=line, syntax="scss-variable", value=value)
        )
        cand.value = cand.value or value

    for m in _CSS_USE_RE.finditer(source):
        raw_name = m.group("name")
        ok, stripped = _matches_prefix(raw_name, prefix)
        if not ok:
            continue
        cand = _get(stripped)
        cand.usages.append(
            FFCSSUsage(
                file=path,
                line=_line_of_offset(source, m.start()),
                syntax="css-variable",
            )
        )

    for m in _SCSS_USE_RE.finditer(source):
        raw_name = m.group("name")
        ok, stripped = _matches_prefix(raw_name, prefix)
        if not ok:
            continue
        tail = source[m.end() : m.end() + 8].lstrip()
        if tail.startswith(":"):
            continue
        cand = _get(stripped)
        cand.usages.append(
            FFCSSUsage(
                file=path,
                line=_line_of_offset(source, m.start()),
                syntax="scss-variable",
            )
        )

    for cand in by_name.values():
        syntaxes = {d.syntax for d in cand.definitions}
        if syntaxes == {"css-variable", "scss-variable"}:
            cand.token_type = "scss-css-bridge"
        elif syntaxes == {"scss-variable"}:
            cand.token_type = "scss-variable"
        else:
            cand.token_type = "css-variable"

    return list(by_name.values())
