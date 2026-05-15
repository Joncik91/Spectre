"""bin/_layer5.py — Layer 5 self-interrogation trace helper (v1.3 prototype).

Provides build_trace_record() used by walker and eval_metadata at the three
named choice points:
  - walker-concern   : concern-resolution in walker.record_answer
  - substitution     : substitution logged in eval_metadata.write_sidecar
  - exemplar-binding : exemplar binding committed in walker

Schema (six fields + timestamp, machine-parseable JSON):
  {
    "choice_point": "walker-concern" | "substitution" | "exemplar-binding",
    "step_or_concern_id": "<id>",
    "options_considered": ["<a>", "<b>", "<c>"],
    "selected": "<a>",
    "rationale": "<one-or-two-sentence-why>",
    "validation_anchor": "<tier-or-check | null>",
    "source_anchor": "<spec-section-or-ADR-id | null>",
    "timestamp": "<ISO8601>"
  }

Emission is skipped when:
  - SPECTRE_LAYER5=off environment variable is set
  - len(options_considered) <= 1 (no real choice)

Stdlib only. No third-party dependencies.
"""
from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any

# Valid choice-point names.
CHOICE_POINTS: frozenset[str] = frozenset({
    "walker-concern",
    "substitution",
    "exemplar-binding",
})

_LAYER5_DISABLED_SENTINEL = "off"


def _layer5_enabled() -> bool:
    """Return False when SPECTRE_LAYER5=off disables trace emission."""
    return os.environ.get("SPECTRE_LAYER5", "").lower() != _LAYER5_DISABLED_SENTINEL


def build_trace_record(
    *,
    choice_point: str,
    step_or_concern_id: str,
    options_considered: list[str],
    selected: str,
    rationale: str,
    validation_anchor: str | None,
    source_anchor: str | None,
) -> dict[str, Any] | None:
    """Build a Layer 5 trace record dict and return it, or None if emission is skipped.

    Returns None (skips emission) when:
    - SPECTRE_LAYER5=off
    - len(options_considered) <= 1 (no real choice to trace)

    The caller appends the returned dict to state.layer5_trace (walker) or
    includes it in the sidecar payload projection (eval_metadata).
    """
    if not _layer5_enabled():
        return None
    if len(options_considered) <= 1:
        return None
    if choice_point not in CHOICE_POINTS:
        raise ValueError(
            f"unknown choice_point {choice_point!r}; expected one of {sorted(CHOICE_POINTS)}"
        )
    return {
        "choice_point": choice_point,
        "step_or_concern_id": step_or_concern_id,
        "options_considered": list(options_considered),
        "selected": selected,
        "rationale": rationale,
        "validation_anchor": validation_anchor,
        "source_anchor": source_anchor,
        "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }


def project_substitution_trace(substitution: dict[str, Any]) -> dict[str, Any] | None:
    """Project a substitution dict into a layer5_trace record.

    The substitution dict (v1.2.1 #6 schema extended by v1.3 #10) may carry
    optional layer5 fields:
      options_considered, selected, rationale, validation_anchor, source_anchor

    Returns a trace record if enough fields are present and emission is not
    disabled, else None.
    """
    options = substitution.get("options_considered")
    if not isinstance(options, list):
        return None
    selected = substitution.get("selected", substitution.get("to", ""))
    rationale = substitution.get("rationale", substitution.get("reason", ""))
    step_id = substitution.get("step_id", "")
    validation_anchor = substitution.get("validation_anchor")
    source_anchor = substitution.get("source_anchor")
    return build_trace_record(
        choice_point="substitution",
        step_or_concern_id=step_id,
        options_considered=options,
        selected=selected,
        rationale=rationale,
        validation_anchor=validation_anchor,
        source_anchor=source_anchor,
    )
