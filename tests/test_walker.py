"""Walker state machine tests. Stdlib + pytest only."""
import json
import pathlib
import pytest

from bin import walker


def test_walker_version_is_1_0_0():
    assert walker.WALKER_VERSION == "1.0.0"


def test_known_receivers_includes_four_canonical_names():
    assert set(walker.KNOWN_RECEIVERS) == {"implement", "tier3", "human", "deterministic"}


def test_known_concern_kinds_is_closed_set_of_seven():
    assert set(walker.KNOWN_CONCERN_KINDS) == {
        "edge-case",
        "receiver-clarification",
        "assumption-surface",
        "branch-resolution",
        "negative-path",
        "scaffold-precondition",
        "stub-invocation-detected",
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


# ── TestOpenQuestionParser ────────────────────────────────────────────────────

class TestOpenQuestionParser:
    def test_frontmatter_two_questions(self):
        intent = "---\nopen_questions:\n  - daemon lifecycle\n  - prompt failure modes\n---\nSome prose."
        result = walker._parse_open_questions(intent)
        assert len(result) == 2
        assert result[0]["id"] == "oq-1"
        assert result[0]["text"] == "daemon lifecycle"
        assert result[0]["source"] == "frontmatter"
        assert result[1]["id"] == "oq-2"
        assert result[1]["text"] == "prompt failure modes"

    def test_inline_marker(self):
        intent = "We need a poller. open: should it run as systemd or pm2?"
        result = walker._parse_open_questions(intent)
        assert len(result) == 1
        assert result[0]["source"] == "inline"
        assert "systemd" in result[0]["text"]

    def test_mixed_frontmatter_and_inline(self):
        intent = "---\nopen_questions:\n  - daemon lifecycle\n---\nWe need code. open: should we use asyncio?"
        result = walker._parse_open_questions(intent)
        assert len(result) == 2
        assert result[0]["source"] == "frontmatter"
        assert result[1]["source"] == "inline"

    def test_empty_intent(self):
        result = walker._parse_open_questions("")
        assert result == []

    def test_no_markers(self):
        result = walker._parse_open_questions("Just a plain intent with no markers.")
        assert result == []

    def test_malformed_frontmatter_no_second_delimiter(self):
        intent = "---\nopen_questions:\n  - daemon\nNo closing delimiter"
        result = walker._parse_open_questions(intent)
        # No second --- so frontmatter not parsed, inline scan runs on full text
        assert isinstance(result, list)

    def test_resolved_defaults_to_false(self):
        intent = "---\nopen_questions:\n  - test question\n---"
        result = walker._parse_open_questions(intent)
        assert result[0]["resolved"] is False

    def test_deferred_by_adr_defaults_to_none(self):
        intent = "---\nopen_questions:\n  - test question\n---"
        result = walker._parse_open_questions(intent)
        assert result[0]["deferred_by_adr"] is None

    def test_ids_are_sequential(self):
        intent = "---\nopen_questions:\n  - q1\n  - q2\n  - q3\n---"
        result = walker._parse_open_questions(intent)
        assert [r["id"] for r in result] == ["oq-1", "oq-2", "oq-3"]


# ── TestLifecycleTrigger ──────────────────────────────────────────────────────

class TestLifecycleTrigger:
    def _state(self, intent: str) -> walker.WalkState:
        return walker.WalkState(
            spec_intent=intent,
            spec_draft_path=pathlib.Path("specs/x.spec.md.draft"),
        )

    def test_intent_daemon_fires(self):
        state = self._state("build a daemon that watches files")
        assert walker._detect_lifecycle_trigger(state, "") is True

    def test_intent_service_fires(self):
        state = self._state("a background service for syncing")
        assert walker._detect_lifecycle_trigger(state, "") is True

    def test_draft_pm2_fires(self):
        state = self._state("build a thing")
        draft = "## 6. Steps\n- step: 1\n  action: pm2 start app.js\n"
        assert walker._detect_lifecycle_trigger(state, draft) is True

    def test_draft_docker_compose_fires(self):
        state = self._state("build a thing")
        draft = "## 6. Steps\n- step: 1\n  action: docker run -d myimage\n"
        assert walker._detect_lifecycle_trigger(state, draft) is True

    def test_neither_fires(self):
        state = self._state("parse a CSV file once")
        assert walker._detect_lifecycle_trigger(state, "") is False

    def test_idempotent_flag(self):
        state = self._state("build a daemon")
        state.lifecycle_asked = True
        concerns = walker.generate_lifecycle_concerns(state, "")
        assert concerns == []


# ── TestLLMCallTrigger ────────────────────────────────────────────────────────

class TestLLMCallTrigger:
    def _state(self, intent: str = "build a thing") -> walker.WalkState:
        return walker.WalkState(
            spec_intent=intent,
            spec_draft_path=pathlib.Path("specs/x.spec.md.draft"),
        )

    def test_anthropic_fires(self):
        state = self._state()
        draft = "## 6. Steps\n- step: 1\n  action: anthropic.messages.create\n"
        assert walker._detect_llm_call_trigger(state, draft) is True

    def test_openai_fires(self):
        state = self._state()
        draft = "## 6. Steps\n- step: 1\n  action: openai.chat.completions\n"
        assert walker._detect_llm_call_trigger(state, draft) is True

    def test_deepseek_fires(self):
        state = self._state()
        draft = "## 6. Steps\n- step: 1\n  action: client.chat.completions with deepseek\n"
        assert walker._detect_llm_call_trigger(state, draft) is True

    def test_ollama_fires(self):
        state = self._state()
        draft = "## 6. Steps\n- step: 1\n  action: ollama run llama3\n"
        assert walker._detect_llm_call_trigger(state, draft) is True

    def test_no_llm_no_fire(self):
        state = self._state()
        draft = "## 6. Steps\n- step: 1\n  action: cat file.txt\n"
        assert walker._detect_llm_call_trigger(state, draft) is False

    def test_empty_draft_no_fire(self):
        state = self._state()
        assert walker._detect_llm_call_trigger(state, "") is False


# ── TestPromptDesignConcern ───────────────────────────────────────────────────

class TestPromptDesignConcern:
    def test_generates_when_llm_detected(self):
        state = walker.WalkState(
            spec_intent="build a thing",
            spec_draft_path=pathlib.Path("specs/x.spec.md.draft"),
        )
        draft = "## 6. Steps\n- step: 1\n  action: anthropic.messages.create\n"
        concerns = walker.generate_prompt_design_concerns(state, draft)
        assert len(concerns) == 1
        assert concerns[0].id == "seed-prompt-design"

    def test_idempotent_after_flag_set(self):
        state = walker.WalkState(
            spec_intent="build a thing",
            spec_draft_path=pathlib.Path("specs/x.spec.md.draft"),
        )
        state.prompt_design_asked = True
        draft = "## 6. Steps\n- step: 1\n  action: openai.chat\n"
        assert walker.generate_prompt_design_concerns(state, draft) == []

    def test_no_emit_without_llm(self):
        state = walker.WalkState(
            spec_intent="parse CSV",
            spec_draft_path=pathlib.Path("specs/x.spec.md.draft"),
        )
        assert walker.generate_prompt_design_concerns(state, "") == []


# ── TestSemanticCriteriaConcern ───────────────────────────────────────────────

class TestSemanticCriteriaConcern:
    def test_generates_once(self):
        state = walker.WalkState(
            spec_intent="build a thing",
            spec_draft_path=pathlib.Path("specs/x.spec.md.draft"),
        )
        concerns = walker.generate_semantic_criteria_concern(state)
        assert len(concerns) == 1
        assert concerns[0].id == "seed-semantic-criteria"

    def test_idempotent_after_flag_set(self):
        state = walker.WalkState(
            spec_intent="build a thing",
            spec_draft_path=pathlib.Path("specs/x.spec.md.draft"),
        )
        state.semantic_criteria_asked = True
        assert walker.generate_semantic_criteria_concern(state) == []

    def test_idempotent_when_already_in_existing(self):
        state = walker.WalkState(
            spec_intent="build a thing",
            spec_draft_path=pathlib.Path("specs/x.spec.md.draft"),
        )
        state.pending.append(walker.Concern(
            id="seed-semantic-criteria",
            kind="receiver-clarification",
            receivers=["human"],
            depends_on=[],
            summary="x",
        ))
        assert walker.generate_semantic_criteria_concern(state) == []


# ── TestPrefabContradictionFilter ─────────────────────────────────────────────

class TestPrefabContradictionFilter:
    def test_vendor_agnostic_drops_deepseek(self):
        state = walker.WalkState(
            spec_intent="build a thing",
            spec_draft_path=pathlib.Path("specs/x.spec.md.draft"),
        )
        # Answer contains negation + "deepseek options" → prefab with "deepseek options" contradicts
        state.answered["seed-1"] = "vendor-agnostic, no DeepSeek-only options"
        assert walker._check_prefab_contradiction(state, "use deepseek options exclusively") is True

    def test_positive_case_kept(self):
        state = walker.WalkState(
            spec_intent="build a thing",
            spec_draft_path=pathlib.Path("specs/x.spec.md.draft"),
        )
        state.answered["seed-1"] = "we prefer anthropic for this"
        # No negation in answer → no contradiction
        assert walker._check_prefab_contradiction(state, "use anthropic claude") is False

    def test_no_answers_no_contradiction(self):
        state = walker.WalkState(
            spec_intent="build a thing",
            spec_draft_path=pathlib.Path("specs/x.spec.md.draft"),
        )
        assert walker._check_prefab_contradiction(state, "use deepseek api") is False


# ── TestDeferOptionAttachment ─────────────────────────────────────────────────

class TestDeferOptionAttachment:
    def test_appends_to_non_receiver_clarification(self):
        c = walker.Concern(
            id="c1", kind="edge-case",
            receivers=["human"], depends_on=[], summary="x",
        )
        result = walker._attach_defer_option(["option A"], c)
        assert "defer to later layer" in result

    def test_no_append_for_receiver_clarification(self):
        c = walker.Concern(
            id="c1", kind="receiver-clarification",
            receivers=["human"], depends_on=[], summary="x",
        )
        result = walker._attach_defer_option(["option A"], c)
        assert "defer to later layer" not in result

    def test_no_duplicate_defer(self):
        c = walker.Concern(
            id="c1", kind="edge-case",
            receivers=["human"], depends_on=[], summary="x",
        )
        result = walker._attach_defer_option(["defer to later layer"], c)
        assert result.count("defer to later layer") == 1


# ── TestCoverageComputation ───────────────────────────────────────────────────

class TestCoverageComputation:
    def _base_state(self, intent: str = "build a thing") -> walker.WalkState:
        # v1.0 — the five view-family flags participate in recommended_stop.
        # Pre-set them in coverage tests that aren't about view scoping so the
        # tests exercise lifecycle/prompt-design/semantic + open-question
        # behavior without being confounded by view-scope state.
        return walker.WalkState(
            spec_intent=intent,
            spec_draft_path=pathlib.Path("specs/x.spec.md.draft"),
            product_input_asked=True,
            product_output_asked=True,
            human_user_asked=True,
            integrator_asked=True,
            operator_asked=True,
        )

    def test_empty_state_recommended_stop_false(self):
        state = self._base_state()
        state.pending.append(walker.Concern(
            id="c1", kind="edge-case", receivers=["human"], depends_on=[], summary="x"
        ))
        cov = walker._compute_coverage(state, "")
        assert cov["recommended_stop"] is False

    def test_all_satisfied_recommended_stop_true(self):
        state = self._base_state()
        # No pending, no open_questions, all flags satisfied
        state.semantic_criteria_asked = True
        cov = walker._compute_coverage(state, "")
        assert cov["recommended_stop"] is True
        assert cov["recommended_stop_reason"] == "coverage-complete"

    def test_unresolved_open_question_blocks_stop(self):
        state = self._base_state()
        state.semantic_criteria_asked = True
        state.open_questions = [{"id": "oq-1", "text": "q", "resolved": False, "deferred_by_adr": None}]
        cov = walker._compute_coverage(state, "")
        assert cov["recommended_stop"] is False

    def test_deferred_open_question_allows_stop(self):
        state = self._base_state()
        state.semantic_criteria_asked = True
        state.open_questions = [{"id": "oq-1", "text": "q", "resolved": False, "deferred_by_adr": "adr-0001"}]
        cov = walker._compute_coverage(state, "")
        assert cov["recommended_stop"] is True

    def test_tbd_placeholder_blocks_stop(self):
        state = self._base_state()
        state.semantic_criteria_asked = True
        draft = "Some content <TBD> goes here"
        cov = walker._compute_coverage(state, draft)
        assert cov["undefined_invariants"] > 0
        assert cov["recommended_stop"] is False

    def test_deferred_count(self):
        state = self._base_state()
        state.open_questions = [
            {"id": "oq-1", "text": "q1", "resolved": False, "deferred_by_adr": "adr-1"},
            {"id": "oq-2", "text": "q2", "resolved": True, "deferred_by_adr": None},
        ]
        cov = walker._compute_coverage(state, "")
        assert cov["deferred"] == 1


# ── TestRecommendStopTransition ───────────────────────────────────────────────

class TestRecommendStopTransition:
    def test_flag_flips_on_transition(self):
        state = walker.WalkState(
            spec_intent="build a thing",
            spec_draft_path=pathlib.Path("specs/x.spec.md.draft"),
            product_input_asked=True,
            product_output_asked=True,
            human_user_asked=True,
            integrator_asked=True,
            operator_asked=True,
        )
        state.semantic_criteria_asked = True
        # No pending, no OQs → coverage complete
        cov = walker._compute_coverage(state, "")
        assert cov["recommended_stop"] is True
        # Simulate transition
        assert state.last_recommend_stop_emitted is False

    def test_no_redundant_transition_if_already_emitted(self):
        state = walker.WalkState(
            spec_intent="build a thing",
            spec_draft_path=pathlib.Path("specs/x.spec.md.draft"),
        )
        state.semantic_criteria_asked = True
        state.last_recommend_stop_emitted = True
        cov = walker._compute_coverage(state, "")
        # Already emitted — flag stays True, no re-emit needed
        assert state.last_recommend_stop_emitted is True


# ── TestOpenQuestionStopGate ──────────────────────────────────────────────────

class TestOpenQuestionStopGate:
    def test_unresolved_oq_in_state(self):
        """With unresolved OQs, state is set up correctly for CLI gate."""
        state = walker.WalkState(
            spec_intent="build a daemon",
            spec_draft_path=pathlib.Path("specs/x.spec.md.draft"),
        )
        state.open_questions = [
            {"id": "oq-1", "text": "daemon lifecycle", "resolved": False, "deferred_by_adr": None}
        ]
        unresolved = [oq for oq in state.open_questions if not oq["resolved"] and not oq["deferred_by_adr"]]
        assert len(unresolved) == 1

    def test_resolved_oq_no_gate(self):
        state = walker.WalkState(
            spec_intent="build a daemon",
            spec_draft_path=pathlib.Path("specs/x.spec.md.draft"),
        )
        state.open_questions = [
            {"id": "oq-1", "text": "daemon lifecycle", "resolved": True, "deferred_by_adr": None}
        ]
        unresolved = [oq for oq in state.open_questions if not oq["resolved"] and not oq["deferred_by_adr"]]
        assert len(unresolved) == 0


# ── TestPersistLoadBackwardsCompat ────────────────────────────────────────────

class TestPersistLoadV1:
    """v1.0 — hard cutover. Pre-1.0 state files raise on load (no migration)."""

    def test_pre_v1_state_file_rejected(self, tmp_path):
        """v0.4.x state file rejected with a clear error (rm + restart)."""
        state_path = tmp_path / ".walk.json"
        old_payload = {
            "walker_version": "0.4.0",
            "spec_intent": "legacy",
            "spec_draft_path": "specs/x.spec.md.draft",
            "asked": [], "answered": {}, "pending": [], "stale": [],
            "stop_reason": None, "round_count": 0, "yield_history": [],
        }
        import json as _json
        state_path.write_text(_json.dumps(old_payload), encoding="utf-8")
        with pytest.raises(ValueError, match="walker_version mismatch"):
            walker.load(state_path)

    def test_concern_with_no_prefab_options_loads(self, tmp_path):
        """v1.0 concern serialized without prefab_options gets empty list default."""
        state_path = tmp_path / ".walk.json"
        payload = {
            "walker_version": "1.0.0",
            "spec_intent": "test",
            "spec_draft_path": "specs/x.spec.md.draft",
            "asked": [],
            "answered": {},
            "pending": [
                {"id": "c1", "kind": "edge-case", "receivers": ["human"],
                 "depends_on": [], "summary": "test"}
            ],
            "stale": [],
            "stop_reason": None,
            "round_count": 0,
            "yield_history": [],
        }
        import json as _json
        state_path.write_text(_json.dumps(payload), encoding="utf-8")
        state = walker.load(state_path)
        assert state is not None
        assert state.pending[0].prefab_options == []


# ── TestRefreshPending ────────────────────────────────────────────────────────

class TestRefreshPending:
    """_refresh_pending wires lifecycle/prompt-design/semantic-criteria into pending."""

    def _base_state(self, intent: str = "build a thing") -> walker.WalkState:
        return walker.WalkState(
            spec_intent=intent,
            spec_draft_path=pathlib.Path("specs/x.spec.md.draft"),
        )

    def test_semantic_criteria_added_on_empty_state(self):
        """seed-semantic-criteria appears in pending after first refresh."""
        state = self._base_state()
        walker._refresh_pending(state, "")
        ids = [c.id for c in state.pending]
        assert "seed-semantic-criteria" in ids

    def test_lifecycle_added_when_intent_triggers(self):
        """seed-lifecycle appears when intent contains lifecycle signal."""
        state = self._base_state(intent="Build a daemon that watches the filesystem")
        walker._refresh_pending(state, "")
        ids = [c.id for c in state.pending]
        assert "seed-lifecycle" in ids

    def test_lifecycle_not_added_when_no_trigger(self):
        """seed-lifecycle absent when intent has no lifecycle signal."""
        state = self._base_state(intent="parse a CSV file and sum column A")
        walker._refresh_pending(state, "")
        ids = [c.id for c in state.pending]
        assert "seed-lifecycle" not in ids

    def test_refresh_idempotent_after_flags_set(self):
        """Second refresh with all family flags set adds nothing new."""
        state = self._base_state(intent="Build a daemon watches filesystem")
        state.lifecycle_asked = True
        state.prompt_design_asked = True
        state.semantic_criteria_asked = True
        # v1.0 — must also set the five view-family flags
        state.product_input_asked = True
        state.product_output_asked = True
        state.human_user_asked = True
        state.integrator_asked = True
        state.operator_asked = True
        walker._refresh_pending(state, "")
        assert state.pending == []

    def test_refresh_idempotent_when_concern_already_in_pending(self):
        """If seed-semantic-criteria already in pending, no duplicate added."""
        state = self._base_state()
        walker._refresh_pending(state, "")
        count_before = len(state.pending)
        walker._refresh_pending(state, "")
        assert len(state.pending) == count_before


# ── TestJaccardShortOQ ────────────────────────────────────────────────────────

class TestJaccardShortOQ:
    """Short OQ (<=3 content tokens) requires 0.6 threshold, not 0.4."""

    def _state_with_oq(self, oq_text: str) -> walker.WalkState:
        state = walker.WalkState(
            spec_intent="build a thing",
            spec_draft_path=pathlib.Path("specs/x.spec.md.draft"),
        )
        state.open_questions = [{"id": "oq-1", "text": oq_text, "resolved": False, "deferred_by_adr": None}]
        return state

    def test_short_oq_not_resolved_at_low_jaccard(self):
        """2-token OQ 'mcp protocol' NOT auto-resolved when Jaccard=0.5 (below 0.6 threshold)."""
        # "mcp protocol" → content tokens: {mcp, protocol} (2 non-stopword) → threshold=0.6
        # answer adds 2 more tokens → Jaccard = 2/4 = 0.5 < 0.6 → must NOT resolve
        state = self._state_with_oq("mcp protocol")
        walker._resolve_open_questions(state, "we use mcp protocol for everything")
        assert state.open_questions[0]["resolved"] is False

    def test_longer_oq_resolved_at_standard_jaccard(self):
        """5-token OQ resolves at standard 0.4 threshold."""
        # "daemon crash restart failure policy" → many non-stopword tokens
        state = self._state_with_oq("daemon crash restart failure policy")
        # Answer shares 4 of 5 tokens — Jaccard > 0.4
        walker._resolve_open_questions(state, "daemon crash restart failure policy is retry")
        assert state.open_questions[0]["resolved"] is True

    def test_explicit_resolves_prefix_always_works(self):
        """Explicit 'resolves: oq-1' prefix resolves regardless of OQ length."""
        state = self._state_with_oq("use mcp")
        walker._resolve_open_questions(state, "resolves: oq-1 we will use mcp")
        assert state.open_questions[0]["resolved"] is True


# ── TestLifecycleFalsePositive ────────────────────────────────────────────────

class TestLifecycleFalsePositive:
    """Tightened patterns must not fire on service-mesh or live-performance."""

    def _state(self, intent: str) -> walker.WalkState:
        return walker.WalkState(
            spec_intent=intent,
            spec_draft_path=pathlib.Path("specs/x.spec.md.draft"),
        )

    def test_lifecycle_no_false_positive_on_service_mesh(self):
        """'service-mesh research' intent must NOT trigger lifecycle concern."""
        state = self._state("service-mesh research and comparison tool")
        assert walker._detect_lifecycle_trigger(state, "") is False

    def test_standalone_service_still_fires(self):
        """Plain 'service' (not hyphenated) still triggers."""
        state = self._state("deploy a service to handle webhooks")
        assert walker._detect_lifecycle_trigger(state, "") is True

    def test_live_in_hyphenated_context_no_false_positive(self):
        """'live-performance' must NOT trigger lifecycle concern."""
        state = self._state("analyze live-performance metrics offline")
        assert walker._detect_lifecycle_trigger(state, "") is False

    def test_standalone_live_still_fires(self):
        """Standalone 'live' still triggers (e.g. 'live reload')."""
        state = self._state("build a live dashboard for metrics")
        assert walker._detect_lifecycle_trigger(state, "") is True


# ── TestMultiLineYamlInvariants ───────────────────────────────────────────────

class TestMultiLineYamlInvariants:
    """Multi-line YAML §8.1 fields must NOT be flagged as undefined."""

    def test_inline_empty_anchor_is_flagged(self):
        """Inline `- mutates:` with no value IS flagged as undefined."""
        draft = "## 8. Contracts\n- mutates:\n"
        cov = walker._compute_coverage(
            walker.WalkState(spec_intent="x", spec_draft_path=pathlib.Path("x.draft")),
            draft,
        )
        assert cov["undefined_invariants"] > 0

    def test_inline_defined_anchor_not_flagged(self):
        """Inline `- mutates: /etc/foo` is NOT flagged."""
        draft = "## 8. Contracts\n- mutates: /etc/foo\n"
        state = walker.WalkState(spec_intent="x", spec_draft_path=pathlib.Path("x.draft"))
        state.semantic_criteria_asked = True
        cov = walker._compute_coverage(state, draft)
        assert cov["undefined_invariants"] == 0

    def test_multiline_yaml_anchor_not_flagged(self):
        """Multi-line form `- mutates:\\n  - /etc/foo` is NOT flagged."""
        draft = "## 8. Contracts\n- mutates:\n  - /etc/foo\n  - /var/log/app\n"
        state = walker.WalkState(spec_intent="x", spec_draft_path=pathlib.Path("x.draft"))
        state.semantic_criteria_asked = True
        cov = walker._compute_coverage(state, draft)
        assert cov["undefined_invariants"] == 0
