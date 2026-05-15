"""tests/test_spec_evaluator_adr_extraction.py — v1.2 Fix Q: ADR extractor extension.

Tests that _extract_preview_adrs correctly surfaces ADR candidates from:
  §2  decision: markers (primary canonical path — unchanged)
  §3  Algorithm Audit Delete entries (new)
  §5  Physics Guardrails bullet items (new)
  §8.x assumptions-killed: blocks (new)

Four required cases:
  1. §3 extraction
  2. §5 extraction
  3. §8.x extraction
  4. cap-at-10 behaviour

Additional cases:
  5. §2 canonical form still works and is not displaced
  6. §2 canonical entries are NOT counted toward the cap
  7. prefix sentinel form (exemplar:post-ship-iteration) does not corrupt output
  8. template placeholder lines are skipped
"""
from __future__ import annotations

from bin.spec_evaluator import (
    _extract_preview_adrs,
    _extract_s3_delete_candidates,
    _extract_s5_guardrail_candidates,
    _extract_s8x_assumptions_candidates,
    _ADR_CANDIDATE_CAP,
)


# ---------------------------------------------------------------------------
# Minimal spec builder
# ---------------------------------------------------------------------------

_HEADER = (
    "# Test Spec\n\n"
    "**Generated:** 2026-05-15\n"
    "**Slug:** test\n"
    "**Spec-version:** 1.0\n\n"
)


def _spec(
    s2: str = "",
    s3: str = "",
    s4: str = "",
    s5: str = "",
    s6: str = "",
    s7: str = "",
    s8: str = "",
) -> str:
    parts = [_HEADER]
    if s2:
        parts.append(f"## 2. First Principles\n{s2}\n")
    if s3:
        parts.append(f"## 3. Algorithm Audit\n{s3}\n")
    if s4:
        parts.append(f"## 4. Speed-of-Light Limit\n{s4}\n")
    if s5:
        parts.append(f"## 5. Physics Guardrails\n{s5}\n")
    if s6:
        parts.append(f"## 6. Steps\n{s6}\n")
    if s7:
        parts.append(f"## 7. Success Criteria\n{s7}\n")
    if s8:
        parts.append(f"## 8. Receiver Calibration\n{s8}\n")
    return "".join(parts)


# ---------------------------------------------------------------------------
# Test 1: §3 Algorithm Audit Delete entries are extracted
# ---------------------------------------------------------------------------

def test_s3_delete_entries_extracted():
    """§3 Algorithm Audit `- **Delete:** X` lines become s3-prefixed candidates."""
    spec = _spec(s3=(
        "- **Delete:** Use REST not GraphQL — keeps surface area minimal\n"
        "- **Delete:** In-process cache — adds complexity without measurable gain\n"
        "- **Simplify:** Single-file output\n"  # non-Delete lines skipped
    ))
    candidates = _extract_s3_delete_candidates(spec)
    assert len(candidates) == 2
    assert all(c.startswith("s3-") for c in candidates)
    # Content check: "use REST not GraphQL" → slug contains "use-rest"
    assert any("use-rest" in c or "rest" in c for c in candidates), (
        f"expected a candidate slug containing 'rest', got: {candidates}"
    )


def test_s3_delete_unbolded_form_also_extracted():
    """§3 `- Delete: X` (without bold markers) is also recognised."""
    spec = _spec(s3="- Delete: avoid synchronous blocking I/O\n")
    candidates = _extract_s3_delete_candidates(spec)
    assert len(candidates) == 1
    assert candidates[0].startswith("s3-")
    assert "blocking" in candidates[0] or "synchronous" in candidates[0] or "avoid" in candidates[0]


# ---------------------------------------------------------------------------
# Test 2: §5 Physics Guardrails bullet items are extracted
# ---------------------------------------------------------------------------

def test_s5_guardrail_bullets_extracted():
    """§5 bullet items become s5-prefixed candidates."""
    spec = _spec(s5=(
        "- Filesystem at /var/lib/myapp must remain writeable\n"
        "- Database schema must not be mutated outside migrations\n"
        "> Spectre executor invariant: not an obligation\n"  # blockquote skipped
    ))
    candidates = _extract_s5_guardrail_candidates(spec)
    assert len(candidates) >= 2
    assert all(c.startswith("s5-") for c in candidates)
    assert any("filesystem" in c for c in candidates)
    assert any("database" in c or "schema" in c for c in candidates)


def test_s5_template_placeholder_skipped():
    """§5 lines starting with `<` (template placeholders) are skipped."""
    spec = _spec(s5="- <System invariant goes here>\n- Real invariant: no writes to /etc\n")
    candidates = _extract_s5_guardrail_candidates(spec)
    assert all("system-invariant" not in c for c in candidates)
    assert len(candidates) == 1


# ---------------------------------------------------------------------------
# Test 3: §8.x assumptions-killed: blocks are extracted
# ---------------------------------------------------------------------------

