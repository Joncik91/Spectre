#!/usr/bin/env python3
"""PostToolUse(Bash) hook: emit a Delta+Anchor additionalContext block."""
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from bin import _scratchpad as sp  # noqa: E402

SPECS_ACTIVE = Path("specs") / ".active"
SCRATCH = Path("state") / "scratchpad.json"

# Each pattern: (regex, delta_template, path_group_indices).
# path_group_indices = tuple of 0-indexed match groups that are filesystem paths.
# For mkdir/touch/rm: capture is a space-separated list — split at extraction time.
# For mv/cp/ln: only destination (group 1) is touched — source either disappears or is read-only.
# Empty tuple = no filesystem path (script run, package install, systemctl, etc.).
DELTA_PATTERNS = [
    (re.compile(r"^\s*mkdir(?:\s+-\w+)*\s+(.+?)(?:\s+2?>&?\d*)?$"), "mkdir {0}", (0,)),
    (re.compile(r"^\s*touch(?:\s+-\w+)*\s+(.+?)(?:\s+2?>&?\d*)?$"), "touch {0}", (0,)),
    (re.compile(r"^\s*rm(?:\s+-\w+)*\s+(.+?)(?:\s+2?>&?\d*)?$"), "rm {0}", (0,)),
    (re.compile(r"^\s*mv\s+(\S+)\s+(\S+)"), "mv {0} -> {1}", (1,)),
    (re.compile(r"^\s*cp(?:\s+-\w+)*\s+(\S+)\s+(\S+)"), "cp {0} -> {1}", (1,)),
    (re.compile(r"^\s*ln\s+(?:-\w+\s+)*(\S+)\s+(\S+)"), "ln {0} -> {1}", (1,)),
    (re.compile(r"^\s*chmod\s+(\S+)\s+(.+)$"), "chmod {0} {1}", (1,)),
    (re.compile(r"^\s*chown\s+(\S+)\s+(.+)$"), "chown {0} {1}", (1,)),
    (re.compile(r"^\s*git\s+commit\b"), "git commit", ()),
    (re.compile(r"^\s*git\s+(add|push|pull|checkout|merge|rebase|reset|tag)\b"), "git {0}", ()),
    (re.compile(r"^\s*apt(?:-get)?\s+install\s+(.+)"), "apt install {0}", ()),
    (re.compile(r"^\s*pip\s+install\s+(.+)"), "pip install {0}", ()),
    (re.compile(r"^\s*npm\s+(install|i|run|start|test|build)\b\s*(.*)"), "npm {0} {1}", ()),
    (re.compile(r"^\s*systemctl\s+(start|stop|restart|reload|enable|disable)\s+(.+)"), "systemctl {0} {1}", ()),
    (re.compile(r"^\s*docker\s+(run|build|stop|rm|exec)\b"), "docker {0}", ()),
    (re.compile(r"(?<![0-9&])>>\s*([^\s&]+)\s*$"), "appended {0}", (0,)),
    (re.compile(r"(?<![0-9&])>\s*([^\s&]+)\s*$"), "wrote {0}", (0,)),
    (re.compile(r"^\s*(?:bash|sh)\s+(\S+\.sh)"), "ran {0}", ()),
    (re.compile(r"^\s*(/[\w/.-]+\.sh)\b"), "ran {0}", ()),
    (re.compile(r"^\s*python3?\s+(\S+\.py)"), "python {0}", ()),
    (re.compile(r"^\s*pytest\b"), "pytest", ()),
]

ERR_PATTERN = re.compile(r"^(Error|error|fatal|E:|FAIL|Traceback)", re.MULTILINE)

# Patterns where the captured group is a multi-arg list (split on whitespace).
_MULTI_ARG_TEMPLATES = {"mkdir {0}", "touch {0}", "rm {0}"}


