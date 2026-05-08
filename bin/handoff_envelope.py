"""handoff_envelope.py — Context Sled v0.7 handoff envelope builder/validator.

Public API:
  - build(spec_path, sidecar_path, walk_path, decisions_dir) -> dict
  - validate(envelope) -> list[str]
  - compute_integrity_hash(envelope) -> str
  - write(envelope, target) -> None
  - read(envelope_path) -> dict

Stdlib only. Python 3.11+.
"""
from __future__ import annotations

import hashlib
import json
import os
import pathlib
import re
import tempfile
from datetime import datetime, timezone
from typing import Any

# ---------------------------------------------------------------------------
# Schema constants
# ---------------------------------------------------------------------------

_PROTOCOL_VERSION = "0.6"
_RECEIVER = "claude-code-implementer"

_REQUIRED_FIELDS: dict[str, Any] = {
    "protocol_version": str,
    "receiver": str,
    "spec_path": str,
    "sidecar_path": str,
    "policy_hash": str,
    "contract_resolution": (dict, type(None)),
    "walker_yield_history": list,
    "walker_stop_reason": (str, type(None)),
    "decisions_indexed": list,
    # v0.6 artifact byte-hashes — included in integrity_hash payload
    "spec_sha256": str,
    "sidecar_sha256": (str, type(None)),  # None when sidecar absent (pre-v0.6)
    # v0.7 §8.2 block hash — excluded from integrity_hash (payload pointer)
    "substrate_sha256": str,  # "" sentinel when §8.2 absent (backward compat)
    "integrity_hash": str,
    "created_at": str,
}

#: Extension appended (not replacing) to the spec filename to form the envelope filename.
#: e.g. specs/foo.spec.md → specs/foo.spec.md.envelope.json
ENVELOPE_EXTENSION = ".envelope.json"


def envelope_path_for(spec_path: pathlib.Path) -> pathlib.Path:
    """Return the canonical envelope path for *spec_path*."""
    spec_path = pathlib.Path(spec_path)
    return spec_path.parent / (spec_path.name + ENVELOPE_EXTENSION)


# ---------------------------------------------------------------------------
# validate
# ---------------------------------------------------------------------------

def validate(envelope: dict) -> list[str]:
    """Return list of schema violations. Empty list = valid."""
    violations: list[str] = []

    for field, expected_type in _REQUIRED_FIELDS.items():
        if field not in envelope:
            violations.append(f"missing field: {field}")
            continue

        value = envelope[field]
        if isinstance(expected_type, tuple):
            # Union type (e.g. (dict, type(None)))
            if not isinstance(value, expected_type):
                type_names = " | ".join(
                    t.__name__ if t is not type(None) else "None"
                    for t in expected_type
                )
                violations.append(
                    f"wrong type for {field}: expected {type_names}, got {type(value).__name__}"
                )
        else:
            if not isinstance(value, expected_type):
                violations.append(
                    f"wrong type for {field}: expected {expected_type.__name__}, got {type(value).__name__}"
                )

    # Semantic checks (only if fields are present with correct types)
    if "protocol_version" in envelope and isinstance(envelope["protocol_version"], str):
        if envelope["protocol_version"] != _PROTOCOL_VERSION:
            violations.append(f"protocol_version must be '{_PROTOCOL_VERSION}'")

    if "receiver" in envelope and isinstance(envelope["receiver"], str):
        if envelope["receiver"] != _RECEIVER:
            violations.append(f"receiver must be '{_RECEIVER}'")

    return violations


# ---------------------------------------------------------------------------
# compute_integrity_hash
# ---------------------------------------------------------------------------

_HASH_EXCLUDE_KEYS: frozenset[str] = frozenset({
    "integrity_hash",
    # v0.7: substrate bytes-hash is a payload pointer, excluded from metadata domain
    "substrate_sha256",
})


def compute_integrity_hash(envelope: dict) -> str:
    """SHA-256 over canonical JSON of envelope MINUS excluded keys.

    Excluded keys (see _HASH_EXCLUDE_KEYS):
    - integrity_hash: excluded to avoid circularity
    - substrate_sha256: payload pointer, not metadata — excluded so consumers
      can re-derive or verify it independently without invalidating the hash

    Uses sort_keys=True, separators=(',',':'), ensure_ascii=False for
    canonical serialization.
    """
    payload = {k: v for k, v in envelope.items() if k not in _HASH_EXCLUDE_KEYS}
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# §8.2 block extraction
# ---------------------------------------------------------------------------

