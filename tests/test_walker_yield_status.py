"""Tests for walker.yield_status_line and walker.generate_negative_path_concerns.

Pragma guard: assertion-style names only. One assertion per test.
Tests asserting absence/emptiness use _returns_empty/_is_none naming.
"""
import pathlib

from bin import walker


# ── yield_status_line ─────────────────────────────────────────────────────────


def _make_state(yield_history: list[int]) -> walker.WalkState:
    state = walker.WalkState(
        spec_intent="test",
        spec_draft_path=pathlib.Path("specs/test.spec.md.draft"),
    )
    state.yield_history = yield_history
    return state


def test_yield_status_line_round_1_shows_correct_count():
    state = _make_state([5])
    line = walker.yield_status_line(state)
    assert "round 1" in line


def test_yield_status_line_round_1_shows_correct_added():
    state = _make_state([5])
    line = walker.yield_status_line(state)
    assert "added 5 new T3 findings" in line


def test_yield_status_line_round_1_shows_threshold():
    state = _make_state([5])
    line = walker.yield_status_line(state)
    assert "stopping when last 3 rounds all <2" in line


def test_yield_status_line_round_1_currently_shows_tail():
    state = _make_state([5])
    line = walker.yield_status_line(state)
    assert "(currently: [5])" in line


def test_yield_status_line_round_4_shows_correct_round():
    state = _make_state([5, 3, 1, 0])
    line = walker.yield_status_line(state)
    assert "round 4" in line


def test_yield_status_line_round_4_shows_correct_added():
    state = _make_state([5, 3, 1, 0])
    line = walker.yield_status_line(state)
    assert "added 0 new T3 findings" in line


def test_yield_status_line_round_4_currently_shows_last_three():
    state = _make_state([5, 3, 1, 0])
    line = walker.yield_status_line(state)
    assert "(currently: [3, 1, 0])" in line


def test_yield_status_line_round_2_shows_tail_of_two():
    state = _make_state([5, 3])
    line = walker.yield_status_line(state)
    assert "(currently: [5, 3])" in line


def test_yield_status_line_empty_history_shows_round_0():
    state = _make_state([])
    line = walker.yield_status_line(state)
    assert "round 0" in line


def test_yield_status_line_empty_history_added_is_zero():
    state = _make_state([])
    line = walker.yield_status_line(state)
    assert "added 0 new T3 findings" in line


def test_yield_status_line_custom_threshold_reflected():
    state = _make_state([3, 1, 1])
    line = walker.yield_status_line(state, yield_threshold=5, yield_converge_rounds=2)
    assert "stopping when last 2 rounds all <5" in line


def test_yield_status_line_custom_converge_rounds_tail():
    state = _make_state([10, 5, 2, 1])
    line = walker.yield_status_line(state, yield_converge_rounds=2)
    assert "(currently: [2, 1])" in line


# ── generate_negative_path_concerns ──────────────────────────────────────────


def _make_fresh_state() -> walker.WalkState:
    return walker.WalkState(
        spec_intent="test",
        spec_draft_path=pathlib.Path("specs/test.spec.md.draft"),
    )


def test_generator_emits_concern_for_step_with_produces_and_no_negative_paths():
    state = _make_fresh_state()
    steps = [{"step": 1, "produces": ["file:/tmp/x"], "negative_paths": []}]
    concerns = walker.generate_negative_path_concerns(state, steps)
    assert len(concerns) == 1


def test_generator_concern_id_is_negpath_prefixed():
    state = _make_fresh_state()
    steps = [{"step": 3, "produces": ["file:/tmp/x"], "negative_paths": []}]
    concerns = walker.generate_negative_path_concerns(state, steps)
    assert concerns[0].id == "negpath-3"


def test_generator_concern_kind_is_negative_path():
    state = _make_fresh_state()
    steps = [{"step": 1, "produces": ["file:/tmp/x"], "negative_paths": []}]
    concerns = walker.generate_negative_path_concerns(state, steps)
    assert concerns[0].kind == "negative-path"


