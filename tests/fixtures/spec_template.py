"""Shared spec-text builder for Tier 1 / Tier 2 test fixtures.

Used by every tests/test_spec_ast_*.py satellite. Each satellite previously
defined its own _SPEC_HEADER / _SPEC_FOOTER pair (22-50 lines each) — same
§1-§8 skeleton, different titles. Extracted here so the §8 receiver-calibration
shape (which Tier 2 cross-checks) lives in one place.

Public API:

    make_spec_text(steps_yaml: str, *, title: str = "Test Spec",
                   slug: str = "test", mutates: str = "...",
                   never_touches: str = "/etc") -> str

The defaults produce a spec body that passes every check EXCEPT what the
caller's steps_yaml is exercising. To exercise a specific §8.1 hard-contract
violation, override mutates= or never_touches=.

Helper write_spec_file() writes the text to a temp .spec.md file and returns
the Path for callers that need on-disk fixtures (classify() takes a Path).
"""
from __future__ import annotations

import os
import pathlib
import tempfile


def make_spec_text(
    steps_yaml: str,
    *,
    title: str = "Test Spec",
    slug: str = "test",
    problem: str = "Testing a Tier 1 check in isolation.",
    first_principles: str = "- One axiom per test.",
    guardrails: str = "- None.",
    success_criteria: str = "- [ ] Check fires correctly.",
    mutates: str = "/tmp/spectre-tests/",
    never_touches: str = "/etc",
    decision_budget: str = "none",
    reboot_survival: str = "none",
) -> str:
    """Build a complete spec body around a YAML steps block.

    `steps_yaml` is inserted between the §6 fence markers — pass the raw YAML
    list (no fence, no leading "## 6. Steps" header).
    """
    return (
        f"# {title}\n"
        f"\n"
        f"**Generated:** 2026-05-12\n"
        f"**Slug:** {slug}\n"
        f"\n"
        f"## 1. Hard Problem\n"
        f"{problem}\n"
        f"\n"
        f"## 2. First Principles\n"
        f"{first_principles}\n"
        f"\n"
        f"## 3. Algorithm Audit\n"
        f"- deterministic\n"
        f"\n"
        f"## 4. Speed-of-Light Limit\n"
        f"Under 100ms.\n"
        f"\n"
        f"## 5. Physics Guardrails\n"
        f"{guardrails}\n"
        f"\n"
        f"## 6. Steps\n"
        f"\n"
        f"```yaml\n"
        f"{steps_yaml}"
        f"```\n"
        f"\n"
        f"## 7. Success Criteria\n"
        f"{success_criteria}\n"
        f"\n"
        f"## 8. Receiver Calibration\n"
        f"\n"
        f"### 8.1 Hard contract (machine-enforced — `block` severity on violation)\n"
        f"\n"
        f"- `mutates:` {mutates}\n"
        f"- `never-touches:` {never_touches}\n"
        f"- `decision-budget:` {decision_budget}\n"
        f"- `reboot-survival:` {reboot_survival}\n"
        f"\n"
        f"### 8.2 Human-facing notes (informational only — `info` severity, never blocks)\n"
        f"\n"
        f"- `assumes:` linux\n"
    )


def write_spec_file(steps_yaml: str, **kwargs) -> pathlib.Path:
    """Write make_spec_text(...) output to a temp .spec.md and return the Path.

    Callers should `path.unlink(missing_ok=True)` in a try/finally.
    """
    content = make_spec_text(steps_yaml, **kwargs)
    fd, path = tempfile.mkstemp(suffix=".spec.md")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(content)
    return pathlib.Path(path)
