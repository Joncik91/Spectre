"""
eval_metadata.py — .eval.json sidecar writer, policy hash, no-downgrade enforcement.

Public API (per Decision 8 of the v0.3 Plan A brief):
  - sidecar_path_for(spec_path) -> pathlib.Path
  - compute_policy_hash(config, severity_overrides) -> str
  - write_sidecar(spec_path, *, ...) -> pathlib.Path
  - validate_no_severity_downgrade(default_severity, override_severity) -> None
  - load_severity_overrides_from_config(config_path) -> dict[str, str]

Stdlib only: hashlib, json, os, tempfile, pathlib, tomllib, datetime.
"""
from __future__ import annotations

import hashlib
import json
import os
import pathlib
import tempfile
import tomllib
from datetime import datetime, timezone
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import findings as findings_mod

# ---------------------------------------------------------------------------
# Policy ground-truth: finding_kind -> default severity
# ---------------------------------------------------------------------------

DEFAULT_SEVERITIES: dict[str, str] = {
    "missing-why": "block",
    "soft-verification": "block",
    "undeclared-resource": "warn",
    "undeclared-host-path": "block",
    "decision-without-adr": "warn",
    "action-not-probed": "warn",
    "missing-receiver-calibration": "block",
    "cross-step-inconsistency": "warn",
    "spec-wide-scope-violation": "warn",
    "calibration-hard-violation": "block",
    "tier3-context-gap": "warn",
    "tier3-attacker-view": "warn",
    "tier3-spec-asserts-wrong": "warn",
    "tier3-unavailable": "info",
}

# Imported lazily at call sites to avoid circular imports in thin stdlib modules.
_SEVERITY_ORDER: dict[str, int] = {"info": 0, "warn": 1, "block": 2}


# ---------------------------------------------------------------------------
# compute_policy_hash
# ---------------------------------------------------------------------------

def compute_policy_hash(config: dict, severity_overrides: dict) -> str:
    """SHA-256 hex of canonical-JSON-serialized {config, severity_overrides}.

    Stable across equal inputs regardless of dict iteration order.
    """
    payload = {"config": config, "severity_overrides": severity_overrides}
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()


# ---------------------------------------------------------------------------
# validate_no_severity_downgrade
# ---------------------------------------------------------------------------

def validate_no_severity_downgrade(default_severity: str, override_severity: str) -> None:
    """Raises ValueError if override_severity < default_severity per SEVERITY_ORDER.

    Strictness can only be raised, never lowered (per Decision 8).
    Returns None on success.
    """
    if default_severity not in _SEVERITY_ORDER:
        raise ValueError(f"unknown severity: {default_severity!r}")
    if override_severity not in _SEVERITY_ORDER:
        raise ValueError(f"unknown severity: {override_severity!r}")
    default_rank = _SEVERITY_ORDER[default_severity]
    override_rank = _SEVERITY_ORDER[override_severity]
    if override_rank < default_rank:
        raise ValueError(
            f"severity downgrade attempted: cannot lower {default_severity!r} to {override_severity!r}"
        )


# ---------------------------------------------------------------------------
# load_severity_overrides_from_config
# ---------------------------------------------------------------------------

def load_severity_overrides_from_config(config_path: pathlib.Path) -> dict[str, str]:
    """Read ~/.spectre/reviewer.toml's [severity_overrides] table.

    Returns {finding_kind: severity}. Returns {} if config missing or table absent.
    Validates each override against the kind's default severity — raises on downgrade.
    """
    config_path = pathlib.Path(config_path)
    if not config_path.exists():
        return {}

    with config_path.open("rb") as f:
        data = tomllib.load(f)

    overrides_table = data.get("severity_overrides")
    if not overrides_table:
        return {}

    result: dict[str, str] = {}
    for kind, override_severity in overrides_table.items():
        if kind not in DEFAULT_SEVERITIES:
            raise ValueError(f"unknown finding kind in severity_overrides: {kind!r}")
        default_severity = DEFAULT_SEVERITIES[kind]
        validate_no_severity_downgrade(default_severity, override_severity)
        result[kind] = override_severity

    return result


# ---------------------------------------------------------------------------
# sidecar_path_for
# ---------------------------------------------------------------------------

#: Suffix appended to the spec filename to form the sidecar filename.
#: e.g.  specs/foo.spec.md  →  specs/foo.spec.md.eval.json
SIDECAR_EXTENSION = ".eval.json"


def sidecar_path_for(spec_path: pathlib.Path) -> pathlib.Path:
    """Return the canonical sidecar path for *spec_path*.

    The sidecar is always the spec filename with ``.eval.json`` appended
    (append-suffix, not replace-suffix).  Example::

        specs/my-feature.spec.md  →  specs/my-feature.spec.md.eval.json

    This is the single source of truth for the sidecar filename convention.
    Both ``write_sidecar`` and callers that need to *read* the sidecar should
    use this function so they stay in sync.
    """
    spec_path = pathlib.Path(spec_path)
    return spec_path.parent / (spec_path.name + SIDECAR_EXTENSION)


# ---------------------------------------------------------------------------
# write_sidecar
# ---------------------------------------------------------------------------

def write_sidecar(
    spec_path: pathlib.Path,
    *,
    evaluator_version: str,
    tiers_run: list[int],
    findings: list,  # list[findings_mod.Finding]
    dismissals: list[dict],
    config_path: pathlib.Path | None,
    config_hash: str | None,
    deepseek_model_version: str | None,
    policy_hash: str,
) -> pathlib.Path:
    """Atomic write of <spec>.eval.json next to the spec file.

    Returns the sidecar path. Raises on write failure (caller handles).
    """
    spec_path = pathlib.Path(spec_path)
    sidecar_path = sidecar_path_for(spec_path)

    # Aggregate findings_summary
    block_count = sum(1 for f in findings if f.severity == "block")
    warn_count = sum(1 for f in findings if f.severity == "warn")
    info_count = sum(1 for f in findings if f.severity == "info")
    dismissed_t3_count = len(dismissals)

    locked_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    payload: dict = {
        "evaluator_version": evaluator_version,
        "tiers_run": tiers_run,
        "policy_hash": policy_hash,
        "config_path": str(config_path) if config_path is not None else None,
        "config_hash": config_hash,
        "findings_summary": {
            "block_count": block_count,
            "warn_count": warn_count,
            "info_count": info_count,
            "dismissed_t3_count": dismissed_t3_count,
        },
        "dismissals": dismissals,
        "deepseek_model_version": deepseek_model_version,
        "locked_at": locked_at,
    }

    # Atomic write: mkstemp + os.replace
    fd, tmp = tempfile.mkstemp(
        dir=sidecar_path.parent, prefix=sidecar_path.name, suffix=".tmp"
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2)
        os.replace(tmp, sidecar_path)
    except Exception:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise

    return sidecar_path
