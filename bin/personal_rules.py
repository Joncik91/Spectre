"""Personal-rules adoption tracker. Stdlib only.

Loads ~/.spectre/personal-rules.toml. The /implement post-halt-success
prompt is the only sanctioned writer. Personal rules can ONLY downgrade
halts (turn a previously-halting fingerprint into a non-halting one).
They CANNOT escalate. Project-locked §8.1 spec rules are immune to
personal-rules overrides — that immunity is enforced by the call site
in bin/tier.py:should_halt, which reads the spec context.

Design: docs/superpowers/specs/2026-05-06-spectre-v0.4-cdlc-closure.md §6.4.

Public API:
    PERSONAL_RULES_VERSION
    DEFAULT_BRAKE_THRESHOLD
    personal_rules_path_default() -> pathlib.Path
    load_personal_rules() -> dict
    is_classifier_halt_overridden(*, classifier_label, fingerprint) -> bool
    append_adoption(*, classifier_label, fingerprint, reason) -> None
    adoption_count_this_session() -> int                          # in-memory (unit tests)
    adoption_count_this_session_persistent(scratchpad_path=None)  # disk-backed (production)
    reset_session_counter() -> None                               # test-only, in-memory
    reset_session_adoption_count_persistent(scratchpad_path)      # test-only, disk
"""
from __future__ import annotations

import os
import pathlib
import sys
import tempfile
import tomllib
from datetime import datetime, timezone

# v1.1.1 Fix G: see bin/walker.py for the rationale on this sys.path shim.
_ROOT = pathlib.Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from bin import _scratchpad  # noqa: E402

PERSONAL_RULES_VERSION = "0.4.1"
DEFAULT_BRAKE_THRESHOLD = 3

# Module-level session counter. Reset only via reset_session_counter (tests)
# or process restart. NOT persisted to disk — kept for unit-test compat.
#
# Production (the SKILL.md heredoc) MUST use the *_persistent helpers
# below: the heredoc spawns a fresh `python3 -` process each invocation,
# so an in-memory counter resets to 0 every prompt — defeating the
# 3-adoption sandbox-paradox brake. v0.4.1 senior-review fix.
_SESSION_ADOPTION_COUNT = 0

# Default track name used by the v2 scratchpad when /implement is invoked
# without an explicit <track> arg. Mirrors expand_v1_to_v2's "default" key.
_DEFAULT_TRACK = "default"
_PERSISTENT_COUNTER_KEY = "session_adoption_count"


def _default_scratchpad_path() -> pathlib.Path:
    """Project-relative scratchpad path. Resolved at call time so that
    monkeypatching pathlib.Path.cwd or chdir-ing into a tmp project both
    Just Work."""
    return pathlib.Path("state/scratchpad.json")


def _ensure_v2(data: dict) -> dict:
    """Return a v2-shaped dict. Auto-promotes a v1 payload (the default
    when scratchpad.json is absent) into v2 with tracks.default seeded
    from track_default()."""
    if data.get("version") == 2 and isinstance(data.get("tracks"), dict):
        return data
    return _scratchpad.expand_v1_to_v2(data)


def _read_persistent_count(scratchpad_path: pathlib.Path, track: str) -> int:
    """Load scratchpad and read tracks.<track>.session_adoption_count.

    Missing file, missing track, or non-int field all read as 0.
    """
    data = _scratchpad.load(scratchpad_path)
    tracks = data.get("tracks") or {}
    track_data = tracks.get(track) or {}
    val = track_data.get(_PERSISTENT_COUNTER_KEY, 0)
    try:
        return int(val)
    except (TypeError, ValueError):
        return 0


def _bump_persistent_count(scratchpad_path: pathlib.Path, track: str) -> int:
    """Atomically increment tracks.<track>.session_adoption_count by 1.
    Returns the new value. Auto-promotes v1 → v2 if needed."""
    data = _scratchpad.load(scratchpad_path)
    data = _ensure_v2(data)
    tracks = data.setdefault("tracks", {})
    track_data = tracks.get(track) or _scratchpad.track_default()
    current = track_data.get(_PERSISTENT_COUNTER_KEY, 0)
    try:
        current = int(current)
    except (TypeError, ValueError):
        current = 0
    new_value = current + 1
    track_data[_PERSISTENT_COUNTER_KEY] = new_value
    tracks[track] = track_data
    _scratchpad.atomic_write(scratchpad_path, data)
    return new_value


def adoption_count_this_session_persistent(
    scratchpad_path: pathlib.Path | None = None,
    *,
    track: str = _DEFAULT_TRACK,
) -> int:
    """Disk-backed adoption count for the active scratchpad track.

    Production code (the SKILL.md heredoc) calls this — its in-memory
    counterpart resets every fork. Defaults to the project-relative
    `state/scratchpad.json` and the `default` track.
    """
    if scratchpad_path is None:
        scratchpad_path = _default_scratchpad_path()
    return _read_persistent_count(scratchpad_path, track)


