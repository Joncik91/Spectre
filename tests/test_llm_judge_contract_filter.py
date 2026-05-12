"""Tests for Tier 3 contract-resolution post-filter and related fixes (fix/tier3-contract-aware-filter).

Covers:
1. Deterministic post-filter: missing-producer dropped when artifact is in Tier 1 produces
2. Deterministic post-filter: missing-producer dropped when resolution map shows resolved_by_step
3. Deterministic post-filter: unresolved artifact passes through (not wrongly dropped)
4. Deterministic post-filter: non-missing-producer findings always pass through
5. contract_resolution=None → no filtering (safe default)
6. temperature=0 is sent in every API request
7. evaluate() passes contract_resolution through to the post-filter
8. _extract_missing_artifact: canonical "missing: X; rationale" format
9. _extract_missing_artifact: falls back to empty string on unexpected format
10. spec_evaluator passes step_objects + contract_resolution to llm_judge.evaluate
"""
import json
from unittest import mock

import pytest

from bin import llm_judge
from bin import findings


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_CFG = llm_judge.JudgeConfig(
    enabled=True,
    api_key_env="TEST_DEEPSEEK_KEY",
    model="deepseek-v4-flash",
)


def _api_resp(content: str) -> mock.MagicMock:
    payload = json.dumps(
        {"choices": [{"message": {"content": content}}]}
    ).encode()
    resp = mock.MagicMock()
    resp.read.return_value = payload
    resp.__enter__ = mock.Mock(return_value=resp)
    resp.__exit__ = mock.Mock(return_value=None)
    return resp


def _contradiction_resp(tuples: list[dict]) -> mock.MagicMock:
    return _api_resp(json.dumps(tuples))


def _env(monkeypatch) -> None:
    monkeypatch.setenv("TEST_DEEPSEEK_KEY", "fake-key-for-tests")


# A minimal spec with two steps; step 1 produces package:foo, step 2 requires it.
_SPEC_WITH_CONTRACTS = """\
# Test Spec

## 6. Steps

```yaml
- step: 1
  why: install dependency
  action: pip install foo
  verification: python -c "import foo"
  produces:
    - package:foo
- step: 2
  why: use dependency
  action: python app.py
  verification: echo ok
  requires:
    - package:foo
```

## 8. Receiver Calibration

### 8.1 Hard contract

- mutates: /var/app
- never-touches: /etc/passwd
- decision-budget: 2
- reboot-survival: no
"""

# Contract resolution matching the spec above.
_CONTRACT_RESOLUTION = {
    "steps": {
        "1": {
            "produces": ["package:foo"],
            "requires": [],
            "resolution": {},
        },
        "2": {
            "produces": [],
            "requires": ["package:foo"],
            "resolution": {
                "package:foo": {"resolved_by_step": 1},
            },
        },
    }
}


# ---------------------------------------------------------------------------
# 1. missing-producer dropped: artifact present in a prior step's produces list
# ---------------------------------------------------------------------------


def test_post_filter_drops_missing_producer_when_artifact_in_produces():
    """When the artifact is in the contract_resolution produces set, the finding is dropped."""
    # Simulate a missing-producer finding for package:foo (which IS produced by step 1).
    f = findings.Finding(
        tier=3,
        kind="missing-producer",
        severity="block",
        location=findings.FindingLocation(scope="step", step=2),
        message="missing: package:foo; step 2 requires foo but no prior step installs it",
        dismissable=True,
    )

    kept, dropped = llm_judge._drop_resolved_producer_findings([f], _CONTRACT_RESOLUTION)

    assert dropped == [f]
    assert kept == []


# ---------------------------------------------------------------------------
# 2. missing-producer dropped: resolution map shows resolved_by_step
# ---------------------------------------------------------------------------


def test_post_filter_drops_missing_producer_when_resolution_map_resolved():
    """Checks resolution dict path: finding at step 2, resolution shows resolved_by_step=1."""
    # Craft a resolution where produces list is empty but resolution map is present.
    resolution = {
        "steps": {
            "1": {"produces": [], "requires": [], "resolution": {}},
            "2": {
                "produces": [],
                "requires": ["package:bar"],
                "resolution": {"package:bar": {"resolved_by_step": 1}},
            },
        }
    }
    f = findings.Finding(
        tier=3,
        kind="missing-producer",
        severity="block",
        location=findings.FindingLocation(scope="step", step=2),
        message="missing: package:bar; step 2 requires bar but no producer found",
        dismissable=True,
    )

    kept, dropped = llm_judge._drop_resolved_producer_findings([f], resolution)

    assert dropped == [f]
    assert kept == []


