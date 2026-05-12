"""Tests for Tier 1 implicit-precondition-missing check (§46).

Pragma guard: assertion-style names only. One assertion per test.
Tests asserting absence/emptiness use _returns_empty/_is_none/_no_ naming.

Covers:
- each negative-path trigger phrasing (absent, missing, does not exist, etc.)
- environmental-trigger passthrough (port, env-var, WAL, etc.)
- directory-shaped token match
- multiple steps / multiple findings
- no finding when the path is covered by any step's produces:
- no finding for triggers with no path-shaped noun
"""
import os
import pathlib
import tempfile

from bin import spec_ast

# §1-§8 skeleton lives in tests/fixtures/spec_template.py.
from tests.fixtures.spec_template import write_spec_file as _write_spec_helper


def _write_spec(steps_yaml: str) -> pathlib.Path:
    return _write_spec_helper(
        steps_yaml,
        title="Implicit Precondition Test Spec",
        slug="implicit-precondition-test",
        problem="Testing implicit-precondition-missing detection.",
        first_principles="- Negative-path triggers naming absent files must be covered by a producer.",
        success_criteria="- [ ] Check passes.",
    )


IPM = "implicit-precondition-missing"

# ── Minimal step that triggers each phrasing ──────────────────────────────────

_ABSENT_YAML = """\
- step: 1
  why: "Install the package."
  action: "pip install -e ."
  verification: "pip show myapp"
  negative-paths:
    - trigger: "pyproject.toml absent"
      handler: "escalate"
"""

_MISSING_YAML = """\
- step: 1
  why: "Install the package."
  action: "pip install -e ."
  verification: "pip show myapp"
  negative-paths:
    - trigger: "pyproject.toml missing"
      handler: "escalate"
"""

_DOES_NOT_EXIST_YAML = """\
- step: 1
  why: "Install the package."
  action: "pip install -e ."
  verification: "pip show myapp"
  negative-paths:
    - trigger: "pyproject.toml does not exist"
      handler: "escalate"
"""

_NOT_FOUND_YAML = """\
- step: 1
  why: "Install the package."
  action: "pip install -e ."
  verification: "pip show myapp"
  negative-paths:
    - trigger: "requirements.txt not found"
      handler: "escalate"
"""

_MALFORMED_YAML = """\
- step: 1
  why: "Install the package."
  action: "pip install -e ."
  verification: "pip show myapp"
  negative-paths:
    - trigger: "pyproject.toml malformed"
      handler: "escalate"
"""

_NOT_WRITABLE_YAML = """\
- step: 1
  why: "Write state."
  action: "python3 -m myapp.writer"
  verification: "test -d state/"
  negative-paths:
    - trigger: "state/ not writable"
      handler: "escalate"
"""

# ── Trigger phrasing — one test per phrasing asserting the Finding kind ───────


def test_trigger_absent_emits_ipm_finding():
    p = _write_spec(_ABSENT_YAML)
    try:
        fs = spec_ast.classify(p)
        f = next((x for x in fs if x.kind == IPM), None)
        assert f is not None
    finally:
        p.unlink(missing_ok=True)


def test_trigger_missing_emits_ipm_finding():
    p = _write_spec(_MISSING_YAML)
    try:
        fs = spec_ast.classify(p)
        f = next((x for x in fs if x.kind == IPM), None)
        assert f is not None
    finally:
        p.unlink(missing_ok=True)


def test_trigger_does_not_exist_emits_ipm_finding():
    p = _write_spec(_DOES_NOT_EXIST_YAML)
    try:
        fs = spec_ast.classify(p)
        f = next((x for x in fs if x.kind == IPM), None)
        assert f is not None
    finally:
        p.unlink(missing_ok=True)


def test_trigger_not_found_emits_ipm_finding():
    p = _write_spec(_NOT_FOUND_YAML)
    try:
        fs = spec_ast.classify(p)
        f = next((x for x in fs if x.kind == IPM), None)
        assert f is not None
    finally:
        p.unlink(missing_ok=True)


def test_trigger_malformed_emits_ipm_finding():
    p = _write_spec(_MALFORMED_YAML)
    try:
        fs = spec_ast.classify(p)
        f = next((x for x in fs if x.kind == IPM), None)
        assert f is not None
    finally:
        p.unlink(missing_ok=True)


