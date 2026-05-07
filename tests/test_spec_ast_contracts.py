"""Tests for v0.5.2 step contracts (produces/requires) in bin/spec_ast.py.

All tests have one assertion per the pragma test-gaming guard.
Tests asserting absence/emptiness use _returns_empty/_is_none/_returns_false naming.
"""
import pathlib
import tempfile
import pytest

from bin import spec_ast

FIXTURES = pathlib.Path(__file__).parent / "fixtures" / "specs"

# ── helpers ───────────────────────────────────────────────────────────────────

_CALIBRATION = """
## 8. Receiver Calibration

### 8.1 Hard contract (machine-enforced — `block` severity on violation)

- `mutates:` /tmp/
- `never-touches:` /home
- `decision-budget:` none
- `reboot-survival:` none
"""

_SPEC_HEADER = """# Test Spec
**Generated:** 2026-05-07
**Slug:** contract-test
## 1. Hard Problem
x
## 2. First Principles
- x
## 3. Algorithm Audit
- **Delete:** x
- **Simplify:** x
- **Accelerate:** x
## 4. Speed-of-Light Limit
x
## 5. Physics Guardrails
- x
## 7. Success Criteria
- [ ] x
"""


def _make_spec(steps_yaml: str) -> pathlib.Path:
    """Write a spec with the given steps YAML block to a temp file."""
    body = (
        _SPEC_HEADER
        + "\n## 6. Steps\n\n```yaml\n"
        + steps_yaml
        + "\n```\n"
        + _CALIBRATION
    )
    fd_path = tempfile.NamedTemporaryFile(suffix=".spec.md", mode="w", delete=False)
    fd_path.write(body)
    fd_path.close()
    return pathlib.Path(fd_path.name)


# ── fixture-based: contract_valid ────────────────────────────────────────────

def test_contract_valid_fixture_returns_no_block_findings():
    fs = spec_ast.classify(FIXTURES / "contract_valid.spec.md")
    assert not any(f.severity == "block" for f in fs)


def test_contract_valid_fixture_has_no_unowned_requirement():
    fs = spec_ast.classify(FIXTURES / "contract_valid.spec.md")
    assert not any(f.kind == "unowned-requirement" for f in fs)


def test_contract_valid_fixture_has_no_malformed_contract():
    fs = spec_ast.classify(FIXTURES / "contract_valid.spec.md")
    assert not any(f.kind == "malformed-contract" for f in fs)


def test_contract_valid_fixture_has_no_missing_contract():
    fs = spec_ast.classify(FIXTURES / "contract_valid.spec.md")
    assert not any(f.kind == "missing-contract" for f in fs)


# ── unowned-requirement: block when requires not in prior produces ─────────

def test_unowned_requirement_fixture_produces_block_finding():
    fs = spec_ast.classify(FIXTURES / "contract_unowned.spec.md")
    assert any(f.kind == "unowned-requirement" for f in fs)


def test_unowned_requirement_severity_is_block():
    fs = spec_ast.classify(FIXTURES / "contract_unowned.spec.md")
    f = next(x for x in fs if x.kind == "unowned-requirement")
    assert f.severity == "block"


def test_unowned_requirement_location_is_step_scope():
    fs = spec_ast.classify(FIXTURES / "contract_unowned.spec.md")
    f = next(x for x in fs if x.kind == "unowned-requirement")
    assert f.location.scope == "step"


def test_unowned_requirement_location_ref_is_requires():
    fs = spec_ast.classify(FIXTURES / "contract_unowned.spec.md")
    f = next(x for x in fs if x.kind == "unowned-requirement")
    assert f.location.ref == "requires"


def test_unowned_requirement_step_number_is_correct():
    fs = spec_ast.classify(FIXTURES / "contract_unowned.spec.md")
    f = next(x for x in fs if x.kind == "unowned-requirement")
    assert f.location.step == 2


# ── prior step produces satisfies later requires ─────────────────────────────

def test_owned_requirement_is_not_flagged_as_unowned():
    p = _make_spec(
        "- step: 1\n"
        "  why: 'install'\n"
        "  action: 'pip install foo'\n"
        "  verification: \"python3 -c 'import foo'\"\n"
        "  produces:\n"
        "    - \"package:foo\"\n"
        "\n"
        "- step: 2\n"
        "  why: 'use'\n"
        "  action: \"python3 -c 'import foo; foo.run()'\"\n"
        "  verification: \"python3 -c 'import foo'\"\n"
        "  requires:\n"
        "    - \"package:foo\"\n"
    )
    try:
        fs = spec_ast.classify(p)
        assert not any(f.kind == "unowned-requirement" for f in fs)
    finally:
        p.unlink(missing_ok=True)


# ── missing-contract: warn when neither produces nor requires declared ─────