# ---------------------------------------------------------------------------
# 3. unresolved artifact passes through (not wrongly dropped)
# ---------------------------------------------------------------------------


def test_post_filter_keeps_genuinely_unresolved_missing_producer():
    """When the artifact truly has no producer, the finding is NOT dropped."""
    resolution = {
        "steps": {
            "1": {"produces": ["package:foo"], "requires": [], "resolution": {}},
            "2": {
                "produces": [],
                "requires": ["package:baz"],
                "resolution": {"package:baz": None},  # None = unresolved
            },
        }
    }
    f = findings.Finding(
        tier=3,
        kind="missing-producer",
        severity="block",
        location=findings.FindingLocation(scope="step", step=2),
        message="missing: package:baz; no step produces it",
        dismissable=True,
    )

    kept, dropped = llm_judge._drop_resolved_producer_findings([f], resolution)

    assert kept == [f]
    assert dropped == []


# ---------------------------------------------------------------------------
# 4. non-missing-producer findings always pass through
# ---------------------------------------------------------------------------


def test_post_filter_never_drops_non_missing_producer_findings():
    """shallow-ownership, adversarial-pathway etc. are not subject to the post-filter."""
    findings_list = [
        findings.Finding(
            tier=3,
            kind="shallow-ownership",
            severity="block",
            location=findings.FindingLocation(scope="step", step=1),
            message="claimed: package:foo; actual: scaffold only",
            dismissable=True,
        ),
        findings.Finding(
            tier=3,
            kind="ambiguous-contract",
            severity="warn",
            location=findings.FindingLocation(scope="step", step=1),
            message="ambiguous: pip install; could be pip or apt",
            dismissable=True,
        ),
    ]

    kept, dropped = llm_judge._drop_resolved_producer_findings(
        findings_list, _CONTRACT_RESOLUTION
    )

    assert kept == findings_list
    assert dropped == []


# ---------------------------------------------------------------------------
# 5. contract_resolution=None → no filtering (safe default)
# ---------------------------------------------------------------------------


def test_post_filter_with_none_resolution_passes_all_through():
    """When contract_resolution is None, the filter is a no-op."""
    f = findings.Finding(
        tier=3,
        kind="missing-producer",
        severity="block",
        location=findings.FindingLocation(scope="step", step=2),
        message="missing: package:foo; rationale",
        dismissable=True,
    )

    kept, dropped = llm_judge._drop_resolved_producer_findings([f], None)

    assert kept == [f]
    assert dropped == []


# ---------------------------------------------------------------------------
# 6. temperature=0 is sent in every API request
# ---------------------------------------------------------------------------


@mock.patch("urllib.request.urlopen")
def test_api_request_includes_temperature_zero(mock_urlopen, monkeypatch):
    """Every call to DeepSeek must include temperature=0 for determinism."""
    _env(monkeypatch)
    mock_urlopen.return_value = _contradiction_resp([])
    llm_judge.evaluate(_SPEC_WITH_CONTRACTS, config=_CFG)
    call_args = mock_urlopen.call_args_list[0]
    req = call_args[0][0]
    body = json.loads(req.data.decode("utf-8"))
    assert body.get("temperature") == 0


# ---------------------------------------------------------------------------
# 7. evaluate() with contract_resolution drops hallucinated missing-producer
# ---------------------------------------------------------------------------


@mock.patch("urllib.request.urlopen")
def test_evaluate_drops_hallucinated_missing_producer_via_contract_resolution(
    mock_urlopen, monkeypatch
):
    """DeepSeek returns missing-producer for package:foo; contract_resolution shows it resolved.
    The finding must be dropped before reaching the caller."""
    _env(monkeypatch)
    tuples = [
        {
            "kind": "missing-producer",
            "consumer_step": 2,
            "missing": "package:foo",
            "rationale": "step 2 uses foo but no prior step installs it",
        }
    ]
    mock_urlopen.return_value = _contradiction_resp(tuples)

    result = llm_judge.evaluate(
        _SPEC_WITH_CONTRACTS,
        config=_CFG,
        contract_resolution=_CONTRACT_RESOLUTION,
    )

    # The missing-producer for package:foo must be dropped (step 1 produces it).
    missing_producer_findings = [f for f in result if f.kind == "missing-producer"]
    assert missing_producer_findings == [], (
        f"Expected 0 missing-producer findings, got {missing_producer_findings}"
    )


# ---------------------------------------------------------------------------
# 8. evaluate() preserves legitimate missing-producer when artifact not in resolution
# ---------------------------------------------------------------------------


