"""Layer 5 exemplar-binding trace (v1.3 #10).

Assert that answering an exemplar-binding concern via walker.record_answer
emits a trace record with choice_point="exemplar-binding", not "walker-concern".
Also verifies that the options_considered contain the catalog slugs that were
presented, and that the record is correctly identified for known exemplar IDs.
"""
import pathlib

import pytest

from bin import walker


_EXEMPLAR_CONCERN_IDS = [
    "input-exemplar-pi",
    "help-text-style-hu",
    "error-text-style-hu",
    "api-exemplar-int",
    "log-format-style-op",
    "observability-style-op",
]


def _make_state(tmp_path: pathlib.Path) -> walker.WalkState:
    draft = tmp_path / "draft.spec.md"
    draft.write_text("# test spec\n", encoding="utf-8")
    return walker.WalkState(
        spec_intent="test intent",
        spec_draft_path=draft,
    )


def _make_exemplar_concern(concern_id: str, slugs: list[str]) -> walker.Concern:
    return walker.Concern(
        id=concern_id,
        kind="receiver-clarification",
        receivers=["human"],
        depends_on=[],
        summary=f"Exemplar binding for {concern_id}",
        prefab_options=slugs,
    )


def test_exemplar_binding_trace_emitted(tmp_path: pathlib.Path):
    """Answering an exemplar-binding concern emits choice_point=exemplar-binding."""
    state = _make_state(tmp_path)
    concern = _make_exemplar_concern(
        "help-text-style-hu",
        ["spectre-cli-help", "cargo-help-text", "kubectl-help-text"],
    )
    state.pending.append(concern)

    walker.record_answer(state, concern_id="help-text-style-hu", answer="spectre-cli-help")

    assert len(state.layer5_trace) == 1
    rec = state.layer5_trace[0]
    assert rec["choice_point"] == "exemplar-binding"
    assert rec["step_or_concern_id"] == "help-text-style-hu"
    assert rec["selected"] == "spectre-cli-help"
    assert "spectre-cli-help" in rec["options_considered"]
    assert len(rec["options_considered"]) == 3


def test_exemplar_binding_trace_six_fields(tmp_path: pathlib.Path):
    """Exemplar-binding trace carries all six required fields plus timestamp."""
    state = _make_state(tmp_path)
    concern = _make_exemplar_concern(
        "api-exemplar-int",
        ["rest-json-api", "graphql-api", "grpc-api"],
    )
    state.pending.append(concern)

    walker.record_answer(state, concern_id="api-exemplar-int", answer="rest-json-api")

    assert len(state.layer5_trace) == 1
    rec = state.layer5_trace[0]
    required = {"choice_point", "step_or_concern_id", "options_considered",
                "selected", "rationale", "validation_anchor", "source_anchor", "timestamp"}
    assert required <= set(rec.keys())


def test_exemplar_binding_validation_anchor_is_cross_view(tmp_path: pathlib.Path):
    """Exemplar-binding traces carry tier2-cross-view-gate as validation_anchor."""
    state = _make_state(tmp_path)
    concern = _make_exemplar_concern(
        "log-format-style-op",
        ["json-lines-logfmt", "plain-logfmt"],
    )
    state.pending.append(concern)

    walker.record_answer(state, concern_id="log-format-style-op", answer="json-lines-logfmt")

    assert state.layer5_trace[0]["validation_anchor"] == "tier2-cross-view-gate"


def test_exemplar_binding_not_emitted_for_non_exemplar_concern(tmp_path: pathlib.Path):
    """Non-exemplar concerns with multiple options emit choice_point=walker-concern."""
    state = _make_state(tmp_path)
    concern = _make_exemplar_concern(
        "scope-product-input",
        ["human-typed", "programmatic-trusted", "not-applicable"],
    )
    state.pending.append(concern)

    walker.record_answer(state, concern_id="scope-product-input", answer="human-typed")

    assert state.layer5_trace[0]["choice_point"] == "walker-concern"


def test_input_exemplar_pi_emits_exemplar_binding(tmp_path: pathlib.Path):
    """input-exemplar-pi concern emits choice_point=exemplar-binding."""
    state = _make_state(tmp_path)
    state.pending.append(_make_exemplar_concern("input-exemplar-pi", ["slug-a", "slug-b", "slug-c"]))
    walker.record_answer(state, concern_id="input-exemplar-pi", answer="slug-a")
    assert len(state.layer5_trace) == 1
    assert state.layer5_trace[0]["choice_point"] == "exemplar-binding"


def test_error_text_style_hu_emits_exemplar_binding(tmp_path: pathlib.Path):
    """error-text-style-hu concern emits choice_point=exemplar-binding."""
    state = _make_state(tmp_path)
    state.pending.append(_make_exemplar_concern("error-text-style-hu", ["slug-a", "slug-b", "slug-c"]))
    walker.record_answer(state, concern_id="error-text-style-hu", answer="slug-b")
    assert len(state.layer5_trace) == 1
    assert state.layer5_trace[0]["choice_point"] == "exemplar-binding"


def test_observability_style_op_emits_exemplar_binding(tmp_path: pathlib.Path):
    """observability-style-op concern emits choice_point=exemplar-binding."""
    state = _make_state(tmp_path)
    state.pending.append(_make_exemplar_concern("observability-style-op", ["slug-a", "slug-b", "slug-c"]))
    walker.record_answer(state, concern_id="observability-style-op", answer="slug-c")
    assert len(state.layer5_trace) == 1
    assert state.layer5_trace[0]["choice_point"] == "exemplar-binding"


def test_exemplar_trace_disabled_by_env(tmp_path: pathlib.Path, monkeypatch):
    """SPECTRE_LAYER5=off disables exemplar-binding trace emission."""
    monkeypatch.setenv("SPECTRE_LAYER5", "off")
    state = _make_state(tmp_path)
    concern = _make_exemplar_concern(
        "help-text-style-hu",
        ["slug-a", "slug-b"],
    )
    state.pending.append(concern)

    walker.record_answer(state, concern_id="help-text-style-hu", answer="slug-a")

    assert state.layer5_trace == []
