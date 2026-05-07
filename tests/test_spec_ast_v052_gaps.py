"""Tests for v0.5.2 Tier 1 gap-closers in bin/spec_ast.py.

Gaps closed:
  D — verification-syntax-error: python3 -c body compiled at lock time
  A — action-invokes-uncreated-artifact: absolute-path invocation w/o prior creation
  C — unowned-requirement: e2e assertion on route/HTML/DB/import not previously authored

Pragma guard: one assertion per test; tests with rejects/raises/refuses/denies/blocks
in name use pytest.raises.
"""
import pathlib
import tempfile

import pytest

from bin import spec_ast


# ── helpers ───────────────────────────────────────────────────────────────────

_HEADER = """\
# Test Spec
**Slug:** test-spec
## 1. Hard Problem
testing
## 2. First Principles
- only stdlib
## 3. Algorithm Audit
- **Delete:** none
- **Simplify:** none
- **Accelerate:** none
## 4. Speed-of-Light Limit
instant
## 5. Physics Guardrails
- none
"""

_FOOTER = """\
## 7. Success Criteria
- [ ] done

## 8. Receiver Calibration

### 8.1 Hard contract (machine-enforced — `block` severity on violation)

- `mutates:` /tmp/spectest/
- `never-touches:` /etc/passwd
- `decision-budget:` none
- `reboot-survival:` none
"""


def _make_spec(steps_yaml: str) -> pathlib.Path:
    """Write a spec with the given steps block and return a temp path."""
    body = _HEADER + "## 6. Steps\n\n```yaml\n" + steps_yaml + "\n```\n\n" + _FOOTER
    f = tempfile.NamedTemporaryFile(
        suffix=".spec.md", mode="w", delete=False, encoding="utf-8"
    )
    f.write(body)
    f.close()
    return pathlib.Path(f.name)


def _cleanup(p: pathlib.Path) -> None:
    p.unlink(missing_ok=True)


# ════════════════════════════════════════════════════════════════════════════
# Gap D — verification-syntax-error
# ════════════════════════════════════════════════════════════════════════════


def test_valid_python_c_verification_passes():
    """python3 -c "print(1)" is valid Python — no finding."""
    # Use YAML single-quote outer so inner double quotes survive the field parser
    p = _make_spec(
        '- step: 1\n'
        '  why: "smoke check"\n'
        '  action: "echo hello"\n'
        "  verification: 'python3 -c \"print(1)\"'\n"
    )
    try:
        fs = spec_ast.classify(p)
        assert not any(f.kind == "verification-syntax-error" for f in fs)
    finally:
        _cleanup(p)


def test_for_loop_missing_colon_verification_blocks():
    """'for line in lines print(line)' (missing colon) is a SyntaxError — must block."""
    # YAML single-quote outer so inner double quotes survive field stripping
    p = _make_spec(
        '- step: 1\n'
        '  why: "broken inline for loop"\n'
        '  action: "echo setup"\n'
        '  verification: \'python3 -c "for line in lines print(line)"\'\n'
    )
    try:
        fs = spec_ast.classify(p)
        assert any(f.kind == "verification-syntax-error" for f in fs)
    finally:
        _cleanup(p)


def test_verification_syntax_error_severity_is_block():
    """verification-syntax-error must carry block severity."""
    p = _make_spec(
        '- step: 1\n'
        '  why: "broken inline for loop"\n'
        '  action: "echo setup"\n'
        '  verification: \'python3 -c "for line in lines print(line)"\'\n'
    )
    try:
        fs = spec_ast.classify(p)
        f = next(x for x in fs if x.kind == "verification-syntax-error")
        assert f.severity == "block"
    finally:
        _cleanup(p)


def test_verification_syntax_error_location_ref_is_verification():
    """verification-syntax-error must point at the verification field."""
    p = _make_spec(
        '- step: 1\n'
        '  why: "broken inline for loop"\n'
        '  action: "echo setup"\n'
        '  verification: \'python3 -c "for line in lines print(line)"\'\n'
    )
    try:
        fs = spec_ast.classify(p)
        f = next(x for x in fs if x.kind == "verification-syntax-error")
        assert f.location.ref == "verification"
    finally:
        _cleanup(p)


def test_action_python_c_syntax_error_blocks():
    """SyntaxError in action's python3 -c body is also caught."""
    p = _make_spec(
        '- step: 1\n'
        '  why: "broken action python"\n'
        '  action: \'python3 -c "assert status =="\'\n'
        '  verification: "echo done"\n'
    )
    try:
        fs = spec_ast.classify(p)
        assert any(f.kind == "verification-syntax-error" for f in fs)
    finally:
        _cleanup(p)


def test_action_python_c_syntax_error_location_ref_is_action():
    """SyntaxError in action field — ref must be 'action'."""
    p = _make_spec(
        '- step: 1\n'
        '  why: "broken action python"\n'
        '  action: \'python3 -c "assert status =="\'\n'
        '  verification: "echo done"\n'
    )
    try:
        fs = spec_ast.classify(p)
        f = next(x for x in fs if x.kind == "verification-syntax-error")
        assert f.location.ref == "action"
    finally:
        _cleanup(p)


