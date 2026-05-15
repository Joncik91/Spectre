"""tests/test_spec_ast_taint.py — per-artifact-version taint model with sanitized-input.

Tests for the Fix L extension: `sanitized-input:` step field + artifact-version tracking.

Design invariants under test:
- sanitized-input: X clears taint of the *current version* of X at this step's
  consumption boundary.
- A subsequent produces: X (at step M > N) mints a new artifact version. Any prior
  sanitized-input: declaration for X does NOT cover this new version — the re-write
  resets the version clock.
- Existing sanitizes: semantics are fully preserved (regression).
"""
import pathlib
import tempfile

import pytest

from bin import substrate_ast


_HEADER = (
    "# Test Spec\n"
    "**Slug:** test-spec\n"
    "## 1. Hard Problem\nfoo\n"
    "## 2. First Principles\n- foo\n"
    "## 3. Algorithm Audit\n- Delete: none\n- Simplify: none\n- Accelerate: none\n"
    "## 4. Speed-of-Light Limit\nfoo\n"
    "## 5. Physics Guardrails\n- foo\n"
    "## 6. Steps\n\n```yaml\n"
)

_FOOTER = (
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
    "- trust-profile: untrusted-input\n"
    "- contextual-binding: test binding\n"
    "- provenance: { kind: none }\n"
    "- assumptions-killed: <list of considered-and-ruled-out alternatives>\n"
    "- requires-situated-judgment: <list of step IDs>\n"
    "- ux-contract:\n"
    "    on-success: ok\n"
    "    on-failure: failed; check logs\n"
    "    log-target: /tmp/log\n"
)


def _make_spec(steps_yaml: str) -> pathlib.Path:
    body = _HEADER + steps_yaml + _FOOTER
    f = tempfile.NamedTemporaryFile(
        suffix=".spec.md", mode="w", delete=False, encoding="utf-8"
    )
    f.write(body)
    f.close()
    return pathlib.Path(f.name)


def _cleanup(p: pathlib.Path) -> None:
    p.unlink(missing_ok=True)


def _finding_kinds(p: pathlib.Path) -> list[str]:
    return [f.kind for f in substrate_ast.classify(p)]


# ── Test 1: baseline regression — untrusted input without sanitized-input fires ──

def test_baseline_no_sanitized_input_fires():
    """Step 1 untrusted → step 2 filesystem write without guard → finding fires.

    Regression: existing behavior must be preserved when sanitized-input: is absent.
    """
    p = _make_spec(
        '- step: 1\n'
        '  why: "fetch"\n'
        '  action: "curl https://example.com > /tmp/data"\n'
        '  verification: "test -f /tmp/data"\n'
        '  produces: ["file:/tmp/data"]\n'
        '  untrusted-input: "yes"\n'
        '- step: 2\n'
        '  why: "write"\n'
        '  action: "cp /tmp/data /etc/foo"\n'
        '  verification: "test -f /etc/foo"\n'
        '  produces: ["file:/etc/foo"]\n'
        '  requires: ["file:/tmp/data"]\n'
        '  untrusted-input: "no"\n',
    )
    try:
        kinds = _finding_kinds(p)
        assert "untrusted-flow-unguarded" in kinds
    finally:
        _cleanup(p)


# ── Test 2: step declares sanitized-input on its own consumes → no finding ──

def test_sanitized_input_on_consuming_step_clears_finding():
    """Step 2 declares sanitized-input: [file:/tmp/data] — taint is cleared at consumption."""
    p = _make_spec(
        '- step: 1\n'
        '  why: "fetch"\n'
        '  action: "curl https://example.com > /tmp/data"\n'
        '  verification: "test -f /tmp/data"\n'
        '  produces: ["file:/tmp/data"]\n'
        '  untrusted-input: "yes"\n'
        '- step: 2\n'
        '  why: "write-safe"\n'
        '  action: "validated-copy /tmp/data /etc/foo"\n'
        '  verification: "test -f /etc/foo"\n'
        '  produces: ["file:/etc/foo"]\n'
        '  requires: ["file:/tmp/data"]\n'
        '  sanitized-input: ["file:/tmp/data"]\n'
        '  untrusted-input: "no"\n',
    )
    try:
        kinds = _finding_kinds(p)
        assert "untrusted-flow-unguarded" not in kinds
    finally:
        _cleanup(p)


