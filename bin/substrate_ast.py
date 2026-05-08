"""Tier 1 deterministic §8.2 + per-step trust annotation parser + taint flow.

Public API:
    classify(spec_path: pathlib.Path) -> list[findings.Finding]
"""
from __future__ import annotations

import math
import pathlib
import re

from bin import findings as _findings

# ── §8.2 schema ──────────────────────────────────────────────────────────────

_BLOCK_SEVERITY_FIELDS = (
    "receiver-fingerprint",
    "trust-profile",
    "contextual-binding",
    "provenance",
)

_82_BLOCK_RE = re.compile(
    r"^###\s+8\.2\b.*?(?=^##\s|^###\s|\Z)", re.DOTALL | re.MULTILINE
)


def _extract_82_block(body: str) -> str | None:
    """Return the §8.2 block text (without the heading) or None."""
    m = _82_BLOCK_RE.search(body)
    return m.group(0) if m else None


def _field_present(block: str, field: str) -> bool:
    """True if the field has a non-empty value in the block."""
    pat = re.compile(rf"^\s*-\s+{re.escape(field)}\s*:\s*(.+)$", re.MULTILINE)
    m = pat.search(block)
    if not m:
        return False
    val = m.group(1).strip()
    return bool(val) and val != "<auto-filled by wizard>"


def _check_82_required_fields(body: str) -> list[_findings.Finding]:
    """Block on missing §8.2 block or missing required fields."""
    results: list[_findings.Finding] = []
    block = _extract_82_block(body)
    if block is None:
        results.append(_findings.Finding(
            tier=1,
            kind="substrate-incomplete",
            severity="block",
            location=_findings.FindingLocation(
                scope="spec-wide", ref="cognitive-substrate"
            ),
            message="§8.2 Cognitive-substrate contract is absent.",
            suggested_fix="Re-run /vision; the wizard auto-injects §8.2.",
        ))
        return results
    # ux-contract is structured (sub-keys); check separately
    has_ux = bool(re.search(r"^\s*-\s+ux-contract\s*:", block, re.MULTILINE))
    fields_to_check = list(_BLOCK_SEVERITY_FIELDS)
    if not has_ux:
        results.append(_findings.Finding(
            tier=1,
            kind="substrate-incomplete",
            severity="block",
            location=_findings.FindingLocation(
                scope="spec-wide", ref="cognitive-substrate"
            ),
            message="§8.2 ux-contract block missing.",
            suggested_fix="Re-run wizard or add ux-contract to §8.2.",
        ))
    for field in fields_to_check:
        if not _field_present(block, field):
            results.append(_findings.Finding(
                tier=1,
                kind="substrate-incomplete",
                severity="block",
                location=_findings.FindingLocation(
                    scope="spec-wide", ref="cognitive-substrate"
                ),
                message=f"§8.2 {field} is missing or empty.",
                suggested_fix="Re-run /vision wizard.",
            ))
    return results


_LIST_FIELD_RE_TPL = (
    r"^\s*-\s+{field}\s*:\s*(?P<inline>[^\n]*)$(?P<block>(?:\n\s+-\s+[^\n]+)*)"
)


def _extract_list_field(block: str, field: str) -> list[str]:
    """Parse a list field that may be inline or indented sequence.

    Returns empty list if value is angle-bracket placeholder (e.g.
    ``<list of step IDs>``) — these are template stubs, not real entries.
    """
    pat = re.compile(_LIST_FIELD_RE_TPL.format(field=re.escape(field)), re.MULTILINE)
    m = pat.search(block)
    if not m:
        return []
    inline = m.group("inline").strip()
    block_part = m.group("block") or ""
    items: list[str] = []
    if inline and not inline.startswith("<"):
        if inline.startswith("[") and inline.endswith("]"):
            inner = inline[1:-1]
            items.extend(t.strip().strip("'\"") for t in inner.split(",") if t.strip())
        else:
            items.append(inline)
    for line in block_part.splitlines():
        s = line.strip()
        if s.startswith("- "):
            items.append(s[2:].strip().strip("'\""))
    return items


def _count_steps(body: str) -> int:
    return len(re.findall(r"^\s*-\s+step\s*:\s*\d+", body, re.MULTILINE))


def _check_assumptions_walk(body: str) -> list[_findings.Finding]:
    block = _extract_82_block(body) or ""
    items = _extract_list_field(block, "assumptions-killed")
    n_steps = _count_steps(body)
    if items:
        return []
    if n_steps > 3:
        return [_findings.Finding(
            tier=1,
            kind="assumptions-walk-empty",
            severity="block",
            location=_findings.FindingLocation(
                scope="spec-wide", ref="assumptions-killed"
            ),
            message=(
                f"§8.2 assumptions-killed is empty; spec has {n_steps} steps so "
                "the possibility-walk discipline is required."
            ),
            suggested_fix="List ≥1 considered-and-ruled-out alternative.",
        )]
    return [_findings.Finding(
        tier=1,
        kind="assumptions-walk-empty",
        severity="warn",
        location=_findings.FindingLocation(
            scope="spec-wide", ref="assumptions-killed"
        ),
        message="§8.2 assumptions-killed is empty.",
        suggested_fix="List considered-and-ruled-out alternatives.",
    )]


def _check_judgment_cap(body: str) -> list[_findings.Finding]:
    block = _extract_82_block(body) or ""
    items = _extract_list_field(block, "requires-situated-judgment")
    n_steps = _count_steps(body)
    if not items or n_steps == 0:
        return []
    cap = max(1, math.floor(0.3 * n_steps))
    if len(items) <= cap:
        return []
    return [_findings.Finding(
        tier=1,
        kind="judgment-claim-overused",
        severity="warn",
        location=_findings.FindingLocation(
            scope="spec-wide", ref="requires-situated-judgment"
        ),
        message=(
            f"§8.2 requires-situated-judgment claims {len(items)} steps; "
            f"cap is {cap} ({n_steps}-step spec)."
        ),
        suggested_fix=(
            "Reduce judgment claims to ≤cap; situated-judgment is an escape "
            "hatch, not the default."
        ),
    )]


def classify(spec_path: pathlib.Path) -> list[_findings.Finding]:
    """Run all Tier 1 §8.2 checks; return finding list."""
    body = spec_path.read_text(encoding="utf-8")
    results: list[_findings.Finding] = []
    results.extend(_check_82_required_fields(body))
    results.extend(_check_assumptions_walk(body))
    results.extend(_check_judgment_cap(body))
    return results
