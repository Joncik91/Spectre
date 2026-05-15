"""Layer 5 substitution trace (v1.3 #10).

Assert that write_sidecar with a layer5_trace kwarg writes the layer5_trace
key to the sidecar payload. Also tests _layer5.project_substitution_trace
which projects an extended substitution dict into a trace record.
"""
import json
import pathlib

from bin import eval_metadata
from bin import _layer5


def test_layer5_trace_omitted_when_none(tmp_path: pathlib.Path):
    """layer5_trace not written when kwarg is None."""
    spec = tmp_path / "x.spec.md"
    spec.write_text("# x\n", encoding="utf-8")
    sidecar = eval_metadata.write_sidecar(
        spec,
        evaluator_version="1.0.0",
        tiers_run=[1],
        findings=[],
        dismissals=[],
        config_path=None,
        config_hash=None,
        deepseek_model_version=None,
        policy_hash="abc",
        layer5_trace=None,
    )
    payload = json.loads(sidecar.read_text(encoding="utf-8"))
    assert "layer5_trace" not in payload


def test_layer5_trace_written_as_empty_list(tmp_path: pathlib.Path):
    """layer5_trace=[] writes an empty array to the sidecar."""
    spec = tmp_path / "x.spec.md"
    spec.write_text("# x\n", encoding="utf-8")
    sidecar = eval_metadata.write_sidecar(
        spec,
        evaluator_version="1.0.0",
        tiers_run=[1],
        findings=[],
        dismissals=[],
        config_path=None,
        config_hash=None,
        deepseek_model_version=None,
        policy_hash="abc",
        layer5_trace=[],
    )
    payload = json.loads(sidecar.read_text(encoding="utf-8"))
    assert payload["layer5_trace"] == []


def test_layer5_trace_round_trips_through_sidecar(tmp_path: pathlib.Path):
    """A populated layer5_trace round-trips through write_sidecar unchanged."""
    spec = tmp_path / "x.spec.md"
    spec.write_text("# x\n", encoding="utf-8")
    trace_record = {
        "choice_point": "walker-concern",
        "step_or_concern_id": "scope-product-input",
        "options_considered": ["human-typed", "programmatic-trusted"],
        "selected": "human-typed",
        "rationale": "Operator chose human-typed for interactive CLI.",
        "validation_anchor": "tier1-structural",
        "source_anchor": None,
        "timestamp": "2026-05-15T12:00:00Z",
    }
    sidecar = eval_metadata.write_sidecar(
        spec,
        evaluator_version="1.0.0",
        tiers_run=[1],
        findings=[],
        dismissals=[],
        config_path=None,
        config_hash=None,
        deepseek_model_version=None,
        policy_hash="abc",
        layer5_trace=[trace_record],
    )
    payload = json.loads(sidecar.read_text(encoding="utf-8"))
    assert payload["layer5_trace"] == [trace_record]


def test_project_substitution_trace_with_options(tmp_path: pathlib.Path):
    """project_substitution_trace returns a valid trace for an extended substitution."""
    sub = {
        "from": "python3 -c 'import x'",
        "to": "pip show x >/dev/null 2>&1",
        "reason": "shell-eval false-positive",
        "tier1_check_name": "untrusted-flow-unguarded",
        "step_id": "step-3",
        "options_considered": ["pip show x >/dev/null 2>&1", "python3 -m x --check"],
        "selected": "pip show x >/dev/null 2>&1",
        "rationale": "pip show is idempotent and doesn't exec user data.",
        "validation_anchor": "tier1-structural",
        "source_anchor": None,
    }
    record = _layer5.project_substitution_trace(sub)
    assert record is not None
    assert record["choice_point"] == "substitution"
    assert record["step_or_concern_id"] == "step-3"
    assert record["options_considered"] == ["pip show x >/dev/null 2>&1", "python3 -m x --check"]
    assert record["selected"] == "pip show x >/dev/null 2>&1"
    assert record["rationale"] == "pip show is idempotent and doesn't exec user data."
    assert record["validation_anchor"] == "tier1-structural"
    assert "timestamp" in record


def test_project_substitution_trace_none_when_no_options():
    """project_substitution_trace returns None when options_considered is absent."""
    sub = {
        "from": "old", "to": "new",
        "reason": "fix", "tier1_check_name": "soft-verification", "step_id": "step-1",
    }
    result = _layer5.project_substitution_trace(sub)
    assert result is None


def test_layer5_and_substitutions_coexist(tmp_path: pathlib.Path):
    """layer5_trace and substitutions can both appear in the same sidecar."""
    spec = tmp_path / "x.spec.md"
    spec.write_text("# x\n", encoding="utf-8")
    sub_entry = {"from": "a", "to": "b", "reason": "r", "tier1_check_name": "t", "step_id": "s-1"}
    trace_record = {
        "choice_point": "substitution",
        "step_or_concern_id": "s-1",
        "options_considered": ["b", "c"],
        "selected": "b",
        "rationale": "b is safer",
        "validation_anchor": "tier1-structural",
        "source_anchor": None,
        "timestamp": "2026-05-15T12:00:00Z",
    }
    sidecar = eval_metadata.write_sidecar(
        spec,
        evaluator_version="1.0.0",
        tiers_run=[1],
        findings=[],
        dismissals=[],
        config_path=None,
        config_hash=None,
        deepseek_model_version=None,
        policy_hash="abc",
        substitutions=[sub_entry],
        layer5_trace=[trace_record],
    )
    payload = json.loads(sidecar.read_text(encoding="utf-8"))
    assert payload["substitutions"] == [sub_entry]
    assert payload["layer5_trace"] == [trace_record]