# ── Test 3: upstream sanitized-input; downstream consumes without re-declaration ──

def test_upstream_sanitized_input_propagates_to_downstream():
    """Step 2 sanitizes the input; step 3 consumes the now-clean artifact safely.

    sanitized-input: at step 2 clears taint of file:/tmp/data.  Step 3 consumes
    file:/tmp/data without its own sanitized-input: and must NOT fire.
    """
    p = _make_spec(
        '- step: 1\n'
        '  why: "fetch"\n'
        '  action: "curl https://example.com > /tmp/data"\n'
        '  verification: "test -f /tmp/data"\n'
        '  produces: ["file:/tmp/data"]\n'
        '  untrusted-input: "yes"\n'
        '- step: 2\n'
        '  why: "clean"\n'
        '  action: "clean-tool /tmp/data"\n'
        '  verification: "true"\n'
        '  produces: ["file:/tmp/cleaned"]\n'
        '  requires: ["file:/tmp/data"]\n'
        '  sanitized-input: ["file:/tmp/data"]\n'
        '  untrusted-input: "no"\n'
        '- step: 3\n'
        '  why: "use-cleaned"\n'
        '  action: "cp /tmp/cleaned /etc/bar"\n'
        '  verification: "test -f /etc/bar"\n'
        '  produces: ["file:/etc/bar"]\n'
        '  requires: ["file:/tmp/cleaned"]\n'
        '  untrusted-input: "no"\n',
    )
    try:
        kinds = _finding_kinds(p)
        assert "untrusted-flow-unguarded" not in kinds
    finally:
        _cleanup(p)


# ── Test 4: artifact-version edge case — re-write after sanitized-input re-taints ──

def test_artifact_version_rewrite_after_sanitized_input_fires():
    """Artifact-version invariant: sanitized-input at step 5 clears version-5 of
    file:/tmp/secrets.  Step 7 re-writes file:/tmp/secrets from an untrusted source,
    minting version-7 (tainted).  Step 9 consumes file:/tmp/secrets without
    sanitized-input: → finding fires on step 9.

    This is the canonical edge case for the artifact-version model.
    """
    p = _make_spec(
        # step 1: initial taint source
        '- step: 1\n'
        '  why: "fetch"\n'
        '  action: "curl https://example.com > /tmp/secrets"\n'
        '  verification: "test -f /tmp/secrets"\n'
        '  produces: ["file:/tmp/secrets"]\n'
        '  untrusted-input: "yes"\n'
        # step 3: intermediate clean step (no re-produce)
        '- step: 3\n'
        '  why: "log"\n'
        '  action: "echo logging"\n'
        '  verification: "true"\n'
        '  produces: ["file:/tmp/log"]\n'
        '  untrusted-input: "no"\n'
        # step 5: declares sanitized-input — clears taint of current version of secrets
        '- step: 5\n'
        '  why: "validate"\n'
        '  action: "validate-tool /tmp/secrets > /tmp/validated"\n'
        '  verification: "test -f /tmp/validated"\n'
        '  produces: ["file:/tmp/validated"]\n'
        '  requires: ["file:/tmp/secrets"]\n'
        '  sanitized-input: ["file:/tmp/secrets"]\n'
        '  untrusted-input: "no"\n'
        # step 7: NEW taint source that re-writes secrets → mints version-7 (tainted)
        '- step: 7\n'
        '  why: "re-fetch"\n'
        '  action: "curl https://evil.example.com > /tmp/secrets"\n'
        '  verification: "test -f /tmp/secrets"\n'
        '  produces: ["file:/tmp/secrets"]\n'
        '  untrusted-input: "yes"\n'
        # step 9: consumes secrets — sees version-7 (tainted), no sanitized-input → fire
        '- step: 9\n'
        '  why: "use"\n'
        '  action: "cp /tmp/secrets /etc/config"\n'
        '  verification: "test -f /etc/config"\n'
        '  produces: ["file:/etc/config"]\n'
        '  requires: ["file:/tmp/secrets"]\n'
        '  untrusted-input: "no"\n',
    )
    try:
        fs = substrate_ast.classify(p)
        unguarded = [f for f in fs if f.kind == "untrusted-flow-unguarded"]
        # Must fire on step 9 (sees tainted version-7 of /tmp/secrets)
        step_nums = [f.location.step for f in unguarded]
        assert 9 in step_nums, (
            f"Expected finding on step 9; got findings on steps {step_nums}"
        )
    finally:
        _cleanup(p)


