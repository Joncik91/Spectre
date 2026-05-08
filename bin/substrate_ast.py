"""Tier 1 deterministic §8.2 + per-step trust annotation parser + taint flow.

Public API:
    classify(spec_path: pathlib.Path) -> list[findings.Finding]
"""
from __future__ import annotations

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
    r"^###\s+8\.2\b.*?(?=^##\s|\Z)", re.DOTALL | re.MULTILINE
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


def classify(spec_path: pathlib.Path) -> list[_findings.Finding]:
    """Run all Tier 1 §8.2 checks; return finding list."""
    body = spec_path.read_text(encoding="utf-8")
    results: list[_findings.Finding] = []
    results.extend(_check_82_required_fields(body))
    return results
