"""Tests for bin/spec_evaluator.py — review-bundle orchestrator.

TDD: all tests written before implementation.
Pragma guard: no _rejects_/_raises_/_refuses_ names without pytest.raises.
One assertion per test.
"""
import hashlib
import json
import os
import pathlib
import tempfile
from unittest.mock import MagicMock, patch

import pytest

from bin import findings as _findings
from bin import spec_evaluator

# ── Fixture helpers ────────────────────────────────────────────────────────────

FIXTURES = pathlib.Path(__file__).parent / "fixtures" / "specs"
_GOOD_MINIMAL = FIXTURES / "good_minimal.spec.md"


def _make_spec(tmp_path: pathlib.Path, body: str) -> pathlib.Path:
    """Write a minimal spec to a temp file and return its path."""
    p = tmp_path / "test.spec.md"
    p.write_text(body, encoding="utf-8")
    return p


def _minimal_spec_text() -> str:
    return _GOOD_MINIMAL.read_text(encoding="utf-8")


# ── 1. evaluate() returns EvaluatorResult ─────────────────────────────────────


def test_evaluate_returns_evaluator_result(tmp_path):
    result = spec_evaluator.evaluate(_GOOD_MINIMAL, bundle_persist_dir=tmp_path)
    assert isinstance(result, spec_evaluator.EvaluatorResult)


# ── 2. aggregates Tier 1 + Tier 2 when no config ──────────────────────────────


def test_evaluate_aggregates_tier1_and_tier2_findings_when_no_config(tmp_path):
    """Both tiers run; result is a list (may be empty on a good spec)."""
    result = spec_evaluator.evaluate(_GOOD_MINIMAL, config_path=None, bundle_persist_dir=tmp_path)
    assert isinstance(result.findings, list)


# ── 3. Tier 3 skipped when config_path is None ────────────────────────────────


def test_evaluate_skips_tier3_when_config_path_is_none(tmp_path):
    """When config_path is None, no Tier 3 findings appear in result."""
    draft_path = tmp_path / "test.spec.md.draft"
    import shutil
    shutil.copy(_GOOD_MINIMAL, draft_path)
    result = spec_evaluator.evaluate(draft_path, config_path=None, bundle_persist_dir=tmp_path)
    assert not any(f.tier == 3 for f in result.findings)


# ── 4. Tier 3 runs when config enables it ─────────────────────────────────────


def test_evaluate_runs_tier3_when_config_enabled(tmp_path):
    """Mock llm_judge.evaluate to return 1 finding; assert it appears in result."""
    toml_text = b"[tier3]\nenabled = true\napi_key_env = \"DEEPSEEK_API_KEY\"\nmodel = \"deepseek-v4-pro\"\n"
    config_path = tmp_path / "reviewer.toml"
    config_path.write_bytes(toml_text)

    mock_finding = _findings.Finding(
        tier=3,
        kind="tier3-context-gap",
        severity="info",
        location=_findings.FindingLocation(scope="spec-wide"),
        message="Mock Tier 3 finding",
        dismissable=True,
    )

    with patch("bin.llm_judge.evaluate", return_value=[mock_finding]):
        result = spec_evaluator.evaluate(
            _GOOD_MINIMAL, config_path=config_path, bundle_persist_dir=tmp_path
        )
    assert any(f.tier == 3 for f in result.findings)


# ── 5–7. max_severity aggregation ────────────────────────────────────────────


def test_evaluate_max_severity_returns_block_when_any_finding_blocks(tmp_path):
    """Force a block finding by using a spec with missing-why."""
    spec_path = FIXTURES / "missing_why.spec.md"
    result = spec_evaluator.evaluate(spec_path, config_path=None, bundle_persist_dir=tmp_path)
    assert result.max_severity == "block"


def test_evaluate_max_severity_returns_warn_when_no_block_present(tmp_path):
    """Spec with only warn findings → max = warn.

    We mock both tiers to control severity output.
    """
    warn_finding = _findings.Finding(
        tier=1,
        kind="action-not-probed",
        severity="warn",
        location=_findings.FindingLocation(scope="step", step=1, ref="verification"),
        message="Step 1 action paths not in verification",
    )
    with (
        patch("bin.spec_ast.classify", return_value=[warn_finding]),
        patch("bin.coverage_gate.classify", return_value=[]),
    ):
        result = spec_evaluator.evaluate(
            _GOOD_MINIMAL, config_path=None, bundle_persist_dir=tmp_path
        )
    assert result.max_severity == "warn"