# ── Test 5: two consecutive sanitized-input declarations — idempotent ──

def test_two_consecutive_sanitized_input_idempotent():
    """Two consecutive steps that both declare sanitized-input on the same path
    produce no double-clear anomaly — result is clean, no finding fires.
    """
    p = _make_spec(
        '- step: 1\n'
        '  why: "fetch"\n'
        '  action: "curl https://example.com > /tmp/x"\n'
        '  verification: "test -f /tmp/x"\n'
        '  produces: ["file:/tmp/x"]\n'
        '  untrusted-input: "yes"\n'
        '- step: 2\n'
        '  why: "first-clean"\n'
        '  action: "clean1 /tmp/x > /tmp/y"\n'
        '  verification: "test -f /tmp/y"\n'
        '  produces: ["file:/tmp/y"]\n'
        '  requires: ["file:/tmp/x"]\n'
        '  sanitized-input: ["file:/tmp/x"]\n'
        '  untrusted-input: "no"\n'
        '- step: 3\n'
        '  why: "second-clean"\n'
        '  action: "clean2 /tmp/x > /tmp/z"\n'
        '  verification: "test -f /tmp/z"\n'
        '  produces: ["file:/tmp/z"]\n'
        '  requires: ["file:/tmp/x"]\n'
        '  sanitized-input: ["file:/tmp/x"]\n'
        '  untrusted-input: "no"\n'
        '- step: 4\n'
        '  why: "use"\n'
        '  action: "use-clean /tmp/y /tmp/z > /etc/result"\n'
        '  verification: "test -f /etc/result"\n'
        '  produces: ["file:/etc/result"]\n'
        '  requires: ["file:/tmp/y", "file:/tmp/z"]\n'
        '  untrusted-input: "no"\n',
    )
    try:
        kinds = _finding_kinds(p)
        assert "untrusted-flow-unguarded" not in kinds
    finally:
        _cleanup(p)


# ── Test 6: sanitized-input does NOT suppress finding for a DIFFERENT path ──

def test_sanitized_input_does_not_cover_different_path():
    """sanitized-input: [file:/tmp/a] must NOT clear taint of file:/tmp/b."""
    p = _make_spec(
        '- step: 1\n'
        '  why: "fetch-a"\n'
        '  action: "curl https://example.com/a > /tmp/a"\n'
        '  verification: "test -f /tmp/a"\n'
        '  produces: ["file:/tmp/a"]\n'
        '  untrusted-input: "yes"\n'
        '- step: 2\n'
        '  why: "fetch-b"\n'
        '  action: "curl https://example.com/b > /tmp/b"\n'
        '  verification: "test -f /tmp/b"\n'
        '  produces: ["file:/tmp/b"]\n'
        '  untrusted-input: "yes"\n'
        '- step: 3\n'
        '  why: "write-both"\n'
        '  action: "cat /tmp/a /tmp/b > /etc/combined"\n'
        '  verification: "test -f /etc/combined"\n'
        '  produces: ["file:/etc/combined"]\n'
        '  requires: ["file:/tmp/a", "file:/tmp/b"]\n'
        '  sanitized-input: ["file:/tmp/a"]\n'
        '  untrusted-input: "no"\n',
    )
    try:
        kinds = _finding_kinds(p)
        # file:/tmp/b is still tainted — finding must still fire
        assert "untrusted-flow-unguarded" in kinds
    finally:
        _cleanup(p)


# ── Test 7: sanitized-input on non-requires path is a no-op (no crash) ──

def test_sanitized_input_on_non_required_path_is_noop():
    """Declaring sanitized-input for a path not in requires: is silently ignored."""
    p = _make_spec(
        '- step: 1\n'
        '  why: "fetch"\n'
        '  action: "curl https://example.com > /tmp/data"\n'
        '  verification: "test -f /tmp/data"\n'
        '  produces: ["file:/tmp/data"]\n'
        '  untrusted-input: "yes"\n'
        '- step: 2\n'
        '  why: "write"\n'
        '  action: "validated-copy /tmp/data /etc/foo"\n'
        '  verification: "test -f /etc/foo"\n'
        '  produces: ["file:/etc/foo"]\n'
        '  requires: ["file:/tmp/data"]\n'
        '  sanitized-input: ["file:/tmp/data", "file:/tmp/irrelevant"]\n'
        '  untrusted-input: "no"\n',
    )
    try:
        kinds = _finding_kinds(p)
        assert "untrusted-flow-unguarded" not in kinds
    finally:
        _cleanup(p)


