"""Tests for bin/substrate_ast.py — Tier 1 §8.2 + per-step taint flow."""
import pathlib
import tempfile

import pytest

from bin import substrate_ast


_HEADER_AND_FOOTER = {
    "header": (
        "# Test Spec\n"
        "**Slug:** test-spec\n"
        "## 1. Hard Problem\nfoo\n"
        "## 2. First Principles\n- foo\n"
        "## 3. Algorithm Audit\n- Delete: none\n- Simplify: none\n- Accelerate: none\n"
        "## 4. Speed-of-Light Limit\nfoo\n"
        "## 5. Physics Guardrails\n- foo\n"
        "## 6. Steps\n\n```yaml\n"
    ),
    "footer_81_only": (
        "\n```\n\n"
        "## 7. Success Criteria\n- [ ] done\n\n"
        "## 8. Receiver Calibration\n\n"
        "### 8.1 Hard contract\n\n"
        "- mutates: /tmp/x\n"
        "- never-touches: /etc\n"
        "- decision-budget: none\n"
        "- reboot-survival: none\n"
    ),
    "footer_complete_82": (
        "\n```\n\n"
        "## 7. Success Criteria\n- [ ] done\n\n"
        "## 8. Receiver Calibration\n\n"
        "### 8.1 Hard contract\n\n"
        "- mutates: /tmp/x\n"
        "- never-touches: /etc\n"
        "- decision-budget: none\n"
        "- reboot-survival: none\n\n"
        "### 8.2 Cognitive-substrate contract\n\n"
        "- receiver-fingerprint: claude-code+human\n"
        "- trust-profile: none\n"
        "- contextual-binding: test binding\n"
        "- provenance: { kind: none }\n"
        "- ux-contract:\n"
        "    on-success: ok\n"
        "    on-failure: failed; check logs\n"
        "    log-target: /tmp/log\n"
    ),
}


def _make_spec(steps_yaml: str, footer_key: str = "footer_complete_82") -> pathlib.Path:
    body = _HEADER_AND_FOOTER["header"] + steps_yaml + _HEADER_AND_FOOTER[footer_key]
    f = tempfile.NamedTemporaryFile(
        suffix=".spec.md", mode="w", delete=False, encoding="utf-8"
    )
    f.write(body)
    f.close()
    return pathlib.Path(f.name)


def _cleanup(p: pathlib.Path) -> None:
    p.unlink(missing_ok=True)


# ── §8.2 block presence ───────────────────────────────────────────────────────


def test_missing_82_block_emits_substrate_incomplete():
    """Spec without ### 8.2 block → block substrate-incomplete."""
    p = _make_spec(
        '- step: 1\n'
        '  why: "do thing"\n'
        '  action: "echo done"\n'
        '  verification: "true"\n',
        footer_key="footer_81_only",
    )
    try:
        fs = substrate_ast.classify(p)
        kinds = [(f.kind, f.severity) for f in fs]
        assert ("substrate-incomplete", "block") in kinds
    finally:
        _cleanup(p)


def test_complete_82_emits_no_findings():
    """A well-formed §8.2 emits no substrate-incomplete findings."""
    p = _make_spec(
        '- step: 1\n'
        '  why: "do thing"\n'
        '  action: "echo done"\n'
        '  verification: "true"\n'
    )
    try:
        fs = substrate_ast.classify(p)
        assert not any(f.kind == "substrate-incomplete" for f in fs)
    finally:
        _cleanup(p)


@pytest.mark.parametrize("missing_field,expected_message_token", [
    ("receiver-fingerprint", "receiver-fingerprint"),
    ("trust-profile", "trust-profile"),
    ("contextual-binding", "contextual-binding"),
    ("provenance", "provenance"),
])
def test_missing_required_field_emits_substrate_incomplete(missing_field, expected_message_token):
    """Each individual block-severity field is enforced."""
    body = _HEADER_AND_FOOTER["header"] + (
        '- step: 1\n  why: "x"\n  action: "echo"\n  verification: "true"\n'
    )
    body += _HEADER_AND_FOOTER["footer_complete_82"]
    body = body.replace(f"- {missing_field}: ", f"- {missing_field}-removed: ")
    f = tempfile.NamedTemporaryFile(
        suffix=".spec.md", mode="w", delete=False, encoding="utf-8"
    )
    f.write(body)
    f.close()
    p = pathlib.Path(f.name)
    try:
        fs = substrate_ast.classify(p)
        msgs = [f.message for f in fs if f.kind == "substrate-incomplete"]
        assert any(expected_message_token in m for m in msgs)
    finally:
        _cleanup(p)
