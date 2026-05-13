"""
eval_metadata.py — .eval.json sidecar writer, policy hash, no-downgrade enforcement.

Public API (per Decision 8 of the v0.3 Plan A brief):
  - sidecar_path_for(spec_path) -> pathlib.Path
  - compute_policy_hash(config, severity_overrides) -> str
  - write_sidecar(spec_path, *, ...) -> pathlib.Path
  - validate_no_severity_downgrade(default_severity, override_severity) -> None
  - load_severity_overrides_from_config(config_path) -> dict[str, str]
  - build_substrate_resolution(spec_text, findings_list) -> dict

Stdlib only: hashlib, json, os, re, tempfile, pathlib, tomllib, datetime.
"""
from __future__ import annotations

import hashlib
import json
import os
import pathlib
import re
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
    # v0.5.2 — explicit step contracts (P3)
    "unowned-requirement": "block",
    "missing-contract": "warn",
    "malformed-contract": "warn",
    # v0.5.2 — Tier 1 deterministic gap-closers (P1)
    "verification-syntax-error": "block",
    "action-invokes-uncreated-artifact": "block",
    "unowned-requirement-heuristic": "block",
    # v0.6 — handoff envelope integrity kinds (P1)
    "envelope-missing": "warn",
    "envelope-tampered": "block",
    "envelope-malformed": "block",
    # v0.6 — walker/contract checks (P2)
    "missing-negative-path": "warn",
    "malformed-negative-path": "warn",
    # v0.6 — Tier 3 CoT faithfulness check (P3)
    "tier3-unfaithful-contradiction": "warn",
    "tier3-faithfulness-malformed": "warn",
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
# build_substrate_resolution
# ---------------------------------------------------------------------------

_82_BLOCK_RE_SIDECAR = re.compile(r"\n###\s+8\.2\b.*?(?=\n##\s|\n###\s|\Z)", re.DOTALL)


def build_substrate_resolution(spec_text: str, findings_list) -> dict:
    """Summarize the §8.2 cognitive-substrate outcome for the sidecar.

    Returns a dict with five keys:
      - receiver_hash       sha-256 of the receiver-fingerprint value (or "" if absent)
      - trust_profile       sorted list of trust-profile tokens
      - taint_outcome       "pass" or "blocked" (blocked when any
                            untrusted-flow-unguarded finding is present)
      - provenance_chain    list of parent-envelope SHA-256s (direct parent only in v0.7)
      - axis_completeness   count of present §8.2 block-severity fields out of 5
                            (receiver-fingerprint, trust-profile, contextual-binding,
                            provenance, ux-contract)
    """
    block_match = _82_BLOCK_RE_SIDECAR.search(spec_text)
    block = block_match.group(0) if block_match else ""

    def _scalar(name: str) -> str:
        m = re.search(rf"^\s*-\s+{re.escape(name)}\s*:\s*(.+)$", block, re.MULTILINE)
        return m.group(1).strip() if m else ""

    receiver = _scalar("receiver-fingerprint")
    trust_raw = _scalar("trust-profile")
    trust = (
        sorted({t.strip() for t in trust_raw.split(",") if t.strip()})
        if trust_raw and trust_raw != "none"
        else []
    )
    taint_outcome = (
        "blocked"
        if any(getattr(f, "kind", "") == "untrusted-flow-unguarded" for f in findings_list)
        else "pass"
    )
    provenance_chain: list[str] = []
    prov_match = re.search(
        r"parent-envelope-sha256:\s*([0-9a-f]{64})", block, re.IGNORECASE
    )
    if prov_match:
        provenance_chain.append(prov_match.group(1).lower())
    axis_completeness = sum(
        1
        for k in ("receiver-fingerprint", "trust-profile", "contextual-binding", "provenance")
        if _scalar(k)
    ) + (1 if "ux-contract" in block else 0)
    return {
        "receiver_hash": hashlib.sha256(receiver.encode("utf-8")).hexdigest() if receiver else "",
        "trust_profile": trust,
        "taint_outcome": taint_outcome,
        "provenance_chain": provenance_chain,
        "axis_completeness": axis_completeness,
    }


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
    findings_summary: dict | None = None,
    contract_resolution: dict | None = None,
    substrate_resolution: dict | None = None,
    findings_inline: list[dict] | None = None,
) -> pathlib.Path:
    """Atomic write of <spec>.eval.json next to the spec file.

    Returns the sidecar path. Raises on write failure (caller handles).

    If *findings_summary* is provided it is used verbatim (round-trip from a
    caller-supplied payload).  When omitted (``None``) the summary is
    recomputed from *findings* and *dismissals* as before.

    *contract_resolution* — when non-None, written verbatim under the
    ``contract_resolution`` key.  Shape::

        {
            "steps": {
                "<step_n>": {
                    "produces": [...],
                    "requires": [...],
                    "resolution": {
                        "<entry>": {"resolved_by_step": N} | null
                    }
                }
            }
        }

    CLI note: the ``write-sidecar`` subcommand passes the full JSON payload
    through; if the payload already contains a ``contract_resolution`` key it
    is forwarded automatically (see the CLI handler below).  Python API callers
    should pass the value from ``result.sidecar_payload.get("contract_resolution")``.
    """
    spec_path = pathlib.Path(spec_path)
    sidecar_path = sidecar_path_for(spec_path)

    if findings_summary is None:
        # Aggregate findings_summary
        block_count = sum(1 for f in findings if f.severity == "block")
        warn_count = sum(1 for f in findings if f.severity == "warn")
        info_count = sum(1 for f in findings if f.severity == "info")
        dismissed_t3_count = len(dismissals)
        findings_summary = {
            "block_count": block_count,
            "warn_count": warn_count,
            "info_count": info_count,
            "dismissed_t3_count": dismissed_t3_count,
        }

    locked_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    payload: dict = {
        "evaluator_version": evaluator_version,
        "tiers_run": tiers_run,
        "policy_hash": policy_hash,
        "config_path": str(config_path) if config_path is not None else None,
        "config_hash": config_hash,
        "findings_summary": findings_summary,
        "dismissals": dismissals,
        "deepseek_model_version": deepseek_model_version,
        "locked_at": locked_at,
    }

    if contract_resolution is not None:
        payload["contract_resolution"] = contract_resolution

    if substrate_resolution is not None:
        payload["substrate_resolution"] = substrate_resolution

    if findings_inline is not None:
        payload["findings"] = findings_inline

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


