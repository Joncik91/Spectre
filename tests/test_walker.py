"""Walker state machine tests. Stdlib + pytest only."""
import json
import pathlib
import pytest

from bin import walker


def test_walker_version_is_0_4_0():
    assert walker.WALKER_VERSION == "0.4.0"


def test_known_receivers_includes_four_canonical_names():
    assert set(walker.KNOWN_RECEIVERS) == {"implement", "tier3", "human", "deterministic"}


def test_known_concern_kinds_is_closed_set_of_four():
    assert set(walker.KNOWN_CONCERN_KINDS) == {
        "edge-case",
        "receiver-clarification",
        "assumption-surface",
        "branch-resolution",
    }


def test_stop_reasons_includes_four_canonical_strings():
    assert set(walker.STOP_REASONS) == {
        "author-arbitrated",
        "tier3-yield-converged",
        "max-rounds",
        "per-receiver-exhausted",
    }


def test_concern_construction_with_required_fields():
    c = walker.Concern(
        id="c1",
        kind="edge-case",
        receivers=["implement"],
        depends_on=[],
        summary="What happens on partial write?",
    )
    assert c.id == "c1"


def test_concern_rejects_unknown_kind():
    with pytest.raises(ValueError, match="unknown concern kind"):
        walker.Concern(
            id="c1",
            kind="bogus-kind",
            receivers=["implement"],
            depends_on=[],
            summary="x",
        )


def test_concern_rejects_unknown_receiver():
    with pytest.raises(ValueError, match="unknown receiver"):
        walker.Concern(
            id="c1",
            kind="edge-case",
            receivers=["implement", "bogus-receiver"],
            depends_on=[],
            summary="x",
        )


def test_concern_rejects_empty_receivers_list():
    with pytest.raises(ValueError, match="at least one receiver"):
        walker.Concern(
            id="c1",
            kind="edge-case",
            receivers=[],
            depends_on=[],
            summary="x",
        )


def test_walk_state_asked_defaults_to_empty_list():
    state = walker.WalkState(
        spec_intent="x",
        spec_draft_path=pathlib.Path("specs/x.spec.md.draft"),
    )
    assert state.asked == []


def test_walk_state_answered_defaults_to_empty_dict():
    state = walker.WalkState(
        spec_intent="x",
        spec_draft_path=pathlib.Path("specs/x.spec.md.draft"),
    )
    assert state.answered == {}


def test_walk_state_pending_defaults_to_empty_list():
    state = walker.WalkState(
        spec_intent="x",
        spec_draft_path=pathlib.Path("specs/x.spec.md.draft"),
    )
    assert state.pending == []


def test_walk_state_stale_defaults_to_empty_set():
    state = walker.WalkState(
        spec_intent="x",
        spec_draft_path=pathlib.Path("specs/x.spec.md.draft"),
    )
    assert state.stale == set()


def test_walk_state_stop_reason_defaults_to_none():
    state = walker.WalkState(
        spec_intent="x",
        spec_draft_path=pathlib.Path("specs/x.spec.md.draft"),
    )
    assert state.stop_reason is None


def test_walk_state_round_count_starts_at_zero():
    state = walker.WalkState(
        spec_intent="x",
        spec_draft_path=pathlib.Path("specs/x.spec.md.draft"),
    )
    assert state.round_count == 0


def test_init_walk_returns_walk_state_with_intent():
    state = walker.init_walk(
        spec_intent="build a btc poller",
        spec_draft_path=pathlib.Path("specs/btc.spec.md.draft"),
    )
    assert state.spec_intent == "build a btc poller"


def test_init_walk_seeds_pending_with_assumption_surface_concern():
    """Every walk starts with at least one assumption-surface concern.
    The walker refuses to prune what biology lets humans skip — round 1
    asks the human to surface the unstated assumptions in their intent."""
    state = walker.init_walk(
        spec_intent="x",
        spec_draft_path=pathlib.Path("specs/x.spec.md.draft"),
    )
    assert any(c.kind == "assumption-surface" for c in state.pending)


def test_init_walk_seeded_concern_targets_human_receiver():
    state = walker.init_walk(
        spec_intent="x",
        spec_draft_path=pathlib.Path("specs/x.spec.md.draft"),
    )
    seed = state.pending[0]
    assert "human" in seed.receivers


def test_init_walk_round_count_is_zero():
    state = walker.init_walk(
        spec_intent="x",
        spec_draft_path=pathlib.Path("specs/x.spec.md.draft"),
    )
    assert state.round_count == 0


def test_init_walk_no_stop_reason_set():
    state = walker.init_walk(
        spec_intent="x",
        spec_draft_path=pathlib.Path("specs/x.spec.md.draft"),
    )
    assert state.stop_reason is None


def test_next_concern_returns_first_pending_concern():
    state = walker.init_walk(
        spec_intent="x",
        spec_draft_path=pathlib.Path("specs/x.spec.md.draft"),
    )
    c = walker.next_concern(state)
    assert c is not None
    assert c.id == "seed-1"


def test_next_concern_skips_stale_concerns():
    state = walker.init_walk(
        spec_intent="x",
        spec_draft_path=pathlib.Path("specs/x.spec.md.draft"),
    )
    state.stale.add("seed-1")
    extra = walker.Concern(
        id="c2",
        kind="edge-case",
        receivers=["implement"],
        depends_on=[],
        summary="non-stale concern",
    )
    state.pending.append(extra)
    c = walker.next_concern(state)
    assert c is not None
    assert c.id == "c2"


def test_next_concern_returns_none_when_pending_empty():
    state = walker.WalkState(
        spec_intent="x",
        spec_draft_path=pathlib.Path("specs/x.spec.md.draft"),
    )
    assert walker.next_concern(state) is None


def test_next_concern_returns_none_when_all_pending_are_stale():
    state = walker.init_walk(
        spec_intent="x",
        spec_draft_path=pathlib.Path("specs/x.spec.md.draft"),
    )
    for c in state.pending:
        state.stale.add(c.id)
    assert walker.next_concern(state) is None
