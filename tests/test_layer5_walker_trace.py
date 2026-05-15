"""Layer 5 walker concern-resolution trace (v1.3 #10).

Assert that calling walker.record_answer with a concern whose prefab_options
has >=2 entries appends a trace record to state.layer5_trace, and that the
trace has all six required fields populated. Also confirms that concerns with
<=1 prefab option produce no trace.
"""
import os
import pathlib

import pytest

from bin import walker


def _make_state(tmp_path: pathlib.Path) -> walker.WalkState:
    draft = tmp_path / "draft.spec.md"
    draft.write_text("# test spec\n", encoding="utf-8")
    return walker.WalkState(
        spec_intent="test intent",
        spec_draft_path=draft,
    )


def _make_concern(
    concern_id: str,
    prefab_options: list[str],
) -> walker.Concern:
    return walker.Concern(
        id=concern_id,
        kind="receiver-clarification",
        receivers=["human"],
        depends_on=[],
        summary=f"Test concern for {concern_id}",
        prefab_options=prefab_options,
    )


def test_walker_concern_trace_appended_on_multichoice(tmp_path: pathlib.Path):
    """record_answer with >=2 prefab options appends a trace record."""
    state = _make_state(tmp_path)
    concern = _make_concern(
        "scope-product-input",
        ["human-typed", "programmatic-trusted", "programmatic-untrusted", "not-applicable"],
    )
    state.pending.append(concern)

    walker.record_answer(state, concern_id="scope-product-input", answer="human-typed")

    assert len(state.layer5_trace) == 1
    record = state.layer5_trace[0]
    assert record["choice_point"] == "walker-concern"
    assert record["step_or_concern_id"] == "scope-product-input"
    assert record["options_considered"] == [
        "human-typed", "programmatic-trusted", "programmatic-untrusted", "not-applicable"
    ]
    assert record["selected"] == "human-typed"
    assert isinstance(record["rationale"], str) and len(record["rationale"]) > 0
    assert "validation_anchor" in record
    assert "source_anchor" in record
    assert "timestamp" in record


def test_walker_concern_trace_six_fields_all_present(tmp_path: pathlib.Path):
    """Each trace record carries all six required fields plus timestamp."""
    state = _make_state(tmp_path)
    concern = _make_concern("scope-human-user", ["cli-user", "web-user", "not-applicable"])
    state.pending.append(concern)

    walker.record_answer(state, concern_id="scope-human-user", answer="cli-user")

    assert len(state.layer5_trace) == 1
    rec = state.layer5_trace[0]
    required = {"choice_point", "step_or_concern_id", "options_considered",
                "selected", "rationale", "validation_anchor", "source_anchor", "timestamp"}
    assert required <= set(rec.keys()), f"Missing fields: {required - set(rec.keys())}"


def test_walker_concern_no_trace_when_zero_prefab(tmp_path: pathlib.Path):
    """Concerns with no prefab options produce no trace (open-ended answer)."""
    state = _make_state(tmp_path)
    concern = _make_concern("seed-lifecycle", [])
    state.pending.append(concern)

    walker.record_answer(state, concern_id="seed-lifecycle", answer="systemd unit")

    assert state.layer5_trace == []


def test_walker_concern_no_trace_when_single_prefab(tmp_path: pathlib.Path):
    """Concerns with exactly one prefab option produce no trace (no real choice)."""
    state = _make_state(tmp_path)
    concern = _make_concern("only-option-concern", ["the-only-choice"])
    state.pending.append(concern)

    walker.record_answer(state, concern_id="only-option-concern", answer="the-only-choice")

    assert state.layer5_trace == []


def test_walker_concern_trace_accumulates_multiple(tmp_path: pathlib.Path):
    """Multiple answered concerns with prefab options accumulate multiple trace records."""
    state = _make_state(tmp_path)
    c1 = _make_concern("scope-product-input", ["human-typed", "programmatic-trusted", "not-applicable"])
    c2 = _make_concern("scope-product-output", ["human-reader", "programmatic-consumer", "not-applicable"])
    state.pending.extend([c1, c2])

    walker.record_answer(state, concern_id="scope-product-input", answer="human-typed")
    walker.record_answer(state, concern_id="scope-product-output", answer="programmatic-consumer")

    assert len(state.layer5_trace) == 2
    assert state.layer5_trace[0]["step_or_concern_id"] == "scope-product-input"
    assert state.layer5_trace[1]["step_or_concern_id"] == "scope-product-output"


def test_walker_concern_trace_disabled_by_env(tmp_path: pathlib.Path, monkeypatch):
    """SPECTRE_LAYER5=off disables trace emission entirely."""
    monkeypatch.setenv("SPECTRE_LAYER5", "off")
    state = _make_state(tmp_path)
    concern = _make_concern("scope-product-input", ["human-typed", "programmatic-trusted"])
    state.pending.append(concern)

    walker.record_answer(state, concern_id="scope-product-input", answer="human-typed")

    assert state.layer5_trace == []