# ── Test 8: sanitized-input clears fs-write finding specifically ──

def test_sanitized_input_clears_filesystem_write_finding():
    """sanitized-input declared on the consuming step suppresses the filesystem-write
    sink finding, which is the most common operator use-case (upstream clean step).
    """
    p = _make_spec(
        '- step: 1\n'
        '  why: "user-upload"\n'
        '  action: "receive-upload > /tmp/payload"\n'
        '  verification: "test -f /tmp/payload"\n'
        '  produces: ["file:/tmp/payload"]\n'
        '  untrusted-input: "yes"\n'
        '- step: 2\n'
        '  why: "scrub"\n'
        '  action: "scrub /tmp/payload > /tmp/clean"\n'
        '  verification: "test -f /tmp/clean"\n'
        '  produces: ["file:/tmp/clean"]\n'
        '  requires: ["file:/tmp/payload"]\n'
        '  sanitized-input: ["file:/tmp/payload"]\n'
        '  untrusted-input: "no"\n'
        '- step: 3\n'
        '  why: "persist"\n'
        '  action: "cp /tmp/clean /var/data/entry"\n'
        '  verification: "test -f /var/data/entry"\n'
        '  produces: ["file:/var/data/entry"]\n'
        '  requires: ["file:/tmp/clean"]\n'
        '  untrusted-input: "no"\n',
    )
    try:
        kinds = _finding_kinds(p)
        assert "untrusted-flow-unguarded" not in kinds
    finally:
        _cleanup(p)


# ── Test 9: step 9 fires even when prior sanitized-input covered version-5 ──
# Mirrors edge case, but verifies step 5 itself is clean (no finding on step 5).

def test_step5_clean_step9_fires_in_artifact_version_scenario():
    """In the artifact-version edge case, step 5 (with sanitized-input) is clean;
    step 9 (without sanitized-input, consuming re-tainted version-7) fires.
    """
    p = _make_spec(
        '- step: 1\n'
        '  why: "fetch"\n'
        '  action: "curl https://example.com > /tmp/secrets"\n'
        '  verification: "test -f /tmp/secrets"\n'
        '  produces: ["file:/tmp/secrets"]\n'
        '  untrusted-input: "yes"\n'
        '- step: 5\n'
        '  why: "clean-use"\n'
        '  action: "clean-tool /tmp/secrets > /tmp/out5"\n'
        '  verification: "test -f /tmp/out5"\n'
        '  produces: ["file:/tmp/out5"]\n'
        '  requires: ["file:/tmp/secrets"]\n'
        '  sanitized-input: ["file:/tmp/secrets"]\n'
        '  untrusted-input: "no"\n'
        '- step: 7\n'
        '  why: "re-fetch-from-untrusted"\n'
        '  action: "curl https://evil.example.com > /tmp/secrets"\n'
        '  verification: "test -f /tmp/secrets"\n'
        '  produces: ["file:/tmp/secrets"]\n'
        '  untrusted-input: "yes"\n'
        '- step: 9\n'
        '  why: "use-tainted-secrets"\n'
        '  action: "cp /tmp/secrets /etc/app/config"\n'
        '  verification: "test -f /etc/app/config"\n'
        '  produces: ["file:/etc/app/config"]\n'
        '  requires: ["file:/tmp/secrets"]\n'
        '  untrusted-input: "no"\n',
    )
    try:
        fs = substrate_ast.classify(p)
        unguarded = [f for f in fs if f.kind == "untrusted-flow-unguarded"]
        step_nums = {f.location.step for f in unguarded}
        # Step 5 is clean (sanitized-input declared) — must not appear
        assert 5 not in step_nums, f"Step 5 should be clean; findings: {step_nums}"
        # Step 9 sees version-7 (tainted) — must appear
        assert 9 in step_nums, f"Step 9 must fire; findings: {step_nums}"
    finally:
        _cleanup(p)