def parse_delta_with_paths(command: str) -> tuple[str, list[str]]:
    """Return (delta_string, list_of_filesystem_paths_touched).

    Paths come from the regex groups marked in DELTA_PATTERNS' third tuple element.
    For multi-arg verbs (mkdir/touch/rm), the captured group is split on whitespace.
    """
    cmd = command.strip()
    for regex, template, path_groups in DELTA_PATTERNS:
        m = regex.search(cmd)
        if not m:
            continue
        groups = m.groups()
        delta = template.format(*groups) if groups else template
        paths: list[str] = []
        for idx in path_groups:
            if idx >= len(groups) or not groups[idx]:
                continue
            raw = groups[idx]
            if template in _MULTI_ARG_TEMPLATES:
                paths.extend(p for p in raw.split() if p)
            else:
                paths.append(raw)
        return delta, paths
    return "unknown — see scratchpad", []


def parse_delta(command: str) -> str:
    """Backwards-compatible: delta string only."""
    return parse_delta_with_paths(command)[0]


def first_error_line(stderr: str) -> str:
    if not stderr:
        return ""
    m = ERR_PATTERN.search(stderr)
    if m:
        line_start = stderr.rfind("\n", 0, m.start()) + 1
        line_end = stderr.find("\n", m.start())
        if line_end == -1:
            line_end = len(stderr)
        return stderr[line_start:line_end].strip()
    return stderr.strip().splitlines()[0] if stderr.strip() else ""


def active_spec() -> str | None:
    if SPECS_ACTIVE.exists():
        return SPECS_ACTIVE.read_text(encoding="utf-8").strip() or None
    return None


def main() -> int:
    try:
        event = json.loads(sys.stdin.read() or "{}")
    except json.JSONDecodeError:
        print(json.dumps({"additionalContext": "COMPACT_ERROR: invalid event JSON"}))
        return 0

    tool_input = event.get("tool_input", {}) or {}
    tool_response = event.get("tool_response", {}) or {}
    command = tool_input.get("command", "")
    exit_code = tool_response.get("exit_code", 0)
    stderr = tool_response.get("stderr", "") or ""

    delta, touched = parse_delta_with_paths(command)
    spec = active_spec()
    anchor = (
        f"Active Spec is '{spec}'." if spec else "no active spec."
    )

    data = sp.load(SCRATCH)
    step = data.get("step", 1)

    data.update({
        "active_spec": spec,
        "last_command": command,
        "exit_code": exit_code,
        "delta": delta,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    })

    if exit_code == 0 and touched:
        tracks = data.get("tracks")
        if isinstance(tracks, dict):
            # v2 schema: write to tracks.<track>.paths_touched
            track_name = "default"
            track_data = tracks.setdefault(track_name, sp.track_default())
            existing = track_data.setdefault("paths_touched", [])
            if not isinstance(existing, list):
                existing = []
                track_data["paths_touched"] = existing
            seen = set(existing)
            for p in touched:
                if p not in seen:
                    existing.append(p)
                    seen.add(p)
            if len(existing) > sp.PATHS_TOUCHED_CAP:
                track_data["paths_touched"] = existing[-sp.PATHS_TOUCHED_CAP:]
        else:
            # v1 / unmigrated fallback: preserve prior behavior
            existing = data.setdefault("paths_touched", [])
            if not isinstance(existing, list):
                existing = []
                data["paths_touched"] = existing
            seen = set(existing)
            for p in touched:
                if p not in seen:
                    existing.append(p)
                    seen.add(p)
            if len(existing) > sp.PATHS_TOUCHED_CAP:
                data["paths_touched"] = existing[-sp.PATHS_TOUCHED_CAP:]

    if exit_code != 0:
        err = first_error_line(stderr) or "(no stderr)"
        data.setdefault("failed_hypotheses", []).append({
            "step": step,
            "command": command,
            "error": err,
            "ts": data["timestamp"],
        })

    write_warning = ""
    try:
        sp.atomic_write(SCRATCH, data)
    except OSError as exc:
        write_warning = f"COMPACT_WARN: scratchpad write failed: {exc}\n"

    failed_count = len(data.get("failed_hypotheses", []))
    ctx = (
        f"{write_warning}"
        f"COMMAND_RESULT: {exit_code}\n"
        f"STATE_DELTA: {delta}\n"
        f"ANCHOR: {anchor} Step {step}.\n"
        f"NEXT: scratchpad.json updated. {failed_count} negative-knowledge entries."
    )
    print(json.dumps({"additionalContext": ctx}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