def test_evaluate_max_severity_returns_info_when_only_info_findings(tmp_path):
    """When both tiers return no findings → max_severity defaults to 'info'."""
    with (
        patch("bin.spec_ast.classify", return_value=[]),
        patch("bin.coverage_gate.classify", return_value=[]),
    ):
        result = spec_evaluator.evaluate(
            _GOOD_MINIMAL, config_path=None, bundle_persist_dir=tmp_path
        )
    assert result.max_severity == "info"


# ── 8. build_bundle returns ReviewBundle with correct hash ────────────────────


def test_build_bundle_returns_review_bundle_with_correct_hash():
    bundle = spec_evaluator.build_bundle(_GOOD_MINIMAL)
    text = _GOOD_MINIMAL.read_text(encoding="utf-8").replace("\r\n", "\n").replace("\r", "\n")
    expected = hashlib.sha256(text.encode()).hexdigest()
    assert bundle.draft_sha256 == expected


# ── 9. build_bundle extracts preview ADRs from decision: markers ──────────────


def test_build_bundle_extracts_preview_adrs_from_decision_markers(tmp_path):
    """A spec with a 'decision:' line in §2 produces a non-empty preview_adrs list."""
    spec_path = FIXTURES / "decision_without_adr.spec.md"
    bundle = spec_evaluator.build_bundle(spec_path)
    assert isinstance(bundle.preview_adrs, list)


# ── 10. build_bundle deduplicates preview_resources by id ────────────────────


def test_build_bundle_extracts_preview_resources_dedupes_by_id(tmp_path):
    """Two steps with the same port produce only one resource entry."""
    body = _minimal_spec_text().replace(
        'action: "install -m 0755 hello /opt/hello/hello"',
        'action: "python3 -m http.server 9100"',
    ).replace(
        'action: "cp hello.service /etc/systemd/system/hello.service && systemctl daemon-reload"',
        'action: "python3 -m http.server 9100"',
    )
    spec_path = tmp_path / "dup_port.spec.md"
    spec_path.write_text(body, encoding="utf-8")
    bundle = spec_evaluator.build_bundle(spec_path)
    ids = [r["id"] for r in bundle.preview_resources]
    assert ids.count("res-port-9100") <= 1


# ── 11. build_bundle extracts tier classifications per step ───────────────────


def test_build_bundle_extracts_tier_classifications_per_step():
    bundle = spec_evaluator.build_bundle(_GOOD_MINIMAL)
    assert isinstance(bundle.preview_tier_classifications, dict)


# ── 12–13. bundle is persisted to disk ────────────────────────────────────────


def test_evaluate_persists_bundle_to_disk(tmp_path):
    bundle_path = tmp_path / ".eval-bundle.json"
    spec_evaluator.evaluate(_GOOD_MINIMAL, bundle_persist_dir=tmp_path)
    assert bundle_path.exists()


def test_evaluate_persisted_bundle_includes_draft_sha256(tmp_path):
    spec_evaluator.evaluate(_GOOD_MINIMAL, bundle_persist_dir=tmp_path)
    bundle_path = tmp_path / ".eval-bundle.json"
    data = json.loads(bundle_path.read_text(encoding="utf-8"))
    assert "draft_sha256" in data


# ── 14–16. load_persisted_bundle ─────────────────────────────────────────────


def test_load_persisted_bundle_returns_bundle_when_hash_matches(tmp_path):
    result = spec_evaluator.evaluate(_GOOD_MINIMAL, bundle_persist_dir=tmp_path)
    bundle_path = tmp_path / ".eval-bundle.json"
    loaded = spec_evaluator.load_persisted_bundle(
        bundle_path, result.bundle.draft_sha256, draft_path=_GOOD_MINIMAL
    )
    assert loaded is not None