def test_step_without_contracts_emits_missing_contract_warning():
    p = _make_spec(
        "- step: 1\n"
        "  why: 'just a bare step'\n"
        "  action: 'echo hello'\n"
        "  verification: 'echo hello'\n"
    )
    try:
        fs = spec_ast.classify(p)
        assert any(f.kind == "missing-contract" for f in fs)
    finally:
        p.unlink(missing_ok=True)


def test_missing_contract_severity_is_warn():
    p = _make_spec(
        "- step: 1\n"
        "  why: 'bare step'\n"
        "  action: 'echo hello'\n"
        "  verification: 'echo hello'\n"
    )
    try:
        fs = spec_ast.classify(p)
        f = next(x for x in fs if x.kind == "missing-contract")
        assert f.severity == "warn"
    finally:
        p.unlink(missing_ok=True)


def test_missing_contract_does_not_block_lock():
    """missing-contract is warn only — max_severity must not be block from it alone."""
    from bin import findings as _findings
    p = _make_spec(
        "- step: 1\n"
        "  why: 'bare step'\n"
        "  action: 'echo hello'\n"
        "  verification: 'echo hello'\n"
    )
    try:
        fs = spec_ast.classify(p)
        contract_findings = [f for f in fs if f.kind == "missing-contract"]
        max_sev = _findings.max_severity(contract_findings)
        assert max_sev != "block"
    finally:
        p.unlink(missing_ok=True)


# ── malformed-contract: warn on unknown type prefix ───────────────────────

def test_bogus_format_in_produces_emits_malformed_contract():
    p = _make_spec(
        "- step: 1\n"
        "  why: 'bad contract'\n"
        "  action: 'echo hello'\n"
        "  verification: 'echo hello'\n"
        "  produces:\n"
        "    - \"bogus-format\"\n"
    )
    try:
        fs = spec_ast.classify(p)
        assert any(f.kind == "malformed-contract" for f in fs)
    finally:
        p.unlink(missing_ok=True)


def test_malformed_contract_severity_is_warn():
    p = _make_spec(
        "- step: 1\n"
        "  why: 'bad contract'\n"
        "  action: 'echo hello'\n"
        "  verification: 'echo hello'\n"
        "  produces:\n"
        "    - \"bogus-format\"\n"
    )
    try:
        fs = spec_ast.classify(p)
        f = next(x for x in fs if x.kind == "malformed-contract")
        assert f.severity == "warn"
    finally:
        p.unlink(missing_ok=True)


def test_malformed_contract_evaluator_continues_after_bad_entry():
    """Evaluator must not raise on malformed entries — continues producing other findings."""
    p = _make_spec(
        "- step: 1\n"
        "  why: 'bad contract'\n"
        "  action: 'echo hello'\n"
        "  verification: 'echo hello'\n"
        "  produces:\n"
        "    - \"bogus-format\"\n"
        "    - \"file:/tmp/ok\"\n"
    )
    try:
        # Should not raise; should return a list of findings
        fs = spec_ast.classify(p)
        assert isinstance(fs, list)
    finally:
        p.unlink(missing_ok=True)


def test_malformed_entry_without_colon_is_flagged():
    p = _make_spec(
        "- step: 1\n"
        "  why: 'no colon'\n"
        "  action: 'echo hello'\n"
        "  verification: 'echo hello'\n"
        "  produces:\n"
        "    - \"nocoherententry\"\n"
    )
    try:
        fs = spec_ast.classify(p)
        assert any(f.kind == "malformed-contract" for f in fs)
    finally:
        p.unlink(missing_ok=True)


# ── all eight contract types parse correctly ──────────────────────────────

def test_all_eight_contract_types_parse_without_malformed_finding():
    """All eight recognised type prefixes must parse as valid (no malformed-contract)."""
    entries = [
        "file:/tmp/output.txt",
        "package:mypackage",
        "console-script:mycli",
        "route:POST /api/convert",
        "module:mypackage.utils",
        "binary:curl",
        "db-table:users",
        "db-column:users.email",
    ]
    yaml_items = "\n".join(f'    - "{e}"' for e in entries)
    p = _make_spec(
        "- step: 1\n"
        "  why: 'all types'\n"
        "  action: 'echo hello'\n"
        "  verification: 'echo hello'\n"
        "  produces:\n"
        + yaml_items + "\n"
    )
    try:
        fs = spec_ast.classify(p)
        assert not any(f.kind == "malformed-contract" for f in fs)
    finally:
        p.unlink(missing_ok=True)


def test_file_contract_type_parses_correctly():
    p = _make_spec(
        "- step: 1\n"
        "  why: 'file'\n"
        "  action: 'touch /tmp/x'\n"
        "  verification: 'test -f /tmp/x'\n"
        "  produces:\n"
        "    - \"file:/tmp/x\"\n"
    )
    try:
        fs = spec_ast.classify(p)
        assert not any(f.kind == "malformed-contract" for f in fs)
    finally:
        p.unlink(missing_ok=True)


