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
        assert any(f.kind == "unowned-requirement-heuristic" for f in fs)
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
        f = next(x for x in fs if x.kind == "unowned-requirement-heuristic")
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
        f = next(x for x in fs if x.kind == "unowned-requirement-heuristic")
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
        assert not any(f.kind == "unowned-requirement-heuristic" for f in fs)
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
        assert any(f.kind == "unowned-requirement-heuristic" for f in fs)
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
        assert not any(f.kind == "unowned-requirement-heuristic" for f in fs)
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
        assert any(f.kind == "unowned-requirement-heuristic" for f in fs)
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
        assert not any(f.kind == "unowned-requirement-heuristic" for f in fs)
    finally:
        _cleanup(p)


# ════════════════════════════════════════════════════════════════════════════
# B1 — curl route captures full path; allowlist suppresses universal probes
# ════════════════════════════════════════════════════════════════════════════


def test_b1_curl_full_path_captured_blocks():
    """`curl http://localhost:8080/api/convert` must block on /api/convert (full path)."""
    p = _make_spec(
        '- step: 1\n'
        '  why: "verify endpoint"\n'
        '  action: "echo started"\n'
        '  verification: "curl http://localhost:8080/api/convert"\n'
    )
    try:
        fs = spec_ast.classify(p)
        assert any(f.kind == "unowned-requirement-heuristic" for f in fs)
    finally:
        _cleanup(p)


def test_b1_curl_healthz_not_flagged():
    """`curl http://localhost/healthz` is in the allowlist — must not block."""
    p = _make_spec(
        '- step: 1\n'
        '  why: "health probe"\n'
        '  action: "echo started"\n'
        '  verification: "curl http://localhost/healthz"\n'
    )
    try:
        fs = spec_ast.classify(p)
        assert not any(f.kind == "unowned-requirement-heuristic" for f in fs)
    finally:
        _cleanup(p)


def test_b1_curl_health_path_not_flagged():
    """`curl http://localhost/health` allowlisted — must not block."""
    p = _make_spec(
        '- step: 1\n'
        '  why: "health probe"\n'
        '  action: "echo started"\n'
        '  verification: "curl http://localhost/health"\n'
    )
    try:
        fs = spec_ast.classify(p)
        assert not any(f.kind == "unowned-requirement-heuristic" for f in fs)
    finally:
        _cleanup(p)


def test_b1_curl_items_42_full_path_blocks():
    """`curl http://localhost/api/items/42` must block on /api/items/42 (not just /42)."""
    p = _make_spec(
        '- step: 1\n'
        '  why: "verify item endpoint"\n'
        '  action: "echo started"\n'
        '  verification: "curl http://localhost/api/items/42"\n'
    )
    try:
        fs = spec_ast.classify(p)
        findings = [f for f in fs if f.kind == "unowned-requirement-heuristic"]
        assert any("/api/items/42" in f.message for f in findings)
    finally:
        _cleanup(p)


def test_b1_prior_step_mentioning_convert_substring_does_not_bypass():
    """A prior step mentioning `/other/convert` must NOT satisfy `/api/convert` authorship."""
    p = _make_spec(
        '- step: 1\n'
        '  why: "unrelated route"\n'
        '  action: "echo /other/convert route registered"\n'
        '  verification: "true"\n'
        '- step: 2\n'
        '  why: "check api convert"\n'
        '  action: "echo done"\n'
        '  verification: "curl http://localhost:8080/api/convert | grep ok"\n'
    )
    try:
        fs = spec_ast.classify(p)
        # /api/convert is NOT in prior corpus (only /other/convert is)
        assert any(f.kind == "unowned-requirement-heuristic" for f in fs)
    finally:
        _cleanup(p)


# ════════════════════════════════════════════════════════════════════════════
# B2 — bare `import X` in python3 -c body is checked
# ════════════════════════════════════════════════════════════════════════════


def test_b2_bare_import_without_prior_author_blocks():
    """`python3 -c 'import yt_readable.server'` with no prior owner — must block."""
    p = _make_spec(
        '- step: 1\n'
        '  why: "check module importable"\n'
        '  action: "echo checking"\n'
        "  verification: \"python3 -c 'import yt_readable.server'\"\n"
    )
    try:
        fs = spec_ast.classify(p)
        assert any(f.kind == "unowned-requirement-heuristic" for f in fs)
    finally:
        _cleanup(p)


def test_b2_bare_import_passes_when_prior_step_authored():
    """`import yt_readable.server` passes when prior step authored the module file."""
    p = _make_spec(
        '- step: 1\n'
        '  why: "create module"\n'
        '  action: "cat > /tmp/spectest/yt_readable/server.py <<EOF\\npass\\nEOF"\n'
        '  verification: "test -f /tmp/spectest/yt_readable/server.py"\n'
        '- step: 2\n'
        '  why: "verify importable"\n'
        '  action: "echo done"\n'
        "  verification: \"python3 -c 'import yt_readable.server'\"\n"
    )
    try:
        fs = spec_ast.classify(p)
        assert not any(f.kind == "unowned-requirement-heuristic" for f in fs)
    finally:
        _cleanup(p)


def test_b2_stdlib_bare_import_not_flagged():
    """`python3 -c 'import os'` — stdlib module, must not block."""
    p = _make_spec(
        '- step: 1\n'
        '  why: "check os module"\n'
        '  action: "echo checking"\n'
        "  verification: \"python3 -c 'import os; print(os.getcwd())'\"\n"
    )
    try:
        fs = spec_ast.classify(p)
        assert not any(f.kind == "unowned-requirement-heuristic" for f in fs)
    finally:
        _cleanup(p)


