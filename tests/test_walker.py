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


def test_walk_state_default_fields_are_empty():
    state = walker.WalkState(
        spec_intent="build a thing",
        spec_draft_path=pathlib.Path("specs/x.spec.md.draft"),
    )
    assert state.asked == []
    assert state.answered == {}
    assert state.pending == []
    assert state.stale == set()
    assert state.stop_reason is None


def test_walk_state_round_count_starts_at_zero():
    state = walker.WalkState(
        spec_intent="x",
        spec_draft_path=pathlib.Path("specs/x.spec.md.draft"),
    )
    assert state.round_count == 0