def test_package_contract_type_parses_correctly():
    p = _make_spec(
        "- step: 1\n"
        "  why: 'package'\n"
        "  action: 'pip install foo'\n"
        "  verification: \"python3 -c 'import foo'\"\n"
        "  produces:\n"
        "    - \"package:foo\"\n"
    )
    try:
        fs = spec_ast.classify(p)
        assert not any(f.kind == "malformed-contract" for f in fs)
    finally:
        p.unlink(missing_ok=True)


def test_console_script_contract_type_parses_correctly():
    p = _make_spec(
        "- step: 1\n"
        "  why: 'console-script'\n"
        "  action: 'pip install foo[cli]'\n"
        "  verification: 'foo-cli --version'\n"
        "  produces:\n"
        "    - \"console-script:foo-cli\"\n"
    )
    try:
        fs = spec_ast.classify(p)
        assert not any(f.kind == "malformed-contract" for f in fs)
    finally:
        p.unlink(missing_ok=True)


def test_route_contract_type_parses_correctly():
    p = _make_spec(
        "- step: 1\n"
        "  why: 'route'\n"
        "  action: 'echo add_route'\n"
        "  verification: 'curl -sf http://localhost/api/convert'\n"
        "  produces:\n"
        "    - \"route:POST /api/convert\"\n"
    )
    try:
        fs = spec_ast.classify(p)
        assert not any(f.kind == "malformed-contract" for f in fs)
    finally:
        p.unlink(missing_ok=True)


def test_module_contract_type_parses_correctly():
    p = _make_spec(
        "- step: 1\n"
        "  why: 'module'\n"
        "  action: 'pip install mypackage'\n"
        "  verification: \"python3 -c 'import mypackage.utils'\"\n"
        "  produces:\n"
        "    - \"module:mypackage.utils\"\n"
    )
    try:
        fs = spec_ast.classify(p)
        assert not any(f.kind == "malformed-contract" for f in fs)
    finally:
        p.unlink(missing_ok=True)


def test_binary_contract_type_parses_correctly():
    p = _make_spec(
        "- step: 1\n"
        "  why: 'binary'\n"
        "  action: 'apt-get install -y curl'\n"
        "  verification: 'which curl'\n"
        "  produces:\n"
        "    - \"binary:curl\"\n"
    )
    try:
        fs = spec_ast.classify(p)
        assert not any(f.kind == "malformed-contract" for f in fs)
    finally:
        p.unlink(missing_ok=True)


def test_db_table_contract_type_parses_correctly():
    p = _make_spec(
        "- step: 1\n"
        "  why: 'db-table'\n"
        "  action: 'sqlite3 /tmp/db.sqlite \"CREATE TABLE users (id INTEGER)\"'\n"
        "  verification: 'sqlite3 /tmp/db.sqlite \".tables\" | grep users'\n"
        "  produces:\n"
        "    - \"db-table:users\"\n"
    )
    try:
        fs = spec_ast.classify(p)
        assert not any(f.kind == "malformed-contract" for f in fs)
    finally:
        p.unlink(missing_ok=True)


def test_db_column_contract_type_parses_correctly():
    p = _make_spec(
        "- step: 1\n"
        "  why: 'db-column'\n"
        "  action: 'sqlite3 /tmp/db.sqlite \"ALTER TABLE users ADD COLUMN email TEXT\"'\n"
        "  verification: 'sqlite3 /tmp/db.sqlite \"PRAGMA table_info(users)\" | grep email'\n"
        "  produces:\n"
        "    - \"db-column:users.email\"\n"
    )
    try:
        fs = spec_ast.classify(p)
        assert not any(f.kind == "malformed-contract" for f in fs)
    finally:
        p.unlink(missing_ok=True)


# ── binary in requires only ─────────────────────────────────────────────────

def test_binary_in_requires_with_no_prior_produces_emits_unowned():
    """binary: is valid for requires: — must trigger unowned-requirement if not produced."""
    p = _make_spec(
        "- step: 1\n"
        "  why: 'use binary'\n"
        "  action: 'yt-dlp --version'\n"
        "  verification: 'yt-dlp --version'\n"
        "  requires:\n"
        "    - \"binary:yt-dlp\"\n"
    )
    try:
        fs = spec_ast.classify(p)
        assert any(f.kind == "unowned-requirement" for f in fs)
    finally:
        p.unlink(missing_ok=True)