@mock.patch("urllib.request.urlopen")
def test_evaluate_keeps_legitimate_missing_producer_when_not_in_resolution(
    mock_urlopen, monkeypatch
):
    """A missing-producer for an artifact NOT in the resolution passes through the filter
    and then goes to the faithfulness check (cite call)."""
    _env(monkeypatch)
    tuples = [
        {
            "kind": "missing-producer",
            "consumer_step": 2,
            "missing": "package:bar",  # NOT produced by any step
            "rationale": "step 2 uses bar but no prior step installs it",
        }
    ]
    # Primary call returns the tuple; cite call returns affirming citation.
    cite_resp = json.dumps([{"index": 0, "step": 2, "citation": "python app.py"}])
    mock_urlopen.side_effect = [
        _contradiction_resp(tuples),
        _api_resp(cite_resp),
    ]

    result = llm_judge.evaluate(
        _SPEC_WITH_CONTRACTS,
        config=_CFG,
        contract_resolution=_CONTRACT_RESOLUTION,
    )

    # package:bar is NOT in any produces list → finding must survive.
    missing_producer_findings = [f for f in result if f.kind == "missing-producer"]
    assert len(missing_producer_findings) == 1


# ---------------------------------------------------------------------------
# 9. _extract_missing_artifact: canonical message format
# ---------------------------------------------------------------------------


def test_extract_missing_artifact_canonical_format():
    """Canonical 'missing: X; rationale' format extracts X correctly."""
    msg = "missing: package:foo; step 2 requires foo but no prior step installs it"
    assert llm_judge._extract_missing_artifact(msg) == "package:foo"


def test_extract_missing_artifact_file_path():
    """Works with file: prefixed artifact names."""
    msg = "missing: file:.vidence/lexicon.json; step 8 reads it but step 1 doesn't produce it"
    assert llm_judge._extract_missing_artifact(msg) == "file:.vidence/lexicon.json"


def test_extract_missing_artifact_no_match_returns_empty():
    """Returns empty string when message doesn't match the pattern."""
    msg = "some other message format without the missing: prefix"
    assert llm_judge._extract_missing_artifact(msg) == ""


def test_extract_missing_artifact_empty_string():
    """Empty string input returns empty string."""
    assert llm_judge._extract_missing_artifact("") == ""


# ---------------------------------------------------------------------------
# 10. spec_evaluator passes step_objects + contract_resolution to llm_judge.evaluate
# ---------------------------------------------------------------------------


def test_spec_evaluator_passes_step_objects_and_contract_resolution_to_tier3(
    tmp_path, monkeypatch
):
    """spec_evaluator.evaluate() must pass step_objects and contract_resolution to
    llm_judge.evaluate() so the step table includes produces/requires fields and the
    post-filter has Tier 1 ground truth."""
    import pathlib
    from bin import spec_evaluator

    spec_content = _SPEC_WITH_CONTRACTS
    spec_file = tmp_path / "test.spec.md"
    spec_file.write_text(spec_content, encoding="utf-8")

    config_content = """\
[tier3]
enabled = true
api_key_env = "TEST_DEEPSEEK_KEY"
model = "deepseek-v4-flash"
"""
    config_file = tmp_path / "reviewer.toml"
    config_file.write_text(config_content, encoding="utf-8")

    monkeypatch.setenv("TEST_DEEPSEEK_KEY", "fake-key-for-tests")

    captured_kwargs: dict = {}

    def _fake_llm_evaluate(spec_text, *, config, step_objects=None, contract_resolution=None):
        captured_kwargs["step_objects"] = step_objects
        captured_kwargs["contract_resolution"] = contract_resolution
        return []

    # _llm_judge is imported lazily inside spec_evaluator; patch the evaluate
    # function on the already-imported llm_judge module.
    import bin.llm_judge as _llm_judge_mod
    monkeypatch.setattr(_llm_judge_mod, "evaluate", _fake_llm_evaluate)

    spec_evaluator.evaluate(
        spec_file,
        config_path=config_file,
        bundle_persist_dir=tmp_path / "state",
    )

    # step_objects must be a non-empty list with produces/requires fields.
    assert captured_kwargs.get("step_objects") is not None
    assert len(captured_kwargs["step_objects"]) > 0
    step1 = next(
        (s for s in captured_kwargs["step_objects"] if s.get("step") == 1), None
    )
    assert step1 is not None
    assert "package:foo" in step1.get("produces", [])

    # contract_resolution must be the Tier 1 resolution dict.
    cr = captured_kwargs.get("contract_resolution")
    assert cr is not None
    assert "steps" in cr
    assert "1" in cr["steps"]
    assert "package:foo" in cr["steps"]["1"]["produces"]


