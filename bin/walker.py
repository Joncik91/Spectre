"""Strict-hybrid interrogation walker for /vision. Stdlib only.

Owns walk state, branching, invalidation, and stop conditions. Emits
structured Concerns; never renders natural-language questions (the skill
renders those). The skill is a thin front-end; this module is canonical.

See docs/superpowers/specs/2026-05-06-spectre-v0.4-cdlc-closure.md §6.1.
"""
from __future__ import annotations

import json
import os
import pathlib
import tempfile
from dataclasses import dataclass, field
from typing import Any

WALKER_VERSION = "0.4.0"

DEFAULT_MAX_ROUNDS = 30
DEFAULT_YIELD_THRESHOLD = 2
DEFAULT_YIELD_CONVERGE_ROUNDS = 3
DEFAULT_BRAKE_THRESHOLD = 3

KNOWN_RECEIVERS: tuple[str, ...] = ("implement", "tier3", "human", "deterministic")
KNOWN_CONCERN_KINDS: tuple[str, ...] = (
    "edge-case",
    "receiver-clarification",
    "assumption-surface",
    "branch-resolution",
)
STOP_REASONS: tuple[str, ...] = (
    "author-arbitrated",
    "tier3-yield-converged",
    "max-rounds",
    "per-receiver-exhausted",
)


@dataclass
class Concern:
    id: str
    kind: str
    receivers: list[str]
    depends_on: list[str]
    summary: str

    def __post_init__(self) -> None:
        if self.kind not in KNOWN_CONCERN_KINDS:
            raise ValueError(f"unknown concern kind: {self.kind!r}")
        if not self.receivers:
            raise ValueError("Concern needs at least one receiver")
        for r in self.receivers:
            if r not in KNOWN_RECEIVERS:
                raise ValueError(f"unknown receiver: {r!r}")


@dataclass
class WalkState:
    spec_intent: str
    spec_draft_path: pathlib.Path
    asked: list[Concern] = field(default_factory=list)
    answered: dict[str, str] = field(default_factory=dict)
    pending: list[Concern] = field(default_factory=list)
    stale: set[str] = field(default_factory=set)
    stop_reason: str | None = None
    round_count: int = 0
    yield_history: list[int] = field(default_factory=list)


def init_walk(*, spec_intent: str, spec_draft_path: pathlib.Path) -> WalkState:
    """Initialize a walk. Seeds pending with one assumption-surface concern
    targeting the human — round 1 always asks the author to enumerate their
    own unstated assumptions, since the LLM doesn't have priors the human does.
    """
    seed = Concern(
        id="seed-1",
        kind="assumption-surface",
        receivers=["human"],
        depends_on=[],
        summary=(
            "Surface the unstated assumptions baked into the intent. What "
            "edge cases, environment quirks, or hard constraints does the "
            "author know that the spec doesn't yet say?"
        ),
    )
    return WalkState(
        spec_intent=spec_intent,
        spec_draft_path=spec_draft_path,
        pending=[seed],
    )


def next_concern(state: WalkState) -> Concern | None:
    """Return the first non-stale pending concern, or None if exhausted."""
    for c in state.pending:
        if c.id not in state.stale:
            return c
    return None


def record_answer(state: WalkState, *, concern_id: str, answer: str) -> WalkState:
    """Move concern from pending to asked, store the answer, bump round_count.
    Mutates state in place AND returns it (chainable).
    """
    for i, c in enumerate(state.pending):
        if c.id == concern_id:
            state.asked.append(c)
            state.answered[concern_id] = answer
            del state.pending[i]
            state.round_count += 1
            return state
    raise KeyError(f"concern_id {concern_id!r} not in pending")


def revise_answer(
    state: WalkState, *, concern_id: str, new_answer: str
) -> tuple[WalkState, list[str]]:
    """Update the answer to a previously-asked concern. Compute the
    transitive closure of concerns that depend on it (directly OR via
    intermediate dependents) and mark them stale.

    Returns (state, invalidated_ids) — the skill renders the invalidated
    set as a diff to the author and asks: re-walk these or accept-stale.

    Raises KeyError if concern_id was never answered.
    """
    if concern_id not in state.answered:
        raise KeyError(f"concern_id {concern_id!r} not in answered")

    state.answered[concern_id] = new_answer

    # Build a forward-dependency map: parent_id -> [child_ids]
    children: dict[str, list[str]] = {}
    for c in state.asked:
        for parent in c.depends_on:
            children.setdefault(parent, []).append(c.id)
    for c in state.pending:
        for parent in c.depends_on:
            children.setdefault(parent, []).append(c.id)

    # BFS from the revised concern.
    invalidated: list[str] = []
    seen: set[str] = set()
    queue: list[str] = list(children.get(concern_id, []))
    while queue:
        nxt = queue.pop(0)
        if nxt in seen:
            continue
        seen.add(nxt)
        invalidated.append(nxt)
        state.stale.add(nxt)
        queue.extend(children.get(nxt, []))

    return state, invalidated
