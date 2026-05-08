"""Tier 1 deterministic §8.2 + per-step trust annotation parser + taint flow.

Public API:
    classify(spec_path: pathlib.Path) -> list[findings.Finding]
"""
from __future__ import annotations

import math
import pathlib
import re

from bin import findings as _findings

# ── §8.2 schema ──────────────────────────────────────────────────────────────

_BLOCK_SEVERITY_FIELDS = (
    "receiver-fingerprint",
    "trust-profile",
    "contextual-binding",
    "provenance",
)

_82_BLOCK_RE = re.compile(
    r"^###\s+8\.2\b.*?(?=^##\s|^###\s|\Z)", re.DOTALL | re.MULTILINE
)


def _extract_82_block(body: str) -> str | None:
    """Return the §8.2 block text (without the heading) or None."""
    m = _82_BLOCK_RE.search(body)
    return m.group(0) if m else None


def _field_present(block: str, field: str) -> bool:
    """True if the field has a non-empty value in the block."""
    pat = re.compile(rf"^\s*-\s+{re.escape(field)}\s*:\s*(.+)$", re.MULTILINE)
    m = pat.search(block)
    if not m:
        return False
    val = m.group(1).strip()
    return bool(val) and val != "<auto-filled by wizard>"


def _check_82_required_fields(body: str) -> list[_findings.Finding]:
    """Block on missing §8.2 block or missing required fields."""
    results: list[_findings.Finding] = []
    block = _extract_82_block(body)
    if block is None:
        results.append(_findings.Finding(
            tier=1,
            kind="substrate-incomplete",
            severity="block",
            location=_findings.FindingLocation(
                scope="spec-wide", ref="cognitive-substrate"
            ),
            message="§8.2 Cognitive-substrate contract is absent.",
            suggested_fix="Re-run /vision; the wizard auto-injects §8.2.",
        ))
        return results
    # ux-contract is structured (sub-keys); check separately
    has_ux = bool(re.search(r"^\s*-\s+ux-contract\s*:", block, re.MULTILINE))
    fields_to_check = list(_BLOCK_SEVERITY_FIELDS)
    if not has_ux:
        results.append(_findings.Finding(
            tier=1,
            kind="substrate-incomplete",
            severity="block",
            location=_findings.FindingLocation(
                scope="spec-wide", ref="cognitive-substrate"
            ),
            message="§8.2 ux-contract block missing.",
            suggested_fix="Re-run wizard or add ux-contract to §8.2.",
        ))
    for field in fields_to_check:
        if not _field_present(block, field):
            results.append(_findings.Finding(
                tier=1,
                kind="substrate-incomplete",
                severity="block",
                location=_findings.FindingLocation(
                    scope="spec-wide", ref="cognitive-substrate"
                ),
                message=f"§8.2 {field} is missing or empty.",
                suggested_fix="Re-run /vision wizard.",
            ))
    return results


_LIST_FIELD_RE_TPL = (
    r"^\s*-\s+{field}\s*:\s*(?P<inline>[^\n]*)$(?P<block>(?:\n\s+-\s+[^\n]+)*)"
)


def _extract_list_field(block: str, field: str) -> list[str]:
    """Parse a list field that may be inline or indented sequence.

    Returns empty list if value is angle-bracket placeholder (e.g.
    ``<list of step IDs>``) — these are template stubs, not real entries.
    """
    pat = re.compile(_LIST_FIELD_RE_TPL.format(field=re.escape(field)), re.MULTILINE)
    m = pat.search(block)
    if not m:
        return []
    inline = m.group("inline").strip()
    block_part = m.group("block") or ""
    items: list[str] = []
    if inline and not inline.startswith("<"):
        if inline.startswith("[") and inline.endswith("]"):
            inner = inline[1:-1]
            items.extend(t.strip().strip("'\"") for t in inner.split(",") if t.strip())
        else:
            items.append(inline)
    for line in block_part.splitlines():
        s = line.strip()
        if s.startswith("- "):
            items.append(s[2:].strip().strip("'\""))
    return items


def _count_steps(body: str) -> int:
    return len(re.findall(r"^\s*-\s+step\s*:\s*\d+", body, re.MULTILINE))


def _check_assumptions_walk(body: str) -> list[_findings.Finding]:
    block = _extract_82_block(body) or ""
    items = _extract_list_field(block, "assumptions-killed")
    n_steps = _count_steps(body)
    if items:
        return []
    if n_steps > 3:
        return [_findings.Finding(
            tier=1,
            kind="assumptions-walk-empty",
            severity="block",
            location=_findings.FindingLocation(
                scope="spec-wide", ref="assumptions-killed"
            ),
            message=(
                f"§8.2 assumptions-killed is empty; spec has {n_steps} steps so "
                "the possibility-walk discipline is required."
            ),
            suggested_fix="List ≥1 considered-and-ruled-out alternative.",
        )]
    return [_findings.Finding(
        tier=1,
        kind="assumptions-walk-empty",
        severity="warn",
        location=_findings.FindingLocation(
            scope="spec-wide", ref="assumptions-killed"
        ),
        message="§8.2 assumptions-killed is empty.",
        suggested_fix="List considered-and-ruled-out alternatives.",
    )]