def test_trigger_not_writable_emits_ipm_finding():
    p = _write_spec(_NOT_WRITABLE_YAML)
    try:
        fs = spec_ast.classify(p)
        f = next((x for x in fs if x.kind == IPM), None)
        assert f is not None
    finally:
        p.unlink(missing_ok=True)


# ── Finding shape ──────────────────────────────────────────────────────────────


def test_ipm_finding_severity_is_block():
    p = _write_spec(_ABSENT_YAML)
    try:
        fs = spec_ast.classify(p)
        f = next(x for x in fs if x.kind == IPM)
        assert f.severity == "block"
    finally:
        p.unlink(missing_ok=True)


def test_ipm_finding_tier_is_1():
    p = _write_spec(_ABSENT_YAML)
    try:
        fs = spec_ast.classify(p)
        f = next(x for x in fs if x.kind == IPM)
        assert f.tier == 1
    finally:
        p.unlink(missing_ok=True)


def test_ipm_finding_location_scope_is_step():
    p = _write_spec(_ABSENT_YAML)
    try:
        fs = spec_ast.classify(p)
        f = next(x for x in fs if x.kind == IPM)
        assert f.location.scope == "step"
    finally:
        p.unlink(missing_ok=True)


def test_ipm_finding_location_step_number_is_1():
    p = _write_spec(_ABSENT_YAML)
    try:
        fs = spec_ast.classify(p)
        f = next(x for x in fs if x.kind == IPM)
        assert f.location.step == 1
    finally:
        p.unlink(missing_ok=True)


def test_ipm_finding_message_contains_path_noun():
    p = _write_spec(_ABSENT_YAML)
    try:
        fs = spec_ast.classify(p)
        f = next(x for x in fs if x.kind == IPM)
        assert "pyproject.toml" in f.message
    finally:
        p.unlink(missing_ok=True)


def test_ipm_finding_location_ref_is_negative_paths():
    p = _write_spec(_ABSENT_YAML)
    try:
        fs = spec_ast.classify(p)
        f = next(x for x in fs if x.kind == IPM)
        assert f.location.ref == "negative-paths"
    finally:
        p.unlink(missing_ok=True)


# ── No finding when path is produced ─────────────────────────────────────────

_WITH_PRODUCER_YAML = """\
- step: 0
  why: "Scaffold the package."
  action: "write pyproject.toml"
  verification: "test -f pyproject.toml"
  produces:
    - "file:pyproject.toml"
  negative-paths:
    - trigger: "disk full"
      handler: "escalate"
- step: 1
  why: "Install the package."
  action: "pip install -e ."
  verification: "pip show myapp"
  negative-paths:
    - trigger: "pyproject.toml absent"
      handler: "escalate"
"""


def test_no_ipm_when_path_covered_by_prior_step_produces_returns_empty():
    p = _write_spec(_WITH_PRODUCER_YAML)
    try:
        fs = spec_ast.classify(p)
        assert not any(f.kind == IPM for f in fs)
    finally:
        p.unlink(missing_ok=True)


_WITH_LATER_PRODUCER_YAML = """\
- step: 1
  why: "Install the package."
  action: "pip install -e ."
  verification: "pip show myapp"
  negative-paths:
    - trigger: "pyproject.toml absent"
      handler: "escalate"
- step: 2
  why: "Scaffold (out of order for test)."
  action: "write pyproject.toml"
  verification: "test -f pyproject.toml"
  produces:
    - "file:pyproject.toml"
  negative-paths:
    - trigger: "disk full"
      handler: "escalate"
"""


def test_no_ipm_when_path_covered_by_later_step_produces_returns_empty():
    # The check looks across ALL steps (not just prior ones).
    p = _write_spec(_WITH_LATER_PRODUCER_YAML)
    try:
        fs = spec_ast.classify(p)
        assert not any(f.kind == IPM for f in fs)
    finally:
        p.unlink(missing_ok=True)


# ── Environmental trigger passthrough ─────────────────────────────────────────

_PORT_YAML = """\
- step: 1
  why: "Start server."
  action: "python3 -m myapp.server"
  verification: "curl localhost:8000/healthz"
  produces:
    - "package:myapp"
  negative-paths:
    - trigger: "port 8000 in use"
      handler: "escalate"
"""

_ENVVAR_YAML = """\
- step: 1
  why: "Start server."
  action: "python3 -m myapp.server"
  verification: "curl localhost:8000/healthz"
  produces:
    - "package:myapp"
  negative-paths:
    - trigger: "DEEPSEEK_API_KEY missing"
      handler: "escalate"
"""