def reset_session_adoption_count_persistent(
    scratchpad_path: pathlib.Path,
    *,
    track: str = _DEFAULT_TRACK,
) -> None:
    """Test-only helper: zero the persistent counter for `track`.
    Production code never calls this."""
    data = _scratchpad.load(scratchpad_path)
    data = _ensure_v2(data)
    tracks = data.setdefault("tracks", {})
    track_data = tracks.get(track) or _scratchpad.track_default()
    track_data[_PERSISTENT_COUNTER_KEY] = 0
    tracks[track] = track_data
    _scratchpad.atomic_write(scratchpad_path, data)


def personal_rules_path_default() -> pathlib.Path:
    return pathlib.Path.home() / ".spectre" / "personal-rules.toml"


def load_personal_rules() -> dict:
    """Parse ~/.spectre/personal-rules.toml. Returns empty dict if file
    missing or malformed (silent fallback — adoption is opt-in, missing
    file just means no overrides in effect)."""
    target = personal_rules_path_default()
    if not target.is_file():
        return {}
    try:
        with open(target, "rb") as f:
            return tomllib.load(f)
    except (tomllib.TOMLDecodeError, OSError):
        return {}


def _override_key(classifier_label: str, fingerprint: str) -> str:
    return f"{classifier_label} / {fingerprint}"


def is_classifier_halt_overridden(*, classifier_label: str, fingerprint: str) -> bool:
    """True iff personal-rules.toml has an [overrides] entry for this exact
    (classifier_label, fingerprint) pair. Caller is responsible for ensuring
    the override is allowed in this context (project-locked §8.1 rules are
    immune — see bin/tier.py)."""
    rules = load_personal_rules()
    overrides = rules.get("overrides", {})
    return _override_key(classifier_label, fingerprint) in overrides