def _check_judgment_cap(body: str) -> list[_findings.Finding]:
    block = _extract_82_block(body) or ""
    items = _extract_list_field(block, "requires-situated-judgment")
    n_steps = _count_steps(body)
    if not items or n_steps == 0:
        return []
    cap = max(1, math.floor(0.3 * n_steps))
    if len(items) <= cap:
        return []
    return [_findings.Finding(
        tier=1,
        kind="judgment-claim-overused",
        severity="warn",
        location=_findings.FindingLocation(
            scope="spec-wide", ref="requires-situated-judgment"
        ),
        message=(
            f"§8.2 requires-situated-judgment claims {len(items)} steps; "
            f"cap is {cap} ({n_steps}-step spec)."
        ),
        suggested_fix=(
            "Reduce judgment claims to ≤cap; situated-judgment is an escape "
            "hatch, not the default."
        ),
    )]


# ── Per-step trust annotation parsing ────────────────────────────────────────

_STEP_RE = re.compile(r"^- step:\s*(\d+)\s*$", re.MULTILINE)


def _scalar(chunk: str, field: str) -> str | None:
    pat = re.compile(rf"^\s+{re.escape(field)}\s*:\s*(.+?)$", re.MULTILINE)
    m = pat.search(chunk)
    if not m:
        return None
    raw = m.group(1).strip()
    return raw.strip("'\"")


def _list(chunk: str, field: str) -> list[str]:
    items: list[str] = []
    inline = re.search(
        rf"^\s+{re.escape(field)}\s*:\s*\[(?P<v>[^\]]*)\]\s*$",
        chunk, re.MULTILINE,
    )
    if inline:
        for part in inline.group("v").split(","):
            t = part.strip().strip("'\"")
            if t:
                items.append(t)
        return items
    block = re.search(
        rf"^\s+{re.escape(field)}\s*:\s*\n(?P<body>(?:\s+-\s+[^\n]+\n?)+)",
        chunk, re.MULTILINE,
    )
    if block:
        for line in block.group("body").splitlines():
            s = line.strip()
            if s.startswith("- "):
                items.append(s[2:].strip().strip("'\""))
    return items


def _split_steps(body: str) -> list[dict]:
    """Crude step splitter: returns list of dicts with action, requires,
    produces, untrusted-input, sanitizes."""
    yaml_block = re.search(
        r"^## 6\. Steps\s*\n.*?^```yaml\n(.*?)^```", body,
        re.DOTALL | re.MULTILINE,
    )
    if not yaml_block:
        return []
    text = yaml_block.group(1)
    starts = [m.start() for m in _STEP_RE.finditer(text)]
    if not starts:
        return []
    chunks: list[str] = []
    for i, s in enumerate(starts):
        e = starts[i + 1] if i + 1 < len(starts) else len(text)
        chunks.append(text[s:e])
    out: list[dict] = []
    for chunk in chunks:
        step_match = _STEP_RE.match(chunk)
        if not step_match:
            continue
        n = int(step_match.group(1))
        info = {
            "step": n,
            "action": _scalar(chunk, "action"),
            "verification": _scalar(chunk, "verification"),
            "untrusted-input": _scalar(chunk, "untrusted-input"),
            "produces": _list(chunk, "produces"),
            "requires": _list(chunk, "requires"),
            "sanitizes": _list(chunk, "sanitizes"),
        }
        out.append(info)
    return out


def _trust_profile(body: str) -> set[str]:
    block = _extract_82_block(body) or ""
    m = re.search(r"^\s*-\s+trust-profile\s*:\s*(.+)$", block, re.MULTILINE)
    if not m:
        return set()
    raw = m.group(1).strip()
    if not raw or raw == "none":
        return set()
    return {t.strip() for t in raw.split(",") if t.strip()}


# ── Sink detectors ───────────────────────────────────────────────────────────

_SHELL_EVAL_RE = re.compile(r"\b(?:bash|sh|zsh)\s+-c\b|\beval\b")
_SQL_RE = re.compile(
    r"\b(?:INSERT|UPDATE|REPLACE|DELETE\s+FROM)\b", re.IGNORECASE
)
_TEMPLATE_RE = re.compile(r"\b(?:jinja2|template_render|format_map)\b")
_NETWORK_EGRESS_RE = re.compile(
    r"\b(?:curl|wget|httpie|http)\b[^|;\n]*"
    r"\b(?:POST|PUT|--data|-d\b|--upload-file)",
    re.IGNORECASE,
)


