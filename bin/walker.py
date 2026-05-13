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
import re
import tempfile
from dataclasses import dataclass, field
from typing import Any

WALKER_VERSION = "1.0.0"

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
    "negative-path",
    "scaffold-precondition",
    "stub-invocation-detected",
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
    prefab_options: list[str] = field(default_factory=list)

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
    open_questions: list[dict] = field(default_factory=list)
    lifecycle_asked: bool = False
    prompt_design_asked: bool = False
    semantic_criteria_asked: bool = False
    last_recommend_stop_emitted: bool = False
    # v1.0 — six-view scope tracking + per-view family flags
    view_scope: dict[str, str] = field(default_factory=dict)   # view -> "in-scope" | "not-applicable"
    product_input_asked: bool = False
    product_output_asked: bool = False
    human_user_asked: bool = False
    integrator_asked: bool = False
    operator_asked: bool = False


_OQ_INLINE_RE = re.compile(
    r"(?im)(?:^|\.\s+)\s*(open|unresolved)\s*:\s*(.+?)(?=[.!?]|\n|$)"
)

# Small frozen English stopword list (no nltk dependency).
_STOPWORDS: frozenset[str] = frozenset({
    "a", "an", "the", "and", "or", "but", "in", "on", "at", "to", "for",
    "of", "with", "by", "from", "is", "it", "this", "that", "be", "as",
    "are", "was", "were", "not", "if", "its", "their", "they", "we", "i",
    "you", "he", "she", "what", "how", "when", "which", "will", "would",
    "should", "can", "do", "does", "did", "have", "has", "had", "our",
    "your", "all", "any", "each", "some", "such", "than", "then",
})


def _parse_open_questions(intent: str) -> list[dict]:
    """Parse open-question markers from intent text.

    Supports two formats:
    1. YAML frontmatter block at the top of intent:
       ---
       open_questions:
         - daemon lifecycle
       ---
    2. Inline markers in prose:
       open: should it run as systemd or pm2?
       unresolved: what's the auth strategy?

    Returns list of dicts with keys: id, text, source, resolved, deferred_by_adr.
    """
    questions: list[str] = []
    sources: list[str] = []
    prose_body = intent

    # ── YAML frontmatter ─────────────────────────────────────────────────────
    if intent.startswith("---\n") or intent.startswith("---\r\n"):
        end_idx = intent.find("\n---", 3)
        if end_idx != -1:
            frontmatter = intent[3:end_idx].strip()
            prose_body = intent[end_idx + 4:].lstrip("\r\n")
            # Minimal YAML parse: look for open_questions: section
            in_oq = False
            for line in frontmatter.splitlines():
                stripped = line.rstrip()
                if re.match(r"^\s*open_questions\s*:", stripped):
                    in_oq = True
                    continue
                if in_oq:
                    # List items under open_questions
                    item_m = re.match(r"^\s{2,}-\s+(.+)$", stripped)
                    if item_m:
                        questions.append(item_m.group(1).strip())
                        sources.append("frontmatter")
                    elif stripped and not stripped.startswith(" "):
                        # Different key — end of open_questions block
                        in_oq = False
                    # Blank lines continue the block
            # Try PyYAML for richer parsing if available and we got nothing
            if not questions:
                try:
                    import yaml  # type: ignore[import]
                    fm_data = yaml.safe_load(frontmatter)
                    if isinstance(fm_data, dict):
                        oq_list = fm_data.get("open_questions", [])
                        if isinstance(oq_list, list):
                            for item in oq_list:
                                if isinstance(item, str) and item.strip():
                                    questions.append(item.strip())
                                    sources.append("frontmatter")
                except Exception:  # noqa: BLE001
                    pass

    # ── Inline markers in prose body ─────────────────────────────────────────
    for m in _OQ_INLINE_RE.finditer(prose_body):
        text = m.group(2).strip()
        if text:
            questions.append(text)
            sources.append("inline")

    # Build result with stable oq-N ids
    result: list[dict] = []
    for n, (text, src) in enumerate(zip(questions, sources), start=1):
        result.append({
            "id": f"oq-{n}",
            "text": text,
            "source": src,
            "resolved": False,
            "deferred_by_adr": None,
        })
    return result


def _jaccard_overlap(a: str, b: str) -> float:
    """Jaccard token overlap over non-stopword lowercased tokens."""
    def _tokens(s: str) -> set[str]:
        raw = re.split(r"[^a-z0-9]+", s.lower())
        return {t for t in raw if t and t not in _STOPWORDS}

    ta, tb = _tokens(a), _tokens(b)
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / len(ta | tb)