def test_load_persisted_bundle_returns_none_when_hash_mismatches(tmp_path):
    spec_evaluator.evaluate(_GOOD_MINIMAL, bundle_persist_dir=tmp_path)
    bundle_path = tmp_path / ".eval-bundle.json"
    loaded = spec_evaluator.load_persisted_bundle(
        bundle_path, "deadbeef" * 8, draft_path=_GOOD_MINIMAL
    )
    assert loaded is None


def test_load_persisted_bundle_returns_none_when_file_missing(tmp_path):
    missing = tmp_path / ".eval-bundle.json"
    loaded = spec_evaluator.load_persisted_bundle(
        missing, "anyhash", draft_path=_GOOD_MINIMAL
    )
    assert loaded is None


# ── 17–18. clear_bundle ───────────────────────────────────────────────────────


def test_clear_bundle_removes_file(tmp_path):
    bundle_path = tmp_path / ".eval-bundle.json"
    bundle_path.write_text("{}", encoding="utf-8")
    spec_evaluator.clear_bundle(bundle_path)
    assert not bundle_path.exists()


def test_clear_bundle_is_idempotent_when_file_absent(tmp_path):
    bundle_path = tmp_path / ".eval-bundle.json"
    spec_evaluator.clear_bundle(bundle_path)  # must not raise
    assert not bundle_path.exists()


# ── 19–20. parse_dismissals ───────────────────────────────────────────────────


def test_parse_dismissals_returns_list_of_fingerprints_and_reasons():
    fp = "a" * 64
    text = f'# tier3-dismissed: {fp} "context gap not applicable"\n'
    result = spec_evaluator.parse_dismissals(text)
    assert result == [{"fingerprint": fp, "reason": "context gap not applicable"}]


def test_parse_dismissals_returns_empty_when_no_dismissed_block():
    text = "# some other comment\nno dismissals here\n"
    result = spec_evaluator.parse_dismissals(text)
    assert result == []


# ── 21. evaluate filters dismissed Tier 3 findings ───────────────────────────


def test_evaluate_filters_dismissed_tier3_findings(tmp_path):
    """Tier 3 finding with known fingerprint + dismissal in spec text is excluded."""
    tier3_finding = _findings.Finding(
        tier=3,
        kind="tier3-context-gap",
        severity="info",
        location=_findings.FindingLocation(scope="spec-wide"),
        message="Context gap finding to be dismissed",
        dismissable=True,
    )
    fp = _findings.fingerprint(tier3_finding)

    # Write a spec that includes the dismissal marker
    base = _minimal_spec_text()
    augmented = base + f'\n# tier3-dismissed: {fp} "test reason"\n'
    spec_path = tmp_path / "dismissed.spec.md"
    spec_path.write_text(augmented, encoding="utf-8")

    toml_text = b"[tier3]\nenabled = true\napi_key_env = \"DEEPSEEK_API_KEY\"\nmodel = \"deepseek-v4-pro\"\n"
    config_path = tmp_path / "reviewer.toml"
    config_path.write_bytes(toml_text)

    with patch("bin.llm_judge.evaluate", return_value=[tier3_finding]):
        result = spec_evaluator.evaluate(
            spec_path, config_path=config_path, bundle_persist_dir=tmp_path
        )
    assert not any(
        f.tier == 3 and f.kind == "tier3-context-gap" for f in result.findings
    )


# ── 22. non-dismissable findings are not filtered even if fingerprint matches ─


def test_evaluate_does_not_filter_non_dismissable_findings(tmp_path):
    """Tier 1 finding with dismissable=False is never filtered by dismissals."""
    tier1_finding = _findings.Finding(
        tier=1,
        kind="missing-why",
        severity="block",
        location=_findings.FindingLocation(scope="step", step=1, ref="why"),
        message="Step 1 is missing the required why: field.",
        dismissable=False,
    )
    fp = _findings.fingerprint(tier1_finding)

    base = _minimal_spec_text()
    augmented = base + f'\n# tier3-dismissed: {fp} "should not matter"\n'
    spec_path = tmp_path / "nondismissable.spec.md"
    spec_path.write_text(augmented, encoding="utf-8")

    with (
        patch("bin.spec_ast.classify", return_value=[tier1_finding]),
        patch("bin.coverage_gate.classify", return_value=[]),
    ):
        result = spec_evaluator.evaluate(
            spec_path, config_path=None, bundle_persist_dir=tmp_path
        )
    assert any(f.kind == "missing-why" for f in result.findings)


