"""spec_evaluator.py — top-level review-bundle orchestrator. Stdlib only.

Public API:
    build_bundle(draft_path) -> ReviewBundle
    evaluate(draft_path, *, config_path, bundle_persist_dir) -> EvaluatorResult
    load_persisted_bundle(bundle_path, draft_sha256) -> ReviewBundle | None
    clear_bundle(bundle_path) -> None
    parse_dismissals(spec_text) -> list[dict]

Design:
- Bundle is built once per draft (keyed by draft SHA-256) and persisted to
  <bundle_persist_dir>/.eval-bundle.json for /vision §6.5/§6.6.
- Tier 1 (spec_ast) + Tier 2 (coverage_gate) always run.
- Tier 3 (llm_judge) runs only when config_path points to a TOML with
  [tier3] enabled = true.
- Dismissed Tier 3 findings (spec contains # tier3-dismissed: <fp> "reason")
  are filtered out — but only when dismissable=True.
- Does NOT write the .eval.json sidecar (that happens in /vision after lock).
"""
from __future__ import annotations

import hashlib
import json
import os
import pathlib
import re
import tempfile
import tomllib
from dataclasses import dataclass, field
from typing import Any

from bin import findings as _findings
from bin import spec_ast as _spec_ast
from bin import spec_lint as _spec_lint
from bin import coverage_gate as _coverage_gate
from bin import resources as _resources
from bin import tier as _tier
from bin import adr as _adr
from bin import eval_metadata as _eval_metadata

# ── Constants ─────────────────────────────────────────────────────────────────

EVALUATOR_VERSION = "0.4.2.5"
TIER1_TIMEOUT_MS = 100
TIER2_TIMEOUT_S = 2
TIER3_TIMEOUT_S = 180
DEFAULT_FINDING_CAP = 20
# Note: DeepSeek's v1 API accepts `deepseek-chat` and `deepseek-reasoner`. The
# v0.3.0 README/docs mentioned a non-existent "v4-pro" alias; v0.3.1 standardizes
# on `deepseek-reasoner` because reasoning > chat for adversarial spec critique.
DEEPSEEK_MODEL = "deepseek-reasoner"
DEEPSEEK_BASE_URL = "https://api.deepseek.com/v1"

# ── Dismissal parser ──────────────────────────────────────────────────────────

_DISMISSAL_RE = re.compile(
    r"^#\s*tier3-dismissed:\s*([0-9a-f]{64})\s+\"([^\"]*)\"\s*$",
    re.MULTILINE,
)


def parse_dismissals(spec_text: str) -> list[dict]:
    """Parse `# tier3-dismissed: <fingerprint> "<reason>"` lines.

    Returns list of {"fingerprint": "<sha256>", "reason": "<text>"}.
    No cryptographic signing in v0.3.0 (single-user).
    """
    result: list[dict] = []
    for m in _DISMISSAL_RE.finditer(spec_text):
        result.append({"fingerprint": m.group(1), "reason": m.group(2)})
    return result


# ── ReviewBundle ──────────────────────────────────────────────────────────────

@dataclass
class ReviewBundle:
    """Transient snapshot built once per draft, validated by all tiers.

    Committed if user says yes; persisted to disk between §6.4 and §6.5.
    """
    draft_path: pathlib.Path
    draft_sha256: str        # SHA-256 of CRLF-normalised draft content
    spec_text: str           # full CRLF-normalised draft body
    preview_adrs: list[str]  # slugs derived from §2 decision: markers
    preview_resources: list[dict]  # each: {"id":..., "kind":..., "identifier":...}
    preview_tier_classifications: dict[int, dict]  # step → {tier, reasons, never_autonomous}

    def to_dict(self) -> dict:
        return {
            "version": 1,
            "draft_sha256": self.draft_sha256,
            "spec_text": self.spec_text,
            "preview_adrs": self.preview_adrs,
            "preview_resources": self.preview_resources,
            "preview_tier_classifications": {
                str(k): v for k, v in self.preview_tier_classifications.items()
            },
        }

    @classmethod
    def from_dict(cls, d: dict, draft_path: pathlib.Path) -> "ReviewBundle":
        return cls(
            draft_path=draft_path,
            draft_sha256=d["draft_sha256"],
            spec_text=d["spec_text"],
            preview_adrs=d["preview_adrs"],
            preview_resources=d["preview_resources"],
            preview_tier_classifications={
                int(k): v for k, v in d["preview_tier_classifications"].items()
            },
        )