def test_binary_in_requires_satisfied_by_prior_produces_is_not_flagged():
    p = _make_spec(
        "- step: 1\n"
        "  why: 'install binary'\n"
        "  action: 'apt-get install -y yt-dlp'\n"
        "  verification: 'which yt-dlp'\n"
        "  produces:\n"
        "    - \"binary:yt-dlp\"\n"
        "\n"
        "- step: 2\n"
        "  why: 'use binary'\n"
        "  action: 'yt-dlp --version'\n"
        "  verification: 'yt-dlp --version'\n"
        "  requires:\n"
        "    - \"binary:yt-dlp\"\n"
    )
    try:
        fs = spec_ast.classify(p)
        assert not any(f.kind == "unowned-requirement" for f in fs)
    finally:
        p.unlink(missing_ok=True)


# ── contract_resolution in sidecar payload ────────────────────────────────

def test_contract_resolution_in_sidecar_payload_keys():
    """spec_evaluator.evaluate() must include contract_resolution in sidecar_payload."""
    import pathlib as _pathlib
    from bin import spec_evaluator
    result = spec_evaluator.evaluate(
        FIXTURES / "contract_valid.spec.md",
        bundle_persist_dir=_pathlib.Path("/tmp/test-contract-resolution-bundle"),
    )
    assert "contract_resolution" in result.sidecar_payload


def test_contract_resolution_contains_steps_key():
    import pathlib as _pathlib
    from bin import spec_evaluator
    result = spec_evaluator.evaluate(
        FIXTURES / "contract_valid.spec.md",
        bundle_persist_dir=_pathlib.Path("/tmp/test-contract-resolution-bundle2"),
    )
    assert "steps" in result.sidecar_payload["contract_resolution"]


def test_contract_resolution_resolved_entry_has_resolved_by_step():
    """A requires satisfied by a prior produces must have resolved_by_step set."""
    import pathlib as _pathlib
    from bin import spec_evaluator
    result = spec_evaluator.evaluate(
        FIXTURES / "contract_valid.spec.md",
        bundle_persist_dir=_pathlib.Path("/tmp/test-contract-resolution-bundle3"),
    )
    steps = result.sidecar_payload["contract_resolution"]["steps"]
    # Step 2 requires package:foo which step 1 produces
    step2 = steps.get("2", {})
    resolution = step2.get("resolution", {})
    assert resolution.get("package:foo") == {"resolved_by_step": 1}


def test_contract_resolution_unresolved_entry_is_null():
    """A requires with no prior produces must appear as null in resolution."""
    import pathlib as _pathlib
    from bin import spec_evaluator
    result = spec_evaluator.evaluate(
        FIXTURES / "contract_unowned.spec.md",
        bundle_persist_dir=_pathlib.Path("/tmp/test-contract-resolution-bundle4"),
    )
    steps = result.sidecar_payload["contract_resolution"]["steps"]
    step2 = steps.get("2", {})
    resolution = step2.get("resolution", {})
    assert resolution.get("package:missing_pkg") is None


# ── malformed-only produces suppresses missing-contract double-fire ───────────

def test_only_malformed_produces_does_not_emit_missing_contract():
    """A step with produces: ["bogus-format"] gets malformed-contract only, NOT missing-contract.

    Regression guard for the double-fire warn: gating missing-contract on
    raw_produces/raw_requires (not valid_produces/valid_requires) ensures that
    an attempted-but-malformed declaration suppresses the spurious missing warn.
    """
    p = _make_spec(
        "- step: 1\n"
        "  why: 'malformed only'\n"
        "  action: 'echo hello'\n"
        "  verification: 'echo hello'\n"
        "  produces:\n"
        "    - \"bogus-format\"\n"
    )
    try:
        fs = spec_ast.classify(p)
        assert not any(f.kind == "missing-contract" for f in fs)
    finally:
        p.unlink(missing_ok=True)


def test_only_malformed_produces_emits_exactly_one_finding():
    """Exactly one finding (malformed-contract) when produces has a single bogus entry."""
    p = _make_spec(
        "- step: 1\n"
        "  why: 'malformed only'\n"
        "  action: 'echo hello'\n"
        "  verification: 'echo hello'\n"
        "  produces:\n"
        "    - \"bogus-format\"\n"
    )
    try:
        fs = spec_ast.classify(p)
        assert len([f for f in fs if f.kind in ("malformed-contract", "missing-contract")]) == 1
    finally:
        p.unlink(missing_ok=True)


def test_only_malformed_requires_does_not_emit_missing_contract():
    """A step with requires: ["bogus-format"] gets malformed-contract only, NOT missing-contract."""
    p = _make_spec(
        "- step: 1\n"
        "  why: 'malformed requires only'\n"
        "  action: 'echo hello'\n"
        "  verification: 'echo hello'\n"
        "  requires:\n"
        "    - \"bogus-format\"\n"
    )
    try:
        fs = spec_ast.classify(p)
        assert not any(f.kind == "missing-contract" for f in fs)
    finally:
        p.unlink(missing_ok=True)