# ── 23–25. sidecar_payload ────────────────────────────────────────────────────


def test_sidecar_payload_includes_evaluator_version(tmp_path):
    result = spec_evaluator.evaluate(_GOOD_MINIMAL, bundle_persist_dir=tmp_path)
    assert "evaluator_version" in result.sidecar_payload


def test_sidecar_payload_includes_tiers_run(tmp_path):
    result = spec_evaluator.evaluate(_GOOD_MINIMAL, bundle_persist_dir=tmp_path)
    assert "tiers_run" in result.sidecar_payload


def test_sidecar_payload_dismissals_count_matches_parse_dismissals(tmp_path):
    """sidecar_payload dismissals list has same length as parse_dismissals output."""
    result = spec_evaluator.evaluate(_GOOD_MINIMAL, bundle_persist_dir=tmp_path)
    text = _GOOD_MINIMAL.read_text(encoding="utf-8").replace("\r\n", "\n").replace("\r", "\n")
    expected_dismissals = spec_evaluator.parse_dismissals(text)
    assert len(result.sidecar_payload.get("dismissals", [])) == len(expected_dismissals)


# ── 26. CRITICAL #2: invalid severity override raises ValueError ───────────────


def test_evaluate_raises_value_error_on_invalid_severity_override(tmp_path):
    """A typo'd severity in [severity_overrides] raises ValueError from evaluate()."""
    toml_text = b"[tier3]\nenabled = false\n\n[severity_overrides]\nmissing-why = \"bloock\"\n"
    config_path = tmp_path / "bad_override.toml"
    config_path.write_bytes(toml_text)
    with pytest.raises(ValueError):
        spec_evaluator.evaluate(
            _GOOD_MINIMAL, config_path=config_path, bundle_persist_dir=tmp_path
        )


# ── 27. IMPORTANT #1: missing config_path emits info finding ─────────────────


def test_evaluate_emits_info_finding_when_config_path_does_not_exist(tmp_path):
    """When config_path is provided but file absent, result contains tier3-unavailable info finding."""
    absent_config = tmp_path / "nonexistent.toml"
    result = spec_evaluator.evaluate(
        _GOOD_MINIMAL, config_path=absent_config, bundle_persist_dir=tmp_path
    )
    assert any(f.kind == "tier3-unavailable" and f.severity == "info" for f in result.findings)


# ── 28. IMPORTANT #2: dismissed_t3_count reflects actually filtered findings ──


def test_dismissed_t3_count_reflects_actually_filtered_findings_not_dismissal_lines(tmp_path):
    """2 dismissal lines but only 1 matching Tier 3 finding → dismissed_t3_count == 1."""
    tier3_finding = _findings.Finding(
        tier=3,
        kind="tier3-context-gap",
        severity="info",
        location=_findings.FindingLocation(scope="spec-wide"),
        message="Context gap finding to be dismissed",
        dismissable=True,
    )
    fp_real = _findings.fingerprint(tier3_finding)
    fp_stale = "b" * 64  # stale dismissal that matches no finding

    base = _minimal_spec_text()
    augmented = (
        base
        + f'\n# tier3-dismissed: {fp_real} "valid dismissal"\n'
        + f'# tier3-dismissed: {fp_stale} "stale dismissal"\n'
    )
    spec_path = tmp_path / "two_dismissals.spec.md"
    spec_path.write_text(augmented, encoding="utf-8")

    toml_text = b"[tier3]\nenabled = true\napi_key_env = \"DEEPSEEK_API_KEY\"\nmodel = \"deepseek-v4-pro\"\n"
    config_path = tmp_path / "reviewer.toml"
    config_path.write_bytes(toml_text)

    with patch("bin.llm_judge.evaluate", return_value=[tier3_finding]):
        result = spec_evaluator.evaluate(
            spec_path, config_path=config_path, bundle_persist_dir=tmp_path
        )
    assert result.sidecar_payload["findings_summary"]["dismissed_t3_count"] == 1
