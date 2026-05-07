"""Finding dataclass + JSON schema for the v0.3 spec evaluator. Stdlib only."""
import hashlib
import json
from dataclasses import dataclass, asdict
from typing import Any

KNOWN_KINDS = {
    "missing-why",
    "soft-verification",
    "undeclared-resource",
    "undeclared-host-path",
    "decision-without-adr",
    "action-not-probed",
    "missing-receiver-calibration",
    "cross-step-inconsistency",
    "spec-wide-scope-violation",
    "calibration-hard-violation",
    "tier3-context-gap",
    "tier3-attacker-view",
    "tier3-spec-asserts-wrong",
    "tier3-unavailable",
    # v0.3.1 — Tier 1.5 spec_lint kinds
    "runuser-no-cd",
    "unsafe-heredoc",
    # v0.5.2 — explicit step contracts (P3)
    "unowned-requirement",
    "missing-contract",
    "malformed-contract",
    # v0.5.2 — Tier 1 deterministic gap-closers (P1)
    "verification-syntax-error",
    "action-invokes-uncreated-artifact",
    "unowned-requirement-heuristic",
    # v0.5.2 — Tier 3 contradiction tuple kinds (P4)
    "missing-producer",
    "shallow-ownership",
    "ambiguous-contract",
    "negative-path-omission",
    "idempotency-risk",
    "migration-on-existing-state",
    "partial-failure-window",
    "concurrency-race",
    "verification-false-positive",
    "tier3-contradiction-unrecognized",
    "tier3-malformed-response",
}

# Severity mapping for Tier 3 contradiction tuple kinds (v0.5.2).
# "block" = spec is provably broken; "warn" = needs attention; "info" = advisory.
TIER3_CONTRADICTION_SEVERITY: dict[str, str] = {
    "missing-producer": "block",
    "shallow-ownership": "block",
    "ambiguous-contract": "warn",
    "negative-path-omission": "info",
    "idempotency-risk": "info",
    "migration-on-existing-state": "info",
    "partial-failure-window": "warn",
    "concurrency-race": "info",
    "verification-false-positive": "warn",
    "tier3-contradiction-unrecognized": "info",
    "tier3-malformed-response": "warn",
}

SEVERITIES = {"block", "warn", "info"}
SEVERITY_ORDER = {"info": 0, "warn": 1, "block": 2}
SCOPES = {"step", "cross-step", "spec-wide"}
MAX_MESSAGE_LEN = 140
MAX_FIX_LEN = 140


@dataclass
class FindingLocation:
    scope: str
    step: int | None = None
    steps: list[int] | None = None
    ref: str | None = None

    def __post_init__(self) -> None:
        if self.scope not in SCOPES:
            raise ValueError(f"unknown scope: {self.scope!r}")


@dataclass
class Finding:
    tier: int
    kind: str
    severity: str
    location: FindingLocation
    message: str
    suggested_fix: str | None = None
    dismissable: bool = False

    def __post_init__(self) -> None:
        if self.kind not in KNOWN_KINDS:
            raise ValueError(f"unknown finding kind: {self.kind!r}")
        if self.severity not in SEVERITIES:
            raise ValueError(f"unknown severity: {self.severity!r}")
        if self.tier not in {1, 2, 3}:
            raise ValueError(f"unknown tier: {self.tier!r}")
        if len(self.message) > MAX_MESSAGE_LEN:
            raise ValueError(f"message exceeds 140 chars: {len(self.message)}")
        if self.suggested_fix is not None and len(self.suggested_fix) > MAX_FIX_LEN:
            raise ValueError(f"suggested_fix exceeds 140 chars: {len(self.suggested_fix)}")


def fingerprint(f: Finding) -> str:
    """
    Stable SHA-256 fingerprint of Finding, excluding message wording.

    Returns hex digest of canonical JSON containing:
    {tier, kind, scope, step, steps (sorted), ref}

    Message and suggested_fix are excluded so LLM nondeterminism doesn't
    break Tier 3 dismissals.
    """
    # Build canonical dict for hashing
    fp_data = {
        "tier": f.tier,
        "kind": f.kind,
        "scope": f.location.scope,
        "step": f.location.step,
        "steps": sorted(f.location.steps) if f.location.steps is not None else None,
        "ref": f.location.ref,
    }

    # Canonical JSON (sorted keys, no whitespace)
    canonical_json = json.dumps(fp_data, sort_keys=True, separators=(",", ":"))

    # SHA-256 hex
    return hashlib.sha256(canonical_json.encode()).hexdigest()


def to_dict(f: Finding) -> dict[str, Any]:
    """Convert Finding to dict for JSON serialization."""
    d = asdict(f)
    # Ensure nested location dict is properly structured
    return d


def from_dict(d: dict[str, Any]) -> Finding:
    """Reconstruct Finding from dict (JSON deserialized)."""
    loc_data = d["location"]
    loc = FindingLocation(
        scope=loc_data["scope"],
        step=loc_data.get("step"),
        steps=loc_data.get("steps"),
        ref=loc_data.get("ref"),
    )
    return Finding(
        tier=d["tier"],
        kind=d["kind"],
        severity=d["severity"],
        location=loc,
        message=d["message"],
        suggested_fix=d.get("suggested_fix"),
        dismissable=d.get("dismissable", False),
    )


def max_severity(fs: list[Finding]) -> str:
    """Return highest severity in list; 'info' for empty list."""
    if not fs:
        return "info"
    return max(fs, key=lambda f: SEVERITY_ORDER[f.severity]).severity