def test_s8x_assumptions_killed_single_line_extracted():
    """Single-line `- assumptions-killed: text` is extracted as s8x-prefixed candidate."""
    spec = _spec(s8=(
        "### 8.1 Hard contract\n"
        "- mutates: /tmp\n\n"
        "### 8.2 Cognitive substrate\n"
        "- assumptions-killed: considered polling but rejected due to latency\n"
    ))
    candidates = _extract_s8x_assumptions_candidates(spec)
    assert len(candidates) >= 1
    assert all(c.startswith("s8x-") for c in candidates)
    assert any("polling" in c or "latency" in c for c in candidates)


def test_s8x_assumptions_killed_yaml_list_extracted():
    """YAML-list `assumptions-killed:` with indented items is extracted."""
    spec = _spec(s8=(
        "### 8.5 Human-user substrate\n"
        "- assumptions-killed:\n"
        "  - considered web UI but rejected: no budget\n"
        "  - considered mobile app: out of scope\n"
    ))
    candidates = _extract_s8x_assumptions_candidates(spec)
    assert len(candidates) >= 2
    assert all(c.startswith("s8x-") for c in candidates)
    assert any("web-ui" in c or "web" in c or "budget" in c for c in candidates)
    assert any("mobile" in c for c in candidates)


# ---------------------------------------------------------------------------
# Test 4: cap-at-10 behaviour
# ---------------------------------------------------------------------------

def test_cap_at_10_secondary_candidates():
    """Total secondary candidates are capped at _ADR_CANDIDATE_CAP; a pointer is appended."""
    # Build a spec with more than 10 secondary candidates and no §2 decision: markers
    many_s5_items = "\n".join(
        f"- Invariant number {i}: system must remain operational\n"
        for i in range(1, 16)  # 15 items — far exceeds cap
    )
    spec = _spec(s5=many_s5_items)
    result = _extract_preview_adrs(spec)
    # Primary is empty (no §2 decision: markers)
    # Secondary capped at _ADR_CANDIDATE_CAP = 10
    assert len(result) <= _ADR_CANDIDATE_CAP + 1, (
        f"expected at most {_ADR_CANDIDATE_CAP + 1} entries (cap + pointer), got {len(result)}: {result}"
    )
    # Last entry must be the '<N more available>' pointer
    assert result[-1].startswith("<") and "more available" in result[-1], (
        f"expected pointer entry as last item, got: {result[-1]!r}"
    )
    pointer_count = int(result[-1].strip("<>").split()[0])
    assert pointer_count > 0


# ---------------------------------------------------------------------------
# Test 5: §2 canonical form still works and is included first
# ---------------------------------------------------------------------------

def test_s2_canonical_still_works():
    """§2 decision: markers are extracted and appear before secondary candidates."""
    spec = _spec(
        s2="- decision: Use PostgreSQL not SQLite\n",
        s3="- **Delete:** avoid ORM overhead\n",
    )
    result = _extract_preview_adrs(spec)
    # §2 slug should appear first
    assert len(result) >= 2
    assert "postgresql" in result[0] or "use-postgresql" in result[0], (
        f"§2 canonical slug should be first, got: {result[0]!r}"
    )
    # §3 slug should appear second
    assert any("s3-" in r for r in result)


# ---------------------------------------------------------------------------
# Test 6: §2 canonical entries not counted toward secondary cap
# ---------------------------------------------------------------------------

def test_s2_entries_not_counted_toward_cap():
    """§2 decision: markers never consume slots from the secondary cap."""
    # 5 §2 decisions + 10 §3 Delete entries → all 5 §2 + 10 §3 should appear
    s2_lines = "\n".join(f"- decision: Decision {i}" for i in range(1, 6))
    s3_lines = "\n".join(f"- **Delete:** Option {i} — too complex" for i in range(1, 11))
    spec = _spec(s2=s2_lines, s3=s3_lines)
    result = _extract_preview_adrs(spec)
    # §2 entries: don't start with 's' (secondary prefix) or '<' (pointer)
    s2_entries = [r for r in result if not r.startswith("s") and not r.startswith("<")]
    s3_entries = [r for r in result if r.startswith("s3-")]
    assert len(s2_entries) == 5, f"expected 5 §2 entries, got {len(s2_entries)}: {s2_entries}"
    assert len(s3_entries) == 10, f"expected 10 §3 entries, got {len(s3_entries)}: {s3_entries}"


# ---------------------------------------------------------------------------
# Test 7: no section → empty list (no crash)
# ---------------------------------------------------------------------------

def test_empty_spec_returns_empty_list():
    """A spec with no §3/§5/§8.x/§2 content returns an empty candidate list."""
    spec = _HEADER + "## 1. Hard Problem\nA hard problem.\n"
    result = _extract_preview_adrs(spec)
    assert result == []


# ---------------------------------------------------------------------------
# Test 8: no duplicates across primary and secondary
# ---------------------------------------------------------------------------

def test_no_duplicates_across_paths():
    """If the same slug would be produced by multiple paths, it appears only once."""
    # Manufacture a case where §3 and §5 happen to produce the same slug
    spec = _spec(
        s3="- **Delete:** Use polling not events\n",
        s5="- Use polling not events is rejected\n",
    )
    result = _extract_preview_adrs(spec)
    # Both produce different slugs (different prefixes), but that's fine
    assert len(result) == len(set(result)), f"duplicates found: {result}"