def _value_in_action(action: str, contract_entry: str) -> bool:
    """True if the contract entry's value substring appears in action."""
    if ":" not in contract_entry:
        return False
    _, _, value = contract_entry.partition(":")
    value = value.strip()
    if not value:
        return False
    return value in action


def _classify_sinks(action: str, tainted_inputs: set[str]) -> list[str]:
    """Return list of sink kinds reached when tainted_inputs are interpolated."""
    sinks: list[str] = []
    has_taint_token = any(
        _value_in_action(action, t) for t in tainted_inputs
    )
    if not has_taint_token:
        return sinks
    if _SHELL_EVAL_RE.search(action):
        sinks.append("shell-eval")
    if _SQL_RE.search(action) or _TEMPLATE_RE.search(action):
        sinks.append("sql-or-template")
    if _NETWORK_EGRESS_RE.search(action):
        sinks.append("network-egress")
    return sinks


# ── Main taint-flow check ────────────────────────────────────────────────────

_VALID_ANNOT = frozenset({"yes", "no"})


def _check_trust_flow(body: str) -> list[_findings.Finding]:
    profile = _trust_profile(body)
    steps = _split_steps(body)
    results: list[_findings.Finding] = []

    requires_annot = bool(profile & {"untrusted-input", "handles-secrets"})

    # ── per-step annotation presence ──────────────────────────────────────
    if requires_annot:
        for step in steps:
            annot = step["untrusted-input"]
            if step["produces"] and annot is None:
                results.append(_findings.Finding(
                    tier=1,
                    kind="trust-annotation-required",
                    severity="block",
                    location=_findings.FindingLocation(
                        scope="step", step=step["step"], ref="untrusted-input"
                    ),
                    message=(
                        f"Step {step['step']} produces artifacts but "
                        "untrusted-input is missing under untrusted profile."
                    ),
                    suggested_fix='Add `untrusted-input: "yes"` or `"no"`.',
                ))
            if annot is not None and annot not in _VALID_ANNOT:
                results.append(_findings.Finding(
                    tier=1,
                    kind="malformed-trust-annotation",
                    severity="warn",
                    location=_findings.FindingLocation(
                        scope="step", step=step["step"], ref="untrusted-input"
                    ),
                    message=(
                        f"Step {step['step']} untrusted-input is "
                        f"{annot!r}; treated as 'yes' (fail-closed)."
                    ),
                    suggested_fix='Use "yes" or "no".',
                ))

    if not requires_annot:
        return results

    # ── propagate taint ───────────────────────────────────────────────────
    tainted: set[str] = set()  # contract entries currently tainted
    for step in steps:
        annot = step["untrusted-input"]
        is_taint_source = annot == "yes" or (
            annot is not None and annot not in _VALID_ANNOT
        )

        action = step["action"] or ""
        sanitized_outputs = set(step["sanitizes"])

        # Inputs flowing in that are tainted
        incoming = [r for r in step["requires"] if r in tainted]

        # Sink detection
        if incoming:
            sink_kinds = _classify_sinks(action, set(incoming))
            output_safe = bool(sanitized_outputs & set(step["produces"]))
            has_fs_write = any(
                p.startswith(("file:", "db-table:", "db-column:"))
                for p in step["produces"]
            )
            if has_fs_write and not output_safe:
                sink_kinds.append("filesystem-write")
            for kind in sink_kinds:
                results.append(_findings.Finding(
                    tier=1,
                    kind="untrusted-flow-unguarded",
                    severity="block",
                    location=_findings.FindingLocation(
                        scope="step", step=step["step"], ref="action"
                    ),
                    message=(
                        f"Step {step['step']} reaches {kind} sink with "
                        f"tainted input; no sanitization output declared."
                    ),
                    suggested_fix=(
                        "Add a prior sanitize step OR list cleaned output "
                        "in this step's `sanitizes:`."
                    ),
                ))

        # Update taint set: outputs are tainted if step is a source OR
        # tainted incoming; UNLESS the output is in sanitizes:.
        for prod in step["produces"]:
            if prod in sanitized_outputs:
                continue
            if is_taint_source or incoming:
                tainted.add(prod)

    return results


def classify(spec_path: pathlib.Path) -> list[_findings.Finding]:
    """Run all Tier 1 §8.2 checks; return finding list."""
    body = spec_path.read_text(encoding="utf-8")
    results: list[_findings.Finding] = []
    results.extend(_check_82_required_fields(body))
    results.extend(_check_assumptions_walk(body))
    results.extend(_check_judgment_cap(body))
    results.extend(_check_trust_flow(body))
    return results
