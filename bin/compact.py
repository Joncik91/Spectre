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

DELTA_PATTERNS = [
    (re.compile(r"^\s*mkdir(?:\s+-\w+)*\s+(.+)$"), "mkdir {}"),
    (re.compile(r"^\s*touch(?:\s+-\w+)*\s+(.+)$"), "touch {}"),
    (re.compile(r"^\s*rm(?:\s+-\w+)*\s+(.+)$"), "rm {}"),
    (re.compile(r"^\s*mv\s+(\S+)\s+(\S+)"), "mv {} -> {}"),
    (re.compile(r"^\s*cp(?:\s+-\w+)*\s+(\S+)\s+(\S+)"), "cp {} -> {}"),
    (re.compile(r"^\s*git\s+commit\b"), "git commit"),
    (re.compile(r"^\s*apt(?:-get)?\s+install\s+(.+)"), "apt install {}"),
    (re.compile(r"^\s*pip\s+install\s+(.+)"), "pip install {}"),
    (re.compile(r"^\s*npm\s+install\s+(.*)"), "npm install {}"),
    (re.compile(r"(?<![0-9&])>\s*([^\s&]+)\s*$"), "wrote {}"),
]

ERR_PATTERN = re.compile(r"^(Error|error|fatal|E:|FAIL|Traceback)", re.MULTILINE)


def parse_delta(command: str) -> str:
    cmd = command.strip()
    for regex, template in DELTA_PATTERNS:
        m = regex.search(cmd)
        if m:
            return template.format(*m.groups()) if m.groups() else template
    return "unknown — see scratchpad"


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

    delta = parse_delta(command)
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
