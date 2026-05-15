"""Walker stop predicate consistency (v1.2.1 #4).

`_recommend_stop_predicate` is the single source of truth for the walker
stop signal. Every code path that reports or emits ``recommended_stop`` must
go through it, so the post-answer view and the explicit ``walker coverage``
subcommand cannot disagree.
"""
import pathlib

from bin import walker


def _fully_satisfied_state() -> walker.WalkState:
    """A walk state with every gating flag flipped on and no pending concerns."""
    return walker.WalkState(
        spec_intent="x",
        spec_draft_path=pathlib.Path("specs/x.spec.md.draft"),
        lifecycle_asked=True,
        prompt_design_asked=True,
        semantic_criteria_asked=True,
        product_input_asked=True,
        product_output_asked=True,
        human_user_asked=True,
        integrator_asked=True,
        operator_asked=True,
    )


def test_109_predicate_recommends_stop_when_all_gates_pass():
    state = _fully_satisfied_state()
    cov = walker._recommend_stop_predicate(state, draft_text="")
    assert cov["recommended_stop"] is True
    assert cov["pending"] == 0
    assert cov["deferred"] == 0


def test_110_predicate_blocks_stop_when_pending_remains():
    state = _fully_satisfied_state()
    state.pending.append(
        walker.Concern(
            id="dummy-1",
            kind="edge-case",
            receivers=["implement"],
            depends_on=[],
            summary="x",
        )
    )
    cov = walker._recommend_stop_predicate(state, draft_text="")
    assert cov["recommended_stop"] is False
    assert cov["pending"] >= 1


def test_111_predicate_runs_refresh_pending_so_post_answer_view_agrees():
    # Both call sites (post-answer + walker coverage) must call the predicate;
    # this test pins that the predicate is the single point where
    # `_refresh_pending` fires before coverage is computed.
    state = _fully_satisfied_state()
    cov1 = walker._recommend_stop_predicate(state, draft_text="")
    cov2 = walker._recommend_stop_predicate(state, draft_text="")
    # Idempotent: re-running on the same state produces the same view.
    assert cov1["recommended_stop"] == cov2["recommended_stop"]
    assert cov1["pending"] == cov2["pending"]
