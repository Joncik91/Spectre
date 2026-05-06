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


def should_stop(
    state: WalkState,
    *,
    max_rounds: int = DEFAULT_MAX_ROUNDS,
    yield_threshold: int = DEFAULT_YIELD_THRESHOLD,
    yield_converge_rounds: int = DEFAULT_YIELD_CONVERGE_ROUNDS,
) -> tuple[bool, str | None]:
    """Check all four stop conditions. Returns (stop, reason).

    Order of evaluation: author-arbitrated > tier3-yield-converged >
    max-rounds > per-receiver-exhausted. The first match wins so the
    reason field is deterministic.
    """
    if yield_converge_rounds <= 0:
        raise ValueError("yield_converge_rounds must be >= 1")

    if state.stop_reason == "author-arbitrated":
        return (True, "author-arbitrated")

    # Tier 3 yield convergence: last `yield_converge_rounds` deltas all below threshold.
    if (
        len(state.yield_history) >= yield_converge_rounds
        and all(
            d < yield_threshold for d in state.yield_history[-yield_converge_rounds:]
        )
    ):
        return (True, "tier3-yield-converged")

    if state.round_count >= max_rounds:
        return (True, "max-rounds")

    # Per-receiver exhaustion: nothing left to ask any receiver.
    if not any(c.id not in state.stale for c in state.pending):
        return (True, "per-receiver-exhausted")

    return (False, None)


def _serialize_concern(c: Concern) -> dict[str, Any]:
    return {
        "id": c.id,
        "kind": c.kind,
        "receivers": list(c.receivers),
        "depends_on": list(c.depends_on),
        "summary": c.summary,
    }


def _deserialize_concern(d: dict[str, Any]) -> Concern:
    return Concern(
        id=d["id"],
        kind=d["kind"],
        receivers=list(d["receivers"]),
        depends_on=list(d["depends_on"]),
        summary=d["summary"],
    )


def persist(state: WalkState, path: pathlib.Path) -> None:
    """Atomically write WalkState to JSON at path.

    Uses tempfile.mkstemp + os.replace for crash-safety — same pattern as
    bin/_scratchpad.atomic_write. Sets only stay encodable by serializing
    as sorted lists.
    """
    payload: dict[str, Any] = {
        "walker_version": WALKER_VERSION,
        "spec_intent": state.spec_intent,
        "spec_draft_path": str(state.spec_draft_path),
        "asked": [_serialize_concern(c) for c in state.asked],
        "answered": dict(state.answered),
        "pending": [_serialize_concern(c) for c in state.pending],
        "stale": sorted(state.stale),
        "stop_reason": state.stop_reason,
        "round_count": state.round_count,
        "yield_history": list(state.yield_history),
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=path.name, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2)
        os.replace(tmp, path)
    except Exception:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


def load(path: pathlib.Path) -> WalkState | None:
    """Load WalkState from JSON. Returns None if file missing.

    Caller is responsible for handling JSON-decode errors (don't silently
    eat — bad walk state should halt with a clear message, not be ignored).
    """
    if not path.is_file():
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    ver = data.get("walker_version")
    if ver != WALKER_VERSION:
        raise ValueError(
            f"walker_version mismatch: file has {ver!r}, walker is {WALKER_VERSION!r}; "
            f"rm state/.walk.json to restart"
        )
    return WalkState(
        spec_intent=data["spec_intent"],
        spec_draft_path=pathlib.Path(data["spec_draft_path"]),
        asked=[_deserialize_concern(c) for c in data.get("asked", [])],
        answered=dict(data.get("answered", {})),
        pending=[_deserialize_concern(c) for c in data.get("pending", [])],
        stale=set(data.get("stale", [])),
        stop_reason=data.get("stop_reason"),
        round_count=data.get("round_count", 0),
        yield_history=list(data.get("yield_history", [])),
    )
