"""Integration test for dismissal pipeline: dismiss → re-run → skip finding flow.

This test validates the full end-to-end dismissal system as per Plan A v0.3,
Copilot review #2 TDD-ordering correction (Task 9.5).

Scenarios:
- Scenario A: Non-dismissable Tier 1 finding survives dismissal block
  (fingerprint match does not filter dismissable=False findings).
- Scenario B: Dismissable Tier 3 findings ARE filtered when fingerprint matches.

All tests single-assertion only (pytest.raises or bare assert).
"""
import pathlib
import tempfile
from unittest import mock

import pytest

from bin import spec_evaluator
from bin import findings
from bin import llm_judge


# ── Test fixtures ─────────────────────────────────────────────────────────────

def _make_minimal_draft_missing_section_8() -> str:
    """Return a minimal valid spec that triggers missing-receiver-calibration.

    Tier 1 finding kind='missing-receiver-calibration', dismissable=False.
    """
    return """\
# Example Spec

## 1. Goal
Deploy a service.

## 2. First Principles
- decision: deploy-method
- decision: monitoring-approach

## 3. Success Criteria
- System up

## 4. Blast Radius
- Limited to test env

## 5. Resources
- Example: "server-1"

## 6. Steps
```yaml
- step: 1
  why: "Start the service"
  action: "echo hello"
  verification: "true"
```

## 7. Rollback
Do nothing.
"""


def _make_synthetic_tier3_finding(fingerprint_input: str | None = None) -> findings.Finding:
    """Create a synthetic Tier 3 finding with dismissable=True for testing.

    If fingerprint_input is provided, the returned finding will have a specific
    message/location that produces that fingerprint. For testing, we use a
    simple approach: create finding with known fields.
    """
    return findings.Finding(
        tier=3,
        kind="tier3-context-gap",
        severity="warn",
        location=findings.FindingLocation(scope="spec-wide"),
        message="Test context gap finding",
        suggested_fix="Add missing context",
        dismissable=True,
    )


def _mock_llm_judge_evaluate(
    spec_text: str,
    *,
    config: llm_judge.JudgeConfig,
    step_objects=None,
    contract_resolution=None,
) -> list[findings.Finding]:
    """Mocked version of llm_judge.evaluate that returns a single Tier 3 finding."""
    return [_make_synthetic_tier3_finding()]


# ── Scenario A: Non-dismissable finding survives dismissal ────────────────────

def test_non_dismissable_finding_survives_matching_dismissal_block():
    """Tier 1 missing-receiver-calibration has dismissable=False.

    Even when a dismissal block with matching fingerprint exists,
    the finding is NOT filtered out.
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir = pathlib.Path(tmpdir)
        draft_path = tmpdir / "spec.md"

        # Step 1: Create draft missing §8
        spec_text = _make_minimal_draft_missing_section_8()
        draft_path.write_text(spec_text, encoding="utf-8")

        # Step 2: Evaluate to get the finding
        result1 = spec_evaluator.evaluate(
            draft_path,
            config_path=None,
            bundle_persist_dir=tmpdir / "state",
        )

        # Find the missing-receiver-calibration finding
        mcr_findings = [f for f in result1.findings if f.kind == "missing-receiver-calibration"]
        assert len(mcr_findings) > 0

        mcr_finding = mcr_findings[0]
        assert mcr_finding.dismissable is False, "Tier 1 missing-receiver-calibration should not be dismissable"

        # Step 3: Compute fingerprint
        fp = findings.fingerprint(mcr_finding)
        assert len(fp) == 64, "Fingerprint should be SHA-256 hex (64 chars)"

        # Step 4: Add dismissal block to draft
        dismissal_line = f'# tier3-dismissed: {fp} "test reason"\n'
        new_spec_text = spec_text + "\n" + dismissal_line
        draft_path.write_text(new_spec_text, encoding="utf-8")

        # Step 5: Re-evaluate
        result2 = spec_evaluator.evaluate(
            draft_path,
            config_path=None,
            bundle_persist_dir=tmpdir / "state",
        )

        # Step 6: Assert finding still present (not filtered)
        mcr_findings_2 = [f for f in result2.findings if f.kind == "missing-receiver-calibration"]
        assert len(mcr_findings_2) > 0, "Non-dismissable finding should NOT be filtered by dismissal block"


def test_dismissable_finding_is_filtered_when_fingerprint_matches():
    """Tier 3 findings with dismissable=True ARE filtered when fingerprint matches.

    Uses mocking to inject a Tier 3 finding.
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir = pathlib.Path(tmpdir)
        draft_path = tmpdir / "spec.md"

        # Create a minimal valid spec (can contain §8 to avoid Tier 1 blocks)
        spec_with_s8 = _make_minimal_draft_missing_section_8() + "\n## 8. Receiver Calibration\n### 8.1\nmutates: {}\nnever-touches: {}\ndecision-budget: n/a\nreboot-survival: false\n"
        draft_path.write_text(spec_with_s8, encoding="utf-8")

        # Step 1: Mock llm_judge.evaluate to return a Tier 3 finding
        tier3_finding = _make_synthetic_tier3_finding()
        fp = findings.fingerprint(tier3_finding)

        # Step 2: Add matching dismissal block
        dismissal_line = f'# tier3-dismissed: {fp} "test dismissal"\n'
        draft_text = spec_with_s8 + dismissal_line
        draft_path.write_text(draft_text, encoding="utf-8")

        # Step 3: Create config that enables Tier 3
        config_path = tmpdir / "eval.toml"
        config_path.write_text("[tier3]\nenabled = true\n", encoding="utf-8")

        # Step 4: Patch llm_judge.evaluate (used inside evaluate function)
        with mock.patch("bin.llm_judge.evaluate", side_effect=_mock_llm_judge_evaluate):
            result = spec_evaluator.evaluate(
                draft_path,
                config_path=config_path,
                bundle_persist_dir=tmpdir / "state",
            )

        # Step 5: Assert Tier 3 finding is filtered out (not in result)
        tier3_findings = [f for f in result.findings if f.tier == 3]
        assert len(tier3_findings) == 0, f"Tier 3 finding should be filtered when fingerprint matches; got {tier3_findings}"


