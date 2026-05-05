"""State Auditor + PBT-lite tests."""
import json
from pathlib import Path

import pytest

from bin import auditor


def test_audit_path_exists_passes(tmp_path):
    p = tmp_path / "foo.txt"
    p.write_text("hi")
    results = auditor.audit_action(
        f"touch {p}", paths_touched=[str(p)], properties=None
    )
    assert any(r.kind == "path_exists" and r.passed for r in results)


def test_audit_path_exists_fails(tmp_path):
    p = tmp_path / "missing.txt"
    results = auditor.audit_action(
        f"touch {p}", paths_touched=[str(p)], properties=None
    )
    fails = [r for r in results if r.kind == "path_exists" and not r.passed]
    assert len(fails) == 1


def test_audit_json_parses_for_dot_json_path(tmp_path):
    p = tmp_path / "out.json"
    p.write_text('{"k": 1}')
    results = auditor.audit_action(
        f"echo {{}} > {p}", paths_touched=[str(p)], properties=None
    )
    assert any(r.kind == "json_parses" and r.passed for r in results)


def test_audit_json_parses_fails_on_bad_json(tmp_path):
    p = tmp_path / "out.json"
    p.write_text("not json {")
    results = auditor.audit_action(
        f"echo {{}} > {p}", paths_touched=[str(p)], properties=None
    )
    fails = [r for r in results if r.kind == "json_parses" and not r.passed]
    assert len(fails) == 1


def test_audit_python_ast_parses_for_dot_py_path(tmp_path):
    p = tmp_path / "ok.py"
    p.write_text("x = 1\ndef foo():\n    return x\n")
    results = auditor.audit_action(
        f"python3 {p}", paths_touched=[str(p)], properties=None
    )
    assert any(r.kind == "python_ast_parses" and r.passed for r in results)


def test_audit_python_ast_parses_fails_on_syntax_error(tmp_path):
    p = tmp_path / "bad.py"
    p.write_text("def (no_name:\n")
    results = auditor.audit_action(
        f"python3 {p}", paths_touched=[str(p)], properties=None
    )
    fails = [r for r in results if r.kind == "python_ast_parses" and not r.passed]
    assert len(fails) == 1


def test_audit_noop_when_no_paths_and_no_properties():
    results = auditor.audit_action("echo hi", paths_touched=[], properties=None)
    assert len(results) == 1
    assert results[0].kind == "noop"


def test_pbt_type_check_passes(tmp_path):
    p = tmp_path / "data.json"
    p.write_text('{"k": 1}')
    props = [{"kind": "type", "target": str(p), "expected": "dict"}]
    results = auditor.audit_action(
        f"echo {{}} > {p}", paths_touched=[str(p)], properties=props
    )
    type_results = [r for r in results if r.kind == "type"]
    assert len(type_results) == 1
    assert type_results[0].passed


def test_pbt_type_check_fails_on_wrong_type(tmp_path):
    p = tmp_path / "data.json"
    p.write_text("[1, 2, 3]")
    props = [{"kind": "type", "target": str(p), "expected": "dict"}]
    results = auditor.audit_action(
        f"echo [] > {p}", paths_touched=[str(p)], properties=props
    )
    type_results = [r for r in results if r.kind == "type"]
    assert len(type_results) == 1
    assert not type_results[0].passed


def test_pbt_length_check_passes(tmp_path):
    p = tmp_path / "data.json"
    p.write_text('{"rows": [1, 2, 3]}')
    props = [{"kind": "length", "target": str(p), "target_field": "rows", "min": 1, "max": 10}]
    results = auditor.audit_action(
        f"echo {{}} > {p}", paths_touched=[str(p)], properties=props
    )
    length_results = [r for r in results if r.kind == "length"]
    assert len(length_results) == 1
    assert length_results[0].passed


def test_pbt_length_check_fails_below_min(tmp_path):
    p = tmp_path / "data.json"
    p.write_text('{"rows": []}')
    props = [{"kind": "length", "target": str(p), "target_field": "rows", "min": 1, "max": 10}]
    results = auditor.audit_action(
        f"echo {{}} > {p}", paths_touched=[str(p)], properties=props
    )
    length_results = [r for r in results if r.kind == "length"]
    assert len(length_results) == 1
    assert not length_results[0].passed