# ── EvaluatorResult ───────────────────────────────────────────────────────────

@dataclass
class EvaluatorResult:
    findings: list[_findings.Finding]
    max_severity: str  # "block" | "warn" | "info"
    bundle: ReviewBundle
    sidecar_payload: dict  # ready to pass to eval_metadata.write_sidecar after lock


# ── Private helpers ───────────────────────────────────────────────────────────

_DECISION_LINE_RE = re.compile(r"^\s*[-*]?\s*decision:\s+\S", re.IGNORECASE | re.MULTILINE)
_STEP_SPLIT_RE = re.compile(r"(?=^\s*- step:)", re.MULTILINE)
_FENCE_RE = re.compile(r"```(?:yaml)?\s*\n(.*?)```", re.DOTALL)


def _extract_spec_text(draft_path: pathlib.Path) -> str:
    """Read draft and normalise CRLF."""
    raw = draft_path.read_text(encoding="utf-8")
    return raw.replace("\r\n", "\n").replace("\r", "\n")


def _extract_preview_adrs(spec_text: str) -> list[str]:
    """Scan §2 First Principles for decision: lines; derive slugs.

    Returns list of slugs (one per unique decision: marker).
    Deterministic rule: matches only literal 'decision:' lines (case-insensitive),
    per Copilot review #5.
    """
    s2_match = re.search(r"^## 2\. First Principles\s*$", spec_text, re.MULTILINE)
    if not s2_match:
        return []

    s2_start = s2_match.end()
    next_h = re.search(r"^## ", spec_text[s2_start:], re.MULTILINE)
    s2_body = (
        spec_text[s2_start : s2_start + next_h.start()]
        if next_h
        else spec_text[s2_start:]
    )

    slugs: list[str] = []
    seen: set[str] = set()
    for m in _DECISION_LINE_RE.finditer(s2_body):
        # Extract the text after 'decision:'
        line = m.group(0)
        after_colon = re.sub(r"^\s*[-*]?\s*decision:\s*", "", line, flags=re.IGNORECASE).strip()
        if after_colon:
            slug = _adr.slugify(after_colon)
        else:
            slug = "unnamed-decision"
        if slug not in seen:
            seen.add(slug)
            slugs.append(slug)

    return slugs


def _extract_preview_resources(spec_text: str) -> list[dict]:
    """Union of extract_resources_from_action across all steps, deduplicated by id."""
    steps = _parse_steps_from_text(spec_text)
    seen_ids: set[str] = set()
    result: list[dict] = []
    for step in steps:
        action: str = step.get("action", "")
        if not action:
            continue
        for res in _resources.extract_resources_from_action(action):
            if res.id not in seen_ids:
                seen_ids.add(res.id)
                result.append({
                    "id": res.id,
                    "kind": res.kind,
                    "identifier": res.identifier,
                })
    return result


def _extract_tier_classifications(spec_text: str) -> dict[int, dict]:
    """Per step: run tier.classify(action) and store as dict."""
    steps = _parse_steps_from_text(spec_text)
    result: dict[int, dict] = {}
    for step in steps:
        step_n: int = step["step"]
        action: str = step.get("action", "")
        if action:
            tier_name, reasons, never_autonomous = _tier.classify(action)
        else:
            tier_name, reasons, never_autonomous = ("silent", [], None)
        result[step_n] = {
            "tier": tier_name,
            "reasons": reasons,
            "never_autonomous": never_autonomous,
        }
    return result


