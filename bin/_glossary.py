"""bin/_glossary.py — Glossary parser, lookup API, and CLI.

Parses docs/glossary.md into Entry dataclasses. Provides:
  load_glossary()           — load + cache the glossary dict
  lookup(code)              — status-code lookup
  lookup_term(noun)         — term lookup (without term: prefix)
  render_pm_sentence(entry, fields) — {placeholder} substitution
  all_codes()               — set of status-code keys
  all_terms()               — set of term keys (without term: prefix)

CLI (via bin/spectre or direct):
  python3 -m bin._glossary glossary [--filter PREFIX] [--audience dev|pm] [--json]
  python3 -m bin._glossary explain <code-or-term>

Stdlib only. No third-party deps.
"""
from __future__ import annotations

import json
import os
import pathlib
import re
import sys
from dataclasses import dataclass, field
from typing import Any

# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------

class GlossaryError(Exception):
    """Raised when a required field is missing from an entry."""

    def __init__(self, entry_key: str, missing_field: str) -> None:
        self.entry_key = entry_key
        self.missing_field = missing_field
        super().__init__(
            f"glossary entry {entry_key!r} is missing required field {missing_field!r}"
        )


@dataclass
class Entry:
    key: str           # "walker.init" or "term:walker"
    kind: str          # "status" | "term"
    dev: str
    pm: str
    triggered_by: str = ""
    user_action: str = ""
    related: list[str] = field(default_factory=list)
    since: str = ""
    extra: dict[str, str] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------

_REQUIRED_BASE = ("kind", "dev", "pm")
_REQUIRED_STATUS = ("triggered_by", "user_action")
_KNOWN_FIELDS = frozenset(("kind", "dev", "pm", "triggered_by", "user_action", "related", "since"))


def _parse_glossary(text: str) -> dict[str, Entry]:
    """Parse glossary markdown text into a dict of key → Entry."""
    entries: dict[str, Entry] = {}
    current_key: str | None = None
    current_fields: dict[str, str] = {}

    def _flush() -> None:
        if current_key is None:
            return
        _build_entry(current_key, current_fields, entries)

    for raw_line in text.splitlines():
        line = raw_line.rstrip()
        # New entry heading
        m_head = re.match(r"^##\s+(.+)$", line)
        if m_head:
            _flush()
            current_key = m_head.group(1).strip()
            current_fields = {}
            continue
        # Field bullet
        if current_key is not None:
            m_field = re.match(r"^-\s+([a-zA-Z_][a-zA-Z0-9_-]*):\s*(.*)?$", line)
            if m_field:
                fname = m_field.group(1).strip()
                fval = (m_field.group(2) or "").strip()
                current_fields[fname] = fval

    _flush()
    return entries


def _build_entry(key: str, fields: dict[str, str], out: dict[str, Entry]) -> None:
    # Check required base fields
    for req in _REQUIRED_BASE:
        if req not in fields:
            raise GlossaryError(key, req)

    kind = fields["kind"]

    # Status entries need triggered_by + user_action
    if kind == "status":
        for req in _REQUIRED_STATUS:
            if req not in fields:
                raise GlossaryError(key, req)

    # Parse related as comma-separated list
    related_raw = fields.get("related", "")
    related: list[str] = (
        [r.strip() for r in related_raw.split(",") if r.strip()]
        if related_raw
        else []
    )

    # Unknown fields → extra dict
    extra: dict[str, str] = {}
    for k, v in fields.items():
        if k not in _KNOWN_FIELDS:
            extra[k] = v

    out[key] = Entry(
        key=key,
        kind=kind,
        dev=fields["dev"],
        pm=fields["pm"],
        triggered_by=fields.get("triggered_by", ""),
        user_action=fields.get("user_action", ""),
        related=related,
        since=fields.get("since", ""),
        extra=extra,
    )


# ---------------------------------------------------------------------------
# Module-level cache
# ---------------------------------------------------------------------------

_GLOSSARY_CACHE: dict[str, Entry] | None = None
_GLOSSARY_CACHE_PATH: pathlib.Path | None = None


def _default_glossary_path() -> pathlib.Path:
    env_path = os.environ.get("SPECTRE_GLOSSARY_PATH")
    if env_path:
        return pathlib.Path(env_path)
    # Relative to this file: bin/_glossary.py → ../docs/glossary.md
    return pathlib.Path(__file__).resolve().parent.parent / "docs" / "glossary.md"


def load_glossary(path: pathlib.Path | None = None) -> dict[str, Entry]:
    """Load and parse docs/glossary.md. Caches at module level.

    Re-loading with a different path invalidates the cache.
    """
    global _GLOSSARY_CACHE, _GLOSSARY_CACHE_PATH  # noqa: PLW0603
    resolved = path or _default_glossary_path()
    if _GLOSSARY_CACHE is not None and _GLOSSARY_CACHE_PATH == resolved:
        return _GLOSSARY_CACHE
    text = resolved.read_text(encoding="utf-8")
    result = _parse_glossary(text)
    _GLOSSARY_CACHE = result
    _GLOSSARY_CACHE_PATH = resolved
    return result


def _get_glossary() -> dict[str, Entry]:
    """Internal: load with default path (safe — raises on missing file)."""
    return load_glossary()


# ---------------------------------------------------------------------------
# Public lookup API
# ---------------------------------------------------------------------------

