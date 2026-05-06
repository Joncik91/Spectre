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
    adoption_count_this_session() -> int
    reset_session_counter() -> None  # test-only helper
"""
from __future__ import annotations

import os
import pathlib
import tempfile
import tomllib
from datetime import datetime, timezone

PERSONAL_RULES_VERSION = "0.4.1"
DEFAULT_BRAKE_THRESHOLD = 3

# Module-level session counter. Reset only via reset_session_counter (tests)
# or process restart. NOT persisted to disk — sandbox-paradox brake is
# session-scoped, not lifetime-scoped.
_SESSION_ADOPTION_COUNT = 0


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