# ── Scenario B: Dismissable finding kept when fingerprint differs ──────────────

def test_dismissable_finding_is_kept_when_fingerprint_differs():
    """Tier 3 finding with fingerprint X, but dismissal block has fingerprint Y.

    The finding is kept (NOT filtered).
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir = pathlib.Path(tmpdir)
        draft_path = tmpdir / "spec.md"

        spec_with_s8 = _make_minimal_draft_missing_section_8() + "\n## 8. Receiver Calibration\n### 8.1\nmutates: {}\nnever-touches: {}\ndecision-budget: n/a\nreboot-survival: false\n"

        # Add dismissal with DIFFERENT fingerprint (not matching the Tier 3 finding)
        wrong_fp = "0" * 64
        dismissal_line = f'# tier3-dismissed: {wrong_fp} "different fp"\n'
        draft_text = spec_with_s8 + dismissal_line
        draft_path.write_text(draft_text, encoding="utf-8")

        config_path = tmpdir / "eval.toml"
        config_path.write_text("[tier3]\nenabled = true\n", encoding="utf-8")

        with mock.patch("bin.llm_judge.evaluate", side_effect=_mock_llm_judge_evaluate):
            result = spec_evaluator.evaluate(
                draft_path,
                config_path=config_path,
                bundle_persist_dir=tmpdir / "state",
            )

        # Tier 3 finding should be present (wrong fingerprint doesn't match)
        tier3_findings = [f for f in result.findings if f.tier == 3]
        assert len(tier3_findings) > 0, "Tier 3 finding should NOT be filtered when dismissal fp differs"


# ── Sidecar payload validation ────────────────────────────────────────────────

def test_dismissals_recorded_in_sidecar_payload():
    """Dismissal blocks are parsed and recorded in result.sidecar_payload."""
    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir = pathlib.Path(tmpdir)
        draft_path = tmpdir / "spec.md"

        spec_with_s8 = _make_minimal_draft_missing_section_8() + "\n## 8. Receiver Calibration\n### 8.1\nmutates: {}\nnever-touches: {}\ndecision-budget: n/a\nreboot-survival: false\n"

        # Add two dismissal blocks
        fp1 = "a" * 64
        fp2 = "b" * 64
        dismissal_lines = (
            f'# tier3-dismissed: {fp1} "reason 1"\n'
            f'# tier3-dismissed: {fp2} "reason 2"\n'
        )
        draft_text = spec_with_s8 + dismissal_lines
        draft_path.write_text(draft_text, encoding="utf-8")

        result = spec_evaluator.evaluate(
            draft_path,
            config_path=None,
            bundle_persist_dir=tmpdir / "state",
        )

        # Assert dismissals in sidecar_payload
        assert "dismissals" in result.sidecar_payload
        dismissals = result.sidecar_payload["dismissals"]
        assert len(dismissals) == 2
        assert dismissals[0]["fingerprint"] == fp1
        assert dismissals[0]["reason"] == "reason 1"
        assert dismissals[1]["fingerprint"] == fp2
        assert dismissals[1]["reason"] == "reason 2"


# ── Dismissed count accuracy ──────────────────────────────────────────────────

def test_actually_dismissed_count_matches_filtered_count_not_dismissal_lines():
    """dismissed_t3_count in sidecar reflects actual filtered findings, not dismissal lines.

    If there are 3 dismissal lines but only 1 matching Tier 3 finding,
    dismissed_t3_count == 1 (not 3).
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir = pathlib.Path(tmpdir)
        draft_path = tmpdir / "spec.md"

        spec_with_s8 = _make_minimal_draft_missing_section_8() + "\n## 8. Receiver Calibration\n### 8.1\nmutates: {}\nnever-touches: {}\ndecision-budget: n/a\nreboot-survival: false\n"

        # Mock Tier 3 to return 1 dismissable finding
        tier3_finding = _make_synthetic_tier3_finding()
        actual_fp = findings.fingerprint(tier3_finding)

        # Add 2 dismissals: 1 matching, 1 not
        matching_dismissal = f'# tier3-dismissed: {actual_fp} "matches"\n'
        non_matching_dismissal = f'# tier3-dismissed: {"f" * 64} "does not match"\n'

        draft_text = spec_with_s8 + matching_dismissal + non_matching_dismissal
        draft_path.write_text(draft_text, encoding="utf-8")

        config_path = tmpdir / "eval.toml"
        config_path.write_text("[tier3]\nenabled = true\n", encoding="utf-8")

        with mock.patch("bin.llm_judge.evaluate", side_effect=_mock_llm_judge_evaluate):
            result = spec_evaluator.evaluate(
                draft_path,
                config_path=config_path,
                bundle_persist_dir=tmpdir / "state",
            )

        # Only 1 finding was actually dismissed (the matching one)
        assert result.sidecar_payload["findings_summary"]["dismissed_t3_count"] == 1


