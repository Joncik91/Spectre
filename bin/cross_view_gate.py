"""bin/cross_view_gate.py — v1.0 Tier-2 cross-view consistency checks.

Reads parsed §8.x family + §§9-13 contracts from a draft spec and verifies:

  1. Every cross-view string reference in §§9-13 (e.g. `<halt-hint from §8.2
     ux-contract>`) resolves to an actual §8.x field.
  2. Every exemplar binding (`<aspect>-style: exemplar:<view-type>:<slug>`
     or bare `exemplar:<slug>`) points at a real catalog entry.
  3. Every exemplar binding's taxonomy-version matches the catalog's current
     taxonomy-version for that view type.
  4. The fingerprint vocabularies across §§8.3-8.7 don't contradict §8.1's
     hard contract.

Returns list[_findings.Finding] for `_spec_evaluator.evaluate()` to fold
into the Tier-2 bucket.

Stdlib only (uses bin/_catalog which is also stdlib-only).
"""
from __future__ import annotations

import pathlib
import re
from typing import Iterable

from bin import _catalog
from bin import findings as _findings


# ---------------------------------------------------------------------------
# Section extraction (mirrors bin/spec_ast helpers)
# ---------------------------------------------------------------------------

_CROSS_VIEW_REF_RE = re.compile(
    # Loose section match catches typos like §8.20, §9.2, §8.99 — validated
    # against _SUBSTRATE_SECTIONS in _check_cross_view_references so out-of-
    # range refs emit a finding instead of silently passing through.
    r"<([a-z][a-z0-9_-]*)\s+from\s+§\s*(\d+(?:\.\d+)*)(?:\s+([a-z][a-z0-9_-]*))?>",
    re.IGNORECASE,
)
_EXEMPLAR_REF_RE = re.compile(r"exemplar:([a-z0-9][a-z0-9:_-]*)")
_TAXONOMY_VERSION_RE = re.compile(
    r"taxonomy-version:\s*([a-z][a-z0-9_-]*):(\d+)",
    re.IGNORECASE,
)
_VIEW_SECTIONS = ("9", "10", "11", "12", "13")
_VIEW_SECTION_LABELS = {
    "9": "Product-Input View",
    "10": "Product-Output View",
    "11": "Human-User View",
    "12": "Integrator View",
    "13": "Operator View",
}
_SUBSTRATE_SECTIONS = ("8.2", "8.3", "8.4", "8.5", "8.6", "8.7")


def _extract_section_body(body: str, heading_pattern: str) -> str | None:
    m = re.search(heading_pattern, body, re.MULTILINE)
    if not m:
        return None
    start = m.end()
    next_h2 = re.search(r"^##\s", body[start:], re.MULTILINE)
    return body[start : start + next_h2.start()] if next_h2 else body[start:]


def _extract_substrate_blocks(body: str) -> dict[str, str]:
    """Return a dict of section-id -> block body for §§8.2-8.7."""
    blocks: dict[str, str] = {}
    for section in _SUBSTRATE_SECTIONS:
        # Match h3 (### 8.2) — substrate blocks are nested under §8
        pattern = rf"^#{{2,3}}\s+{re.escape(section)}\b.*$"
        m = re.search(pattern, body, re.MULTILINE)
        if not m:
            continue
        start = m.end()
        next_h = re.search(r"^#{2,3}\s", body[start:], re.MULTILINE)
        blocks[section] = body[start : start + next_h.start()] if next_h else body[start:]
    return blocks


def _extract_view_blocks(body: str) -> dict[str, str]:
    """Return a dict of section-id -> block body for §§9-13."""
    blocks: dict[str, str] = {}
    for section in _VIEW_SECTIONS:
        label = _VIEW_SECTION_LABELS[section]
        section_body = _extract_section_body(
            body, rf"^##\s+{re.escape(section)}\.\s+{re.escape(label)}\b"
        )
        if section_body is not None:
            blocks[section] = section_body
    return blocks


def _fields_in_substrate_block(block: str) -> set[str]:
    """Extract field names from a substrate block.

    Recognizes top-level fields (`- field-name: value`) and ux-contract
    sub-fields (`    on-success:`, `    on-failure:`, `    log-target:`).
    """
    fields: set[str] = set()
    for line in block.splitlines():
        m = re.match(r"^\s*-?\s*([a-z][a-z0-9-]*)\s*:", line)
        if m:
            fields.add(m.group(1))
        # ux-contract sub-fields with 4-space indent under the parent bullet
        m2 = re.match(r"^\s{4,}([a-z][a-z0-9-]*)\s*:", line)
        if m2:
            fields.add(m2.group(1))
    return fields