# Matches the §8.2 block from its heading line up to the next ## or ### heading
# or end of string.  Stops at "## " or "### " (not "####") to avoid over-capture.
_82_BLOCK_RE = re.compile(
    r"\n###\s+8\.2\b.*?(?=\n##\s|\n###\s|\Z)",
    re.DOTALL,
)


# ---------------------------------------------------------------------------
# build
# ---------------------------------------------------------------------------

def build(
    spec_path: pathlib.Path,
    sidecar_path: pathlib.Path,
    walk_path: pathlib.Path | None,
    decisions_dir: pathlib.Path | None,
) -> dict:
    """Assemble a v0.6 handoff envelope from disk artifacts.

    Reads:
    - spec_path bytes (used in integrity_hash inputs via field presence)
    - sidecar_path → JSON → extract policy_hash, contract_resolution
    - walk_path (optional) → JSON → extract yield_history, stop_reason
    - decisions_dir (optional) → sorted list of *.md filenames

    Returns a dict with all required fields including integrity_hash.
    """
    spec_path = pathlib.Path(spec_path)
    sidecar_path = pathlib.Path(sidecar_path)

    # Read sidecar
    sidecar_data = json.loads(sidecar_path.read_text(encoding="utf-8"))
    policy_hash: str = sidecar_data["policy_hash"]
    contract_resolution: dict | None = sidecar_data.get("contract_resolution", None)

    # Read walker output (optional)
    walker_yield_history: list[int] = []
    walker_stop_reason: str | None = None
    if walk_path is not None:
        walk_path = pathlib.Path(walk_path)
        if walk_path.exists():
            walk_data = json.loads(walk_path.read_text(encoding="utf-8"))
            walker_yield_history = walk_data.get("yield_history", [])
            walker_stop_reason = walk_data.get("stop_reason", None)

    # Index decisions (optional)
    decisions_indexed: list[str] = []
    if decisions_dir is not None:
        decisions_dir = pathlib.Path(decisions_dir)
        if decisions_dir.exists() and decisions_dir.is_dir():
            decisions_indexed = sorted(
                p.name for p in decisions_dir.glob("*.md")
            )

    # Compute byte-level hashes of spec and sidecar at lock time.
    # These are included as regular envelope fields so compute_integrity_hash()
    # covers them automatically — mutating either file post-lock is detected on
    # next validate_on_implement_start() call (fixes Gap E / B1-B3).
    spec_bytes = spec_path.read_bytes()
    spec_sha256 = hashlib.sha256(spec_bytes).hexdigest()
    sidecar_sha256 = hashlib.sha256(sidecar_path.read_bytes()).hexdigest()

    # v0.7: hash the §8.2 block bytes if present, else empty string sentinel.
    # substrate_sha256 is excluded from compute_integrity_hash() (payload pointer,
    # not metadata) — see _HASH_EXCLUDE_KEYS.
    spec_text = spec_bytes.decode("utf-8")
    _m = _82_BLOCK_RE.search(spec_text)
    substrate_sha256 = (
        hashlib.sha256(_m.group(0).encode("utf-8")).hexdigest() if _m else ""
    )

    created_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    envelope: dict = {
        "protocol_version": _PROTOCOL_VERSION,
        "receiver": _RECEIVER,
        "spec_path": str(spec_path),
        "sidecar_path": str(sidecar_path),
        "policy_hash": policy_hash,
        "contract_resolution": contract_resolution,
        "walker_yield_history": walker_yield_history,
        "walker_stop_reason": walker_stop_reason,
        "decisions_indexed": decisions_indexed,
        "spec_sha256": spec_sha256,
        "sidecar_sha256": sidecar_sha256,
        "substrate_sha256": substrate_sha256,
        "created_at": created_at,
    }

    # Compute and insert integrity_hash last
    envelope["integrity_hash"] = compute_integrity_hash(envelope)

    return envelope


# ---------------------------------------------------------------------------
# write / read
# ---------------------------------------------------------------------------

def write(envelope: dict, target: pathlib.Path) -> None:
    """Atomic write of envelope dict to *target* via tempfile+rename."""
    target = pathlib.Path(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=target.parent, prefix=target.name, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(envelope, f, indent=2, ensure_ascii=False)
        os.replace(tmp, target)
    except Exception:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


def read(envelope_path: pathlib.Path) -> dict:
    """Load and return a handoff envelope dict from *envelope_path*."""
    envelope_path = pathlib.Path(envelope_path)
    return json.loads(envelope_path.read_text(encoding="utf-8"))
