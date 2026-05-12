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
                print(f"ERROR: could not persist walk state: {exc}", file=sys.stderr)
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
            }
            print(json.dumps(payload, indent=2, sort_keys=True))
        else:
            stop = state.stop_reason if state.stop_reason else "none"
            pending_count = sum(1 for c in state.pending if c.id not in state.stale)
            print(f"WALK: {state.round_count} rounds, {pending_count} pending, stop={stop}")

    elif args.cmd == "peek-pending":
        state_path = pathlib.Path(args.state_path)
        try:
            state = load(state_path)
        except ValueError as exc:
            print(f"ERROR: {exc}", file=sys.stderr)
            sys.exit(1)
        if state is None:
            print("ERROR: walk state not found", file=sys.stderr)
            sys.exit(1)

        concern = next_concern(state)
        if concern is None:
            print("EMPTY")
            sys.exit(0)

        if args.json_mode:
            print(json.dumps(_serialize_concern(concern), indent=2, sort_keys=True))
        else:
            print(f"id: {concern.id}")
            print(f"kind: {concern.kind}")
            print(f"receiver: {', '.join(concern.receivers)}")
            print(f"depends_on: {', '.join(concern.depends_on) if concern.depends_on else 'none'}")
            print(f"summary: {concern.summary}")

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

    elif args.cmd == "get-state":
        state_path = pathlib.Path(args.state_path)
        try:
            state = load(state_path)
        except ValueError as exc:
            print(f"ERROR: {exc}", file=sys.stderr)
            sys.exit(1)
        if state is None:
            print("ERROR: no walk state at " + str(state_path), file=sys.stderr)
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
            }
            print(json.dumps(payload, indent=2, sort_keys=True))
        else:
            stop = state.stop_reason if state.stop_reason else "none"
            pending_count = sum(1 for c in state.pending if c.id not in state.stale)
            answered_count = len(state.answered)
            print(
                f"WALK: rounds={state.round_count} answered={answered_count} "
                f"pending={pending_count} stop={stop}"
            )

    elif args.cmd == "append-concern":
        state_path = pathlib.Path(args.state_path)
        try:
            state = load(state_path)
        except ValueError as exc:
            print(f"ERROR: {exc}", file=sys.stderr)
            sys.exit(1)
        if state is None:
            print("ERROR: no walk state at " + str(state_path), file=sys.stderr)
            sys.exit(1)

        # Validate kind (argparse choices already enforces this, but guard explicitly
        # in case the function is reused programmatically)
        if args.kind not in KNOWN_CONCERN_KINDS:
            print(f"ERROR: unknown kind {args.kind!r}", file=sys.stderr)
            sys.exit(1)

        # Reject duplicate id (in pending OR answered)
        existing_ids = {c.id for c in state.pending} | {c.id for c in state.asked} | set(state.answered)
        if args.id in existing_ids:
            print(f"ERROR: concern id {args.id!r} already exists", file=sys.stderr)
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
            print(f"ERROR: could not persist walk state: {exc}", file=sys.stderr)
            sys.exit(1)
        print(f"OK: appended concern {args.id!r} to pending")

    elif args.cmd == "answer-concern":
        state_path = pathlib.Path(args.state_path)
        try:
            state = load(state_path)
        except ValueError as exc:
            print(f"ERROR: {exc}", file=sys.stderr)
            sys.exit(1)
        if state is None:
            print("ERROR: no walk state at " + str(state_path), file=sys.stderr)
            sys.exit(1)

        try:
            record_answer(state, concern_id=args.id, answer=args.answer)
        except KeyError as exc:
            print(f"ERROR: {exc}", file=sys.stderr)
            sys.exit(1)

        try:
            persist(state, state_path)
        except OSError as exc:
            print(f"ERROR: could not persist walk state: {exc}", file=sys.stderr)
            sys.exit(1)
        print(f"OK: answered concern {args.id!r}; round_count={state.round_count}")

    elif args.cmd == "stop":
        state_path = pathlib.Path(args.state_path)
        try:
            state = load(state_path)
        except ValueError as exc:
            print(f"ERROR: {exc}", file=sys.stderr)
            sys.exit(1)
        if state is None:
            print("ERROR: no walk state at " + str(state_path), file=sys.stderr)
            sys.exit(1)

        state.stop_reason = args.reason
        try:
            persist(state, state_path)
        except OSError as exc:
            print(f"ERROR: could not persist walk state: {exc}", file=sys.stderr)
            sys.exit(1)
        print(f"OK: stop_reason set to {args.reason!r}")