def _is_not_applicable(block: str) -> bool:
    return bool(re.search(r"^\s*-?\s*not-applicable\s*:", block, re.MULTILINE))


# ---------------------------------------------------------------------------
# Check 1: cross-view string references resolve to existing §8.x fields
# ---------------------------------------------------------------------------

def _check_cross_view_references(
    view_blocks: dict[str, str],
    substrate_blocks: dict[str, str],
) -> list[_findings.Finding]:
    results: list[_findings.Finding] = []
    substrate_fields = {
        section: _fields_in_substrate_block(block)
        for section, block in substrate_blocks.items()
    }
    for section, block in view_blocks.items():
        for m in _CROSS_VIEW_REF_RE.finditer(block):
            field_name = m.group(1).lower()
            ref_section = m.group(2)
            # Ignore template placeholders verbatim from the v1.0 template body
            # (the catalog example references "halt-hint from §8.2 ux-contract"
            # as documentation — only flag broken refs in real specs).
            if ref_section not in substrate_fields:
                results.append(_findings.Finding(
                    tier=2,
                    kind="cross-view-string-unresolved",
                    severity="block",
                    location=_findings.FindingLocation(
                        scope="spec-wide", ref=f"section-{section}"
                    ),
                    message=(
                        f"§{section} references §{ref_section} which is not present in the spec."
                    ),
                    suggested_fix=f"Add §{ref_section} or change the reference to an existing substrate block.",
                ))
                continue
            if field_name not in substrate_fields[ref_section]:
                results.append(_findings.Finding(
                    tier=2,
                    kind="cross-view-string-unresolved",
                    severity="block",
                    location=_findings.FindingLocation(
                        scope="spec-wide", ref=f"section-{section}"
                    ),
                    message=(
                        f"§{section} references §{ref_section}.{field_name} which is not a field in §{ref_section}."
                    ),
                    suggested_fix=f"Add `{field_name}:` to §{ref_section} or correct the reference.",
                ))
    return results


# ---------------------------------------------------------------------------
# Check 2 + 3: exemplar bindings + taxonomy versions
# ---------------------------------------------------------------------------

# Map view section -> expected catalog view-type for exemplar bindings.
# Multiple view-types are allowed because a §11 Human-User View may bind to
# both help-text and error-text catalog entries.
_VIEW_TO_CATALOG_TYPES: dict[str, set[str]] = {
    "9": {"help-text"},                       # placeholder until v1.1 ships input-shape exemplars
    "10": {"help-text"},                      # placeholder until v1.1 ships output-shape exemplars
    "11": {"help-text", "error-text"},
    "12": {"api-shape"},
    "13": {"log-format", "observability"},
}


def _check_exemplar_bindings(
    view_blocks: dict[str, str],
) -> list[_findings.Finding]:
    results: list[_findings.Finding] = []
    catalog = _catalog.load_catalog()
    for section, block in view_blocks.items():
        if _is_not_applicable(block):
            continue
        # Parse taxonomy-version declarations (`taxonomy-version: help-text:1, error-text:1`)
        spec_taxonomies: dict[str, int] = {}
        for tv_match in _TAXONOMY_VERSION_RE.finditer(block):
            view_type = tv_match.group(1).lower()
            try:
                version = int(tv_match.group(2))
            except ValueError:
                continue
            spec_taxonomies[view_type] = version
        # Find exemplar bindings
        for m in _EXEMPLAR_REF_RE.finditer(block):
            raw_ref = m.group(1).strip()
            # Skip template angle-bracket placeholders
            if raw_ref.startswith("<") or raw_ref in ("slug", "name"):
                continue
            ex = _catalog.lookup(raw_ref)
            if ex is None:
                # Could be unqualified; try matching against all catalog entries
                results.append(_findings.Finding(
                    tier=2,
                    kind="exemplar-not-found",
                    severity="block",
                    location=_findings.FindingLocation(
                        scope="spec-wide", ref=f"section-{section}"
                    ),
                    message=f"§{section} references exemplar:{raw_ref} which is not in the catalog (plugin or user overlay).",
                    suggested_fix=f"Run `spectre exemplars list` to see valid slugs; add the exemplar to ~/.spectre/exemplars/<view-type>/ or remove the binding.",
                ))
                continue
            # Taxonomy version check
            for view_type in ex.view_types:
                spec_version = spec_taxonomies.get(view_type)
                if spec_version is None:
                    continue
                if spec_version != ex.taxonomy_version:
                    results.append(_findings.Finding(
                        tier=2,
                        kind="exemplar-taxonomy-mismatch",
                        severity="block",
                        location=_findings.FindingLocation(
                            scope="spec-wide", ref=f"section-{section}"
                        ),
                        message=(
                            f"§{section} binds exemplar:{raw_ref} (taxonomy-version {ex.taxonomy_version}) "
                            f"but spec pins {view_type}:{spec_version}."
                        ),
                        suggested_fix=(
                            f"Either upgrade the spec to taxonomy-version {ex.taxonomy_version} "
                            f"(re-run /vision for view §{section}) or pick an exemplar at version {spec_version}."
                        ),
                    ))
    return results