# ---------------------------------------------------------------------------
# write_envelope_alongside_sidecar  (v0.6)
# ---------------------------------------------------------------------------

def write_envelope_alongside_sidecar(
    spec_path: pathlib.Path,
    sidecar_path: pathlib.Path,
    walk_path: pathlib.Path | None,
    decisions_dir: pathlib.Path | None,
) -> pathlib.Path:
    """Build and write the v0.6 handoff envelope. Returns envelope path.

    Called from the /vision skill's lock step after the sidecar has been written.
    Imports handoff_envelope lazily to avoid circular-import risk in thin callers.
    """
    import importlib
    he = importlib.import_module("handoff_envelope")

    envelope = he.build(spec_path, sidecar_path, walk_path, decisions_dir)
    envelope_path = he.envelope_path_for(pathlib.Path(spec_path))
    he.write(envelope, envelope_path)
    return envelope_path


# ── CLI entrypoint ────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse
    import sys
    from bin import _status

    parser = argparse.ArgumentParser(
        prog="eval_metadata",
        description="eval_metadata CLI — policy-hash, sidecar-path, write-sidecar, sha256.",
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    # ── policy-hash ───────────────────────────────────────────────────────────
    p_ph = sub.add_parser(
        "policy-hash",
        help="Compute and print the policy hash hex string.",
    )
    p_ph.add_argument("--config", default=None, help="Path to reviewer TOML config.")
    p_ph.add_argument(
        "--severity-overrides",
        default=None,
        help="JSON object of severity overrides, e.g. '{\"missing-why\":\"block\"}'.",
    )

    # ── sidecar-path ──────────────────────────────────────────────────────────
    p_sp = sub.add_parser(
        "sidecar-path",
        help="Print the canonical .eval.json sidecar path for a spec file.",
    )
    p_sp.add_argument("--spec", required=True, help="Path to the spec file.")

    # ── write-sidecar ─────────────────────────────────────────────────────────
    p_ws = sub.add_parser(
        "write-sidecar",
        help=(
            "Write the .eval.json sidecar. Payload JSON is read from --payload <file> "
            "or stdin when --payload is '-' or omitted."
        ),
    )
    p_ws.add_argument("--spec", required=True, help="Path to the spec file (.spec.md, already locked).")
    p_ws.add_argument(
        "--payload",
        default=None,
        help="Path to JSON payload file, or '-' / omitted to read from stdin.",
    )

    # ── write-envelope ────────────────────────────────────────────────────────
    p_we = sub.add_parser(
        "write-envelope",
        help="Build and write the v0.6 handoff envelope for a spec file.",
    )
    p_we.add_argument("--spec", required=True, help="Path to the spec file (.spec.md, already locked).")
    p_we.add_argument("--walk", default=None, help="Path to walker output JSON (.walk.json), optional.")
    p_we.add_argument("--decisions-dir", default=None, help="Path to decisions/ directory, optional.")
    p_we.add_argument(
        "--sidecar",
        default=None,
        help="Path to sidecar .eval.json; defaults to <spec>.eval.json.",
    )

    # ── sha256 ────────────────────────────────────────────────────────────────
    p_sha = sub.add_parser(
        "sha256",
        help="Compute SHA-256 of a file (or stdin) and print the hex digest.",
    )
    sha_src = p_sha.add_mutually_exclusive_group()
    sha_src.add_argument("--file", default=None, help="Path to file to hash.")
    sha_src.add_argument("--stdin", action="store_true", help="Read content from stdin.")

    args = parser.parse_args()

    if args.cmd == "policy-hash":
        config_dict: dict = {}
        if args.config is not None:
            config_path = pathlib.Path(args.config)
            if not config_path.exists():
                _status.emit("error", "eval_metadata.config_missing", dest="stderr",
                             path=args.config,
                             remediation="create ~/.spectre/reviewer.toml (see docs/SETUP.md)")
                sys.exit(1)
            with config_path.open("rb") as _f:
                config_dict = tomllib.load(_f)
        severity_overrides: dict = {}
        if args.severity_overrides is not None:
            try:
                severity_overrides = json.loads(args.severity_overrides)
            except json.JSONDecodeError as exc:
                _status.emit("error", "eval_metadata.bad_severity_json", dest="stderr",
                             reason=str(exc),
                             remediation="fix ~/.spectre/reviewer.toml syntax or delete it to use defaults")
                sys.exit(1)
        print(compute_policy_hash(config_dict, severity_overrides))

    elif args.cmd == "sidecar-path":
        spec_path = pathlib.Path(args.spec)
        # Use relative path to avoid absolute path leaks
        from bin import _path_display
        print(_path_display.display(sidecar_path_for(spec_path)))

    elif args.cmd == "write-sidecar":
        spec_path = pathlib.Path(args.spec)
        # Read payload JSON
        if args.payload is None or args.payload == "-":
            raw = sys.stdin.read()
        else:
            payload_path = pathlib.Path(args.payload)
            if not payload_path.exists():
                _status.emit("error", "eval_metadata.payload_missing", dest="stderr",
                             path=args.payload,
                             remediation="open an issue with the full halt output")
                sys.exit(1)
            raw = payload_path.read_text(encoding="utf-8")
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError as exc:
            _status.emit("error", "eval_metadata.bad_payload_json", dest="stderr",
                         reason=str(exc),
                         remediation="open an issue with the full halt output")
            sys.exit(1)

        # Map payload keys to write_sidecar kwargs.
        # Payload is expected to match the sidecar_payload dict from EvaluatorResult.
        try:
            sidecar = write_sidecar(
                spec_path,
                evaluator_version=payload["evaluator_version"],
                tiers_run=payload["tiers_run"],
                findings=[],  # findings are not re-serialized from CLI; summary comes from payload
                dismissals=payload.get("dismissals", []),
                config_path=(
                    pathlib.Path(payload["config_path"])
                    if payload.get("config_path")
                    else None
                ),
                config_hash=payload.get("config_hash"),
                deepseek_model_version=payload.get("deepseek_model_version"),
                policy_hash=payload["policy_hash"],
                findings_summary=payload.get("findings_summary"),
                contract_resolution=payload.get("contract_resolution"),
                substrate_resolution=payload.get("substrate_resolution"),
                findings_inline=payload.get("findings_inline"),
            )
        except KeyError as exc:
            _status.emit("error", "eval_metadata.sidecar_missing_field", dest="stderr",
                         field=str(exc),
                         remediation="run /vision to regenerate a complete sidecar")
            sys.exit(1)
        except OSError as exc:
            _status.emit("error", "eval_metadata.sidecar_write", dest="stderr",
                         reason=str(exc),
                         remediation="check filesystem permissions in the specs/ directory")
            sys.exit(1)
        from bin import _path_display
        _status.emit("ok", "eval.sidecar_written",
                     path=_path_display.display(sidecar))

    elif args.cmd == "write-envelope":
        spec_path = pathlib.Path(args.spec)
        if not spec_path.exists():
            _status.emit("error", "eval_metadata.spec_missing", dest="stderr",
                         path=args.spec,
                         remediation="run /vision to lock a fresh spec")
            sys.exit(1)
        sidecar_path = pathlib.Path(args.sidecar) if args.sidecar else sidecar_path_for(spec_path)
        if not sidecar_path.exists():
            _status.emit("error", "eval_metadata.sidecar_missing", dest="stderr",
                         path=str(sidecar_path),
                         remediation="run /vision to regenerate the evaluation sidecar")
            sys.exit(1)
        walk_path = pathlib.Path(args.walk) if args.walk else None
        decisions_dir = pathlib.Path(args.decisions_dir) if args.decisions_dir else None
        try:
            envelope_path = write_envelope_alongside_sidecar(spec_path, sidecar_path, walk_path, decisions_dir)
        except (OSError, KeyError, ValueError) as exc:
            _status.emit("error", "eval_metadata.envelope_write", dest="stderr",
                         reason=str(exc),
                         remediation="check filesystem permissions on the state/ directory")
            sys.exit(1)
        from bin import _path_display
        _status.emit("ok", "eval.envelope_written",
                     path=_path_display.display(envelope_path))

    elif args.cmd == "sha256":
        if args.stdin:
            data = sys.stdin.buffer.read()
        elif args.file is not None:
            fp = pathlib.Path(args.file)
            if not fp.exists():
                _status.emit("error", "eval_metadata.file_missing", dest="stderr",
                             path=args.file,
                             remediation="re-run /vision to regenerate missing files")
                sys.exit(1)
            data = fp.read_bytes()
        else:
            _status.emit("error", "eval_metadata.no_input", dest="stderr",
                         reason="provide --file or --stdin",
                         remediation="open an issue with the full halt output")
            sys.exit(1)
        print(hashlib.sha256(data).hexdigest())