def test_pbt_length_check_fails_above_max(tmp_path):
    p = tmp_path / "data.json"
    p.write_text('{"rows": [1,2,3,4,5,6,7,8,9,10,11]}')
    props = [{"kind": "length", "target": str(p), "target_field": "rows", "min": 1, "max": 10}]
    results = auditor.audit_action(
        f"echo {{}} > {p}", paths_touched=[str(p)], properties=props
    )
    length_results = [r for r in results if r.kind == "length"]
    assert len(length_results) == 1
    assert not length_results[0].passed


def test_pbt_range_check_passes(tmp_path):
    p = tmp_path / "data.json"
    p.write_text('{"price_usd": 50000}')
    props = [{"kind": "range", "target": str(p), "target_field": "price_usd", "min": 0, "max": 1000000}]
    results = auditor.audit_action(
        f"echo {{}} > {p}", paths_touched=[str(p)], properties=props
    )
    range_results = [r for r in results if r.kind == "range"]
    assert len(range_results) == 1
    assert range_results[0].passed


def test_pbt_range_check_fails_outside_range(tmp_path):
    p = tmp_path / "data.json"
    p.write_text('{"price_usd": -5}')
    props = [{"kind": "range", "target": str(p), "target_field": "price_usd", "min": 0, "max": 1000000}]
    results = auditor.audit_action(
        f"echo {{}} > {p}", paths_touched=[str(p)], properties=props
    )
    range_results = [r for r in results if r.kind == "range"]
    assert len(range_results) == 1
    assert not range_results[0].passed


def test_pbt_schema_check_passes_when_keys_present(tmp_path):
    p = tmp_path / "data.json"
    p.write_text('{"a": 1, "b": 2, "c": 3}')
    props = [{"kind": "schema", "target": str(p), "required_keys": ["a", "b"]}]
    results = auditor.audit_action(
        f"echo {{}} > {p}", paths_touched=[str(p)], properties=props
    )
    schema_results = [r for r in results if r.kind == "schema"]
    assert len(schema_results) == 1
    assert schema_results[0].passed


def test_pbt_schema_check_fails_when_key_missing(tmp_path):
    p = tmp_path / "data.json"
    p.write_text('{"a": 1}')
    props = [{"kind": "schema", "target": str(p), "required_keys": ["a", "b"]}]
    results = auditor.audit_action(
        f"echo {{}} > {p}", paths_touched=[str(p)], properties=props
    )
    schema_results = [r for r in results if r.kind == "schema"]
    assert len(schema_results) == 1
    assert not schema_results[0].passed


def test_audit_returns_dataclass_with_kind_passed_message(tmp_path):
    p = tmp_path / "foo.txt"
    p.write_text("hi")
    results = auditor.audit_action(
        f"touch {p}", paths_touched=[str(p)], properties=None
    )
    assert all(hasattr(r, "kind") for r in results)
    assert all(hasattr(r, "passed") for r in results)
    assert all(hasattr(r, "message") for r in results)


def test_pbt_unknown_kind_returns_failed_result(tmp_path):
    p = tmp_path / "data.json"
    p.write_text("{}")
    props = [{"kind": "magic", "target": str(p)}]
    results = auditor.audit_action(
        f"echo {{}} > {p}", paths_touched=[str(p)], properties=props
    )
    magic_results = [r for r in results if r.kind == "magic"]
    assert len(magic_results) == 1
    assert not magic_results[0].passed
    assert "unknown" in magic_results[0].message.lower()


def test_pbt_length_check_fails_on_string_value(tmp_path):
    p = tmp_path / "data.json"
    p.write_text('{"name": "Alice"}')
    props = [{"kind": "length", "target": str(p), "target_field": "name", "min": 1, "max": 10}]
    results = auditor.audit_action(
        f"echo {{}} > {p}", paths_touched=[str(p)], properties=props
    )
    length_results = [r for r in results if r.kind == "length"]
    assert len(length_results) == 1
    assert not length_results[0].passed
    assert "not list/dict" in length_results[0].message


def test_pbt_length_check_passes_on_dict_value(tmp_path):
    p = tmp_path / "data.json"
    p.write_text('{"obj": {"a": 1, "b": 2}}')
    props = [{"kind": "length", "target": str(p), "target_field": "obj", "min": 1, "max": 5}]
    results = auditor.audit_action(
        f"echo {{}} > {p}", paths_touched=[str(p)], properties=props
    )
    length_results = [r for r in results if r.kind == "length"]
    assert len(length_results) == 1
    assert length_results[0].passed