def test_multiple_python_c_bodies_all_checked():
    """Two -c bodies in one step: both checked (first valid, second has SyntaxError)."""
    # First body valid (print(1)), second body invalid (assert status ==)
    p = _make_spec(
        '- step: 1\n'
        '  why: "multi-body step"\n'
        '  action: \'python3 -c "print(1)"\'\n'
        '  verification: \'python3 -c "assert status =="\'\n'
    )
    try:
        fs = spec_ast.classify(p)
        assert any(f.kind == "verification-syntax-error" for f in fs)
    finally:
        _cleanup(p)


def test_print_1_single_statement_verification_passes():
    """python3 -c "print(1)" — single statement — is valid and must not block."""
    p = _make_spec(
        '- step: 1\n'
        '  why: "valid single-statement"\n'
        '  action: "echo test"\n'
        '  verification: \'python3 -c "print(1)"\'\n'
    )
    try:
        fs = spec_ast.classify(p)
        assert not any(f.kind == "verification-syntax-error" for f in fs)
    finally:
        _cleanup(p)


# ════════════════════════════════════════════════════════════════════════════
# Gap A — action-invokes-uncreated-artifact
# ════════════════════════════════════════════════════════════════════════════


def test_action_invokes_uncreated_path_blocks():
    """Step 2 invokes /tmp/spectest/run.py that no prior step created — block."""
    p = _make_spec(
        '- step: 1\n'
        '  why: "setup env"\n'
        '  action: "mkdir -p /tmp/spectest"\n'
        '  verification: "test -d /tmp/spectest"\n'
        '- step: 2\n'
        '  why: "run the script"\n'
        '  action: "python3 /tmp/spectest/run.py"\n'
        '  verification: "test -f /tmp/spectest/run.py"\n'
    )
    try:
        fs = spec_ast.classify(p)
        assert any(f.kind == "action-invokes-uncreated-artifact" for f in fs)
    finally:
        _cleanup(p)


def test_action_invokes_uncreated_artifact_severity_is_block():
    """action-invokes-uncreated-artifact must carry block severity."""
    p = _make_spec(
        '- step: 1\n'
        '  why: "setup env"\n'
        '  action: "mkdir -p /tmp/spectest"\n'
        '  verification: "test -d /tmp/spectest"\n'
        '- step: 2\n'
        '  why: "run the script"\n'
        '  action: "python3 /tmp/spectest/run.py"\n'
        '  verification: "test -f /tmp/spectest/run.py"\n'
    )
    try:
        fs = spec_ast.classify(p)
        f = next(x for x in fs if x.kind == "action-invokes-uncreated-artifact")
        assert f.severity == "block"
    finally:
        _cleanup(p)


def test_action_invokes_path_created_by_prior_heredoc_passes():
    """Step 2's heredoc creates /tmp/spectest/run.py — step 3 invocation passes."""
    p = _make_spec(
        '- step: 1\n'
        '  why: "make dir"\n'
        '  action: "mkdir -p /tmp/spectest"\n'
        '  verification: "test -d /tmp/spectest"\n'
        '- step: 2\n'
        '  why: "create the script"\n'
        '  action: "cat > /tmp/spectest/run.py <<EOF\\nprint(1)\\nEOF"\n'
        '  verification: "test -f /tmp/spectest/run.py"\n'
        '- step: 3\n'
        '  why: "run it"\n'
        '  action: "python3 /tmp/spectest/run.py"\n'
        '  verification: "python3 /tmp/spectest/run.py | grep 1"\n'
    )
    try:
        fs = spec_ast.classify(p)
        assert not any(f.kind == "action-invokes-uncreated-artifact" for f in fs)
    finally:
        _cleanup(p)


def test_external_binary_without_absolute_path_not_flagged():
    """Invocations of external tools (curl, pip) without absolute paths are not flagged."""
    p = _make_spec(
        '- step: 1\n'
        '  why: "install deps"\n'
        '  action: "pip install yt-dlp && curl http://example.com/check"\n'
        '  verification: "yt-dlp --version"\n'
    )
    try:
        fs = spec_ast.classify(p)
        assert not any(f.kind == "action-invokes-uncreated-artifact" for f in fs)
    finally:
        _cleanup(p)


def test_action_not_probed_warn_still_emitted():
    """Existing action-not-probed warn behavior is preserved alongside new checks."""
    p = _make_spec(
        '- step: 1\n'
        '  why: "write config"\n'
        '  action: "echo key=val > /tmp/spectest/cfg.conf"\n'
        '  verification: "test -d /tmp"\n'
    )
    try:
        fs = spec_ast.classify(p)
        assert any(f.kind == "action-not-probed" and f.severity == "warn" for f in fs)
    finally:
        _cleanup(p)


# ════════════════════════════════════════════════════════════════════════════
# Gap C — unowned-requirement
# ════════════════════════════════════════════════════════════════════════════


