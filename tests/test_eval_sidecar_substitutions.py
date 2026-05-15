"""Eval sidecar substitution log (v1.2.1 #6).

`write_sidecar(substitutions=...)` writes a `substitutions: [...]` array to
the sidecar payload as contemporaneous evidence of agent rewrites that
satisfied Tier-1 checks. Empty when no rewrite happened; populated when
rewrites did happen. Not a finding — auditable evidence.
"""
import json
import pathlib

from bin import eval_metadata


def test_118_substitutions_omitted_when_none(tmp_path: pathlib.Path):
    spec = tmp_path / "x.spec.md"
    spec.write_text("# x\n", encoding="utf-8")
    returned = eval_metadata.write_sidecar(
        spec,
        evaluator_version="1.0.0",
        tiers_run=[1],
        findings=[],
        dismissals=[],
        config_path=None,
        config_hash=None,
        deepseek_model_version=None,
        policy_hash="abc123",
        substitutions=None,
    )
    assert returned.exists() and returned.name == "x.spec.md.eval.json"
    payload = json.loads(returned.read_text(encoding="utf-8"))
    assert "substitutions" not in payload


def test_119_substitutions_empty_list_written_as_empty(tmp_path: pathlib.Path):
    spec = tmp_path / "x.spec.md"
    spec.write_text("# x\n", encoding="utf-8")
    returned = eval_metadata.write_sidecar(
        spec,
        evaluator_version="1.0.0",
        tiers_run=[1],
        findings=[],
        dismissals=[],
        config_path=None,
        config_hash=None,
        deepseek_model_version=None,
        policy_hash="abc123",
        substitutions=[],
    )
    assert returned.exists()
    payload = json.loads(returned.read_text(encoding="utf-8"))
    assert payload["substitutions"] == []


def test_120_substitutions_populated_round_trips(tmp_path: pathlib.Path):
    spec = tmp_path / "x.spec.md"
    spec.write_text("# x\n", encoding="utf-8")
    entry = {
        "from": "python3 -c 'import x'",
        "to": "pip show x | grep -q 'Name: x'",
        "reason": "Tier-1 _SHELL_EVAL_RE false-positive workaround",
        "tier1_check_name": "untrusted-flow-unguarded",
        "step_id": "step-3",
    }
    returned = eval_metadata.write_sidecar(
        spec,
        evaluator_version="1.0.0",
        tiers_run=[1],
        findings=[],
        dismissals=[],
        config_path=None,
        config_hash=None,
        deepseek_model_version=None,
        policy_hash="abc123",
        substitutions=[entry],
    )
    assert returned.exists()
    payload = json.loads(returned.read_text(encoding="utf-8"))
    assert payload["substitutions"] == [entry]


def test_121_substitutions_multiple_entries_preserved_in_order(
    tmp_path: pathlib.Path,
):
    spec = tmp_path / "x.spec.md"
    spec.write_text("# x\n", encoding="utf-8")
    entries = [
        {
            "from": "tee /etc/x", "to": "tee state/x",
            "reason": "out-of-root", "tier1_check_name": "self-cycle-produces",
            "step_id": "step-1",
        },
        {
            "from": "bash -c 'echo'", "to": "echo hi",
            "reason": "simplify", "tier1_check_name": "soft-verification",
            "step_id": "step-2",
        },
    ]
    returned = eval_metadata.write_sidecar(
        spec,
        evaluator_version="1.0.0",
        tiers_run=[1],
        findings=[],
        dismissals=[],
        config_path=None,
        config_hash=None,
        deepseek_model_version=None,
        policy_hash="abc123",
        substitutions=entries,
    )
    assert returned.exists()
    payload = json.loads(returned.read_text(encoding="utf-8"))
    assert payload["substitutions"] == entries
    assert len(payload["substitutions"]) == 2