def _parse_steps_from_text(spec_text: str) -> list[dict]:
    """Lightweight step parser — extracts step number and action."""
    steps_match = re.search(r"^## 6\. Steps\s*$", spec_text, re.MULTILINE)
    if not steps_match:
        return []

    section_start = steps_match.end()
    next_heading = re.search(r"^## ", spec_text[section_start:], re.MULTILINE)
    section_body = (
        spec_text[section_start : section_start + next_heading.start()]
        if next_heading
        else spec_text[section_start:]
    )

    yaml_blocks: list[str] = []
    for m in _FENCE_RE.finditer(section_body):
        yaml_blocks.append(m.group(1))
    if not yaml_blocks:
        yaml_blocks = [section_body]

    steps: list[dict] = []
    for yaml_text in yaml_blocks:
        for raw in _STEP_SPLIT_RE.split(yaml_text):
            raw = raw.strip()
            if not raw:
                continue
            step: dict = {}
            for line in raw.splitlines():
                m_step = re.match(r"^\s*-\s+step:\s*(\d+)", line)
                if m_step:
                    step["step"] = int(m_step.group(1))
                    continue
                m_field = re.match(r"^\s+(action):\s*(.*)", line)
                if m_field:
                    step["action"] = m_field.group(2).strip().strip('"').strip("'")
            if "step" in step:
                steps.append(step)
    return steps