def _atomic_write_toml(path: pathlib.Path, body: str) -> None:
    """Same atomic-write pattern as bin/setup_wizard.write_walker_config."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=path.name + ".", dir=str(path.parent), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(body)
        os.chmod(tmp, 0o600)
        os.replace(tmp, path)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


_TOML_ESCAPES = {
    "\\": "\\\\",
    '"': '\\"',
    "\n": "\\n",
    "\r": "\\r",
    "\t": "\\t",
    "\b": "\\b",
    "\f": "\\f",
}


def _escape_toml_string(s: str) -> str:
    """Escape a string for use inside a TOML basic-string ('"..."').

    Handles \\ " and the five control-char escape sequences. Per TOML spec,
    basic strings forbid raw 0x00-0x1F except via these escapes. Other
    control chars (0x00-0x07, 0x0B, 0x0E-0x1F, 0x7F) get \\u escaped.
    """
    out_chars: list[str] = []
    for ch in s:
        if ch in _TOML_ESCAPES:
            out_chars.append(_TOML_ESCAPES[ch])
            continue
        cp = ord(ch)
        if cp < 0x20 or cp == 0x7F:
            out_chars.append(f"\\u{cp:04X}")
            continue
        out_chars.append(ch)
    return "".join(out_chars)


def append_adoption(
    *,
    classifier_label: str,
    fingerprint: str,
    reason: str,
    scratchpad_path: pathlib.Path | None = None,
    track: str = _DEFAULT_TRACK,
) -> None:
    """Add an entry to personal-rules.toml. Increments BOTH session counters.

    - In-memory `_SESSION_ADOPTION_COUNT` (kept for unit-test compat).
    - Persistent `tracks.<track>.session_adoption_count` in scratchpad.json
      (the brake the SKILL.md heredoc actually consults — survives
      python3-heredoc forks). Pass `scratchpad_path` to override the default
      `state/scratchpad.json` location (tests do this; production omits it).

    Persistent-bump errors are swallowed when the scratchpad path is
    unwritable/missing-parent — the in-memory counter and TOML write must
    still succeed even on a read-only project. The TOML body is rewritten
    in full each call (the file is small; correctness wins over append-only
    speed). Existing entries are preserved verbatim.
    """
    global _SESSION_ADOPTION_COUNT
    rules = load_personal_rules()
    overrides: dict = rules.get("overrides", {})
    overrides[_override_key(classifier_label, fingerprint)] = {
        "reason": reason,
        "adopted_at": datetime.now(timezone.utc).isoformat(),
    }
    rules["version"] = PERSONAL_RULES_VERSION
    rules["overrides"] = overrides

    # Hand-rolled TOML writer (stdlib has no toml dumper). The structure
    # is fixed and the values are already escaped on input — we just
    # serialize known shapes.
    lines = [
        '# personal-rules.toml — auto-generated by setup_wizard.',
        '# Edit this file to remove an adoption. Do NOT add adoptions by hand;',
        '# the /implement post-halt prompt is the only sanctioned writer.',
        '',
        f'version = "{rules["version"]}"',
        '',
        '[overrides]',
    ]
    for key, entry in sorted(overrides.items()):
        escaped_key = _escape_toml_string(key)
        escaped_reason = _escape_toml_string(entry["reason"])
        escaped_at = entry["adopted_at"]
        lines.append(
            f'"{escaped_key}" = '
            f'{{ reason = "{escaped_reason}", adopted_at = "{escaped_at}" }}'
        )
    body = "\n".join(lines) + "\n"

    _atomic_write_toml(personal_rules_path_default(), body)
    _SESSION_ADOPTION_COUNT += 1

    # Best-effort persistent bump. If state/ doesn't exist or is unwritable,
    # the in-memory counter still incremented above so unit tests that don't
    # touch disk still pass. Production always has state/ (created by /vision).
    target = scratchpad_path if scratchpad_path is not None else _default_scratchpad_path()
    try:
        _bump_persistent_count(target, track)
    except OSError:
        pass

    # v0.4.2: also append to per-project CDLC ledger.
    try:
        from bin import cdlc_ledger as _ledger
        _ledger.append_transition(
            kind="adapt",
            payload={
                "classifier_label": classifier_label,
                "fingerprint": fingerprint,
                "reason": reason,
            },
            project_path=pathlib.Path.cwd(),
        )
    except Exception:
        pass


def adoption_count_this_session() -> int:
    """Number of personal-rules adoptions in this Python process so far.
    The /implement skill consults this against DEFAULT_BRAKE_THRESHOLD to
    decide whether to keep firing the post-halt-success prompt."""
    return _SESSION_ADOPTION_COUNT


def reset_session_counter() -> None:
    """Test-only helper. Production code never calls this."""
    global _SESSION_ADOPTION_COUNT
    _SESSION_ADOPTION_COUNT = 0


# ── CLI entrypoint ────────────────────────────────────────────────────────────


if __name__ == "__main__":
    import argparse
    import sys
    from bin import _status

    parser = argparse.ArgumentParser(
        prog="personal_rules",
        description=(
            "Personal-rules CLI — adopt (with sandbox-paradox brake), check "
            "the persistent session counter."
        ),
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_ad = sub.add_parser(
        "adopt",
        help=(
            "Append an entry to ~/.spectre/personal-rules.toml, bump the "
            "persistent session counter, and emit `ADOPTED. (N/3 this session)`. "
            "If the persistent counter already >= DEFAULT_BRAKE_THRESHOLD, "
            "skip the write and print the BRAKE message (the post-halt-success "
            "prompt's sandbox-paradox brake)."
        ),
    )
    p_ad.add_argument(
        "--label",
        required=True,
        help="Classifier label (the first reason from the tier classifier).",
    )
    p_ad.add_argument("--fingerprint", required=True, help="Halt fingerprint (hex).")
    p_ad.add_argument("--reason", required=True, help="One-line user reason.")
    p_ad.add_argument(
        "--scratchpad",
        default="state/scratchpad.json",
        help=(
            "Path to scratchpad.json — needed for the persistent brake "
            "counter. Default: state/scratchpad.json."
        ),
    )
    p_ad.add_argument(
        "--track",
        default=_DEFAULT_TRACK,
        help=f"Track name for the brake counter (default: {_DEFAULT_TRACK!r}).",
    )

    p_cnt = sub.add_parser(
        "session-count",
        help=(
            "Print the persistent session adoption count from "
            "tracks.<track>.session_adoption_count. Returns 0 when the file "
            "or field is missing."
        ),
    )
    p_cnt.add_argument(
        "--scratchpad",
        default="state/scratchpad.json",
        help="Path to scratchpad.json (default: state/scratchpad.json).",
    )
    p_cnt.add_argument(
        "--track",
        default=_DEFAULT_TRACK,
        help=f"Track name (default: {_DEFAULT_TRACK!r}).",
    )

    args = parser.parse_args()

    if args.cmd == "adopt":
        sp_path = pathlib.Path(args.scratchpad)
        try:
            current = adoption_count_this_session_persistent(sp_path, track=args.track)
        except Exception as exc:  # noqa: BLE001
            _status.emit("error", "personal_rules.adopt", dest="stderr", reason=str(exc),
                         remediation="verify state/scratchpad.json is valid JSON and writable")
            sys.exit(1)
        if current >= DEFAULT_BRAKE_THRESHOLD:
            _status.emit("warn", "personal_rules.brake",
                         session_count=current,
                         max=DEFAULT_BRAKE_THRESHOLD,
                         remediation="~/.spectre/personal-rules.toml")
            sys.exit(0)
        try:
            append_adoption(
                classifier_label=args.label,
                fingerprint=args.fingerprint,
                reason=args.reason,
                scratchpad_path=sp_path,
                track=args.track,
            )
            new_count = adoption_count_this_session_persistent(sp_path, track=args.track)
        except Exception as exc:  # noqa: BLE001
            _status.emit("error", "personal_rules.adopt", dest="stderr", reason=str(exc),
                         remediation="verify state/scratchpad.json is valid JSON and writable")
            sys.exit(1)
        _status.emit("ok", "personal_rules.adopt",
                     session_count=new_count,
                     max=DEFAULT_BRAKE_THRESHOLD)

    elif args.cmd == "session-count":
        try:
            n = adoption_count_this_session_persistent(
                pathlib.Path(args.scratchpad), track=args.track
            )
        except Exception as exc:  # noqa: BLE001
            _status.emit("error", "personal_rules.session_count", dest="stderr", reason=str(exc),
                         remediation="verify state/scratchpad.json is valid JSON")
            sys.exit(1)
        print(n)
