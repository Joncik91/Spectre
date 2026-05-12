"""Walker state machine tests. Stdlib + pytest only."""
import json
import pathlib
import pytest

from bin import walker


def test_walker_version_is_0_4_0():
    assert walker.WALKER_VERSION == "0.4.0"


def test_known_receivers_includes_four_canonical_names():
    assert set(walker.KNOWN_RECEIVERS) == {"implement", "tier3", "human", "deterministic"}


def test_known_concern_kinds_is_closed_set_of_six():
    assert set(walker.KNOWN_CONCERN_KINDS) == {
        "edge-case",
        "receiver-clarification",
        "assumption-surface",
        "branch-resolution",
        "negative-path",
        "scaffold-precondition",
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
    # Mark every seeded concern stale so c2 is the only non-stale candidate.
    for seed in list(state.pending):
        state.stale.add(seed.id)
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


def test_record_answer_moves_concern_from_pending_to_asked():
    state = walker.init_walk(
        spec_intent="x",
        spec_draft_path=pathlib.Path("specs/x.spec.md.draft"),
    )
    state2 = walker.record_answer(state, concern_id="seed-1", answer="my answer")
    assert any(c.id == "seed-1" for c in state2.asked)


def test_record_answer_removes_concern_from_pending():
    state = walker.init_walk(
        spec_intent="x",
        spec_draft_path=pathlib.Path("specs/x.spec.md.draft"),
    )
    state2 = walker.record_answer(state, concern_id="seed-1", answer="my answer")
    assert all(c.id != "seed-1" for c in state2.pending)


def test_record_answer_stores_answer_text():
    state = walker.init_walk(
        spec_intent="x",
        spec_draft_path=pathlib.Path("specs/x.spec.md.draft"),
    )
    state2 = walker.record_answer(state, concern_id="seed-1", answer="my answer")
    assert state2.answered["seed-1"] == "my answer"


def test_record_answer_increments_round_count():
    state = walker.init_walk(
        spec_intent="x",
        spec_draft_path=pathlib.Path("specs/x.spec.md.draft"),
    )
    state2 = walker.record_answer(state, concern_id="seed-1", answer="x")
    assert state2.round_count == 1


def test_record_answer_raises_for_unknown_concern_id():
    state = walker.init_walk(
        spec_intent="x",
        spec_draft_path=pathlib.Path("specs/x.spec.md.draft"),
    )
    with pytest.raises(KeyError, match="not in pending"):
        walker.record_answer(state, concern_id="nonexistent", answer="x")


def test_revise_answer_updates_stored_answer():
    state = walker.init_walk(
        spec_intent="x",
        spec_draft_path=pathlib.Path("specs/x.spec.md.draft"),
    )
    state = walker.record_answer(state, concern_id="seed-1", answer="old")
    new_state, _ = walker.revise_answer(state, concern_id="seed-1", new_answer="new")
    assert new_state.answered["seed-1"] == "new"


def test_revise_answer_returns_empty_invalidated_set_when_no_dependents():
    state = walker.init_walk(
        spec_intent="x",
        spec_draft_path=pathlib.Path("specs/x.spec.md.draft"),
    )
    state = walker.record_answer(state, concern_id="seed-1", answer="old")
    _, invalidated = walker.revise_answer(state, concern_id="seed-1", new_answer="new")
    assert invalidated == []


def test_revise_answer_marks_direct_dependent_stale():
    state = walker.init_walk(
        spec_intent="x",
        spec_draft_path=pathlib.Path("specs/x.spec.md.draft"),
    )
    state = walker.record_answer(state, concern_id="seed-1", answer="old")
    dep = walker.Concern(
        id="c2",
        kind="edge-case",
        receivers=["implement"],
        depends_on=["seed-1"],
        summary="depends on seed",
    )
    state.asked.append(dep)
    state.answered["c2"] = "downstream answer"
    new_state, invalidated = walker.revise_answer(
        state, concern_id="seed-1", new_answer="new"
    )
    assert "c2" in invalidated


def test_revise_answer_marks_transitive_dependents_stale():
    state = walker.init_walk(
        spec_intent="x",
        spec_draft_path=pathlib.Path("specs/x.spec.md.draft"),
    )
    state = walker.record_answer(state, concern_id="seed-1", answer="old")
    state.asked.append(walker.Concern(
        id="c2", kind="edge-case", receivers=["implement"],
        depends_on=["seed-1"], summary="depends on seed",
    ))
    state.answered["c2"] = "x"
    state.asked.append(walker.Concern(
        id="c3", kind="edge-case", receivers=["implement"],
        depends_on=["c2"], summary="depends on c2",
    ))
    state.answered["c3"] = "y"
    _, invalidated = walker.revise_answer(
        state, concern_id="seed-1", new_answer="new"
    )
    assert set(invalidated) == {"c2", "c3"}


def test_revise_answer_adds_invalidated_ids_to_stale_set():
    state = walker.init_walk(
        spec_intent="x",
        spec_draft_path=pathlib.Path("specs/x.spec.md.draft"),
    )
    state = walker.record_answer(state, concern_id="seed-1", answer="old")
    state.asked.append(walker.Concern(
        id="c2", kind="edge-case", receivers=["implement"],
        depends_on=["seed-1"], summary="x",
    ))
    state.answered["c2"] = "x"
    new_state, _ = walker.revise_answer(
        state, concern_id="seed-1", new_answer="new"
    )
    assert "c2" in new_state.stale


def test_revise_answer_raises_for_unanswered_concern():
    state = walker.init_walk(
        spec_intent="x",
        spec_draft_path=pathlib.Path("specs/x.spec.md.draft"),
    )
    with pytest.raises(KeyError, match="not in answered"):
        walker.revise_answer(state, concern_id="seed-1", new_answer="x")


def test_should_stop_returns_true_when_author_arbitrated():
    state = walker.init_walk(
        spec_intent="x",
        spec_draft_path=pathlib.Path("specs/x.spec.md.draft"),
    )
    state.stop_reason = "author-arbitrated"
    stop, reason = walker.should_stop(state)
    assert stop is True
    assert reason == "author-arbitrated"


def test_should_stop_returns_true_when_max_rounds_hit():
    state = walker.init_walk(
        spec_intent="x",
        spec_draft_path=pathlib.Path("specs/x.spec.md.draft"),
    )
    state.round_count = walker.DEFAULT_MAX_ROUNDS
    stop, reason = walker.should_stop(state)
    assert stop is True
    assert reason == "max-rounds"


def test_should_stop_returns_false_when_round_count_below_max():
    state = walker.init_walk(
        spec_intent="x",
        spec_draft_path=pathlib.Path("specs/x.spec.md.draft"),
    )
    state.round_count = 1
    stop, _ = walker.should_stop(state)
    assert stop is False


def test_should_stop_returns_true_on_per_receiver_exhaustion():
    """All pending concerns marked stale AND no answered concerns yet
    is the seed-only-and-skipped edge — exhausted for every receiver."""
    state = walker.init_walk(
        spec_intent="x",
        spec_draft_path=pathlib.Path("specs/x.spec.md.draft"),
    )
    state.pending = []  # no pending concerns at all
    stop, reason = walker.should_stop(state)
    assert stop is True
    assert reason == "per-receiver-exhausted"


def test_should_stop_returns_true_on_tier3_yield_converged():
    """Three consecutive rounds with <2 new T3 fingerprints each."""
    state = walker.init_walk(
        spec_intent="x",
        spec_draft_path=pathlib.Path("specs/x.spec.md.draft"),
    )
    state.round_count = 5
    state.yield_history = [5, 4, 1, 1, 0]  # last 3 rounds: 1, 1, 0 — all <2
    state.pending.append(walker.Concern(
        id="c2", kind="edge-case", receivers=["implement"],
        depends_on=[], summary="not exhausted",
    ))
    stop, reason = walker.should_stop(state)
    assert stop is True
    assert reason == "tier3-yield-converged"


def test_should_stop_yield_not_converged_when_only_two_low_rounds():
    state = walker.init_walk(
        spec_intent="x",
        spec_draft_path=pathlib.Path("specs/x.spec.md.draft"),
    )
    state.round_count = 5
    state.yield_history = [5, 4, 3, 1, 1]  # last 3: 3, 1, 1 — not all <2
    state.pending.append(walker.Concern(
        id="c2", kind="edge-case", receivers=["implement"],
        depends_on=[], summary="x",
    ))
    stop, _ = walker.should_stop(state)
    assert stop is False


def test_should_stop_returns_false_with_pending_concerns_and_low_rounds():
    state = walker.init_walk(
        spec_intent="x",
        spec_draft_path=pathlib.Path("specs/x.spec.md.draft"),
    )
    stop, reason = walker.should_stop(state)
    assert stop is False
    assert reason is None


def test_persist_creates_file_at_path(tmp_path):
    state = walker.init_walk(
        spec_intent="x",
        spec_draft_path=pathlib.Path("specs/x.spec.md.draft"),
    )
    target = tmp_path / "walk.json"
    walker.persist(state, target)
    assert target.exists()


def test_persist_writes_valid_json(tmp_path):
    state = walker.init_walk(
        spec_intent="x",
        spec_draft_path=pathlib.Path("specs/x.spec.md.draft"),
    )
    target = tmp_path / "walk.json"
    walker.persist(state, target)
    data = json.loads(target.read_text(encoding="utf-8"))
    assert data["walker_version"] == walker.WALKER_VERSION


def test_persist_includes_spec_intent(tmp_path):
    state = walker.init_walk(
        spec_intent="my unique intent string",
        spec_draft_path=pathlib.Path("specs/x.spec.md.draft"),
    )
    target = tmp_path / "walk.json"
    walker.persist(state, target)
    data = json.loads(target.read_text(encoding="utf-8"))
    assert data["spec_intent"] == "my unique intent string"


def test_load_returns_none_when_file_missing(tmp_path):
    missing = tmp_path / "nope.json"
    assert walker.load(missing) is None


def test_persist_load_round_trip_preserves_intent(tmp_path):
    state = walker.init_walk(
        spec_intent="round-trip intent",
        spec_draft_path=pathlib.Path("specs/x.spec.md.draft"),
    )
    target = tmp_path / "walk.json"
    walker.persist(state, target)
    loaded = walker.load(target)
    assert loaded is not None
    assert loaded.spec_intent == "round-trip intent"


def test_persist_load_round_trip_preserves_pending_concerns(tmp_path):
    state = walker.init_walk(
        spec_intent="x",
        spec_draft_path=pathlib.Path("specs/x.spec.md.draft"),
    )
    target = tmp_path / "walk.json"
    walker.persist(state, target)
    loaded = walker.load(target)
    assert len(loaded.pending) == len(state.pending)


def test_persist_load_round_trip_preserves_stale_set(tmp_path):
    state = walker.init_walk(
        spec_intent="x",
        spec_draft_path=pathlib.Path("specs/x.spec.md.draft"),
    )
    state.stale.add("c-stale-1")
    state.stale.add("c-stale-2")
    target = tmp_path / "walk.json"
    walker.persist(state, target)
    loaded = walker.load(target)
    assert loaded.stale == {"c-stale-1", "c-stale-2"}


def test_persist_load_round_trip_preserves_yield_history(tmp_path):
    state = walker.init_walk(
        spec_intent="x",
        spec_draft_path=pathlib.Path("specs/x.spec.md.draft"),
    )
    state.yield_history = [3, 2, 1, 0]
    target = tmp_path / "walk.json"
    walker.persist(state, target)
    loaded = walker.load(target)
    assert loaded.yield_history == [3, 2, 1, 0]


def test_persist_uses_atomic_write_no_tmp_leftover(tmp_path):
    state = walker.init_walk(
        spec_intent="x",
        spec_draft_path=pathlib.Path("specs/x.spec.md.draft"),
    )
    target = tmp_path / "walk.json"
    walker.persist(state, target)
    leftovers = [p for p in tmp_path.iterdir() if p.name.endswith(".tmp")]
    assert leftovers == []


def test_should_stop_raises_when_yield_converge_rounds_is_zero():
    state = walker.init_walk(
        spec_intent="x",
        spec_draft_path=pathlib.Path("specs/x.spec.md.draft"),
    )
    with pytest.raises(ValueError, match="yield_converge_rounds must be >= 1"):
        walker.should_stop(state, yield_converge_rounds=0)


def test_should_stop_raises_when_yield_converge_rounds_is_negative():
    state = walker.init_walk(
        spec_intent="x",
        spec_draft_path=pathlib.Path("specs/x.spec.md.draft"),
    )
    with pytest.raises(ValueError, match="yield_converge_rounds must be >= 1"):
        walker.should_stop(state, yield_converge_rounds=-1)


def test_load_raises_on_walker_version_mismatch(tmp_path):
    state = walker.init_walk(
        spec_intent="x",
        spec_draft_path=pathlib.Path("specs/x.spec.md.draft"),
    )
    target = tmp_path / "walk.json"
    walker.persist(state, target)
    # Hand-edit the version to simulate a stale walk file
    data = json.loads(target.read_text(encoding="utf-8"))
    data["walker_version"] = "0.99.0-future"
    target.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(ValueError, match="walker_version"):
        walker.load(target)


def test_init_walk_seeds_mutates_concern():
    state = walker.init_walk(
        spec_intent="x",
        spec_draft_path=pathlib.Path("specs/x.spec.md.draft"),
    )
    assert any(
        c.kind == "receiver-clarification" and "mutates" in c.summary.lower()
        for c in state.pending
    )


def test_init_walk_seeds_never_touches_concern():
    state = walker.init_walk(
        spec_intent="x",
        spec_draft_path=pathlib.Path("specs/x.spec.md.draft"),
    )
    assert any(
        c.kind == "receiver-clarification" and "never-touches" in c.summary.lower()
        for c in state.pending
    )


def test_init_walk_seeds_decision_budget_concern():
    state = walker.init_walk(
        spec_intent="x",
        spec_draft_path=pathlib.Path("specs/x.spec.md.draft"),
    )
    assert any(
        c.kind == "receiver-clarification" and "decision-budget" in c.summary.lower()
        for c in state.pending
    )


def test_init_walk_seeds_reboot_survival_concern():
    state = walker.init_walk(
        spec_intent="x",
        spec_draft_path=pathlib.Path("specs/x.spec.md.draft"),
    )
    assert any(
        c.kind == "receiver-clarification" and "reboot-survival" in c.summary.lower()
        for c in state.pending
    )


def test_init_walk_pending_starts_with_seed_assumption_then_four_receiver_clarifications():
    state = walker.init_walk(
        spec_intent="x",
        spec_draft_path=pathlib.Path("specs/x.spec.md.draft"),
    )
    assert len(state.pending) == 5


def test_full_walk_with_revise_and_stop_persists_correctly(tmp_path):
    """E2E: answer seed-1, add three downstream concerns, answer them,
    revise seed-1, confirm c2+c3 invalidated (NOT c4 — it doesn't depend
    on seed-1), stop, persist, reload, confirm invalidation set survived."""
    walk_path = tmp_path / "walk.json"

    # Round 0 (init) — pending = [seed-1, seed-mutates, seed-never-touches, seed-decision-budget, seed-reboot-survival]
    state = walker.init_walk(
        spec_intent="build a btc poller",
        spec_draft_path=tmp_path / "btc.spec.md.draft",
    )
    walker.persist(state, walk_path)

    # Round 1: answer seed-1
    state = walker.record_answer(
        state, concern_id="seed-1", answer="assumes coingecko reachable"
    )

    # Add three downstream concerns by hand (in v0.4.1 the walker generates these
    # automatically). c2 depends on seed-1; c3 depends on c2; c4 is independent.
    state.pending.extend([
        walker.Concern(
            id="c2",
            kind="edge-case",
            receivers=["implement"],
            depends_on=["seed-1"],
            summary="rate limit handling",
        ),
        walker.Concern(
            id="c3",
            kind="edge-case",
            receivers=["implement"],
            depends_on=["c2"],
            summary="429 backoff",
        ),
        walker.Concern(
            id="c4",
            kind="receiver-clarification",
            receivers=["tier3"],
            depends_on=[],
            summary="adversarial review surface",
        ),
    ])
    walker.persist(state, walk_path)

    # Rounds 2-4: answer the three new concerns
    state = walker.record_answer(state, concern_id="c2", answer="exponential")
    state = walker.record_answer(state, concern_id="c3", answer="cap at 60s")
    state = walker.record_answer(state, concern_id="c4", answer="check egress")
    walker.persist(state, walk_path)

    # Revise round 1 — should invalidate c2 and c3 transitively, NOT c4
    state, invalidated = walker.revise_answer(
        state,
        concern_id="seed-1",
        new_answer="assumes BOTH coingecko and binance reachable",
    )
    assert set(invalidated) == {"c2", "c3"}

    # Stop + persist
    state.stop_reason = "author-arbitrated"
    walker.persist(state, walk_path)

    # Reload — confirm stale set survived round-trip
    loaded = walker.load(walk_path)
    assert loaded.stale == {"c2", "c3"}


def test_should_stop_after_full_walk_returns_author_arbitrated(tmp_path):
    state = walker.init_walk(
        spec_intent="x",
        spec_draft_path=tmp_path / "x.spec.md.draft",
    )
    state = walker.record_answer(state, concern_id="seed-1", answer="x")
    state.stop_reason = "author-arbitrated"
    stop, reason = walker.should_stop(state)
    assert stop is True
    assert reason == "author-arbitrated"
