"""Shared fixtures for stub-producer / stub-invocation tests.

Used by:
- tests/test_spec_ast_stub_producer.py (Tier 1 producer-body-depth check)
- tests/test_walker_stub_invocation.py (walker stub-invocation-detected concern)

Both test files build identical step-dict scaffolding to drive their respective
detectors. Extracted here to keep the stub-keyword set + heredoc shapes in one
place — when v0.7+ adds another stub marker, only this file changes.
"""
from __future__ import annotations


def step(
    n: int,
    action: str = "",
    why: str = "test",
    produces: list[str] | None = None,
    requires: list[str] | None = None,
) -> dict:
    """Build a parsed step-dict matching the shape spec_ast._parse_steps_section
    emits. Both stub-producer (Tier 1) and stub-invocation (walker) consume
    this shape directly.
    """
    return {
        "step": n,
        "why": why,
        "action": action,
        "produces": produces or [],
        "requires": requires or [],
        "negative_paths": [],
    }


# Canonical stub action (raise NotImplementedError). Detected by:
# - _why_is_stub (when "stub" appears in why:)
# - heredoc-body parsing for NotImplementedError / pass # TODO / etc.
STUB_ACTION: str = (
    "cat > /app/vidence/bootstrap.py <<'EOF'\n"
    "def bootstrap():\n"
    "    raise NotImplementedError\n"
    "EOF"
)