def lookup(code: str) -> Entry | None:
    """Status code lookup. Returns None if not found."""
    try:
        g = _get_glossary()
    except Exception:  # noqa: BLE001
        return None
    return g.get(code)


def lookup_term(noun: str) -> Entry | None:
    """Term lookup. Pass without the `term:` prefix; this adds it."""
    key = noun if noun.startswith("term:") else f"term:{noun}"
    try:
        g = _get_glossary()
    except Exception:  # noqa: BLE001
        return None
    return g.get(key)


def render_pm_sentence(entry: Entry, fields: dict[str, Any]) -> str:
    """Substitute {placeholder} from fields into entry.pm.

    Missing keys → empty string (no crash).
    """
    def _replace(m: re.Match) -> str:
        key = m.group(1)
        val = fields.get(key)
        return str(val) if val is not None else ""

    return re.sub(r"\{([^}]+)\}", _replace, entry.pm)


def all_codes() -> set[str]:
    """Set of all status-code keys (kind=status) in the glossary."""
    try:
        g = _get_glossary()
    except Exception:  # noqa: BLE001
        return set()
    return {k for k, v in g.items() if v.kind == "status"}


def all_terms() -> set[str]:
    """Set of all term nouns (without term: prefix)."""
    try:
        g = _get_glossary()
    except Exception:  # noqa: BLE001
        return set()
    return {k[len("term:"):] for k, v in g.items() if v.kind == "term"}


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _render_entry_text(entry: Entry, audience: str = "dev") -> str:
    lines: list[str] = [f"## {entry.key}", f"kind: {entry.kind}"]
    if audience == "pm":
        lines.append(f"pm:   {entry.pm}")
        lines.append(f"dev:  {entry.dev}")
    else:
        lines.append(f"dev:  {entry.dev}")
        lines.append(f"pm:   {entry.pm}")
    if entry.triggered_by:
        lines.append(f"triggered_by: {entry.triggered_by}")
    if entry.user_action:
        lines.append(f"user_action:  {entry.user_action}")
    if entry.related:
        lines.append(f"related:      {', '.join(entry.related)}")
    if entry.since:
        lines.append(f"since:        {entry.since}")
    if entry.extra:
        for k, v in entry.extra.items():
            lines.append(f"{k}: {v}")
    return "\n".join(lines)


def _entry_to_dict(entry: Entry) -> dict:
    return {
        "key": entry.key,
        "kind": entry.kind,
        "dev": entry.dev,
        "pm": entry.pm,
        "triggered_by": entry.triggered_by,
        "user_action": entry.user_action,
        "related": entry.related,
        "since": entry.since,
        "extra": entry.extra,
    }


def _cmd_glossary(args: list[str]) -> int:
    import argparse

    p = argparse.ArgumentParser(
        prog="spectre glossary",
        description="List glossary entries.",
    )
    p.add_argument("--filter", dest="prefix", default="",
                   help="Filter entries by key prefix (e.g. walker.)")
    p.add_argument("--audience", choices=["dev", "pm"], default="dev",
                   help="Which description to show (dev=technical, pm=plain)")
    p.add_argument("--json", dest="json_out", action="store_true",
                   help="Output JSON array")
    parsed = p.parse_args(args)

    try:
        g = load_glossary()
    except GlossaryError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    except OSError as exc:
        print(f"ERROR: cannot read glossary: {exc}", file=sys.stderr)
        return 1

    items = sorted(g.values(), key=lambda e: e.key)
    if parsed.prefix:
        items = [e for e in items if e.key.startswith(parsed.prefix)]

    if parsed.json_out:
        print(json.dumps([_entry_to_dict(e) for e in items], indent=2))
        return 0

    for entry in items:
        print(_render_entry_text(entry, audience=parsed.audience))
        print()
    print(f"({len(items)} entries)")
    return 0


def _cmd_explain(args: list[str]) -> int:
    if not args:
        print("Usage: spectre explain <code-or-term>", file=sys.stderr)
        print("  code:  e.g. walker.init", file=sys.stderr)
        print("  term:  e.g. term:walker  or  walker (without prefix)", file=sys.stderr)
        return 1

    key = args[0]
    try:
        g = load_glossary()
    except GlossaryError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    except OSError as exc:
        print(f"ERROR: cannot read glossary: {exc}", file=sys.stderr)
        return 1

    entry = g.get(key) or g.get(f"term:{key}")
    if entry is None:
        print(f"ERROR: no glossary entry for {key!r}", file=sys.stderr)
        codes = sorted(g.keys())
        close = [c for c in codes if key.split(".")[0] in c][:5]
        if close:
            print(f"  Did you mean: {', '.join(close)}", file=sys.stderr)
        return 1

    audience = os.environ.get("SPECTRE_AUDIENCE", "dev")
    print(_render_entry_text(entry, audience=audience))
    return 0


def _main() -> int:
    if len(sys.argv) < 2:
        print("Usage: spectre <glossary|explain> [args…]", file=sys.stderr)
        return 1

    subcmd = sys.argv[1]
    rest = sys.argv[2:]

    if subcmd == "glossary":
        return _cmd_glossary(rest)
    elif subcmd == "explain":
        return _cmd_explain(rest)
    else:
        print(f"Unknown subcommand: {subcmd!r}. Use glossary or explain.", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(_main())