# ---------------------------------------------------------------------------
# Check 4: §8.x fingerprint vs §8.1 hard contract
# ---------------------------------------------------------------------------

_MUTATES_RE = re.compile(r"^\s*-?\s*mutates\s*:\s*(.+)$", re.MULTILINE)
_HUMAN_USER_FP_RE = re.compile(r"^\s*-?\s*receiver-fingerprint\s*:\s*(\S+)", re.MULTILINE)


def _check_fingerprint_vs_hard_contract(
    body: str,
    substrate_blocks: dict[str, str],
) -> list[_findings.Finding]:
    """Flag obvious contradictions between §8.x fingerprints and §8.1 mutates.

    Initial v1.0 check: §8.5 declares gui-only human-user but §8.1 mutates
    includes stdout-equivalent paths (the canonical contradiction the plan
    called out).
    """
    results: list[_findings.Finding] = []
    block_85 = substrate_blocks.get("8.5")
    if block_85 is None or _is_not_applicable(block_85):
        return results
    fp_match = _HUMAN_USER_FP_RE.search(block_85)
    if fp_match is None:
        return results
    if fp_match.group(1).strip() != "gui-only":
        return results
    # Find §8.1 mutates
    block_81_match = re.search(r"^#{2,3}\s+8\.1\b.*$", body, re.MULTILINE)
    if block_81_match is None:
        return results
    start = block_81_match.end()
    next_h = re.search(r"^#{2,3}\s", body[start:], re.MULTILINE)
    block_81 = body[start : start + next_h.start()] if next_h else body[start:]
    mut_match = _MUTATES_RE.search(block_81)
    if mut_match is None:
        return results
    mutates = mut_match.group(1).strip()
    if any(tok in mutates for tok in ("stdout", "stderr", "/dev/tty")):
        results.append(_findings.Finding(
            tier=2,
            kind="view-fingerprint-contradicts-hard-contract",
            severity="block",
            location=_findings.FindingLocation(scope="spec-wide", ref="section-8.5"),
            message=(
                "§8.5 fingerprint 'gui-only' contradicts §8.1 mutates "
                "(terminal-stream path); a gui-only receiver cannot read stdout/stderr/tty."
            ),
            suggested_fix="Change §8.5 fingerprint to cli-power-user/cli-novice/no-human-user, OR drop the terminal-stream path from §8.1 mutates.",
        ))
    return results


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def classify(spec_path: pathlib.Path) -> list[_findings.Finding]:
    """Tier-2 cross-view checks. Returns findings list; never raises."""
    try:
        body = spec_path.read_text(encoding="utf-8")
    except OSError:
        return []
    # Only fire v1.0 cross-view checks for v1.0 specs. Shared with spec_ast
    # Tier-1 and llm_judge Tier-3 so all three checkers agree.
    from bin import spec_ast as _spec_ast
    if not _spec_ast.is_v1_spec(body):
        return []
    substrate_blocks = _extract_substrate_blocks(body)
    view_blocks = _extract_view_blocks(body)
    results: list[_findings.Finding] = []
    results.extend(_check_cross_view_references(view_blocks, substrate_blocks))
    results.extend(_check_exemplar_bindings(view_blocks))
    results.extend(_check_fingerprint_vs_hard_contract(body, substrate_blocks))
    return results