# ── Idempotency ───────────────────────────────────────────────────────────────

def test_dismissal_block_does_not_corrupt_subsequent_evaluate_calls():
    """Running evaluate twice on the same draft with dismissals is idempotent.

    Two consecutive calls produce identical result.findings.
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir = pathlib.Path(tmpdir)
        draft_path = tmpdir / "spec.md"

        spec_with_s8 = _make_minimal_draft_missing_section_8() + "\n## 8. Receiver Calibration\n### 8.1\nmutates: {}\nnever-touches: {}\ndecision-budget: n/a\nreboot-survival: false\n"

        fp = "c" * 64
        dismissal_line = f'# tier3-dismissed: {fp} "reason"\n'
        draft_text = spec_with_s8 + dismissal_line
        draft_path.write_text(draft_text, encoding="utf-8")

        # Run twice
        result1 = spec_evaluator.evaluate(
            draft_path,
            config_path=None,
            bundle_persist_dir=tmpdir / "state",
        )
        result2 = spec_evaluator.evaluate(
            draft_path,
            config_path=None,
            bundle_persist_dir=tmpdir / "state",
        )

        # Results should be identical
        assert len(result1.findings) == len(result2.findings)
        for f1, f2 in zip(result1.findings, result2.findings):
            assert f1.tier == f2.tier
            assert f1.kind == f2.kind
            assert f1.severity == f2.severity


# ── Invalid dismissal format ──────────────────────────────────────────────────

def test_dismissal_with_invalid_fingerprint_format_ignored():
    """Dismissal block with invalid fingerprint (not 64 hex chars) is ignored.

    Parser only matches the regex ^[0-9a-f]{64}; shorter strings don't match.
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir = pathlib.Path(tmpdir)
        draft_path = tmpdir / "spec.md"

        spec_with_s8 = _make_minimal_draft_missing_section_8() + "\n## 8. Receiver Calibration\n### 8.1\nmutates: {}\nnever-touches: {}\ndecision-budget: n/a\nreboot-survival: false\n"

        # Invalid: only 32 hex chars (should be 64)
        invalid_dismissal = '# tier3-dismissed: ' + ('3' * 32) + ' "invalid fp"\n'
        draft_text = spec_with_s8 + invalid_dismissal
        draft_path.write_text(draft_text, encoding="utf-8")

        result = spec_evaluator.evaluate(
            draft_path,
            config_path=None,
            bundle_persist_dir=tmpdir / "state",
        )

        # Invalid dismissal should not be parsed
        assert len(result.sidecar_payload["dismissals"]) == 0
