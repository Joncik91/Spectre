"""Tier 1.5 spec-author lint: catch invocation-shape gotchas at lock-time.

Stdlib only. Reuses bin.spec_ast._parse_steps_section to walk action: fields.

Two checks:

  - runuser-no-cd (warn): `runuser -l <user> -c '<inner>'` where the inner command
    references a relative path or simple binary name without `cd <path>` AND
    without absolute paths. Ships sad-paths to the user's HOME instead of the
    project root, silently passing tests that "ran" but collected nothing.

  - unsafe-heredoc (info): heredoc-bearing actions (`cat > foo <<EOF ... EOF`)
    that don't open with `set -euo pipefail`. Shell errors mid-heredoc are
    swallowed without the pragma; verifications then probe a half-written file.
"""
from __future__ import annotations

import pathlib
import re

from bin import findings as _findings
from bin import spec_ast as _spec_ast


# ── runuser-no-cd ──────────────────────────────────────────────────────────────

_RUNUSER_RE = re.compile(
    # Match `runuser`, then any tokens that aren't `-c`, until we hit `-c '...'`.
    # The closing quote is optional because spec_ast._parse_steps_section strips
    # outer YAML quoting and may swallow the inner quote when the action: value
    # is wrapped in matching outer quotes.
    r"\brunuser\s+(?:(?!-c\b)\S+\s+)*-c\s+(?P<quote>['\"])(?P<inner>.*?)(?:(?P=quote)|$)",
    re.DOTALL,
)

# Path tokens inside the inner command that contain a slash or are common
# project-relative directories. `tests/`, `src/foo`, `./scripts` — all suspect
# unless prefixed with cd. The regex allows trailing slashes (`tests/`).
_RELATIVE_PATH_RE = re.compile(r"(?<![\w/])(?:\./[\w./-]*|[\w][\w-]*/[\w./-]*)")


def _inner_has_cd(inner: str) -> bool:
    """True if the inner command starts with cd <path> && (or ;) ..."""
    return bool(re.match(r"^\s*cd\s+\S+\s*[;&]", inner))


def _inner_uses_only_absolute_paths(inner: str) -> bool:
    """True if every path-like token is absolute (or there are no path tokens)."""
    has_relative = bool(_RELATIVE_PATH_RE.search(inner))
    return not has_relative


def _check_runuser_no_cd(action: str, step: int) -> list[_findings.Finding]:
    out: list[_findings.Finding] = []
    for m in _RUNUSER_RE.finditer(action):
        inner = m.group("inner")
        if _inner_has_cd(inner):
            continue
        if _inner_uses_only_absolute_paths(inner):
            continue
        out.append(_findings.Finding(
            tier=1,
            kind="runuser-no-cd",
            severity="warn",
            location=_findings.FindingLocation(scope="step", step=step, ref="action"),
            message=f"Step {step}: runuser -c '...' lacks cd; inner command runs in $HOME.",
            suggested_fix="Prefix inner with cd <project-root> && or use absolute paths.",
        ))
    return out


# ── unsafe-heredoc ─────────────────────────────────────────────────────────────

_HEREDOC_RE = re.compile(
    r"<<\s*['\"]?(?P<tag>[A-Za-z_]\w*)['\"]?\s*\n(?P<body>.*?)\n\s*(?P=tag)\b",
    re.DOTALL,
)
_SET_E_RE = re.compile(r"^\s*set\s+-[^\n]*e", re.MULTILINE)


def _check_unsafe_heredoc(action: str, step: int) -> list[_findings.Finding]:
    out: list[_findings.Finding] = []
    for m in _HEREDOC_RE.finditer(action):
        body = m.group("body")
        if _SET_E_RE.search(body):
            continue
        # Heredoc bodies that are pure data (no shell verbs) don't need set -e.
        # Heuristic: if any line begins with a recognizable shell verb, treat as a script.
        is_script = bool(re.search(
            r"^\s*(?:if|for|while|case|echo|cat|cp|mv|rm|mkdir|chmod|chown|"
            r"systemctl|loginctl|curl|wget|git|python|sh|bash|exec)\b",
            body, re.MULTILINE,
        ))
        if not is_script:
            continue
        out.append(_findings.Finding(
            tier=1,
            kind="unsafe-heredoc",
            severity="info",
            location=_findings.FindingLocation(scope="step", step=step, ref="action"),
            message=f"Step {step}: heredoc script lacks `set -euo pipefail`; errors swallowed.",
            suggested_fix="Add `set -euo pipefail` as first line of the heredoc body.",
        ))
    return out


# ── public API ─────────────────────────────────────────────────────────────────


def lint_action(action: str, step: int) -> list[_findings.Finding]:
    """Run all lint checks against a single action: string."""
    findings: list[_findings.Finding] = []
    findings.extend(_check_runuser_no_cd(action, step))
    findings.extend(_check_unsafe_heredoc(action, step))
    return findings


def lint_spec(spec_path: pathlib.Path) -> list[_findings.Finding]:
    """Lint every step's action: field. Returns aggregated findings."""
    text = spec_path.read_text(encoding="utf-8")
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    steps = _spec_ast._parse_steps_section(text)
    findings: list[_findings.Finding] = []
    for step in steps:
        action = step.get("action", "")
        step_n = step.get("step", 0)
        if isinstance(action, str) and isinstance(step_n, int) and action:
            findings.extend(lint_action(action, step_n))
    return findings