def test_generator_concern_receiver_is_human():
    state = _make_fresh_state()
    steps = [{"step": 1, "produces": ["file:/tmp/x"], "negative_paths": []}]
    concerns = walker.generate_negative_path_concerns(state, steps)
    assert "human" in concerns[0].receivers


def test_generator_concern_summary_mentions_step_number():
    state = _make_fresh_state()
    steps = [{"step": 7, "produces": ["file:/tmp/x"], "negative_paths": []}]
    concerns = walker.generate_negative_path_concerns(state, steps)
    assert "Step 7" in concerns[0].summary


def test_generator_emits_one_concern_per_qualifying_step():
    state = _make_fresh_state()
    steps = [
        {"step": 1, "produces": ["file:/tmp/a"], "negative_paths": []},
        {"step": 2, "produces": ["file:/tmp/b"], "negative_paths": []},
    ]
    concerns = walker.generate_negative_path_concerns(state, steps)
    assert len(concerns) == 2


def test_generator_returns_empty_for_step_without_produces():
    state = _make_fresh_state()
    steps = [{"step": 1, "produces": [], "negative_paths": []}]
    concerns = walker.generate_negative_path_concerns(state, steps)
    assert concerns == []


def test_generator_returns_empty_for_step_with_negative_paths_present():
    state = _make_fresh_state()
    steps = [
        {
            "step": 1,
            "produces": ["file:/tmp/x"],
            "negative_paths": [{"trigger": "disk full", "handler": "reject"}],
        }
    ]
    concerns = walker.generate_negative_path_concerns(state, steps)
    assert concerns == []


def test_generator_idempotent_when_concern_already_in_asked():
    state = _make_fresh_state()
    existing = walker.Concern(
        id="negpath-1",
        kind="negative-path",
        receivers=["human"],
        depends_on=[],
        summary="already asked",
    )
    state.asked.append(existing)
    state.answered["negpath-1"] = "some answer"
    steps = [{"step": 1, "produces": ["file:/tmp/x"], "negative_paths": []}]
    concerns = walker.generate_negative_path_concerns(state, steps)
    assert concerns == []


def test_generator_idempotent_when_concern_already_in_pending():
    state = _make_fresh_state()
    existing = walker.Concern(
        id="negpath-2",
        kind="negative-path",
        receivers=["human"],
        depends_on=[],
        summary="already pending",
    )
    state.pending.append(existing)
    steps = [{"step": 2, "produces": ["file:/tmp/y"], "negative_paths": []}]
    concerns = walker.generate_negative_path_concerns(state, steps)
    assert concerns == []


def test_generator_emits_concern_for_unanswered_step_when_other_answered():
    state = _make_fresh_state()
    # Step 1 already in asked/answered; step 2 is new
    existing = walker.Concern(
        id="negpath-1",
        kind="negative-path",
        receivers=["human"],
        depends_on=[],
        summary="step 1 asked",
    )
    state.asked.append(existing)
    state.answered["negpath-1"] = "handled"
    steps = [
        {"step": 1, "produces": ["file:/tmp/a"], "negative_paths": []},
        {"step": 2, "produces": ["file:/tmp/b"], "negative_paths": []},
    ]
    concerns = walker.generate_negative_path_concerns(state, steps)
    assert len(concerns) == 1


def test_generator_new_concern_for_step2_has_correct_id():
    state = _make_fresh_state()
    existing = walker.Concern(
        id="negpath-1",
        kind="negative-path",
        receivers=["human"],
        depends_on=[],
        summary="step 1",
    )
    state.asked.append(existing)
    state.answered["negpath-1"] = "handled"
    steps = [
        {"step": 1, "produces": ["file:/tmp/a"], "negative_paths": []},
        {"step": 2, "produces": ["file:/tmp/b"], "negative_paths": []},
    ]
    concerns = walker.generate_negative_path_concerns(state, steps)
    assert concerns[0].id == "negpath-2"
