"""handoff_validator.py — Tier 0 integrity check for /implement startup.

Public API:
  - validate_on_implement_start(project_path) -> list[str]

Returns list of violations. Empty list = pass.
Distinguish between warn-level (envelope-missing) and block-level (envelope-tampered).
Callers inspect the message prefix to determine severity.

Stdlib only. Python 3.11+.
"""
from __future__ import annotations

import json
import pathlib
import sys

# Allow importing sibling modules from bin/
_BIN_DIR = pathlib.Path(__file__).parent
if str(_BIN_DIR) not in sys.path:
    sys.path.insert(0, str(_BIN_DIR))

import handoff_envelope


def validate_on_implement_start(project_path: pathlib.Path) -> list[str]:
    """Tier 0 integrity check for /implement startup.

    Returns a list of violations:
    - Empty list → pass, proceed with implementation.
    - ["no active spec — run /vision first"] → no active spec.
    - ["envelope-missing: ..."] → warn-level, pre-v0.6 spec.
    - ["envelope-tampered: ..."] → block-level, spec modified after lock.
    - [schema violation strings] → from handoff_envelope.validate().
    """
    project_path = pathlib.Path(project_path)
    active_spec_pointer = project_path / "specs" / ".active"

    # Step 1: Read specs/.active → spec_path
    if not active_spec_pointer.exists():
        return ["no active spec — run /vision first"]

    spec_path_str = active_spec_pointer.read_text(encoding="utf-8").strip()
    if not spec_path_str:
        return ["no active spec — run /vision first"]

    # Resolve spec_path relative to project root
    spec_path = project_path / spec_path_str if not pathlib.Path(spec_path_str).is_absolute() else pathlib.Path(spec_path_str)

    # Step 2: Compute envelope_path
    envelope_path = handoff_envelope.envelope_path_for(spec_path)

    # Step 3: If envelope missing → warn-level (pre-v0.6 compat)
    if not envelope_path.exists():
        return [
            "envelope-missing: pre-v0.6 spec; re-run /vision to generate envelope"
        ]

    # Step 4: Load envelope, extract claimed integrity_hash, recompute
    try:
        stored_envelope = handoff_envelope.read(envelope_path)
    except (json.JSONDecodeError, OSError) as exc:
        return [f"envelope-tampered: cannot read envelope: {exc}"]

    # Step 5: Schema validation first
    schema_violations = handoff_envelope.validate(stored_envelope)
    if schema_violations:
        return schema_violations

    # Step 6: Recompute integrity hash from stored envelope fields
    # (The stored envelope contains spec_path, sidecar_path, walker fields, etc.
    # We recompute from the stored envelope content itself — the hash covers all
    # fields except integrity_hash, so any mutation of those fields will be caught.)
    claimed_hash = stored_envelope.get("integrity_hash", "")
    recomputed_hash = handoff_envelope.compute_integrity_hash(stored_envelope)

    if claimed_hash != recomputed_hash:
        return [
            "envelope-tampered: spec/sidecar/contracts modified after lock — re-run /vision"
        ]

    # Also verify spec and sidecar still exist and match what was locked
    sidecar_path_str = stored_envelope.get("sidecar_path", "")
    sidecar_path = pathlib.Path(sidecar_path_str) if sidecar_path_str else None

    # Re-read current sidecar to detect post-lock drift
    if sidecar_path is not None and sidecar_path.exists():
        try:
            current_sidecar = json.loads(sidecar_path.read_text(encoding="utf-8"))
            current_policy_hash = current_sidecar.get("policy_hash", "")
        except (json.JSONDecodeError, OSError):
            return [
                "envelope-tampered: spec/sidecar/contracts modified after lock — re-run /vision"
            ]

        if current_policy_hash != stored_envelope.get("policy_hash", ""):
            return [
                "envelope-tampered: spec/sidecar/contracts modified after lock — re-run /vision"
            ]

    return []