# ---------------------------------------------------------------------------
# Fix 1 — target_artifact field: structured field used by filter when present
# ---------------------------------------------------------------------------


def test_target_artifact_set_when_missing_field_present():
    """_parse_contradiction_findings sets target_artifact when 'missing' field is non-empty."""
    content = json.dumps([
        {
            "kind": "missing-producer",
            "consumer_step": 2,
            "missing": "package:foo",
            "rationale": "step 2 uses foo but no prior step installs it",
        }
    ])
    result = llm_judge._parse_contradiction_findings(content)
    assert len(result) == 1
    assert result[0].target_artifact == "package:foo"


def test_target_artifact_none_when_missing_field_absent():
    """_parse_contradiction_findings sets target_artifact=None when 'missing' field is omitted."""
    content = json.dumps([
        {
            "kind": "missing-producer",
            "consumer_step": 2,
            # no 'missing' field
            "rationale": "step 2 uses foo but no prior step installs it",
        }
    ])
    result = llm_judge._parse_contradiction_findings(content)
    assert len(result) == 1
    assert result[0].target_artifact is None


def test_post_filter_uses_target_artifact_directly_when_set():
    """Filter drops finding via target_artifact without regex-parsing the message."""
    # Craft a finding where the message does NOT contain the canonical prefix
    # but target_artifact IS set — verifies structured field is preferred.
    f = findings.Finding(
        tier=3,
        kind="missing-producer",
        severity="block",
        location=findings.FindingLocation(scope="step", step=2),
        message="step 2 uses foo but no prior step installs it",  # no "missing: X;" prefix
        dismissable=True,
        target_artifact="package:foo",
    )

    kept, dropped = llm_judge._drop_resolved_producer_findings([f], _CONTRACT_RESOLUTION)

    assert dropped == [f], "Finding with target_artifact='package:foo' must be dropped"
    assert kept == []


def test_post_filter_falls_back_to_regex_when_target_artifact_none():
    """When target_artifact is None, filter falls back to regex over the message string."""
    # No target_artifact; message has canonical prefix so regex should match.
    f = findings.Finding(
        tier=3,
        kind="missing-producer",
        severity="block",
        location=findings.FindingLocation(scope="step", step=2),
        message="missing: package:foo; rationale",
        dismissable=True,
        target_artifact=None,
    )

    kept, dropped = llm_judge._drop_resolved_producer_findings([f], _CONTRACT_RESOLUTION)

    assert dropped == [f], "Regex fallback must still drop the finding"
    assert kept == []


@mock.patch("urllib.request.urlopen")
def test_filter_drops_when_missing_field_present_in_tuple(mock_urlopen, monkeypatch):
    """When 'missing' field IS in the tuple, target_artifact is set and filter drops it."""
    _env(monkeypatch)
    tuples = [
        {
            "kind": "missing-producer",
            "consumer_step": 2,
            "missing": "package:foo",
            "rationale": "step 2 uses foo",
        }
    ]
    mock_urlopen.return_value = _contradiction_resp(tuples)

    result = llm_judge.evaluate(
        _SPEC_WITH_CONTRACTS,
        config=_CFG,
        contract_resolution=_CONTRACT_RESOLUTION,
    )

    missing_findings = [f for f in result if f.kind == "missing-producer"]
    assert missing_findings == [], "Should be dropped via target_artifact"


@mock.patch("urllib.request.urlopen")
def test_filter_falls_back_when_missing_field_absent_in_tuple(mock_urlopen, monkeypatch):
    """When 'missing' field is absent, target_artifact=None; regex fallback; finding passes through
    (no artifact name → can't match → survives)."""
    _env(monkeypatch)
    tuples = [
        {
            "kind": "missing-producer",
            "consumer_step": 2,
            # no 'missing' field — model omitted it
            "rationale": "step 2 uses foo but no prior step installs it",
        }
    ]
    # Primary + cite call (cite affirms → finding kept).
    cite_resp = json.dumps([{"index": 0, "step": 2, "citation": "python app.py"}])
    mock_urlopen.side_effect = [
        _contradiction_resp(tuples),
        _api_resp(cite_resp),
    ]

    result = llm_judge.evaluate(
        _SPEC_WITH_CONTRACTS,
        config=_CFG,
        contract_resolution=_CONTRACT_RESOLUTION,
    )

    # No artifact name → regex returns "" → filter can't match → finding survives.
    missing_findings = [f for f in result if f.kind == "missing-producer"]
    assert len(missing_findings) == 1, (
        "Without artifact name, filter cannot match, finding must pass through"
    )