def _resolve_open_questions(state: WalkState, answer: str) -> None:
    """Attempt to resolve open questions based on an answer text.

    Jaccard threshold: 0.4 for OQs with >=4 content tokens; 0.6 for
    shorter OQs (<=3 tokens) to prevent false resolution of terse OQs.
    """
    def _content_tokens(s: str) -> set[str]:
        raw = re.split(r"[^a-z0-9]+", s.lower())
        return {t for t in raw if t and t not in _STOPWORDS}

    answer_lower = answer.lower().strip()
    for oq in state.open_questions:
        if oq["resolved"]:
            continue
        # Explicit prefix: "resolves: oq-N"
        if answer_lower.startswith(f"resolves: {oq['id']}"):
            oq["resolved"] = True
            continue
        # Jaccard token overlap — raise threshold for short OQs (<=3 content tokens)
        oq_tokens = _content_tokens(oq["text"])
        threshold = 0.6 if len(oq_tokens) <= 3 else 0.4
        if _jaccard_overlap(answer, oq["text"]) >= threshold:
            oq["resolved"] = True


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
    open_questions = _parse_open_questions(spec_intent)
    return WalkState(
        spec_intent=spec_intent,
        spec_draft_path=spec_draft_path,
        pending=seeds,
        open_questions=open_questions,
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
    Also flips lifecycle/prompt-design/semantic-criteria asked flags and
    attempts open-question resolution.
    """
    for i, c in enumerate(state.pending):
        if c.id == concern_id:
            state.asked.append(c)
            state.answered[concern_id] = answer
            del state.pending[i]
            state.round_count += 1
            # Flip seed-family flags
            if concern_id == "seed-lifecycle":
                state.lifecycle_asked = True
            elif concern_id == "seed-prompt-design":
                state.prompt_design_asked = True
            elif concern_id == "seed-semantic-criteria":
                state.semantic_criteria_asked = True
            # v1.0 — record view scope when a scope-check concern is answered.
            # The scope-* concern IDs map 1:1 to view names; the answer is
            # treated as "not-applicable" only when it contains that exact
            # token (case-insensitive) — anything else flips the view in-scope.
            scope_view = _VIEW_SCOPE_CONCERN_IDS.get(concern_id)
            if scope_view is not None:
                if "not-applicable" in answer.lower():
                    state.view_scope[scope_view] = "not-applicable"
                else:
                    state.view_scope[scope_view] = "in-scope"
            # v1.0 — flip per-view family flags when the last follow-up answered.
            # The family is "asked" once its scope-check is answered AND all
            # in-scope follow-ups have been answered. For N/A scope, the family
            # is asked immediately (no follow-ups will surface).
            for view, family_attr, follow_up_ids in (
                ("product-input", "product_input_asked",
                 {"input-source-pi", "input-schema-pi", "input-retry-pi", "input-exemplar-pi"}),
                ("product-output", "product_output_asked",
                 {"output-sink-po", "output-schema-po", "output-on-failure-po"}),
                ("human-user", "human_user_asked",
                 {"help-text-hu", "help-text-style-hu", "error-text-style-hu", "error-text-shape-hu", "examples-hu"}),
                ("integrator", "integrator_asked",
                 {"api-style-int", "api-versioning-int", "api-error-model-int", "api-exemplar-int"}),
                ("operator", "operator_asked",
                 {"log-format-op", "log-format-style-op", "metrics-op", "observability-style-op", "paging-op"}),
            ):
                scoped = state.view_scope.get(view)
                if scoped == "not-applicable":
                    setattr(state, family_attr, True)
                elif scoped == "in-scope" and follow_up_ids.issubset(set(state.answered)):
                    setattr(state, family_attr, True)
            # Attempt open-question resolution
            _resolve_open_questions(state, answer)
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
    draft_text: str = "",
) -> tuple[bool, str | None]:
    """Check all stop conditions. Returns (stop, reason).

    Order of evaluation: author-arbitrated > tier3-yield-converged >
    max-rounds > per-receiver-exhausted. The first match wins so the
    reason field is deterministic.

    Drive-to-completeness override: yield-convergence is NOT authoritative
    while any hard drive-to-completeness contract is unsatisfied (Contract 1
    or Contract 2). In that case, tier3-yield-converged is suppressed so
    the walker keeps walking. max-rounds and author-arbitrated still fire.
    """
    if yield_converge_rounds <= 0:
        raise ValueError("yield_converge_rounds must be >= 1")

    if state.stop_reason == "author-arbitrated":
        return (True, "author-arbitrated")

    # Tier 3 yield convergence: last `yield_converge_rounds` deltas all below threshold.
    # Only fires when drive-to-completeness contracts are satisfied.
    yield_converged = (
        len(state.yield_history) >= yield_converge_rounds
        and all(
            d < yield_threshold for d in state.yield_history[-yield_converge_rounds:]
        )
    )
    if yield_converged:
        if _drive_to_completeness_satisfied(state, draft_text):
            return (True, "tier3-yield-converged")
        # Contracts unsatisfied — suppress yield-convergence, keep walking.

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
        "prefab_options": list(c.prefab_options),
    }


def _deserialize_concern(d: dict[str, Any]) -> Concern:
    return Concern(
        id=d["id"],
        kind=d["kind"],
        receivers=list(d["receivers"]),
        depends_on=list(d["depends_on"]),
        summary=d["summary"],
        prefab_options=list(d.get("prefab_options", [])),
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
        "open_questions": list(state.open_questions),
        "lifecycle_asked": state.lifecycle_asked,
        "prompt_design_asked": state.prompt_design_asked,
        "semantic_criteria_asked": state.semantic_criteria_asked,
        "last_recommend_stop_emitted": state.last_recommend_stop_emitted,
        # v1.0 — six-view scope + per-view family flags
        "view_scope": dict(state.view_scope),
        "product_input_asked": state.product_input_asked,
        "product_output_asked": state.product_output_asked,
        "human_user_asked": state.human_user_asked,
        "integrator_asked": state.integrator_asked,
        "operator_asked": state.operator_asked,
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
    # v1.0 — hard cutover. Pre-1.0 state files are rejected (no v0.9 specs
    # remain in the wild per the pre-flight checklist; first external users
    # define the backwards-compat story when they exist).
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
        open_questions=list(data.get("open_questions", [])),
        lifecycle_asked=data.get("lifecycle_asked", False),
        prompt_design_asked=data.get("prompt_design_asked", False),
        semantic_criteria_asked=data.get("semantic_criteria_asked", False),
        last_recommend_stop_emitted=data.get("last_recommend_stop_emitted", False),
        view_scope=dict(data.get("view_scope", {})),
        product_input_asked=data.get("product_input_asked", False),
        product_output_asked=data.get("product_output_asked", False),
        human_user_asked=data.get("human_user_asked", False),
        integrator_asked=data.get("integrator_asked", False),
        operator_asked=data.get("operator_asked", False),
    )


def yield_status_line(
    state: WalkState,
    *,
    yield_threshold: int = DEFAULT_YIELD_THRESHOLD,
    yield_converge_rounds: int = DEFAULT_YIELD_CONVERGE_ROUNDS,
) -> str:
    """Return a human-readable countdown line for the yield convergence check.

    Format:
        "YIELD: round N added M new T3 findings; stopping when last K rounds all <T (currently: [a,b,c])"

    where N = len(yield_history), M = yield_history[-1] (or 0 if empty),
    K = yield_converge_rounds, T = yield_threshold, and the trailing list is
    yield_history[-K:].

    Examples:
        round 1 with yield_history=[5]:
            "YIELD: round 1 added 5 new T3 findings; stopping when last 3 rounds all <2 (currently: [5])"
        round 4 with yield_history=[5,3,1,0]:
            "YIELD: round 4 added 0 new T3 findings; stopping when last 3 rounds all <2 (currently: [3,1,0])"
    """
    history = state.yield_history
    n = len(history)
    m = history[-1] if history else 0
    tail = history[-yield_converge_rounds:] if history else []
    return (
        f"YIELD: round {n} added {m} new T3 findings; "
        f"stopping when last {yield_converge_rounds} rounds all <{yield_threshold} "
        f"(currently: {tail})"
    )


# ── Lifecycle / LLM-call / Semantic patterns (Decision 1) ────────────────────

_INTENT_LIFECYCLE_PATTERNS: list[re.Pattern] = [
    re.compile(r"\bdaemon\b", re.IGNORECASE),
    # Tightened: \bservice\b matches "service-mesh" because Python \b treats
    # hyphen as non-word. Use negative lookbehind/lookahead on [-a-z] instead.
    re.compile(r"(?<![a-z-])service(?![-a-z])", re.IGNORECASE),
    re.compile(r"\bsystemd\b", re.IGNORECASE),
    re.compile(r"\blong-running\b", re.IGNORECASE),
    re.compile(r"\balways-on\b", re.IGNORECASE),
    re.compile(r"\bbackground\b", re.IGNORECASE),
    re.compile(r"\bpersistent\b", re.IGNORECASE),
    re.compile(r"\bwatches\b", re.IGNORECASE),
    re.compile(r"on save", re.IGNORECASE),
    re.compile(r"on change", re.IGNORECASE),
    re.compile(r"\bincremental\b", re.IGNORECASE),
    # Tightened: \blive\b matches "live" inside "live performance" (not a
    # lifecycle trigger). Require no surrounding hyphen or letter.
    re.compile(r"(?<![a-z-])live(?![-a-z])", re.IGNORECASE),
    re.compile(r"hot reload", re.IGNORECASE),
    re.compile(r"\blistens\b", re.IGNORECASE),
    re.compile(r"\bserves\b", re.IGNORECASE),
    re.compile(r"\bendpoint\b", re.IGNORECASE),
    re.compile(r"\bsocket\b", re.IGNORECASE),
    re.compile(r"\bRPC\b", re.IGNORECASE),
    re.compile(r"MCP server", re.IGNORECASE),
    re.compile(r"\bpolls\b", re.IGNORECASE),
    re.compile(r"every\s+\d+", re.IGNORECASE),
    re.compile(r"\bcron\b", re.IGNORECASE),
    re.compile(r"\bscheduled\b", re.IGNORECASE),
    re.compile(r"\bperiodic\b", re.IGNORECASE),
    re.compile(r"\bsubscribes\b", re.IGNORECASE),
    re.compile(r"\bconsumes\b", re.IGNORECASE),
    re.compile(r"on event", re.IGNORECASE),
    re.compile(r"queue worker", re.IGNORECASE),
]

_DRAFT_LIFECYCLE_PATTERNS: list[re.Pattern] = [
    re.compile(r"\bpm2\b", re.IGNORECASE),
    re.compile(r"\bforever\b", re.IGNORECASE),
    re.compile(r"\bnodemon\b", re.IGNORECASE),
    re.compile(r"\bsupervisord\b", re.IGNORECASE),
    re.compile(r"docker run -d", re.IGNORECASE),
    re.compile(r"docker-compose", re.IGNORECASE),
    re.compile(r"\bkubectl\b", re.IGNORECASE),
    re.compile(r"restart:\s*always", re.IGNORECASE),
    re.compile(r"\bsystemd\b", re.IGNORECASE),
    re.compile(r"\blaunchd\b", re.IGNORECASE),
    re.compile(r"\.plist\b", re.IGNORECASE),
    re.compile(r"\bsc create\b", re.IGNORECASE),
    re.compile(r"\bchokidar\b", re.IGNORECASE),
    re.compile(r"\bwatchman\b", re.IGNORECASE),
    re.compile(r"\bwatchdog\b", re.IGNORECASE),
    re.compile(r"\bfsnotify\b", re.IGNORECASE),
    re.compile(r"\binotify\b", re.IGNORECASE),
    re.compile(r"\bexpress\b", re.IGNORECASE),
    re.compile(r"\bfastify\b", re.IGNORECASE),
    re.compile(r"\bflask\b", re.IGNORECASE),
    re.compile(r"\bfastapi\b", re.IGNORECASE),
    re.compile(r"\baxum\b", re.IGNORECASE),
    re.compile(r"while True", re.IGNORECASE),
    re.compile(r"\bsetInterval\b", re.IGNORECASE),
    re.compile(r"\btokio::spawn\b", re.IGNORECASE),
    re.compile(r"\bonStartupFinished\b", re.IGNORECASE),
    re.compile(r"def activate\s*\(", re.IGNORECASE),
    re.compile(r"function activate\s*\(", re.IGNORECASE),
]

_DRAFT_LLM_PATTERNS: list[re.Pattern] = [
    re.compile(r"\banthropic\b", re.IGNORECASE),
    re.compile(r"\bopenai\b", re.IGNORECASE),
    re.compile(r"\bdeepseek\b", re.IGNORECASE),
    re.compile(r"\bollama\b", re.IGNORECASE),
    re.compile(r"client\.messages\.create", re.IGNORECASE),
    re.compile(r"client\.chat\.completions", re.IGNORECASE),
    re.compile(r"client\.responses\.create", re.IGNORECASE),
]


def _extract_step_actions(draft_text: str) -> list[str]:
    """Extract action: values from ## 6. Steps section of draft."""
    steps_m = re.search(r"^## 6\. Steps\s*$", draft_text, re.MULTILINE)
    if not steps_m:
        return []
    section_start = steps_m.end()
    next_h = re.search(r"^## ", draft_text[section_start:], re.MULTILINE)
    body = (
        draft_text[section_start: section_start + next_h.start()]
        if next_h
        else draft_text[section_start:]
    )
    actions: list[str] = []
    for line in body.splitlines():
        m = re.match(r"^\s+action:\s*(.*)", line, re.IGNORECASE)
        if m:
            actions.append(m.group(1).strip().strip('"').strip("'"))
    return actions


def _detect_lifecycle_trigger(state: WalkState, draft_text: str) -> bool:
    """True if intent or draft step actions match lifecycle patterns."""
    intent = state.spec_intent
    for pat in _INTENT_LIFECYCLE_PATTERNS:
        if pat.search(intent):
            return True
    if draft_text:
        actions = _extract_step_actions(draft_text)
        for action in actions:
            for pat in _DRAFT_LIFECYCLE_PATTERNS:
                if pat.search(action):
                    return True
    return False


def _detect_llm_call_trigger(state: WalkState, draft_text: str) -> bool:
    """True if any step action matches LLM-call patterns."""
    if not draft_text:
        return False
    actions = _extract_step_actions(draft_text)
    for action in actions:
        for pat in _DRAFT_LLM_PATTERNS:
            if pat.search(action):
                return True
    return False


def _existing_concern_ids(state: WalkState) -> set[str]:
    """All concern IDs in asked, pending, and answered."""
    return (
        {c.id for c in state.asked}
        | {c.id for c in state.pending}
        | set(state.answered)
    )


def generate_lifecycle_concerns(
    state: WalkState,
    draft_text: str,
) -> list[Concern]:
    """Emit seed-lifecycle concern when triggered and not yet asked."""
    if state.lifecycle_asked:
        return []
    if "seed-lifecycle" in _existing_concern_ids(state):
        return []
    if not _detect_lifecycle_trigger(state, draft_text):
        return []
    return [Concern(
        id="seed-lifecycle",
        kind="receiver-clarification",
        receivers=["human"],
        depends_on=[],
        summary=(
            "Process lifecycle for the produced daemon/service: how does it start, "
            "stop, restart on crash, survive a reboot, and who owns the process? "
            "Provide a one-paragraph answer or 'defer to later layer'."
        ),
    )]


def generate_prompt_design_concerns(
    state: WalkState,
    draft_text: str,
) -> list[Concern]:
    """Emit seed-prompt-design concern when LLM calls detected and not yet asked."""
    if state.prompt_design_asked:
        return []
    if "seed-prompt-design" in _existing_concern_ids(state):
        return []
    if not _detect_llm_call_trigger(state, draft_text):
        return []
    return [Concern(
        id="seed-prompt-design",
        kind="receiver-clarification",
        receivers=["human"],
        depends_on=[],
        summary=(
            "Prompt design for LLM-call steps: describe the structure of the LLM "
            "prompt (system/user split, format), failure modes on malformed output, "
            "parse-retry strategy, and how you'll handle version instability across "
            "model upgrades. Provide a one-paragraph answer or 'defer to later layer'."
        ),
    )]


def generate_semantic_criteria_concern(
    state: WalkState,
) -> list[Concern]:
    """Emit seed-semantic-criteria concern once per walk."""
    if state.semantic_criteria_asked:
        return []
    if "seed-semantic-criteria" in _existing_concern_ids(state):
        return []
    return [Concern(
        id="seed-semantic-criteria",
        kind="receiver-clarification",
        receivers=["human"],
        depends_on=[],
        summary=(
            "Semantic success criteria for the product: beyond CI / mechanical checks "
            "(exit codes, file existence, JSON shape), what are 1-3 criteria a human "
            "reviewer would use to judge whether this works? Provide a list or "
            "'defer to later layer'."
        ),
    )]


_VIEW_SCOPE_CONCERN_IDS = {
    "scope-product-input": "product-input",
    "scope-product-output": "product-output",
    "scope-human-user": "human-user",
    "scope-integrator": "integrator",
    "scope-operator": "operator",
}


def _view_in_scope(state: WalkState, view: str) -> bool:
    """A view is in-scope when the scope-check concern has been answered
    with anything other than 'not-applicable' (or no answer means we haven't
    asked yet — also out-of-scope for follow-up purposes)."""
    return state.view_scope.get(view) == "in-scope"


def generate_product_input_concerns(
    state: WalkState,
    draft_text: str,
) -> list[Concern]:
    """Emit the product-input scope check + follow-ups when in-scope."""
    if state.product_input_asked:
        return []
    existing = _existing_concern_ids(state)
    new: list[Concern] = []
    if "scope-product-input" not in existing:
        new.append(Concern(
            id="scope-product-input",
            kind="receiver-clarification",
            receivers=["human"],
            depends_on=[],
            summary=(
                "Product-input view scope: what feeds this product? Choose from "
                "[human-typed, programmatic-trusted, programmatic-untrusted, "
                "streamed-event, not-applicable]. If not-applicable, the input "
                "view body will be replaced with a single 'not-applicable: <reason>' "
                "field and follow-up concerns will be skipped."
            ),
            prefab_options=[
                "human-typed",
                "programmatic-trusted",
                "programmatic-untrusted",
                "streamed-event",
                "not-applicable",
            ],
        ))
    if _view_in_scope(state, "product-input"):
        for cid, summary in (
            ("input-source-pi", "Input source — stdin, file path, network protocol, env var? Name the wire format."),
            ("input-schema-pi", "Input validation schema — JSON Schema URL or inline, or 'none' if input is opaque bytes. Include the strictness level (strict | lenient | tolerant)."),
            ("input-retry-pi", "Retry budget — how many retries on malformed input before the product rejects? '0' (fail fast) | '<int>' | 'unlimited'."),
            ("input-exemplar-pi", "Exemplar binding — pick a catalog entry whose input-handling conventions match your product (run `spectre exemplars list --view-type help-text` for now; an input-shape view will surface in v1.1) or 'none' to skip exemplar-binding for this view."),
        ):
            if cid not in existing:
                new.append(Concern(
                    id=cid, kind="receiver-clarification", receivers=["human"],
                    depends_on=["scope-product-input"], summary=summary,
                ))
    return new


def generate_product_output_concerns(
    state: WalkState,
    draft_text: str,
) -> list[Concern]:
    if state.product_output_asked:
        return []
    existing = _existing_concern_ids(state)
    new: list[Concern] = []
    if "scope-product-output" not in existing:
        new.append(Concern(
            id="scope-product-output",
            kind="receiver-clarification",
            receivers=["human"],
            depends_on=[],
            summary=(
                "Product-output view scope: who reads what this product emits? Choose from "
                "[human-reader, programmatic-consumer, streaming-sink, log-aggregator, "
                "not-applicable]."
            ),
            prefab_options=[
                "human-reader",
                "programmatic-consumer",
                "streaming-sink",
                "log-aggregator",
                "not-applicable",
            ],
        ))
    if _view_in_scope(state, "product-output"):
        for cid, summary in (
            ("output-sink-po", "Output sink — stdout, file path, network protocol? Name the wire format."),
            ("output-schema-po", "Output schema — JSON Schema URL or inline, or 'none' if output is opaque text. Include exit-code-on-success and exit-code-on-failure."),
            ("output-on-failure-po", "Failure shape — what does the consumer see when this product fails? Reference §8.4 ux-contract.on-failure if you want the same string in both places."),
        ):
            if cid not in existing:
                new.append(Concern(
                    id=cid, kind="receiver-clarification", receivers=["human"],
                    depends_on=["scope-product-output"], summary=summary,
                ))
    return new


def generate_human_user_concerns(
    state: WalkState,
    draft_text: str,
) -> list[Concern]:
    if state.human_user_asked:
        return []
    existing = _existing_concern_ids(state)
    new: list[Concern] = []
    if "scope-human-user" not in existing:
        new.append(Concern(
            id="scope-human-user",
            kind="receiver-clarification",
            receivers=["human"],
            depends_on=[],
            summary=(
                "Human-user view scope: who interacts with this product directly? Choose from "
                "[cli-power-user, cli-novice, gui-only, no-human-user, not-applicable]. "
                "no-human-user covers libraries/services with no direct human UI."
            ),
            prefab_options=[
                "cli-power-user",
                "cli-novice",
                "gui-only",
                "no-human-user",
                "not-applicable",
            ],
        ))
    if _view_in_scope(state, "human-user"):
        for cid, summary in (
            ("help-text-hu", "Help text — what flags trigger help (`--help, -h`)? What categories must it include (usage, flags, examples, link-to-docs, version)?"),
            ("help-text-style-hu", "Help text exemplar — bind to a `help-text` catalog entry (e.g. `curl`, `gh`, `rustc`, `git`). Run `spectre exemplars list --view-type help-text` to see options + their axis values. Or 'none' to skip exemplar binding."),
            ("error-text-style-hu", "Error text exemplar — bind to an `error-text` catalog entry (e.g. `git`, `rust-compiler`, `gh`, `postgres`). Run `spectre exemplars list --view-type error-text`."),
            ("error-text-shape-hu", "Error text shape — what categories must each error include (what-failed, why, recovery)? What exit code on error (nonzero | specific int)?"),
            ("examples-hu", "Examples — does the help text include runnable examples? If yes, where (inline per-flag, separate EXAMPLES section, runnable code blocks)?"),
        ):
            if cid not in existing:
                new.append(Concern(
                    id=cid, kind="receiver-clarification", receivers=["human"],
                    depends_on=["scope-human-user"], summary=summary,
                ))
    return new


def generate_integrator_concerns(
    state: WalkState,
    draft_text: str,
) -> list[Concern]:
    if state.integrator_asked:
        return []
    existing = _existing_concern_ids(state)
    new: list[Concern] = []
    if "scope-integrator" not in existing:
        new.append(Concern(
            id="scope-integrator",
            kind="receiver-clarification",
            receivers=["human"],
            depends_on=[],
            summary=(
                "Integrator view scope: who programmatically integrates against this product? Choose from "
                "[library-consumer, api-consumer, webhook-subscriber, sdk-author, "
                "no-integrator, not-applicable]. no-integrator covers products with no "
                "external programmatic surface (e.g. local CLI scripts)."
            ),
            prefab_options=[
                "library-consumer",
                "api-consumer",
                "webhook-subscriber",
                "sdk-author",
                "no-integrator",
                "not-applicable",
            ],
        ))
    if _view_in_scope(state, "integrator"):
        for cid, summary in (
            ("api-style-int", "Interface style — rest-resource, rest-rpc, graphql, grpc, library, webhook? Name the wire protocol and authentication mechanism."),
            ("api-versioning-int", "Versioning — semver, url-path (/v1/), header, content-negotiation, or none? Include the breaking-change policy in one line."),
            ("api-error-model-int", "Error model — http-status-only, status-plus-body, problem-details-rfc7807, error-code-taxonomy? List required fields in error responses (code, message, request-id)."),
            ("api-exemplar-int", "API shape exemplar — bind to an `api-shape` catalog entry (e.g. `stripe-rest`, `github-graphql`, `kubernetes-api`). Run `spectre exemplars list --view-type api-shape`."),
        ):
            if cid not in existing:
                new.append(Concern(
                    id=cid, kind="receiver-clarification", receivers=["human"],
                    depends_on=["scope-integrator"], summary=summary,
                ))
    return new


def generate_operator_concerns(
    state: WalkState,
    draft_text: str,
) -> list[Concern]:
    if state.operator_asked:
        return []
    existing = _existing_concern_ids(state)
    new: list[Concern] = []
    if "scope-operator" not in existing:
        new.append(Concern(
            id="scope-operator",
            kind="receiver-clarification",
            receivers=["human"],
            depends_on=[],
            summary=(
                "Operator view scope: who runs this product in production and watches its observability? Choose from "
                "[on-call-engineer, sre-team, self-operated, no-operator, not-applicable]."
            ),
            prefab_options=[
                "on-call-engineer",
                "sre-team",
                "self-operated",
                "no-operator",
                "not-applicable",
            ],
        ))
    if _view_in_scope(state, "operator"):
        for cid, summary in (
            ("log-format-op", "Log format — plaintext, key-value (logfmt), or json-lines? List required log keys (timestamp, level, source, op, duration_ms, request_id, ...)."),
            ("log-format-style-op", "Log format exemplar — bind to a `log-format` catalog entry (e.g. `systemd-journal`, `nginx`, `structlog-json`). Run `spectre exemplars list --view-type log-format`."),
            ("metrics-op", "Metrics — what metric names does this product emit? Counter-only, counters+gauges, full Prometheus four-types, or OpenTelemetry? List 3-5 metric names."),
            ("observability-style-op", "Observability exemplar — bind to an `observability` catalog entry (e.g. `prometheus`, `tmux-status`, `htop`). Run `spectre exemplars list --view-type observability`."),
            ("paging-op", "Paging trigger — under what conditions does this product page its operator? Reference §8.7 ux-contract.on-failure for the failure signature."),
        ):
            if cid not in existing:
                new.append(Concern(
                    id=cid, kind="receiver-clarification", receivers=["human"],
                    depends_on=["scope-operator"], summary=summary,
                ))
    return new


def _check_prefab_contradiction(state: WalkState, prefab_text: str) -> bool:
    """Return True if prefab_text contradicts a prior answered concern.

    Contradiction rule: the answer contains a negation token AND shares >= 2
    content tokens with the prefab (both lowercased).
    """
    _NEGATION_TOKENS: frozenset[str] = frozenset({
        "not", "no", "never", "without", "excluding", "vendor-agnostic",
    })

    def _tokens(s: str) -> set[str]:
        # Split on non-alphanumeric (including hyphens) to normalize compound words
        return {t for t in re.split(r"[^a-z0-9]+", s.lower()) if t and len(t) > 1}

    prefab_tokens = _tokens(prefab_text)
    for answer in state.answered.values():
        answer_tokens = _tokens(answer)
        # Check for negation tokens (also split vendor-agnostic)
        has_negation = bool(answer_tokens & {"not", "no", "never", "without", "excluding"})
        if not has_negation and "vendor-agnostic" in answer.lower():
            has_negation = True
        if has_negation:
            shared = (prefab_tokens & answer_tokens) - _STOPWORDS
            # Remove negation-adjacent tokens from shared computation
            shared -= {"not", "no", "never", "without", "excluding", "vendor", "agnostic"}
            if len(shared) >= 2:
                return True
    return False


def _attach_defer_option(prefab_options: list[str], concern: Concern) -> list[str]:
    """Append 'defer to later layer' if not already present and concern is not receiver-clarification."""
    if concern.kind == "receiver-clarification":
        return list(prefab_options)
    for opt in prefab_options:
        if "defer to later layer" in opt.lower():
            return list(prefab_options)
    return list(prefab_options) + ["defer to later layer"]


def _refresh_pending(state: WalkState, draft_text: str) -> None:
    """Run all dynamic generators and append newly-applicable concerns to pending.

    Called from peek-pending (before returning the next concern) and from
    answer-concern (after recording an answer, before computing coverage) so
    generators fire as the draft evolves and intent signals are met.

    Generators that are already satisfied (flag set / already in pending+asked)
    are no-ops per their own guards.
    """
    state.pending.extend(generate_lifecycle_concerns(state, draft_text))
    state.pending.extend(generate_prompt_design_concerns(state, draft_text))
    state.pending.extend(generate_semantic_criteria_concern(state))
    # v1.0 — six-view concern families
    state.pending.extend(generate_product_input_concerns(state, draft_text))
    state.pending.extend(generate_product_output_concerns(state, draft_text))
    state.pending.extend(generate_human_user_concerns(state, draft_text))
    state.pending.extend(generate_integrator_concerns(state, draft_text))
    state.pending.extend(generate_operator_concerns(state, draft_text))


def _compute_coverage(state: WalkState, draft_text: str) -> dict:
    """Compute coverage metrics for the current walk state.

    Returns dict with keys: answered, pending, deferred, undefined_invariants,
    rounds, recommended_stop, recommended_stop_reason.
    """
    answered_count = len(state.answered)
    pending_count = sum(1 for c in state.pending if c.id not in state.stale)
    deferred_count = sum(1 for oq in state.open_questions if oq.get("deferred_by_adr"))
    rounds = state.round_count

    # Count undefined §8.1 invariants
    undefined_invariants = 0
    if draft_text:
        for placeholder in ("<TBD>", "<placeholder>", "<unresolved>"):
            if placeholder in draft_text:
                undefined_invariants += 1
        draft_lines = draft_text.splitlines()
        for anchor in ("mutates:", "never-touches:", "decision-budget:", "reboot-survival:"):
            # Inline check: `- anchor: ?` or `- anchor:` with nothing after colon.
            # Also handles multi-line YAML (`- anchor:\n  - value`) by peeking at
            # the next non-blank line — if it's indented content, the field IS
            # defined and we don't flag it.
            anchor_re = re.compile(
                r"^\s*-\s+" + re.escape(anchor) + r"\s*(\?|$)",
                re.MULTILINE,
            )
            m = anchor_re.search(draft_text)
            if m:
                # Anchor line has empty/? value — peek at next non-blank line
                line_end = draft_text.find("\n", m.start())
                rest = draft_text[line_end + 1:] if line_end != -1 else ""
                next_nonblank = next(
                    (ln for ln in rest.splitlines() if ln.strip()), ""
                )
                # If next non-blank line is indented (multi-line value), field
                # is defined — skip. Otherwise it is truly undefined.
                if not next_nonblank.startswith("  "):
                    undefined_invariants += 1

    # Check open questions — all resolved or deferred
    oq_all_resolved = all(
        oq.get("resolved") or oq.get("deferred_by_adr")
        for oq in state.open_questions
    ) if state.open_questions else True

    # Check seed families satisfied
    lifecycle_satisfied = (
        state.lifecycle_asked
        or not _detect_lifecycle_trigger(state, draft_text)
    )
    prompt_design_satisfied = (
        state.prompt_design_asked
        or not _detect_llm_call_trigger(state, draft_text)
    )
    # semantic_criteria_asked is the single source of truth — set by record_answer
    # when seed-semantic-criteria is answered. No need to also check state.answered.
    semantic_satisfied = state.semantic_criteria_asked

    recommended_stop = (
        oq_all_resolved
        and undefined_invariants == 0
        and lifecycle_satisfied
        and prompt_design_satisfied
        and semantic_satisfied
        and pending_count == 0
    )
    recommended_stop_reason = "coverage-complete" if recommended_stop else None

    return {
        "answered": answered_count,
        "pending": pending_count,
        "deferred": deferred_count,
        "undefined_invariants": undefined_invariants,
        "rounds": rounds,
        "recommended_stop": recommended_stop,
        "recommended_stop_reason": recommended_stop_reason,
    }


def generate_negative_path_concerns(
    state: WalkState,
    steps: list[dict],
) -> list[Concern]:
    """For each step that has non-empty `produces` AND no `negative_paths` field,
    generate one Concern asking the human about the obvious failure branch.

    Idempotent: never emits a concern whose `id` already exists in state.asked
    or state.pending.

    Parameters
    ----------
    state:
        Current walk state; used for idempotency check against asked/pending ids.
    steps:
        List of step dicts as returned by spec_ast._parse_steps_section, where each
        dict may have 'produces' (list[str]) and 'negative_paths' (list[dict]).
    """
    existing_ids: set[str] = (
        {c.id for c in state.asked}
        | {c.id for c in state.pending}
        | set(state.answered)
    )
    concerns: list[Concern] = []
    for step in steps:
        step_n = step.get("step")
        if step_n is None:
            continue
        produces = step.get("produces", []) or []
        if not produces:
            continue
        negative_paths = step.get("negative_paths", []) or []
        if negative_paths:
            continue
        concern_id = f"negpath-{step_n}"
        if concern_id in existing_ids:
            continue
        concerns.append(Concern(
            id=concern_id,
            kind="negative-path",
            receivers=["human"],
            depends_on=[],
            summary=(
                f"Step {step_n} declares produces:{produces} but no negative-paths. "
                f"What is the obvious failure branch (yt-dlp 4xx? disk full? interrupted "
                f"mid-write?) and how should we handle it (retry / reject / escalate)?"
            ),
        ))
    return concerns


# ── Scaffold-precondition concern ─────────────────────────────────────────────

# Stdlib top-level modules for `python -m <pkg>` heuristic — these do NOT need
# a scaffold step.  Mirrors the list in spec_ast._STDLIB_TOPS (kept in sync
# manually; a single canonical location is out of scope for stdlib-only policy).
_SCAFFOLD_STDLIB_TOPS: frozenset[str] = frozenset({
    "abc", "ast", "asyncio", "base64", "binascii", "builtins",
    "calendar", "cgi", "cgitb", "chunk", "cmath", "cmd", "code",
    "codecs", "codeop", "collections", "colorsys", "compileall",
    "concurrent", "configparser", "contextlib", "contextvars", "copy",
    "copyreg", "cProfile", "csv", "ctypes", "curses", "dataclasses",
    "datetime", "dbm", "decimal", "difflib", "dis", "doctest", "email",
    "encodings", "enum", "errno", "faulthandler", "fcntl", "filecmp",
    "fileinput", "fnmatch", "fractions", "ftplib", "functools", "gc",
    "getopt", "getpass", "gettext", "glob", "grp", "gzip", "hashlib",
    "heapq", "hmac", "html", "http", "idlelib", "imaplib", "importlib",
    "inspect", "io", "ipaddress", "itertools", "json", "keyword",
    "lib2to3", "linecache", "locale", "logging", "lzma", "mailbox",
    "marshal", "math", "mimetypes", "mmap", "modulefinder",
    "multiprocessing", "netrc", "nis", "nntplib", "numbers", "operator",
    "optparse", "os", "pathlib", "pdb", "pkgutil", "platform",
    "plistlib", "poplib", "posix", "posixpath", "pprint", "profile",
    "pstats", "pty", "pwd", "py_compile", "pyclbr", "pydoc", "queue",
    "quopri", "random", "re", "readline", "reprlib", "resource",
    "rlcompleter", "runpy", "sched", "secrets", "select", "selectors",
    "shelve", "shlex", "shutil", "signal", "site", "smtpd", "smtplib",
    "sndhdr", "socket", "socketserver", "spwd", "sqlite3",
    "sre_compile", "sre_constants", "sre_parse", "ssl", "stat",
    "statistics", "string", "stringprep", "struct", "subprocess",
    "sunau", "symtable", "sys", "sysconfig", "syslog", "tabnanny",
    "tarfile", "telnetlib", "tempfile", "termios", "test", "textwrap",
    "threading", "time", "timeit", "tkinter", "token", "tokenize",
    "tomllib", "trace", "traceback", "tracemalloc", "tty", "turtle",
    "turtledemo", "types", "typing", "unicodedata", "unittest", "urllib",
    "uu", "uuid", "venv", "pip", "warnings", "wave", "weakref",
    "webbrowser", "wsgiref", "xdrlib", "xml", "xmlrpc", "zipapp",
    "zipfile", "zipimport", "zlib", "zoneinfo", "_thread",
    "http.server", "venv", "ensurepip", "distutils",
})

# Pre-compiled patterns for _detect_scaffold_gap — compiled once at import time.
_SCAFFOLD_PIP_INSTALL_RE = re.compile(
    r"\bpip\s+install\s+(-e\s+\.|\.)(?:\s|$|&&|;)"
)
_SCAFFOLD_PIP_REQUIREMENTS_RE = re.compile(
    r"\bpip\s+install\s+-r\s+(\S+)"
)
_SCAFFOLD_CARGO_RE = re.compile(
    r"\bcargo\s+(build|run|test|install)\b"
)
_SCAFFOLD_NPM_RE = re.compile(
    r"\bnpm\s+(install|ci|run)\b"
)
_SCAFFOLD_YARN_PNPM_RE = re.compile(
    r"\b(yarn|pnpm)\s*(install)?\b"
)
_SCAFFOLD_MAKE_BARE_RE = re.compile(
    r"^\s*make(\s+\S+)?\s*$"
)
_SCAFFOLD_MAKE_INLINE_RE = re.compile(
    r"(?:^|&&|;|\s)\bmake\b(?:\s+\w+)?(?:\s|$|&&|;)"
)
_SCAFFOLD_GO_RE = re.compile(
    r"\bgo\s+(build|test|run)\b"
)
_SCAFFOLD_PYTHON_M_RE = re.compile(
    r"\bpython3?\s+-m\s+([\w.]+)"
)
_SCAFFOLD_SYSTEMCTL_RE = re.compile(
    r"\bsystemctl\s+(start|enable)\s+([\w@.-]+)"
)
_SCAFFOLD_DOCKER_COMPOSE_RE = re.compile(
    r"\bdocker[\s-]compose\s+up\b"
)


def _detect_scaffold_gap(
    action: str,
    all_produces: list[str],
) -> tuple[str, str] | None:
    """Detect whether *action* implies a precondition that no step produces.

    Returns (implied_precondition_description, question_text) when a gap is
    detected, or None when no gap is found.

    ``all_produces`` is a flat list of every produces: entry across ALL steps,
    used to check whether the implied precondition is covered anywhere in the
    spec (the forgotten-scaffold pattern often omits the file entirely).
    """
    a = action.strip()

    def _produces_contains(token: str) -> bool:
        """True when any produces entry contains the token as a substring."""
        return any(token in p for p in all_produces)

    # ── pip install -e . / pip install . ─────────────────────────────────────
    if _SCAFFOLD_PIP_INSTALL_RE.search(a):
        if not (_produces_contains("pyproject.toml") or _produces_contains("setup.py")):
            return (
                "pyproject.toml (or setup.py)",
                (
                    "Step 1's action is `{action}` which requires `pyproject.toml` in the cwd. "
                    "No step authors this file. Should there be a Step 0 that scaffolds the "
                    "package skeleton (pyproject.toml + your package's __init__.py)? Or does "
                    "some earlier process provide this file outside the spec?"
                ),
            )

    # ── pip install -r <file> ─────────────────────────────────────────────────
    m = _SCAFFOLD_PIP_REQUIREMENTS_RE.search(a)
    if m:
        req_file = m.group(1).split("&&")[0].split(";")[0].strip()
        if not _produces_contains(req_file):
            return (
                req_file,
                (
                    "Step 1's action is `{action}` which requires `"
                    + req_file
                    + "` in the cwd. "
                    "No step authors this file. Should there be a Step 0 that writes the "
                    "requirements file? Or is it committed to the repo already?"
                ),
            )

    # ── cargo build / cargo run / cargo test / cargo install --path . ────────
    if _SCAFFOLD_CARGO_RE.search(a):
        if not _produces_contains("Cargo.toml"):
            return (
                "Cargo.toml",
                (
                    "Step 1's action is `{action}` which requires `Cargo.toml` in the cwd. "
                    "No step authors this file. Should there be a Step 0 that scaffolds the "
                    "Rust package (Cargo.toml + src/main.rs or src/lib.rs)?"
                ),
            )

    # ── npm install / npm ci / npm run ───────────────────────────────────────
    if _SCAFFOLD_NPM_RE.search(a):
        if not _produces_contains("package.json"):
            return (
                "package.json",
                (
                    "Step 1's action is `{action}` which requires `package.json` in the cwd. "
                    "No step authors this file. Should there be a Step 0 that scaffolds the "
                    "Node package (package.json)?"
                ),
            )

    # ── yarn / yarn install / pnpm install ───────────────────────────────────
    if _SCAFFOLD_YARN_PNPM_RE.search(a):
        if not _produces_contains("package.json"):
            return (
                "package.json",
                (
                    "Step 1's action is `{action}` which requires `package.json` in the cwd. "
                    "No step authors this file. Should there be a Step 0 that scaffolds the "
                    "Node package (package.json)?"
                ),
            )

    # ── make / make <target> ─────────────────────────────────────────────────
    if _SCAFFOLD_MAKE_BARE_RE.search(a) or _SCAFFOLD_MAKE_INLINE_RE.search(a):
        if not _produces_contains("Makefile"):
            return (
                "Makefile",
                (
                    "Step 1's action is `{action}` which requires a `Makefile` in the cwd. "
                    "No step authors this file. Should there be a Step 0 that writes the Makefile?"
                ),
            )

    # ── go build / go test / go run (bare cwd form) ──────────────────────────
    if _SCAFFOLD_GO_RE.search(a):
        if not _produces_contains("go.mod"):
            return (
                "go.mod",
                (
                    "Step 1's action is `{action}` which requires `go.mod` in the cwd. "
                    "No step authors this file. Should there be a Step 0 that runs "
                    "`go mod init` or scaffolds the module?"
                ),
            )

    # ── python -m <pkg> / python3 -m <pkg> ───────────────────────────────────
    m = _SCAFFOLD_PYTHON_M_RE.search(a)
    if m:
        pkg = m.group(1)
        top = pkg.split(".")[0]
        if top not in _SCAFFOLD_STDLIB_TOPS:
            # Check if the package appears in produces anywhere
            pkg_slash = pkg.replace(".", "/")
            if not (_produces_contains(pkg) or _produces_contains(pkg_slash)):
                return (
                    pkg,
                    (
                        "Step 1's action is `{action}` which invokes `python -m "
                        + pkg
                        + "`. "
                        "No step authors the `"
                        + pkg
                        + "` package. Should there be a Step 0 that "
                        "installs or scaffolds it? Or does some earlier process provide it?"
                    ),
                )

    # ── systemctl start/enable <unit> ────────────────────────────────────────
    m = _SCAFFOLD_SYSTEMCTL_RE.search(a)
    if m:
        unit = m.group(2)
        unit_file = unit if unit.endswith(".service") else unit + ".service"
        if not (
            _produces_contains(unit_file)
            or _produces_contains(f"/etc/systemd/system/{unit_file}")
        ):
            return (
                unit_file,
                (
                    "Step 1's action is `{action}` which requires `"
                    + unit_file
                    + "` to exist. "
                    "No step authors this unit file. Should there be a Step 0 that writes "
                    f"`/etc/systemd/system/{unit_file}`?"
                ),
            )

    # ── docker compose up / docker-compose up ────────────────────────────────
    if _SCAFFOLD_DOCKER_COMPOSE_RE.search(a):
        if not (
            _produces_contains("docker-compose.yml")
            or _produces_contains("compose.yaml")
            or _produces_contains("docker-compose.yaml")
            or _produces_contains("compose.yml")
        ):
            return (
                "docker-compose.yml (or compose.yaml)",
                (
                    "Step 1's action is `{action}` which requires a Compose file in the cwd. "
                    "No step authors `docker-compose.yml` or `compose.yaml`. Should there be "
                    "a Step 0 that writes the Compose file?"
                ),
            )

    return None


def generate_scaffold_precondition_concern(
    state: WalkState,
    steps: list[dict],
) -> list[Concern]:
    """Seed-pass: emit at most ONE ``scaffold-precondition`` concern.

    Fires when Step 1's action implicitly requires filesystem state that no
    step in the spec produces.  This is a one-shot concern (id ``seed-scaffold``)
    so it is naturally idempotent via the existing_ids guard.

    Parameters
    ----------
    state:
        Current walk state; used for idempotency check.
    steps:
        List of step dicts as returned by spec_ast._parse_steps_section.
    """
    existing_ids: set[str] = (
        {c.id for c in state.asked}
        | {c.id for c in state.pending}
        | set(state.answered)
    )
    concern_id = "seed-scaffold"
    if concern_id in existing_ids:
        return []

    # Locate Step 1
    step1 = next((s for s in steps if s.get("step") == 1), None)
    if step1 is None:
        return []

    action: str = step1.get("action", "") or ""  # type: ignore[assignment]
    if not action:
        return []

    # Collect all produces entries across ALL steps
    all_produces: list[str] = []
    for s in steps:
        entries = s.get("produces", []) or []
        all_produces.extend(str(e) for e in entries)

    result = _detect_scaffold_gap(action, all_produces)
    if result is None:
        return []

    _precondition_desc, question_template = result
    question = question_template.format(action=action)
    # Truncate to a reasonable summary length (walker summary has no hard cap but
    # we stay consistent with the rest of the codebase's terse summaries).
    if len(question) > 280:
        question = question[:277] + "..."

    return [
        Concern(
            id=concern_id,
            kind="scaffold-precondition",
            receivers=["human"],
            depends_on=[],
            summary=question,
        )
    ]


# ── Stub-invocation concern ───────────────────────────────────────────────────

# Stub marker strings — kept in sync with spec_ast._STUB_MARKER_STRINGS.
_WALKER_STUB_MARKERS: tuple[str, ...] = (
    "raise NotImplementedError",
    "pass  # stub",
    "pass  # TODO",
    "pass  # placeholder",
    "# TODO: implement",
    "# todo: implement",
    "# TODO: Implement",
    'console.log("stub")',
    "console.log('stub')",
    'console.log("not implemented")',
    "console.log('not implemented')",
)

_WALKER_STUB_WHY_KEYWORDS: tuple[str, ...] = (
    "stub",
    "placeholder",
    "scaffold-only",
    "replaced by step",
)

# Heredoc body extraction pattern for walker (same as spec_ast).
_WALKER_HEREDOC_RE = re.compile(
    r"(?:cat\s*>|tee)\s*(/[a-zA-Z0-9_./\-]+)\s*<<['\"]?(\w+)['\"]?\n(.*?)\n\s*\2\b",
    re.DOTALL,
)

_WALKER_WRITE_RE = re.compile(
    r"(?:echo|printf)\s+['\"]([^'\"]{0,500})['\"]\s*(?:>>?\s*)(/[a-zA-Z0-9_./\-]+)"
)

_WALKER_REDIRECT_RE = re.compile(r"(?:>>?)\s*(/[a-zA-Z0-9_./\-]+)")


def _walker_extract_write_bodies(action: str) -> list[tuple[str, str]]:
    """Return (path, body) pairs from write operations in *action*."""
    results: list[tuple[str, str]] = []
    for m in _WALKER_HEREDOC_RE.finditer(action):
        results.append((m.group(1), m.group(3)))
    for m in _WALKER_WRITE_RE.finditer(action):
        results.append((m.group(2), m.group(1)))
    return results


def _walker_body_is_stub(body: str) -> tuple[bool, str]:
    """Return (is_stub, reason) using heuristic stub detection."""
    for marker in _WALKER_STUB_MARKERS:
        if marker in body:
            return True, f"contains {marker!r}"
    non_blank = [l for l in body.splitlines() if l.strip() and not l.strip().startswith("#")]
    if non_blank and all(l.strip() in ("pass",) for l in non_blank):
        return True, "body is only 'pass'"
    if len(non_blank) < 5:
        bl = body.lower()
        if "pass" in bl or "todo" in bl or "stub" in bl:
            return True, f"short body ({len(non_blank)} lines) with stub keyword"
    return False, ""


def _walker_why_is_stub(why: str) -> tuple[bool, str]:
    """Return (is_stub, reason) if why: text contains stub-intent keywords."""
    wl = why.lower()
    for kw in _WALKER_STUB_WHY_KEYWORDS:
        if kw in wl:
            return True, f"why: contains {kw!r}"
    return False, ""


def _walker_action_writes_path(action: str, path_suffix: str) -> bool:
    """Return True if *action* writes to a path matching *path_suffix*."""
    for path, _ in _walker_extract_write_bodies(action):
        if path and (
            path == path_suffix
            or path.endswith("/" + path_suffix.lstrip("/"))
        ):
            return True
    for m in _WALKER_REDIRECT_RE.finditer(action):
        p = m.group(1)
        if p == path_suffix or p.endswith("/" + path_suffix.lstrip("/")):
            return True
    return False


def _walker_artifact_path(entry: str) -> str:
    """Return a path-like string from a contract entry."""
    if ":" not in entry:
        return entry
    scheme, _, value = entry.partition(":")
    if scheme == "file":
        return value
    if scheme == "module":
        return value.replace(".", "/")
    return value


def generate_stub_invocation_concerns(
    state: WalkState,
    steps: list[dict],
) -> list[Concern]:
    """Seed-pass: emit ``stub-invocation-detected`` concerns.

    For each step N with a requires: entry produced by step M, check:
    1. Does step M's action write a stub body for the artifact?
    2. Does step M's why: text contain stub-intent keywords?
    3. Is there a healing step between M and N that replaces the stub body?

    If stub detected and not healed, emit one concern per (step_n, artifact) pair.
    Idempotent: skips concerns whose id is already in state.

    Parameters
    ----------
    state:
        Current walk state; used for idempotency check.
    steps:
        Parsed steps from spec_ast._parse_steps_section.
    """
    existing_ids: set[str] = (
        {c.id for c in state.asked}
        | {c.id for c in state.pending}
        | set(state.answered)
    )

    concerns: list[Concern] = []

    for idx_n, step in enumerate(steps):
        step_n: int = step.get("step", 0)
        requires: list[str] = step.get("requires", []) or []

        for req_entry in requires:
            if ":" not in req_entry:
                continue

            # Find last producing step before step N
            producer_step: dict | None = None
            producer_idx: int = -1
            for idx_m in range(idx_n):
                m_step = steps[idx_m]
                m_produces: list[str] = m_step.get("produces", []) or []
                if req_entry in m_produces:
                    producer_step = m_step
                    producer_idx = idx_m

            if producer_step is None:
                continue

            m_action: str = producer_step.get("action", "") or ""
            m_why: str = producer_step.get("why", "") or ""
            m_step_n: int = producer_step.get("step", 0)

            is_stub = False
            stub_reason = ""

            stub_from_why, why_reason = _walker_why_is_stub(m_why)
            if stub_from_why:
                is_stub = True
                stub_reason = why_reason

            if not is_stub and m_action:
                for _p, body in _walker_extract_write_bodies(m_action):
                    body_stub, body_reason = _walker_body_is_stub(body)
                    if body_stub:
                        is_stub = True
                        stub_reason = body_reason
                        break

            if not is_stub:
                continue

            # Check for healing step between M and N
            artifact_path = _walker_artifact_path(req_entry)
            healed = False
            for idx_h in range(producer_idx + 1, idx_n):
                h_step = steps[idx_h]
                h_action: str = h_step.get("action", "") or ""
                if not h_action:
                    continue
                if not _walker_action_writes_path(h_action, artifact_path):
                    continue
                # Non-stub write heals the chain
                all_stub = True
                for _p, body in _walker_extract_write_bodies(h_action):
                    body_stub, _ = _walker_body_is_stub(body)
                    if not body_stub:
                        all_stub = False
                        break
                if not all_stub:
                    healed = True
                    break

            if healed:
                continue

            concern_id = f"seed-stub-{step_n}-{req_entry.replace(':', '-').replace('/', '-')}"
            # Truncate id to a safe length
            if len(concern_id) > 80:
                concern_id = concern_id[:80]
            if concern_id in existing_ids:
                continue

            artifact_display = artifact_path[:50] if len(artifact_path) <= 50 else artifact_path[-47:]
            summary = (
                f"Step {step_n} invokes {req_entry!r} produced by Step {m_step_n}. "
                f"Step {m_step_n}'s action looks like a stub ({stub_reason}). "
                f"No later step replaces Step {m_step_n}'s body before Step {step_n}. "
                f"Either Step {m_step_n} should write the real implementation of "
                f"{artifact_display!r}, or insert an authoring step before Step {step_n}. "
                f"Otherwise /implement will hit Path B retry at Step {step_n}."
            )
            if len(summary) > 280:
                summary = summary[:277] + "..."

            concerns.append(Concern(
                id=concern_id,
                kind="stub-invocation-detected",
                receivers=["implement"],
                depends_on=[],
                summary=summary,
            ))

    return concerns


def _drive_to_completeness_satisfied(
    state: WalkState,
    draft_text: str,
) -> bool:
    """Return True when all drive-to-completeness contracts are satisfied.

    Checks:
    1. No pending unresolved-requires concerns (Contract 1 — requires resolution).
       Proxy: any pending concern whose summary mentions 'requires' and 'unowned'.
    2. No stub-invocation-detected concerns still pending (Contract 2).
    3. (Contract 3 is warn-only — does NOT block convergence here.)

    This is a lightweight heuristic check; the authoritative enforcement is Tier 1
    at lock time. The walker uses this to keep yielding when a hard gap is detected.
    """
    from bin import spec_ast as _spec_ast  # lazy import

    if not draft_text:
        return True

    try:
        steps = _spec_ast._parse_steps_section(draft_text)
    except Exception:  # noqa: BLE001
        return True  # Can't parse — don't block on parse failure

    # Contract 1: any step with requires: not satisfied by a prior produces:
    cumulative: set[str] = set()
    for step in steps:
        requires: list[str] = step.get("requires", []) or []
        produces: list[str] = step.get("produces", []) or []
        for req in requires:
            if ":" not in req:
                continue
            scheme, _, value = req.partition(":")
            # Simple check: is it in cumulative produces?
            if req not in cumulative:
                # Check parent-package match (mirrors spec_ast logic)
                satisfied = False
                if scheme == "module":
                    top = value.split(".")[0] if value else ""
                    if top and f"package:{top}" in cumulative:
                        satisfied = True
                    if not satisfied:
                        for prod in cumulative:
                            if prod.startswith("module:"):
                                pv = prod.split(":", 1)[1]
                                if value == pv or value.startswith(pv + "."):
                                    satisfied = True
                                    break
                if not satisfied:
                    return False
        # Accumulate valid produces
        for p in produces:
            if ":" in p:
                cumulative.add(p)

    # Contract 2: any stub-invocation-detected concern still pending
    for c in state.pending:
        if c.id not in state.stale and c.kind == "stub-invocation-detected":
            return False

    return True


# ── CLI entrypoint ────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse
    import sys
    from bin import _status

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
    p_ior.add_argument(
        "--json",
        action="store_true",
        dest="json_mode",
        help="Emit full walk state as JSON instead of the one-line summary.",
    )

    # ── peek-pending ──────────────────────────────────────────────────────────
    p_pp = sub.add_parser(
        "peek-pending",
        help=(
            "Return the next pending concern's full body. "
            "Prints EMPTY and exits 0 if no pending concerns remain."
        ),
    )
    p_pp.add_argument(
        "--state-path",
        default="state/.walk.json",
        help="Path to walk state JSON (default: state/.walk.json).",
    )
    p_pp.add_argument(
        "--json",
        action="store_true",
        dest="json_mode",
        help="Emit the concern as JSON instead of the human-readable format.",
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

    # ── get-state ─────────────────────────────────────────────────────────────
    p_gs = sub.add_parser(
        "get-state",
        help=(
            "Read current walk state. Without --json prints a 1-line summary; "
            "with --json emits the full state dict."
        ),
    )
    p_gs.add_argument(
        "--state-path",
        default="state/.walk.json",
        help="Path to walk state JSON (default: state/.walk.json).",
    )
    p_gs.add_argument(
        "--json",
        action="store_true",
        default=False,
        help="Emit full state as JSON instead of 1-line summary.",
    )

    # ── append-concern ────────────────────────────────────────────────────────
    p_ac = sub.add_parser(
        "append-concern",
        help="Append a new concern dict to pending.",
    )
    p_ac.add_argument("--id", required=True, help="Unique concern id.")
    p_ac.add_argument(
        "--kind",
        required=True,
        choices=list(KNOWN_CONCERN_KINDS),
        help=f"Concern kind. One of: {', '.join(KNOWN_CONCERN_KINDS)}.",
    )
    p_ac.add_argument(
        "--receiver",
        required=True,
        choices=list(KNOWN_RECEIVERS),
        help=f"Receiver. One of: {', '.join(KNOWN_RECEIVERS)}.",
    )
    p_ac.add_argument("--summary", required=True, help="Concern summary text.")
    p_ac.add_argument(
        "--state-path",
        default="state/.walk.json",
        help="Path to walk state JSON (default: state/.walk.json).",
    )

    # ── answer-concern ────────────────────────────────────────────────────────
    p_an = sub.add_parser(
        "answer-concern",
        help="Move a concern from pending to answered, increment round_count.",
    )
    p_an.add_argument("--id", required=True, help="Concern id to answer.")
    p_an.add_argument("--answer", required=True, help="Answer text.")
    p_an.add_argument(
        "--state-path",
        default="state/.walk.json",
        help="Path to walk state JSON (default: state/.walk.json).",
    )
    p_an.add_argument(
        "--verbose",
        action="store_true",
        dest="verbose",
        help="Emit full coverage line per round.",
    )

    # ── stop ──────────────────────────────────────────────────────────────────
    p_st = sub.add_parser(
        "stop",
        help="Set stop_reason on the walk state.",
    )
    p_st.add_argument("--reason", required=True, help=f"Stop reason. Canonical: {', '.join(STOP_REASONS)} (other strings accepted).")
    p_st.add_argument(
        "--state-path",
        default="state/.walk.json",
        help="Path to walk state JSON (default: state/.walk.json).",
    )
    p_st.add_argument(
        "--draft",
        default=None,
        help="Path to spec draft file (for coverage computation).",
    )

    # ── coverage ──────────────────────────────────────────────────────────────
    p_cov = sub.add_parser(
        "coverage",
        help="Read-only coverage report for the current walk state.",
    )
    p_cov.add_argument(
        "--state-path",
        default="state/.walk.json",
        help="Path to walk state JSON (default: state/.walk.json).",
    )
    p_cov.add_argument(
        "--draft",
        default=None,
        help="Path to spec draft file.",
    )
    p_cov.add_argument(
        "--json",
        action="store_true",
        dest="json_mode",
        help="Emit pure JSON to stdout (status to stderr).",
    )

    # ── defer-open-question ───────────────────────────────────────────────────
    p_doq = sub.add_parser(
        "defer-open-question",
        help="Mark an open question as deferred to a specific ADR.",
    )
    p_doq.add_argument("--id", required=True, help="Open question id (e.g. oq-2).")
    p_doq.add_argument("--adr", required=True, help="ADR slug (e.g. adr-0007).")
    p_doq.add_argument(
        "--state-path",
        default="state/.walk.json",
        help="Path to walk state JSON (default: state/.walk.json).",
    )

    args = parser.parse_args()

    if args.cmd == "init-or-resume":
        state_path = pathlib.Path(args.state_path)
        draft_path = pathlib.Path(args.draft)
        try:
            state = load(state_path)
        except ValueError as exc:
            _status.emit("error", "walker.state_load", dest="stderr", reason=str(exc),
                         remediation="run /vision to initialize a new walk")
            sys.exit(1)

        if state is None:
            state = init_walk(
                spec_intent=args.intent,
                spec_draft_path=draft_path,
            )
            # Extend seeds with scaffold-precondition concern if the draft
            # already exists and Step 1 implies a missing scaffold.
            if draft_path.exists():
                try:
                    draft_text = draft_path.read_text(encoding="utf-8")
                except OSError:
                    draft_text = ""
                if draft_text:
                    from bin import spec_ast as _spec_ast  # lazy — avoid circular import cost
                    steps = _spec_ast._parse_steps_section(draft_text)
                    state.pending.extend(
                        generate_scaffold_precondition_concern(state, steps)
                    )
                    # Contract 2: stub-invocation-detected concerns
                    state.pending.extend(
                        generate_stub_invocation_concerns(state, steps)
                    )
            try:
                persist(state, state_path)
            except OSError as exc:
                _status.emit("error", "walker.persist", dest="stderr", reason=str(exc),
                             remediation="verify write permissions on state/ then retry")
                sys.exit(1)

        if args.json_mode:
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
                "open_questions": list(state.open_questions),
                "lifecycle_asked": state.lifecycle_asked,
                "prompt_design_asked": state.prompt_design_asked,
                "semantic_criteria_asked": state.semantic_criteria_asked,
                "last_recommend_stop_emitted": state.last_recommend_stop_emitted,
            }
            print(json.dumps(payload, indent=2, sort_keys=True))
        else:
            stop = state.stop_reason if state.stop_reason else "none"
            pending_count = sum(1 for c in state.pending if c.id not in state.stale)
            oq_count = len(state.open_questions)
            _status.emit("ok", "walker.init",
                         rounds=state.round_count,
                         pending=pending_count,
                         open_questions=oq_count,
                         stop=stop)
            if oq_count > 0:
                oq_ids = ",".join(oq["id"] for oq in state.open_questions)
                _status.emit("result", "walker.open-questions-detected",
                             count=oq_count, ids=oq_ids)

    elif args.cmd == "peek-pending":
        state_path = pathlib.Path(args.state_path)
        try:
            state = load(state_path)
        except ValueError as exc:
            _status.emit("error", "walker.state_load", dest="stderr", reason=str(exc),
                         remediation="run /vision to initialize a new walk")
            sys.exit(1)
        if state is None:
            from bin import _path_display
            _status.emit("error", "walker.state_missing", dest="stderr",
                         path=_path_display.display(state_path),
                         remediation="run /vision to start")
            sys.exit(1)

        # Read draft for dynamic generator refresh
        draft_text_pp = ""
        if state.spec_draft_path.exists():
            try:
                draft_text_pp = state.spec_draft_path.read_text(encoding="utf-8")
            except OSError:
                pass
        # Fire newly-applicable generators before returning next concern
        _refresh_pending(state, draft_text_pp)
        # Persist if generators added anything (idempotent if nothing changed)
        try:
            persist(state, state_path)
        except OSError as exc:
            _status.emit("error", "walker.persist", dest="stderr", reason=str(exc),
                         remediation="verify write permissions on state/ then retry")
            sys.exit(1)

        concern = next_concern(state)
        if concern is None:
            if args.json_mode:
                print("null")
            else:
                _status.emit("ok", "walker.empty")
            sys.exit(0)

        if args.json_mode:
            print(json.dumps(_serialize_concern(concern), indent=2, sort_keys=True))
            # In JSON mode, PROMPT goes to stderr to keep stdout pure-JSON
            _prompt_kwargs: dict = dict(
                id=concern.id,
                round=state.round_count,
                prompt=concern.summary,
                dest="stderr",
            )
            if concern.prefab_options:
                _prompt_kwargs["options"] = ",".join(concern.prefab_options)
            _status.emit("prompt", "walker.concern", **_prompt_kwargs)
        else:
            _status.emit("result", "walker.peek",
                         id=concern.id,
                         kind=concern.kind,
                         receiver=", ".join(concern.receivers),
                         depends_on=", ".join(concern.depends_on) if concern.depends_on else "none",
                         summary=concern.summary)
            # Also emit PROMPT so skill can render structured numbered choices
            _prompt_kwargs = dict(
                id=concern.id,
                round=state.round_count,
                prompt=concern.summary,
            )
            if concern.prefab_options:
                _prompt_kwargs["options"] = ",".join(concern.prefab_options)
            _status.emit("prompt", "walker.concern", **_prompt_kwargs)

    elif args.cmd == "yield-check":
        from bin import spec_evaluator as _se  # lazy import — avoid cost on init-or-resume

        state_path = pathlib.Path(args.state_path)
        draft_path = pathlib.Path(args.draft)
        try:
            state = load(state_path)
        except ValueError as exc:
            _status.emit("error", "walker.state_load", dest="stderr", reason=str(exc),
                         remediation="run /vision to initialize a new walk")
            sys.exit(1)
        if state is None:
            _status.emit("ok", "walker.yield_skipped", reason="no-walk-state")
            sys.exit(0)
        if not draft_path.exists():
            _status.emit("ok", "walker.yield_skipped", reason="draft-missing")
            sys.exit(0)
        if state.round_count <= 0:
            _status.emit("ok", "walker.yield_skipped", reason="round_count=0")
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
            _status.emit("error", "walker.evaluator_failed", dest="stderr", reason=str(exc),
                         remediation="check spec syntax then run /vision to re-initialize")
            sys.exit(1)

        new_t3 = sum(
            1 for f in result.findings if f.tier == 3 and f.kind != "tier3-unavailable"
        )
        state.yield_history.append(new_t3)
        try:
            persist(state, state_path)
        except OSError as exc:
            _status.emit("error", "walker.persist", dest="stderr", reason=str(exc),
                         remediation="verify write permissions on state/ then retry")
            sys.exit(1)
        _status.emit("ok", "walker.yield",
                     new_t3=new_t3,
                     history=str(state.yield_history[-5:]))

    elif args.cmd == "get-state":
        state_path = pathlib.Path(args.state_path)
        try:
            state = load(state_path)
        except ValueError as exc:
            _status.emit("error", "walker.state_load", dest="stderr", reason=str(exc),
                         remediation="run /vision to initialize a new walk")
            sys.exit(1)
        if state is None:
            _status.emit("error", "walker.state_missing", dest="stderr",
                         path=str(state_path),
                         remediation="run /vision to start")
            sys.exit(1)

        if args.json:
            payload = {
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
                "open_questions": list(state.open_questions),
                "lifecycle_asked": state.lifecycle_asked,
                "prompt_design_asked": state.prompt_design_asked,
                "semantic_criteria_asked": state.semantic_criteria_asked,
                "last_recommend_stop_emitted": state.last_recommend_stop_emitted,
            }
            print(json.dumps(payload, indent=2, sort_keys=True))
        else:
            stop = state.stop_reason if state.stop_reason else "none"
            pending_count = sum(1 for c in state.pending if c.id not in state.stale)
            answered_count = len(state.answered)
            _status.emit("result", "walker.state",
                         rounds=state.round_count,
                         answered=answered_count,
                         pending=pending_count,
                         stop=stop)

    elif args.cmd == "append-concern":
        state_path = pathlib.Path(args.state_path)
        try:
            state = load(state_path)
        except ValueError as exc:
            _status.emit("error", "walker.state_load", dest="stderr", reason=str(exc),
                         remediation="run /vision to initialize a new walk")
            sys.exit(1)
        if state is None:
            _status.emit("error", "walker.state_missing", dest="stderr",
                         path=str(state_path),
                         remediation="run /vision to start")
            sys.exit(1)

        # Validate kind (argparse choices already enforces this, but guard explicitly
        # in case the function is reused programmatically)
        if args.kind not in KNOWN_CONCERN_KINDS:
            _status.emit("error", "walker.unknown_kind", dest="stderr", kind=args.kind,
                         remediation="open an issue at https://github.com/Joncik91/Spectre/issues with this halt's full output")
            sys.exit(1)

        # Reject duplicate id (in pending OR answered)
        existing_ids = {c.id for c in state.pending} | {c.id for c in state.asked} | set(state.answered)
        if args.id in existing_ids:
            _status.emit("error", "walker.duplicate_id", dest="stderr", id=args.id,
                         remediation="open an issue at https://github.com/Joncik91/Spectre/issues with this halt's full output")
            sys.exit(1)

        receiver = args.receiver  # already validated by argparse choices
        new_concern = Concern(
            id=args.id,
            kind=args.kind,
            receivers=[receiver],
            depends_on=[],
            summary=args.summary,
        )
        state.pending.append(new_concern)
        try:
            persist(state, state_path)
        except OSError as exc:
            _status.emit("error", "walker.persist", dest="stderr", reason=str(exc),
                         remediation="verify write permissions on state/ then retry")
            sys.exit(1)
        _status.emit("ok", "walker.concern_appended", id=args.id)

    elif args.cmd == "answer-concern":
        state_path = pathlib.Path(args.state_path)
        try:
            state = load(state_path)
        except ValueError as exc:
            _status.emit("error", "walker.state_load", dest="stderr", reason=str(exc),
                         remediation="run /vision to initialize a new walk")
            sys.exit(1)
        if state is None:
            _status.emit("error", "walker.state_missing", dest="stderr",
                         path=str(state_path),
                         remediation="run /vision to start")
            sys.exit(1)

        try:
            record_answer(state, concern_id=args.id, answer=args.answer)
        except KeyError as exc:
            _status.emit("error", "walker.answer_failed", dest="stderr", reason=str(exc),
                         remediation="run 'spectre walker get-state --json' to list valid concern IDs")
            sys.exit(1)

        # Read draft for generator refresh + coverage computation
        draft_text = ""
        draft_path = state.spec_draft_path
        if draft_path.exists():
            try:
                draft_text = draft_path.read_text(encoding="utf-8")
            except OSError:
                pass

        # Fire newly-applicable generators now that the draft may have evolved
        _refresh_pending(state, draft_text)

        # Coverage and recommend-stop transition
        cov = _compute_coverage(state, draft_text)
        prev_emitted = state.last_recommend_stop_emitted
        if cov["recommended_stop"] and not prev_emitted:
            _status.emit("result", "walker.recommend-stop", reason="coverage-complete")
            state.last_recommend_stop_emitted = True
        # Per-round verbose coverage (explicit flag or env var)
        if getattr(args, "verbose", False) or os.environ.get("SPECTRE_VERBOSE") == "1":
            _status.emit(
                "result", "walker.coverage",
                answered=cov["answered"],
                pending=cov["pending"],
                deferred=cov["deferred"],
                **{"undefined-invariants": cov["undefined_invariants"]},
                **{"recommended-stop": "yes" if cov["recommended_stop"] else "no"},
                rounds=cov["rounds"],
            )

        try:
            persist(state, state_path)
        except OSError as exc:
            _status.emit("error", "walker.persist", dest="stderr", reason=str(exc),
                         remediation="verify write permissions on state/ then retry")
            sys.exit(1)
        _status.emit("ok", "walker.answer", id=args.id, round_count=state.round_count)

    elif args.cmd == "stop":
        state_path = pathlib.Path(args.state_path)
        try:
            state = load(state_path)
        except ValueError as exc:
            _status.emit("error", "walker.state_load", dest="stderr", reason=str(exc),
                         remediation="run /vision to initialize a new walk")
            sys.exit(1)
        if state is None:
            _status.emit("error", "walker.state_missing", dest="stderr",
                         path=str(state_path),
                         remediation="run /vision to start")
            sys.exit(1)

        # Open-question gate for author-arbitrated stop
        if args.reason == "author-arbitrated":
            unresolved_oqs = [
                oq for oq in state.open_questions
                if not oq.get("resolved") and not oq.get("deferred_by_adr")
            ]
            if unresolved_oqs:
                oq_ids = ",".join(oq["id"] for oq in unresolved_oqs)
                _status.emit(
                    "warn", "walker.open-questions-unresolved",
                    count=len(unresolved_oqs),
                    ids=oq_ids,
                    remediation="answer each question or run 'spectre walker defer-open-question --id <oq-id> --adr <slug>'",
                )
                sys.exit(1)

        # Compute and emit full coverage line
        draft_text = ""
        draft_path_for_cov = pathlib.Path(args.draft) if getattr(args, "draft", None) else state.spec_draft_path
        if draft_path_for_cov.exists():
            try:
                draft_text = draft_path_for_cov.read_text(encoding="utf-8")
            except OSError:
                pass
        cov = _compute_coverage(state, draft_text)
        _status.emit(
            "result", "walker.coverage",
            answered=cov["answered"],
            pending=cov["pending"],
            deferred=cov["deferred"],
            **{"undefined-invariants": cov["undefined_invariants"]},
            **{"recommended-stop": "yes" if cov["recommended_stop"] else "no"},
            rounds=cov["rounds"],
        )

        state.stop_reason = args.reason
        try:
            persist(state, state_path)
        except OSError as exc:
            _status.emit("error", "walker.persist", dest="stderr", reason=str(exc),
                         remediation="verify write permissions on state/ then retry")
            sys.exit(1)
        _status.emit("ok", "walker.stop", reason=args.reason)

    elif args.cmd == "coverage":
        state_path = pathlib.Path(args.state_path)
        try:
            state = load(state_path)
        except ValueError as exc:
            _status.emit("error", "walker.state_load", dest="stderr", reason=str(exc),
                         remediation="run /vision to initialize a new walk")
            sys.exit(1)
        if state is None:
            _status.emit("error", "walker.state_missing", dest="stderr",
                         path=str(state_path),
                         remediation="run /vision to start")
            sys.exit(1)

        draft_text = ""
        if getattr(args, "draft", None):
            draft_path_cov = pathlib.Path(args.draft)
            if draft_path_cov.exists():
                try:
                    draft_text = draft_path_cov.read_text(encoding="utf-8")
                except OSError:
                    pass
        cov = _compute_coverage(state, draft_text)

        if args.json_mode:
            print(json.dumps(cov, indent=2))
        else:
            _status.emit(
                "result", "walker.coverage",
                answered=cov["answered"],
                pending=cov["pending"],
                deferred=cov["deferred"],
                **{"undefined-invariants": cov["undefined_invariants"]},
                **{"recommended-stop": "yes" if cov["recommended_stop"] else "no"},
                rounds=cov["rounds"],
            )

    elif args.cmd == "defer-open-question":
        state_path = pathlib.Path(args.state_path)
        try:
            state = load(state_path)
        except ValueError as exc:
            _status.emit("error", "walker.state_load", dest="stderr", reason=str(exc),
                         remediation="run /vision to initialize a new walk")
            sys.exit(1)
        if state is None:
            _status.emit("error", "walker.state_missing", dest="stderr",
                         path=str(state_path),
                         remediation="run /vision to start")
            sys.exit(1)

        # Find the open question by id
        target_oq = None
        for oq in state.open_questions:
            if oq["id"] == args.id:
                target_oq = oq
                break

        if target_oq is None:
            _status.emit("error", "walker.bad_oq_id", dest="stderr", id=args.id,
                         remediation="run 'spectre walker get-state --json' to list valid IDs")
            sys.exit(1)

        target_oq["deferred_by_adr"] = args.adr
        try:
            persist(state, state_path)
        except OSError as exc:
            _status.emit("error", "walker.persist", dest="stderr", reason=str(exc),
                         remediation="verify write permissions on state/ then retry")
            sys.exit(1)
        _status.emit("ok", "walker.open-question-deferred", id=args.id, adr=args.adr)