def test_curl_route_verification_without_prior_author_blocks():
    """Step verifies /api/convert route; no prior step authored it — block."""
    p = _make_spec(
        '- step: 1\n'
        '  why: "check api"\n'
        '  action: "echo started"\n'
        '  verification: "curl -X POST http://localhost:8080/api/convert | grep ok"\n'
    )
    try:
        fs = spec_ast.classify(p)
        assert any(f.kind == "unowned-requirement" for f in fs)
    finally:
        _cleanup(p)


def test_curl_route_verification_severity_is_block():
    """unowned-requirement must carry block severity."""
    p = _make_spec(
        '- step: 1\n'
        '  why: "check api"\n'
        '  action: "echo started"\n'
        '  verification: "curl -X POST http://localhost:8080/api/convert | grep ok"\n'
    )
    try:
        fs = spec_ast.classify(p)
        f = next(x for x in fs if x.kind == "unowned-requirement")
        assert f.severity == "block"
    finally:
        _cleanup(p)


def test_curl_route_verification_location_ref_is_verification():
    """unowned-requirement must point at the verification field."""
    p = _make_spec(
        '- step: 1\n'
        '  why: "check api"\n'
        '  action: "echo started"\n'
        '  verification: "curl -X POST http://localhost:8080/api/convert | grep ok"\n'
    )
    try:
        fs = spec_ast.classify(p)
        f = next(x for x in fs if x.kind == "unowned-requirement")
        assert f.location.ref == "verification"
    finally:
        _cleanup(p)


def test_curl_route_passes_when_prior_step_authored_it():
    """Step 2 verifies /api/convert; step 1's action mentions /api/convert — pass."""
    p = _make_spec(
        '- step: 1\n'
        '  why: "author the route /api/convert"\n'
        '  action: "cat > /tmp/spectest/server.py <<EOF\\n# route /api/convert\\nEOF"\n'
        '  verification: "test -f /tmp/spectest/server.py"\n'
        '- step: 2\n'
        '  why: "test the route"\n'
        '  action: "python3 /tmp/spectest/server.py &"\n'
        '  verification: "curl -X POST http://localhost:8080/api/convert | grep ok"\n'
    )
    try:
        fs = spec_ast.classify(p)
        assert not any(f.kind == "unowned-requirement" for f in fs)
    finally:
        _cleanup(p)


def test_sql_select_without_prior_author_blocks():
    """Verification queries 'articles' table with 'status' column no prior step created."""
    p = _make_spec(
        '- step: 1\n'
        '  why: "check db state"\n'
        '  action: "echo checking"\n'
        '  verification: "python3 -c \\"import sqlite3; c=sqlite3.connect(\'db.sqlite\'); '
        'r=c.execute(\'SELECT status FROM articles WHERE id=1\').fetchone(); assert r[0]==\'done\'\\"\n'
    )
    try:
        fs = spec_ast.classify(p)
        assert any(f.kind == "unowned-requirement" for f in fs)
    finally:
        _cleanup(p)


def test_sql_select_passes_when_prior_step_has_create_table():
    """Prior step's action has CREATE TABLE articles with status column — verification passes."""
    p = _make_spec(
        '- step: 1\n'
        '  why: "create db schema"\n'
        '  action: "python3 -c \\"import sqlite3; c=sqlite3.connect(\'db.sqlite\'); '
        'c.execute(\'CREATE TABLE articles (id INTEGER, status TEXT)\')\\"\n'
        '  verification: "test -f db.sqlite"\n'
        '- step: 2\n'
        '  why: "verify schema"\n'
        '  action: "echo done"\n'
        '  verification: "python3 -c \\"import sqlite3; c=sqlite3.connect(\'db.sqlite\'); '
        'r=c.execute(\'SELECT status FROM articles WHERE id=1\').fetchone()\\"\n'
    )
    try:
        fs = spec_ast.classify(p)
        assert not any(f.kind == "unowned-requirement" for f in fs)
    finally:
        _cleanup(p)


def test_python_import_verification_without_prior_author_blocks():
    """Verification imports yt_readable.server but no prior step authored it — block."""
    p = _make_spec(
        '- step: 1\n'
        '  why: "verify app importable"\n'
        '  action: "echo checking"\n'
        "  verification: \"python3 -c 'from yt_readable.server import app; assert app'\"\n"
    )
    try:
        fs = spec_ast.classify(p)
        assert any(f.kind == "unowned-requirement" for f in fs)
    finally:
        _cleanup(p)


def test_python_import_passes_when_prior_step_authored_module():
    """Step 1 authors yt_readable/server.py — step 2 import verification passes."""
    p = _make_spec(
        '- step: 1\n'
        '  why: "create module"\n'
        '  action: "cat > /tmp/spectest/yt_readable/server.py <<EOF\\napp=True\\nEOF"\n'
        '  verification: "test -f /tmp/spectest/yt_readable/server.py"\n'
        '- step: 2\n'
        '  why: "test import"\n'
        '  action: "echo done"\n'
        "  verification: \"python3 -c 'from yt_readable.server import app; assert app'\"\n"
    )
    try:
        fs = spec_ast.classify(p)
        assert not any(f.kind == "unowned-requirement" for f in fs)
    finally:
        _cleanup(p)