def _persist_bundle(bundle: ReviewBundle, bundle_persist_dir: pathlib.Path) -> None:
    """Atomic write of bundle to <bundle_persist_dir>/.eval-bundle.json."""
    bundle_persist_dir.mkdir(parents=True, exist_ok=True)
    bundle_path = bundle_persist_dir / ".eval-bundle.json"
    payload = json.dumps(bundle.to_dict(), indent=2)
    fd, tmp = tempfile.mkstemp(dir=bundle_persist_dir, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(payload)
        os.replace(tmp, bundle_path)
    except Exception:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


def _load_toml_config(config_path: pathlib.Path) -> dict:
    """Load TOML config. Returns empty dict on missing file."""
    if not config_path.exists():
        return {}
    with config_path.open("rb") as f:
        return tomllib.load(f)


def _apply_severity_overrides(
    findings_list: list[_findings.Finding],
    overrides: dict[str, str],
) -> list[_findings.Finding]:
    """Apply severity_overrides from config. Raises ValueError on invalid override."""
    if not overrides:
        return findings_list
    # Validate overrides up-front — raises ValueError on unknown or downgraded severity
    for kind, new_severity in overrides.items():
        default = _eval_metadata.DEFAULT_SEVERITIES.get(kind)
        if default is not None:
            # Raises ValueError on downgrade or unknown severity
            _eval_metadata.validate_no_severity_downgrade(default, new_severity)
        else:
            # Unknown kind — validate the severity string itself is valid
            if new_severity not in _findings.SEVERITIES:
                raise ValueError(f"unknown severity: {new_severity!r}")
    # Apply
    result: list[_findings.Finding] = []
    for f in findings_list:
        new_sev = overrides.get(f.kind)
        if new_sev and new_sev != f.severity:
            result.append(_findings.Finding(
                tier=f.tier,
                kind=f.kind,
                severity=new_sev,
                location=f.location,
                message=f.message,
                suggested_fix=f.suggested_fix,
                dismissable=f.dismissable,
            ))
        else:
            result.append(f)
    return result


# ── Public API ────────────────────────────────────────────────────────────────


def build_bundle(draft_path: pathlib.Path) -> ReviewBundle:
    """Materialise preview ADRs + Resources + tier classifications.

    Reads the draft, computes draft_sha256, runs ADR scan + resource extraction
    + tier classify per step. Returns bundle ready for tier checks.
    """
    spec_text = _extract_spec_text(draft_path)
    draft_sha256 = hashlib.sha256(spec_text.encode()).hexdigest()
    preview_adrs = _extract_preview_adrs(spec_text)
    preview_resources = _extract_preview_resources(spec_text)
    preview_tier_classifications = _extract_tier_classifications(spec_text)
    return ReviewBundle(
        draft_path=draft_path,
        draft_sha256=draft_sha256,
        spec_text=spec_text,
        preview_adrs=preview_adrs,
        preview_resources=preview_resources,
        preview_tier_classifications=preview_tier_classifications,
    )


def evaluate(
    draft_path: pathlib.Path,
    *,
    config_path: pathlib.Path | None = None,
    bundle_persist_dir: pathlib.Path | None = None,
) -> EvaluatorResult:
    """Full pipeline: build bundle → Tier 1 → Tier 2 → Tier 3 (if config enables)
    → aggregate findings → compute max severity → persist bundle → return result.

    Does NOT write the .eval.json sidecar — that happens in /vision after user
    replies yes (Task 10).

    Persists the bundle to <bundle_persist_dir>/.eval-bundle.json (default:
    "state/" relative to draft_path's parent if bundle_persist_dir not given).

    Filters out dismissed Tier 3 findings: parses any
    `# tier3-dismissed: <fingerprint> "<reason>"` lines from the draft and
    excludes matching findings where dismissable=True.
    """
    draft_path = pathlib.Path(draft_path)

    # Default bundle persist dir
    if bundle_persist_dir is None:
        bundle_persist_dir = draft_path.parent / "state"

    # ── Step 1: Build bundle ─────────────────────────────────────────────────
    bundle = build_bundle(draft_path)

    # ── Step 2: Persist bundle ───────────────────────────────────────────────
    _persist_bundle(bundle, bundle_persist_dir)

    # ── Step 3: Tier 1 ──────────────────────────────────────────────────────
    tier1_findings = _spec_ast.classify(draft_path)
    # Tier 1.5 spec-author lints (v0.3.1): runuser-no-cd, unsafe-heredoc.
    # Folded into Tier 1 results so callers see a single deterministic group.
    tier1_findings.extend(_spec_lint.lint_spec(draft_path))

    # ── Step 4: Tier 2 ──────────────────────────────────────────────────────
    tier2_findings = _coverage_gate.classify(
        draft_path, preview_adrs=bundle.preview_adrs
    )

    # ── Step 5: Tier 3 (opt-in) ─────────────────────────────────────────────
    tier3_findings: list[_findings.Finding] = []
    tiers_run = [1, 2]
    severity_overrides: dict[str, str] = {}
    config_dict: dict = {}
    config_hash: str | None = None
    deepseek_model_version: str | None = None

    if config_path is not None:
        config_path = pathlib.Path(config_path)
        if not config_path.exists():
            # Config was explicitly requested but file is absent — emit a visible signal.
            tier3_findings.append(_findings.Finding(
                tier=3,
                kind="tier3-unavailable",
                severity="info",
                location=_findings.FindingLocation(scope="spec-wide"),
                message=f"Tier 3 skipped (config-missing): {config_path}",
                dismissable=False,
            ))
        else:
            from bin import llm_judge as _llm_judge

            config_dict = _load_toml_config(config_path)
            config_hash = hashlib.sha256(config_path.read_bytes()).hexdigest()
            tier3_cfg = config_dict.get("tier3", {})
            severity_overrides = config_dict.get("severity_overrides", {})

            if tier3_cfg.get("enabled", False):
                judge_config = _llm_judge.JudgeConfig(
                    enabled=True,
                    api_key_env=tier3_cfg.get("api_key_env", "DEEPSEEK_API_KEY"),
                    model=tier3_cfg.get("model", DEEPSEEK_MODEL),
                    base_url=tier3_cfg.get("base_url", DEEPSEEK_BASE_URL),
                    budget_tokens_per_spec=tier3_cfg.get("budget_tokens_per_spec", 50_000),
                    timeout_s=tier3_cfg.get("timeout_s", TIER3_TIMEOUT_S),
                )
                tier3_findings = _llm_judge.evaluate(bundle.spec_text, config=judge_config)
                # tiers_run only flips to [1, 2, 3] when llm_judge actually reached the API
                # (i.e. didn't return a tier3-unavailable sentinel). Detect by absence of
                # tier3-unavailable findings.
                if not any(f.kind == "tier3-unavailable" for f in tier3_findings):
                    tiers_run = [1, 2, 3]
                    deepseek_model_version = tier3_cfg.get("model", DEEPSEEK_MODEL)
            else:
                # Config exists but Tier 3 is explicitly disabled — emit a visible signal.
                tier3_findings.append(_findings.Finding(
                    tier=3,
                    kind="tier3-unavailable",
                    severity="info",
                    location=_findings.FindingLocation(scope="spec-wide"),
                    message=f"Tier 3 skipped (disabled-in-config): {config_path}",
                    dismissable=False,
                ))

    # ── Step 6: Aggregate ────────────────────────────────────────────────────
    all_findings = tier1_findings + tier2_findings + tier3_findings

    # ── Step 7: Parse dismissals ─────────────────────────────────────────────
    dismissals = parse_dismissals(bundle.spec_text)
    dismissed_fps: set[str] = {d["fingerprint"] for d in dismissals}

    # ── Step 8: Filter dismissed (only dismissable=True findings) ────────────
    # Track pre-filter list to accurately count actually-dismissed findings.
    all_findings_pre_filter = all_findings
    filtered: list[_findings.Finding] = []
    for f in all_findings_pre_filter:
        if f.dismissable and _findings.fingerprint(f) in dismissed_fps:
            continue
        filtered.append(f)

    # Count findings that were actually suppressed by the dismissal filter.
    actually_dismissed_count = sum(
        1 for f in all_findings_pre_filter
        if f.dismissable and _findings.fingerprint(f) in dismissed_fps
    )

    # ── Step 9: Apply severity overrides (raise-only) ────────────────────────
    filtered = _apply_severity_overrides(filtered, severity_overrides)

    # ── Step 10: Max severity ────────────────────────────────────────────────
    max_sev = _findings.max_severity(filtered)

    # ── Step 11: Build sidecar_payload ───────────────────────────────────────
    # policy_hash is always computed (over the loaded config dict + severity
    # overrides). config_dict stays {} when no config_path was supplied or the
    # path didn't exist, so the hash is stable for the no-config case.
    policy_hash = _eval_metadata.compute_policy_hash(config_dict, severity_overrides)
    sidecar_payload: dict = {
        "evaluator_version": EVALUATOR_VERSION,
        "tiers_run": tiers_run,
        "dismissals": dismissals,
        "policy_hash": policy_hash,
        "config_hash": config_hash,
        "deepseek_model_version": deepseek_model_version,
        "findings_summary": {
            "block_count": sum(1 for f in filtered if f.severity == "block"),
            "warn_count": sum(1 for f in filtered if f.severity == "warn"),
            "info_count": sum(1 for f in filtered if f.severity == "info"),
            "dismissed_t3_count": actually_dismissed_count,
        },
    }

    return EvaluatorResult(
        findings=filtered,
        max_severity=max_sev,
        bundle=bundle,
        sidecar_payload=sidecar_payload,
    )


def load_persisted_bundle(
    bundle_path: pathlib.Path,
    draft_sha256: str,
    *,
    draft_path: pathlib.Path,
) -> ReviewBundle | None:
    """Read persisted bundle and verify it matches the current draft hash.

    Returns None if file missing or hash mismatch (caller rebuilds).
    `draft_path` is required because the bundle JSON deliberately omits it;
    the caller (/vision §6.5/6.6) always knows the spec file path.
    """
    bundle_path = pathlib.Path(bundle_path)
    draft_path = pathlib.Path(draft_path)
    if not bundle_path.exists():
        return None
    try:
        data = json.loads(bundle_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
    if data.get("draft_sha256") != draft_sha256:
        return None
    try:
        return ReviewBundle.from_dict(data, draft_path)
    except (KeyError, TypeError, ValueError):
        return None


def clear_bundle(bundle_path: pathlib.Path) -> None:
    """Remove the persisted bundle file (idempotent — no-op if absent)."""
    bundle_path = pathlib.Path(bundle_path)
    try:
        bundle_path.unlink()
    except FileNotFoundError:
        pass
