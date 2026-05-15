"""Tests for Fix D: walker.round status emission in record_answer.

Two cases:
  1. walker.round is emitted after record_answer increments round_count.
  2. The emitted fields contain the correct round number and pending count.

Calls real walker.record_answer and captures _status.emit via monkeypatching
the _status module's emit function (not mocking record_answer itself).

Pragma guard: assertion-style names only. One assertion per test.
Tests asserting absence/emptiness use _returns_empty/_is_none/_no_ naming.
"""
from __future__ import annotations

import pathlib
from unittest import mock

from bin import walker
from bin import _status


# ── Helpers ───────────────────────────────────────────────────────────────────


def _state_with_concerns(*concern_ids: str) -> walker.WalkState:
    """Return a WalkState with the given concerns in pending."""
    state = walker.WalkState(
        spec_intent="test intent",
        spec_draft_path=pathlib.Path("/tmp/test.spec.md.draft"),
    )
    for cid in concern_ids:
        state.pending.append(walker.Concern(
            id=cid,
            kind="edge-case",
            receivers=["human"],
            depends_on=[],
            summary=f"Test concern {cid}",
        ))
    return state


# ── Case 1: walker.round is emitted ──────────────────────────────────────────


def test_record_answer_emits_walker_round_status():
    """record_answer must emit an info status with code 'walker.round'."""
    state = _state_with_concerns("c-1", "c-2")
    emitted_codes: list[str] = []

    def _capture_emit(level: str, code: str, **kwargs):
        emitted_codes.append(code)

    with mock.patch("bin._status.emit", side_effect=_capture_emit):
        walker.record_answer(state, concern_id="c-1", answer="yes")

    assert "walker.round" in emitted_codes


# ── Case 2: emitted fields are correct ───────────────────────────────────────


def test_record_answer_emits_walker_round_with_correct_round_and_pending():
    """Emitted walker.round event must have round=1 and pending=1 after first answer."""
    state = _state_with_concerns("c-1", "c-2")
    captured_kwargs: list[dict] = []

    def _capture_emit(level: str, code: str, **kwargs):
        if code == "walker.round":
            captured_kwargs.append({"level": level, **kwargs})

    with mock.patch("bin._status.emit", side_effect=_capture_emit):
        walker.record_answer(state, concern_id="c-1", answer="done")

    assert len(captured_kwargs) == 1
    ev = captured_kwargs[0]
    assert ev["round"] == 1 and ev["pending"] == 1
