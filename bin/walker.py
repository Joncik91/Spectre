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
    plus four §8.1 receiver-clarification concerns.

    The five seeds guarantee the resulting draft has §8.1 hard-contract
    fields populated (mutates, never-touches, decision-budget, reboot-survival)
    so the §6.4 evaluator doesn't block on missing-receiver-calibration.
    """
    seeds = [
        Concern(
            id="seed-1",
            kind="assumption-surface",
            receivers=["human"],
            depends_on=[],
            summary=(
                "Surface the unstated assumptions baked into the intent. What "
                "edge cases, environment quirks, or hard constraints does the "
                "author know that the spec doesn't yet say?"
            ),
        ),
        Concern(
            id="seed-mutates",
            kind="receiver-clarification",
            receivers=["human"],
            depends_on=[],
            summary=(
                "§8.1 mutates: which paths is this spec authorized to write or "
                "modify? Comma-separated list of file/dir paths."
            ),
        ),
        Concern(
            id="seed-never-touches",
            kind="receiver-clarification",
            receivers=["human"],
            depends_on=[],
            summary=(
                "§8.1 never-touches: which paths must this spec NOT write to "
                "under any circumstance? Comma-separated list."
            ),
        ),
        Concern(
            id="seed-decision-budget",
            kind="receiver-clarification",
            receivers=["human"],
            depends_on=[],
            summary=(
                "§8.1 decision-budget: paid-API call budget (e.g. '1 paid call "
                "per minute, CoinGecko free tier' or 'none')."
            ),
        ),
        Concern(
            id="seed-reboot-survival",
            kind="receiver-clarification",
            receivers=["human"],
            depends_on=[],
            summary=(
                "§8.1 reboot-survival: 'required' | 'best-effort' | 'none'. Does "
                "the spec's effect need to survive a host reboot?"
            ),
        ),
    ]
    return WalkState(
        spec_intent=spec_intent,
        spec_draft_path=spec_draft_path,
        pending=seeds,
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


# ── CLI entrypoint ────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse
    import sys

    parser = argparse.ArgumentParser(
        prog="walker",
        description="Walker CLI — init-or-resume walk state.",
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    # ── init-or-resume ────────────────────────────────────────────────────────
    p_ior = sub.add_parser(
        "init-or-resume",
        help=(
            "Load existing walk state from --state-path or initialise a new one. "
            "Prints: WALK: N rounds, M pending, stop=<reason|none>"
        ),
    )
    p_ior.add_argument(
        "--intent",
        required=True,
        help="Spec intent string (used only when initialising; ignored on resume).",
    )
    p_ior.add_argument(
        "--draft",
        required=True,
        help="Path to the spec draft file (e.g. specs/<slug>.spec.md.draft).",
    )
    p_ior.add_argument(
        "--state-path",
        default="state/.walk.json",
        help="Path to walk state JSON (default: state/.walk.json).",
    )

    # ── yield-check ───────────────────────────────────────────────────────────
    p_yc = sub.add_parser(
        "yield-check",
        help=(
            "Run the §4.4 Tier 3 yield-delta check: load walk state, evaluate "
            "the draft, count new T3 findings, append to yield_history, "
            "re-persist. Prints `YIELD: N new T3 findings this round; "
            "history=[...]`."
        ),
    )
    p_yc.add_argument("--draft", required=True, help="Spec draft path.")
    p_yc.add_argument(
        "--state-path",
        default="state/.walk.json",
        help="Path to walk state JSON (default: state/.walk.json).",
    )
    p_yc.add_argument(
        "--config",
        default=None,
        help="Reviewer config (default: ~/.spectre/reviewer.toml).",
    )
    p_yc.add_argument(
        "--bundle-dir",
        default="state",
        help="Directory for bundle persistence (default: 'state').",
    )

    args = parser.parse_args()

    if args.cmd == "init-or-resume":
        state_path = pathlib.Path(args.state_path)
        draft_path = pathlib.Path(args.draft)
        try:
            state = load(state_path)
        except ValueError as exc:
            print(f"ERROR: {exc}", file=sys.stderr)
            sys.exit(1)

        if state is None:
            state = init_walk(
                spec_intent=args.intent,
                spec_draft_path=draft_path,
            )
            try:
                persist(state, state_path)
            except OSError as exc:
                print(f"ERROR: could not persist walk state: {exc}", file=sys.stderr)
                sys.exit(1)

        stop = state.stop_reason if state.stop_reason else "none"
        pending_count = sum(1 for c in state.pending if c.id not in state.stale)
        print(f"WALK: {state.round_count} rounds, {pending_count} pending, stop={stop}")

    elif args.cmd == "yield-check":
        from bin import spec_evaluator as _se  # lazy import — avoid cost on init-or-resume

        state_path = pathlib.Path(args.state_path)
        draft_path = pathlib.Path(args.draft)
        try:
            state = load(state_path)
        except ValueError as exc:
            print(f"ERROR: {exc}", file=sys.stderr)
            sys.exit(1)
        if state is None:
            print("YIELD: skipped (no walk state)")
            sys.exit(0)
        if not draft_path.exists():
            print("YIELD: skipped (draft missing)")
            sys.exit(0)
        if state.round_count <= 0:
            print("YIELD: skipped (round_count=0)")
            sys.exit(0)

        config_path = (
            pathlib.Path(args.config)
            if args.config
            else pathlib.Path.home() / ".spectre" / "reviewer.toml"
        )
        bundle_dir = pathlib.Path(args.bundle_dir)
        try:
            result = _se.evaluate(
                draft_path,
                config_path=config_path,
                bundle_persist_dir=bundle_dir,
            )
        except Exception as exc:  # noqa: BLE001
            print(f"ERROR: evaluator failed: {exc}", file=sys.stderr)
            sys.exit(1)

        new_t3 = sum(
            1 for f in result.findings if f.tier == 3 and f.kind != "tier3-unavailable"
        )
        state.yield_history.append(new_t3)
        try:
            persist(state, state_path)
        except OSError as exc:
            print(f"ERROR: could not persist walk state: {exc}", file=sys.stderr)
            sys.exit(1)
        print(
            f"YIELD: {new_t3} new T3 findings this round; "
            f"history={state.yield_history[-5:]}"
        )