_WAL_YAML = """\
- step: 1
  why: "Start server."
  action: "python3 -m myapp.server"
  verification: "curl localhost:8000/healthz"
  produces:
    - "package:myapp"
  negative-paths:
    - trigger: "WAL mode rejected"
      handler: "escalate"
"""


def test_env_port_in_use_trigger_no_ipm_returns_empty():
    p = _write_spec(_PORT_YAML)
    try:
        fs = spec_ast.classify(p)
        assert not any(f.kind == IPM for f in fs)
    finally:
        p.unlink(missing_ok=True)


def test_env_var_missing_trigger_no_ipm_returns_empty():
    p = _write_spec(_ENVVAR_YAML)
    try:
        fs = spec_ast.classify(p)
        assert not any(f.kind == IPM for f in fs)
    finally:
        p.unlink(missing_ok=True)


def test_wal_mode_trigger_no_ipm_returns_empty():
    p = _write_spec(_WAL_YAML)
    try:
        fs = spec_ast.classify(p)
        assert not any(f.kind == IPM for f in fs)
    finally:
        p.unlink(missing_ok=True)


# ── Directory-shaped token ────────────────────────────────────────────────────

_DIR_NO_PRODUCER_YAML = """\
- step: 1
  why: "Write state."
  action: "python3 -m myapp.writer"
  verification: "test -d state/"
  negative-paths:
    - trigger: "state/ not writable"
      handler: "escalate"
"""

_DIR_WITH_PRODUCER_YAML = """\
- step: 0
  why: "Create state dir."
  action: "mkdir -p state"
  verification: "test -d state"
  produces:
    - "file:/abs/state"
  negative-paths:
    - trigger: "disk full"
      handler: "escalate"
- step: 1
  why: "Write state."
  action: "python3 -m myapp.writer"
  verification: "test -d state/"
  produces:
    - "package:myapp"
  negative-paths:
    - trigger: "state/ not writable"
      handler: "escalate"
"""


def test_directory_token_emits_ipm_when_not_produced():
    p = _write_spec(_DIR_NO_PRODUCER_YAML)
    try:
        fs = spec_ast.classify(p)
        f = next((x for x in fs if x.kind == IPM), None)
        assert f is not None
    finally:
        p.unlink(missing_ok=True)


def test_directory_token_no_ipm_when_produced_returns_empty():
    p = _write_spec(_DIR_WITH_PRODUCER_YAML)
    try:
        fs = spec_ast.classify(p)
        assert not any(f.kind == IPM for f in fs)
    finally:
        p.unlink(missing_ok=True)


# ── Multiple steps / multiple findings ────────────────────────────────────────

_MULTI_STEP_YAML = """\
- step: 1
  why: "Install."
  action: "pip install -e ."
  verification: "pip show myapp"
  negative-paths:
    - trigger: "pyproject.toml absent"
      handler: "escalate"
- step: 2
  why: "Build."
  action: "cargo build"
  verification: "test -f target/debug/myapp"
  negative-paths:
    - trigger: "Cargo.toml missing"
      handler: "escalate"
"""


def test_multi_step_ipm_count_is_two():
    p = _write_spec(_MULTI_STEP_YAML)
    try:
        fs = spec_ast.classify(p)
        ipm = [f for f in fs if f.kind == IPM]
        assert len(ipm) == 2
    finally:
        p.unlink(missing_ok=True)


def test_multi_step_ipm_step_numbers_are_1_and_2():
    p = _write_spec(_MULTI_STEP_YAML)
    try:
        fs = spec_ast.classify(p)
        ipm = [f for f in fs if f.kind == IPM]
        steps = {f.location.step for f in ipm}
        assert steps == {1, 2}
    finally:
        p.unlink(missing_ok=True)


# ── Path with slash token ─────────────────────────────────────────────────────

_SLASH_PATH_YAML = """\
- step: 1
  why: "Run migration."
  action: "python3 -m myapp.migrate"
  verification: "test -f db/state.db"
  negative-paths:
    - trigger: "db/state.db not found"
      handler: "escalate"
"""


def test_slash_path_noun_emits_ipm_finding():
    p = _write_spec(_SLASH_PATH_YAML)
    try:
        fs = spec_ast.classify(p)
        f = next((x for x in fs if x.kind == IPM), None)
        assert f is not None
    finally:
        p.unlink(missing_ok=True)


