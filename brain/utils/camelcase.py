"""Split camelCase and PascalCase identifiers for FTS5 tokenization."""
from __future__ import annotations

import re

_CAMEL_SPLIT_RE = re.compile(
    r"""
    (?<=[a-z])(?=[A-Z0-9])      # aB → a B, a2 → a 2
    | (?<=[0-9])(?=[A-Z])       # 2B → 2 B
    | (?<=[A-Z])(?=[A-Z][a-z])  # HTTPStatus → HTTP Status
    """,
    re.VERBOSE,
)


def split_camel(s: str) -> str:
    """Split camelCase / PascalCase into space-separated tokens.

    Non-camelCase input (snake_case, kebab-case, all-lowercase, all-caps)
    is returned unchanged.
    """
    if not s:
        return ""
    return _CAMEL_SPLIT_RE.sub(" ", s)
