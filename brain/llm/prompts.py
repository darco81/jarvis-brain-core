"""Centralized LLM extraction prompts used by the Path-A LLM backends.

Keeping the system prompt in one place guarantees Path-A (LLM) emits the
same shapes Path-B (skill regex) emits. Callers pass `include_ffcss` and
`prefix` so the FFCSS section is added only when the group's config opted
in (`groups.yml: groups.<g>.ffcss.enabled: true`).
"""
from __future__ import annotations

_BASE_SCHEMA = (
    "You are a code-analysis assistant that extracts structured knowledge "
    "graphs from source files. Return STRICT JSON with this schema:\n\n"
    "{\n"
    '  "nodes": [ {"id": "<group>/<repo>:<path>", "kind": '
    '"class|function|module|doc|component", "name": "...", '
    '"file": "...", "line": N, "metadata": {}} ],\n'
    '  "edges": [ {"source": "...", "target": "...", '
    '"relation": "imports|extends|...", '
    '"confidence": "extracted|inferred", "metadata": {}} ]\n'
    "}\n\n"
    "Relations whitelist: imports, exports, extends, implements, calls, "
    "renders, uses_hook, documents, imports_from_parent_repo, "
    "semantically_similar_to.\n\n"
    "Output MUST be a single JSON object - no prose, no markdown fences."
)


FFCSS_RULES_SECTION = """\
FFCSS TOKEN EXTRACTION (additional rules, emit alongside regular nodes):

Add "ffcss_token" to the kind whitelist. A token is either:
  - a CSS custom property: `--<name>: <value>;`
  - a SCSS variable:       `$<name>: <value>;`

For every token whose <name> starts with the configured prefix (see below),
emit a node with:
  - kind: "ffcss_token"
  - id:   "<group>/<repo>:ffcss:<token-name-without-prefix>"
  - name: <token-name-without-prefix>
  - metadata.token_type: "css-variable" | "scss-variable" | "scss-css-bridge"
      * "scss-css-bridge" when BOTH `--<prefix><name>` AND `$<prefix><name>`
        are defined in the same repo (alias pair).
  - metadata.value: first definition value (string)
  - metadata.definitions: array of {file, line, syntax, value} for each def
  - metadata.canonical: true if this repo is the "core" role, else false.

For every usage `var(--<prefix><name>)` or bare SCSS `$<prefix><name>`
reference in a `.vue`/`.scss`/`.css` file, emit an edge:
  - source: the component/module node id
  - target: the token node id
  - relation: "uses_token"
  - confidence: "extracted"

For every file/module that DEFINES a token, emit an edge:
  - source: the module/file node id
  - target: the token node id
  - relation: "defines_token"
  - confidence: "extracted"

Do NOT invent overrides_token/duplicates_token edges here - those are
derived cross-repo by the federation merger.

Relations added to the whitelist for FFCSS: defines_token, uses_token,
overrides_token, duplicates_token.
"""


def build_extraction_system_prompt(
    *,
    include_ffcss: bool,
    prefix: str = "dt-",
) -> str:
    """Compose the extraction system prompt, optionally with FFCSS rules."""
    out = _BASE_SCHEMA
    if include_ffcss:
        if prefix == "":
            prefix_clause = (
                "Prefix configured is EMPTY - treat all CSS custom "
                "properties and all SCSS variables as candidate tokens."
            )
        else:
            prefix_clause = (
                f"Prefix configured is: '{prefix}'. Only tokens whose raw "
                f"name starts with '{prefix}' are FFCSS tokens. Strip the "
                "prefix before emitting token name/id."
            )
        out = out + "\n\n" + prefix_clause + "\n\n" + FFCSS_RULES_SECTION
    return out