# ════════════════════════════════════════════════════════════════════════════
# B3 — `from X import Y` anywhere in -c body (not just at body start)
# ════════════════════════════════════════════════════════════════════════════


def test_b3_from_import_after_leading_statement_blocks():
    """`python3 -c "import sys; from yt_readable.server import app"` — must block."""
    p = _make_spec(
        '- step: 1\n'
        '  why: "verify app importable after sys"\n'
        '  action: "echo checking"\n'
        '  verification: \'python3 -c "import sys; from yt_readable.server import app"\'\n'
    )
    try:
        fs = spec_ast.classify(p)
        assert any(f.kind == "unowned-requirement-heuristic" for f in fs)
    finally:
        _cleanup(p)


def test_b3_from_import_after_leading_statement_passes_when_authored():
    """`import sys; from yt_readable.server import app` passes when module is authored."""
    p = _make_spec(
        '- step: 1\n'
        '  why: "create module"\n'
        '  action: "cat > /tmp/spectest/yt_readable/server.py <<EOF\\napp=1\\nEOF"\n'
        '  verification: "test -f /tmp/spectest/yt_readable/server.py"\n'
        '- step: 2\n'
        '  why: "verify importable"\n'
        '  action: "echo done"\n'
        '  verification: \'python3 -c "import sys; from yt_readable.server import app"\'\n'
    )
    try:
        fs = spec_ast.classify(p)
        assert not any(f.kind == "unowned-requirement-heuristic" for f in fs)
    finally:
        _cleanup(p)


def test_b3_multi_import_both_checked():
    """`from yt_readable.db import migrate` in multi-statement body — must block."""
    p = _make_spec(
        '- step: 1\n'
        '  why: "verify db module"\n'
        '  action: "echo checking"\n'
        '  verification: \'python3 -c "import os; from yt_readable.db import migrate"\'\n'
    )
    try:
        fs = spec_ast.classify(p)
        assert any(f.kind == "unowned-requirement-heuristic" for f in fs)
    finally:
        _cleanup(p)


# ════════════════════════════════════════════════════════════════════════════
# v0.6.2 regression — issue #36: `from X import Y` symbol misclassified as module
# ════════════════════════════════════════════════════════════════════════════


def test_issue36_from_import_symbol_does_not_fire_as_unowned_module():
    """`from foo.bar import baz` — `baz` is a SYMBOL, not a module.  The
    IMPORT_ALT regex must skip spans already covered by IMPORT_RE (which
    captures `foo.bar`)."""
    p = _make_spec(
        '- step: 1\n'
        '  why: "create module"\n'
        '  action: "mkdir -p /tmp/spectest/spectre_daemon && touch /tmp/spectest/spectre_daemon/blocklist.py"\n'
        '  verification: "test -f /tmp/spectest/spectre_daemon/blocklist.py"\n'
        '  produces:\n'
        '    - "module:spectre_daemon.blocklist"\n'
        '- step: 2\n'
        '  why: "verify importable"\n'
        '  action: "echo done"\n'
        '  verification: \'python3 -c "from spectre_daemon.blocklist import is_blocked; print(is_blocked)"\'\n'
        '  requires:\n'
        '    - "module:spectre_daemon.blocklist"\n'
    )
    try:
        fs = spec_ast.classify(p)
        msgs = [f.message for f in fs if f.kind == "unowned-requirement-heuristic"]
        assert msgs == [], f"unexpected heuristic findings: {msgs}"
    finally:
        _cleanup(p)


def test_issue36_package_produces_shadows_submodule_requires():
    """`package:foo` declared on step 1 must satisfy `module:foo.bar` required
    by step 2 — parent-package match in contract resolution."""
    p = _make_spec(
        '- step: 1\n'
        '  why: "create package"\n'
        '  action: "mkdir -p /tmp/spectest/foo && touch /tmp/spectest/foo/__init__.py"\n'
        '  verification: "test -f /tmp/spectest/foo/__init__.py"\n'
        '  produces:\n'
        '    - "package:foo"\n'
        '- step: 2\n'
        '  why: "verify submodule importable"\n'
        '  action: "echo done"\n'
        '  verification: "test -d /tmp/spectest/foo"\n'
        '  requires:\n'
        '    - "module:foo.bar"\n'
    )
    try:
        fs = spec_ast.classify(p)
        kinds = {f.kind for f in fs}
        assert "unowned-requirement" not in kinds, f"unexpected unowned-requirement; got {kinds}"
    finally:
        _cleanup(p)


def test_issue36_module_produces_shadows_deeper_module_requires():
    """`module:foo.bar` declared on step 1 must satisfy `module:foo.bar.baz`
    required by step 2 — parent-module match."""
    p = _make_spec(
        '- step: 1\n'
        '  why: "create module"\n'
        '  action: "echo init"\n'
        '  verification: "true"\n'
        '  produces:\n'
        '    - "module:foo.bar"\n'
        '- step: 2\n'
        '  why: "verify deeper module"\n'
        '  action: "echo done"\n'
        '  verification: "true"\n'
        '  requires:\n'
        '    - "module:foo.bar.baz"\n'
    )
    try:
        fs = spec_ast.classify(p)
        assert not any(f.kind == "unowned-requirement" for f in fs)
    finally:
        _cleanup(p)
