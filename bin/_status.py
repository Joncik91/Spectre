"""bin/_status.py — central status emitter for Spectre CLI.

Single public function: emit(level, code, **fields)

Levels (always lower-case):
    ok      — successful completion of a low-level step
    info    — informational context (suppressed under SPECTRE_QUIET=1)
    warn    — recoverable issue; user should be aware
    halt    — execution blocked; user must act
    error   — unrecoverable failure
    result  — summary output the user asked for
    prompt  — question / input request directed at the user

Output format (default text mode):
    <LEVEL> <code> key=value key=value ...

    One line. Human-readable. Shell-parseable (starts with a known word).

Environment variables:
    SPECTRE_QUIET=1   — suppresses ok and info lines (warn/halt/error/result/prompt always emit)
    SPECTRE_VERBOSE=1 — renders optional expand= field as additional context lines
    SPECTRE_JSON=1    — writes JSON record to stdout; text goes to stderr
"""
from __future__ import annotations

import json
import os
import sys
from typing import Any

# Recognised levels (order is intentional: ascending severity)
LEVELS = ("ok", "info", "warn", "halt", "error", "result", "prompt")

# These levels always emit regardless of SPECTRE_QUIET.
_ALWAYS_LEVELS = frozenset(("warn", "halt", "error", "result", "prompt"))


def _is_quiet() -> bool:
    return os.environ.get("SPECTRE_QUIET", "0").strip() == "1"


def _is_verbose() -> bool:
    return os.environ.get("SPECTRE_VERBOSE", "0").strip() == "1"


def _is_json_mode() -> bool:
    return os.environ.get("SPECTRE_JSON", "0").strip() == "1"


def _format_fields(fields: dict[str, Any]) -> str:
    """Render key=value pairs. Values with spaces are quoted."""
    parts: list[str] = []
    for k, v in fields.items():
        if k == "expand":
            continue  # never included in the one-line format
        s = str(v)
        if " " in s or not s:
            parts.append(f'{k}="{s}"')
        else:
            parts.append(f"{k}={s}")
    return " ".join(parts)


def emit(
    level: str,
    code: str,
    *,
    dest: str = "stdout",
    **fields: Any,
) -> None:
    """Emit a structured status line.

    Parameters
    ----------
    level:
        One of LEVELS. Validated; raises ValueError for unknown levels.
    code:
        Stable dotted identifier, e.g. 'walker.init', 'eval.tier'.
    dest:
        'stdout' (default) or 'stderr'. Overrides the stream selection logic
        when you need a specific stream regardless of JSON mode.
    **fields:
        Structured payload rendered as key=value pairs.
        Special key 'expand': multi-line context rendered only under
        SPECTRE_VERBOSE=1 (never included in the default one-line form).
    """
    if level not in LEVELS:
        raise ValueError(f"unknown status level: {level!r} — must be one of {LEVELS}")

    quiet = _is_quiet()
    verbose = _is_verbose()
    json_mode = _is_json_mode()

    # Quiet suppression: ok/info skipped unless verbose overrides
    if quiet and not verbose and level not in _ALWAYS_LEVELS:
        return

    expand_text: str | None = fields.pop("expand", None)

    if json_mode and dest == "stdout":
        # JSON mode: structured record to stdout; text status to stderr
        record: dict[str, Any] = {"level": level, "code": code, **fields}
        if expand_text and verbose:
            record["expand"] = expand_text
        print(json.dumps(record, separators=(",", ":")), file=sys.stdout)
        # Also emit human text to stderr so the operator can still follow progress
        field_str = _format_fields(fields)
        text_line = f"{level.upper()} {code}"
        if field_str:
            text_line += f" {field_str}"
        print(text_line, file=sys.stderr)
    else:
        # Text mode
        stream = sys.stderr if dest == "stderr" else sys.stdout
        field_str = _format_fields(fields)
        text_line = f"{level.upper()} {code}"
        if field_str:
            text_line += f" {field_str}"
        print(text_line, file=stream)

        if expand_text and verbose:
            # Print expand lines indented, to same stream
            for exp_line in expand_text.splitlines():
                print(f"  {exp_line}", file=stream)


def ok(code: str, **fields: Any) -> None:
    emit("ok", code, **fields)


def info(code: str, **fields: Any) -> None:
    emit("info", code, **fields)


def warn(code: str, **fields: Any) -> None:
    emit("warn", code, **fields)


def halt(code: str, **fields: Any) -> None:
    emit("halt", code, **fields)


def error(code: str, **fields: Any) -> None:
    emit("error", code, **fields)


def result(code: str, **fields: Any) -> None:
    emit("result", code, **fields)


def prompt(code: str, **fields: Any) -> None:
    emit("prompt", code, **fields)