def test_slash_path_ipm_message_names_the_path():
    p = _write_spec(_SLASH_PATH_YAML)
    try:
        fs = spec_ast.classify(p)
        f = next(x for x in fs if x.kind == IPM)
        assert "db/state.db" in f.message
    finally:
        p.unlink(missing_ok=True)


# ── Bare-name files (no extension, no slash) ──────────────────────────────────

_MAKEFILE_ABSENT_YAML = """\
- step: 1
  why: "Build the project."
  action: "make all"
  verification: "test -f bin/myapp"
  negative-paths:
    - trigger: "Makefile absent"
      handler: "escalate"
"""

_DOCKERFILE_MISSING_YAML = """\
- step: 1
  why: "Build the image."
  action: "docker build -t myapp ."
  verification: "docker images | grep myapp"
  negative-paths:
    - trigger: "Dockerfile missing"
      handler: "escalate"
"""

_GO_MOD_ABSENT_YAML = """\
- step: 1
  why: "Build the Go binary."
  action: "go build ./..."
  verification: "test -f bin/myapp"
  negative-paths:
    - trigger: "go.mod absent"
      handler: "escalate"
"""

_GEMFILE_MISSING_YAML = """\
- step: 1
  why: "Install Ruby gems."
  action: "bundle install"
  verification: "bundle exec ruby -e 'puts :ok'"
  negative-paths:
    - trigger: "Gemfile missing"
      handler: "escalate"
"""


def test_bare_name_makefile_absent_emits_ipm():
    p = _write_spec(_MAKEFILE_ABSENT_YAML)
    try:
        fs = spec_ast.classify(p)
        f = next((x for x in fs if x.kind == IPM), None)
        assert f is not None
    finally:
        p.unlink(missing_ok=True)


def test_bare_name_dockerfile_missing_emits_ipm():
    p = _write_spec(_DOCKERFILE_MISSING_YAML)
    try:
        fs = spec_ast.classify(p)
        f = next((x for x in fs if x.kind == IPM), None)
        assert f is not None
    finally:
        p.unlink(missing_ok=True)


def test_bare_name_go_mod_absent_emits_ipm():
    p = _write_spec(_GO_MOD_ABSENT_YAML)
    try:
        fs = spec_ast.classify(p)
        f = next((x for x in fs if x.kind == IPM), None)
        assert f is not None
    finally:
        p.unlink(missing_ok=True)


def test_bare_name_gemfile_missing_emits_ipm():
    p = _write_spec(_GEMFILE_MISSING_YAML)
    try:
        fs = spec_ast.classify(p)
        f = next((x for x in fs if x.kind == IPM), None)
        assert f is not None
    finally:
        p.unlink(missing_ok=True)


def test_bare_noun_not_in_list_no_ipm_returns_empty():
    # "database" is not in _PRECOND_BARE_NAMES and has no suffix/slash
    yaml = """\
- step: 1
  why: "Run query."
  action: "python3 -m myapp.query"
  verification: "echo done"
  produces:
    - "package:myapp"
  negative-paths:
    - trigger: "database missing"
      handler: "escalate"
"""
    p = _write_spec(yaml)
    try:
        fs = spec_ast.classify(p)
        assert not any(f.kind == IPM for f in fs)
    finally:
        p.unlink(missing_ok=True)


# ── Verb-first trigger phrasings ──────────────────────────────────────────────

_VERB_FIRST_MISSING_YAML = """\
- step: 1
  why: "Install the package."
  action: "pip install -e ."
  verification: "pip show myapp"
  negative-paths:
    - trigger: "missing pyproject.toml"
      handler: "escalate"
"""

_VERB_FIRST_CANNOT_FIND_YAML = """\
- step: 1
  why: "Build the project."
  action: "make all"
  verification: "test -f bin/myapp"
  negative-paths:
    - trigger: "cannot find Makefile"
      handler: "escalate"
"""


def test_verb_first_missing_pyproject_emits_ipm():
    p = _write_spec(_VERB_FIRST_MISSING_YAML)
    try:
        fs = spec_ast.classify(p)
        f = next((x for x in fs if x.kind == IPM), None)
        assert f is not None
    finally:
        p.unlink(missing_ok=True)


def test_verb_first_cannot_find_makefile_emits_ipm():
    p = _write_spec(_VERB_FIRST_CANNOT_FIND_YAML)
    try:
        fs = spec_ast.classify(p)
        f = next((x for x in fs if x.kind == IPM), None)
        assert f is not None
    finally:
        p.unlink(missing_ok=True)
