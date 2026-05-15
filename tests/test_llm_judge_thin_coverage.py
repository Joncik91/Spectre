"""Tests for Fix C: tier3-negative-paths-thin-coverage alongside-finding.

Three cases exercised through llm_judge.evaluate() with mocked HTTP:
  1. Thin fires: negative-path-omission present + step has < 3 negative-paths.
  2. Thick doesn't fire: negative-path-omission present + step has >= 3 negative-paths.
  3. Kind is not negative-path-omission: thin-coverage must not fire.

Mocks urllib.request.urlopen (the real HTTP boundary), calls real llm_judge.evaluate().

Pragma guard: assertion-style names only. One assertion per test.
Tests asserting absence/emptiness use _returns_empty/_is_none/_no_ naming.
"""
from __future__ import annotations

import json
from unittest import mock

from bin import llm_judge


# ── Spec fixture ──────────────────────────────────────────────────────────────

_SPEC = """\
# Thin Coverage Spec

## 6. Steps

```yaml
- step: 5
  why: run the pipeline
  action: python3 run.py --input data.csv
  verification: test -f output.json
```

## 8. Receiver Calibration

### 8.1 Hard contract
- mutates: /tmp/out
- never-touches: /etc
- decision-budget: none
- reboot-survival: none
"""

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


def _step_objects(neg_path_count: int) -> list[dict]:
    """step_objects with a specific number of negative-paths entries for step 5."""
    return [
        {
            "step": 5,
            "negative_paths": [
                {"trigger": f"fail{i}", "handler": "abort"}
                for i in range(neg_path_count)
            ],
        }
    ]


# negative-path-omission has "info" severity — no faithfulness second call.
_NEG_PATH_OMISSION_TUPLE = {
    "kind": "negative-path-omission",
    "step": 5,
    "rationale": "step 5 has no negative-paths documented",
}

# missing-producer has "block" severity — triggers a faithfulness second call.
_MISSING_PRODUCER_TUPLE = {
    "kind": "missing-producer",
    "consumer_step": 5,
    "missing": "some-artifact",
    "rationale": "no producer step found for some-artifact",
}


# ── Case 1: thin fires (< 3 negative-paths) ──────────────────────────────────


@mock.patch("urllib.request.urlopen")
def test_thin_coverage_emitted_when_neg_path_omission_present_and_paths_is_zero(mock_urlopen, monkeypatch):
    """Thin fires: negative-path-omission present + step has 0 negative-paths."""
    monkeypatch.setenv("TEST_DEEPSEEK_KEY", "fake-key")
    # Only one API call — negative-path-omission is info severity, no faithfulness check.
    mock_urlopen.return_value = _api_resp(json.dumps([_NEG_PATH_OMISSION_TUPLE]))
    result = llm_judge.evaluate(_SPEC, config=_CFG, step_objects=_step_objects(0))
    assert any(f.kind == "tier3-negative-paths-thin-coverage" for f in result)


@mock.patch("urllib.request.urlopen")
def test_thin_coverage_emitted_when_neg_path_omission_present_and_paths_is_two(mock_urlopen, monkeypatch):
    """Thin fires: negative-path-omission present + step has 2 negative-paths (< 3)."""
    monkeypatch.setenv("TEST_DEEPSEEK_KEY", "fake-key")
    mock_urlopen.return_value = _api_resp(json.dumps([_NEG_PATH_OMISSION_TUPLE]))
    result = llm_judge.evaluate(_SPEC, config=_CFG, step_objects=_step_objects(2))
    assert any(f.kind == "tier3-negative-paths-thin-coverage" for f in result)


@mock.patch("urllib.request.urlopen")
def test_thin_coverage_finding_severity_is_warn(mock_urlopen, monkeypatch):
    monkeypatch.setenv("TEST_DEEPSEEK_KEY", "fake-key")
    mock_urlopen.return_value = _api_resp(json.dumps([_NEG_PATH_OMISSION_TUPLE]))
    result = llm_judge.evaluate(_SPEC, config=_CFG, step_objects=_step_objects(1))
    thin = next((f for f in result if f.kind == "tier3-negative-paths-thin-coverage"), None)
    assert thin is not None and thin.severity == "warn"


@mock.patch("urllib.request.urlopen")
def test_thin_coverage_finding_is_dismissable(mock_urlopen, monkeypatch):
    monkeypatch.setenv("TEST_DEEPSEEK_KEY", "fake-key")
    mock_urlopen.return_value = _api_resp(json.dumps([_NEG_PATH_OMISSION_TUPLE]))
    result = llm_judge.evaluate(_SPEC, config=_CFG, step_objects=_step_objects(0))
    thin = next((f for f in result if f.kind == "tier3-negative-paths-thin-coverage"), None)
    assert thin is not None and thin.dismissable is True


@mock.patch("urllib.request.urlopen")
def test_thin_coverage_finding_location_step_matches_original(mock_urlopen, monkeypatch):
    monkeypatch.setenv("TEST_DEEPSEEK_KEY", "fake-key")
    mock_urlopen.return_value = _api_resp(json.dumps([_NEG_PATH_OMISSION_TUPLE]))
    result = llm_judge.evaluate(_SPEC, config=_CFG, step_objects=_step_objects(1))
    thin = next((f for f in result if f.kind == "tier3-negative-paths-thin-coverage"), None)
    assert thin is not None and thin.location.step == 5


# ── Case 2: thick doesn't fire (>= 3 negative-paths) ────────────────────────


@mock.patch("urllib.request.urlopen")
def test_thin_coverage_not_emitted_when_neg_paths_count_is_three(mock_urlopen, monkeypatch):
    """Thick: same finding but step has 3 negative-paths — no thin finding."""
    monkeypatch.setenv("TEST_DEEPSEEK_KEY", "fake-key")
    mock_urlopen.return_value = _api_resp(json.dumps([_NEG_PATH_OMISSION_TUPLE]))
    result = llm_judge.evaluate(_SPEC, config=_CFG, step_objects=_step_objects(3))
    assert not any(f.kind == "tier3-negative-paths-thin-coverage" for f in result)


@mock.patch("urllib.request.urlopen")
def test_thin_coverage_not_emitted_when_neg_paths_count_is_five(mock_urlopen, monkeypatch):
    monkeypatch.setenv("TEST_DEEPSEEK_KEY", "fake-key")
    mock_urlopen.return_value = _api_resp(json.dumps([_NEG_PATH_OMISSION_TUPLE]))
    result = llm_judge.evaluate(_SPEC, config=_CFG, step_objects=_step_objects(5))
    assert not any(f.kind == "tier3-negative-paths-thin-coverage" for f in result)


# ── Case 3: different kind — thin-coverage must not fire ─────────────────────


@mock.patch("urllib.request.urlopen")
def test_thin_coverage_not_emitted_when_finding_kind_is_not_negative_path_omission(mock_urlopen, monkeypatch):
    """missing-producer finding with 0 negative-paths → thin-coverage must NOT fire."""
    monkeypatch.setenv("TEST_DEEPSEEK_KEY", "fake-key")
    # missing-producer is block severity → triggers faithfulness second call.
    cite_resp_content = json.dumps([{"index": 0, "step": 5, "citation": "python3 run.py"}])
    mock_urlopen.side_effect = [
        _api_resp(json.dumps([_MISSING_PRODUCER_TUPLE])),
        _api_resp(cite_resp_content),
    ]
    result = llm_judge.evaluate(_SPEC, config=_CFG, step_objects=_step_objects(0))
    assert not any(f.kind == "tier3-negative-paths-thin-coverage" for f in result)
