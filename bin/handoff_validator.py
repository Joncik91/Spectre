"""handoff_validator.py — Tier 0 integrity check for /implement startup.

Public API:
  - validate_on_implement_start(project_path) -> list[str]

Returns list of violations. Empty list = pass.
Distinguish between warn-level (envelope-missing) and block-level (envelope-tampered).
Callers inspect the message prefix to determine severity.

Violation prefixes:
  "no active spec"          — no .active pointer
  "envelope-missing:"       — warn, pre-v0.6 spec
  "envelope-tampered:"      — block, spec/sidecar modified after lock
  "envelope-malformed:"     — block, schema violation in envelope

Stdlib only. Python 3.11+.
"""
from __future__ import annotations

import hashlib
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

    # Step 5: Schema validation first — prefix violations with "envelope-malformed:"
    # Special case: missing substrate_sha256 is a pre-v0.7 compat warning, not a hard error.
    # We strip it from schema_violations here and handle it in Step 9 instead.
    schema_violations = handoff_envelope.validate(stored_envelope)
    hard_schema_violations = [
        v for v in schema_violations if v != "missing field: substrate_sha256"
    ]
    if hard_schema_violations:
        return [f"envelope-malformed: {v}" for v in hard_schema_violations]

    # Step 6: Recompute integrity hash from stored envelope fields.
    # The hash covers all fields except integrity_hash itself, including the new
    # spec_sha256 / sidecar_sha256 fields — any envelope-field mutation is caught here.
    claimed_hash = stored_envelope.get("integrity_hash", "")
    recomputed_hash = handoff_envelope.compute_integrity_hash(stored_envelope)

    if claimed_hash != recomputed_hash:
        return [
            "envelope-tampered: spec/sidecar/contracts modified after lock — re-run /vision"
        ]

    # Step 7: Bytewise spec verification (fixes B1).
    # Compare spec bytes on disk against the hash captured at lock time.
    # This catches out-of-band edits to spec.md after the envelope was written.
    locked_spec_sha256 = stored_envelope.get("spec_sha256")
    if locked_spec_sha256 is not None:
        try:
            current_spec_sha256 = hashlib.sha256(spec_path.read_bytes()).hexdigest()
        except OSError:
            return [
                "envelope-tampered: spec file missing or unreadable after lock — re-run /vision"
            ]
        if current_spec_sha256 != locked_spec_sha256:
            return [
                "envelope-tampered: spec content modified after lock — re-run /vision"
            ]

    # Step 8: Bytewise sidecar verification (fixes B2 and B3).
    # None means the envelope was written before sidecar-hashing was added (pre-v0.6.1);
    # in that case fall back to the legacy policy_hash-only check below.
    locked_sidecar_sha256 = stored_envelope.get("sidecar_sha256")
    sidecar_path_str = stored_envelope.get("sidecar_path", "")
    sidecar_path = pathlib.Path(sidecar_path_str) if sidecar_path_str else None

    if locked_sidecar_sha256 is not None:
        # sidecar_sha256 was recorded at lock time — must still exist and match (fixes B3).
        if sidecar_path is None or not sidecar_path.exists():
            return [
                "envelope-tampered: sidecar deleted after lock — re-run /vision"
            ]
        try:
            current_sidecar_sha256 = hashlib.sha256(sidecar_path.read_bytes()).hexdigest()
        except OSError:
            return [
                "envelope-tampered: sidecar unreadable after lock — re-run /vision"
            ]
        if current_sidecar_sha256 != locked_sidecar_sha256:
            return [
                "envelope-tampered: sidecar modified after lock — re-run /vision"
            ]
    else:
        # Legacy fallback: envelope predates sidecar byte-hashing.
        # Check policy_hash only (weaker, but avoids false positives on pre-v0.6.1 envelopes).
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

    # Step 9: §8.2 substrate integrity (v0.7).
    # substrate_sha256 absent from envelope → pre-v0.7 lock, warn but proceed.
    # substrate_sha256 == "" → spec had no §8.2 at lock time, nothing to verify.
    # substrate_sha256 non-empty → compare against live §8.2 bytes; mismatch = block.
    if "substrate_sha256" not in stored_envelope:
        return [
            "envelope-missing-substrate: §8.2 bytes not bound by envelope (pre-v0.7 lock)."
        ]

    substrate_recorded = stored_envelope["substrate_sha256"]
    if substrate_recorded != "":
        import re as _re
        _82_re = _re.compile(r"\n###\s+8\.2\b.*?(?=\n##\s|\n###\s|\Z)", _re.DOTALL)
        try:
            spec_text = spec_path.read_text(encoding="utf-8")
        except OSError:
            spec_text = ""
        _m = _82_re.search(spec_text)
        substrate_live = (
            hashlib.sha256(_m.group(0).encode("utf-8")).hexdigest() if _m else ""
        )
        if substrate_recorded != substrate_live:
            return [
                "envelope-tampered:substrate-bytes-changed: §8.2 modified since lock."
            ]

    return []


# ---------------------------------------------------------------------------
# CLI entrypoint (W1)
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        prog="handoff_validator",
        description="Tier 0 handoff envelope integrity checker.",
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_check = sub.add_parser(
        "check",
        help="Validate the handoff envelope for the active spec in a project.",
    )
    p_check.add_argument(
        "--project-path",
        required=True,
        help="Path to the project root (contains specs/.active).",
    )

    args = parser.parse_args()

    if args.cmd == "check":
        violations = validate_on_implement_start(pathlib.Path(args.project_path))
        for v in violations:
            print(v)
        # Exit 0 if no violations OR only warn-level (envelope-missing).
        # Exit 1 for any block-level violation.
        block = [v for v in violations if not v.startswith("envelope-missing:")]
        sys.exit(1 if block else 0)
