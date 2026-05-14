"""CLI tests for bin/eval_metadata.py __main__ entrypoint.

Invokes the module via `python3 -m bin.eval_metadata <subcommand>` as a
subprocess so the CLI is tested end-to-end.

Pragma guard: one assertion per test; no _rejects_/_raises_ without
pytest.raises; no mocked exit.
"""
import hashlib
import json
import pathlib
import subprocess
import sys

import pytest

_CMD = [sys.executable, "-m", "bin.eval_metadata"]
_REPO = pathlib.Path(__file__).parent.parent


def _run(*args, cwd=None, stdin=None):
    return subprocess.run(
        _CMD + list(args),
        capture_output=True,
        text=True,
        cwd=cwd or _REPO,
        input=stdin,
    )


# ── Helpers ───────────────────────────────────────────────────────────────────

def _write_minimal_toml(path: pathlib.Path) -> None:
    path.write_text("[tier3]\nenabled = false\n", encoding="utf-8")


def _make_sidecar_payload(**overrides) -> dict:
    base = {
        "evaluator_version": "0.5.0-rc1",
        "tiers_run": [1, 2],
        "dismissals": [],
        "policy_hash": "deadbeef" * 8,
        "config_path": None,
        "config_hash": None,
        "deepseek_model_version": None,
    }
    base.update(overrides)
    return base


# ── policy-hash ───────────────────────────────────────────────────────────────

class TestPolicyHashCli:
    def test_happy_path_exits_zero(self):
        r = _run("policy-hash")
        assert r.returncode == 0

    def test_output_is_64_hex_chars(self):
        r = _run("policy-hash")
        assert len(r.stdout.strip()) == 64

    def test_output_is_valid_hex(self):
        r = _run("policy-hash")
        int(r.stdout.strip(), 16)  # raises if not hex

    def test_stable_with_empty_config(self):
        r1 = _run("policy-hash")
        r2 = _run("policy-hash")
        assert r1.stdout == r2.stdout

    def test_with_valid_toml_exits_zero(self, tmp_path):
        cfg = tmp_path / "reviewer.toml"
        _write_minimal_toml(cfg)
        r = _run("policy-hash", "--config", str(cfg))
        assert r.returncode == 0

    def test_with_valid_toml_different_from_empty(self, tmp_path):
        cfg = tmp_path / "reviewer.toml"
        cfg.write_text("[tier3]\nenabled = true\n", encoding="utf-8")
        r_with = _run("policy-hash", "--config", str(cfg))
        r_empty = _run("policy-hash")
        assert r_with.stdout.strip() != r_empty.stdout.strip()

    def test_missing_config_exits_1(self, tmp_path):
        r = _run("policy-hash", "--config", str(tmp_path / "no_such.toml"))
        assert r.returncode == 1

    def test_malformed_severity_overrides_exits_1(self):
        r = _run("policy-hash", "--severity-overrides", "not-json")
        assert r.returncode == 1

    def test_malformed_severity_overrides_stderr_nonempty(self):
        r = _run("policy-hash", "--severity-overrides", "not-json")
        assert r.stderr != ""

    def test_with_valid_severity_overrides(self):
        r = _run("policy-hash", "--severity-overrides", '{"missing-why": "block"}')
        assert r.returncode == 0

    def test_stderr_empty_on_success(self):
        r = _run("policy-hash")
        assert r.stderr == ""


# ── sidecar-path ──────────────────────────────────────────────────────────────

class TestSidecarPathCli:
    def test_happy_path_exits_zero(self):
        r = _run("sidecar-path", "--spec", "specs/foo.spec.md")
        assert r.returncode == 0

    def test_output_appends_eval_json(self):
        r = _run("sidecar-path", "--spec", "specs/foo.spec.md")
        assert r.stdout.strip() == "specs/foo.spec.md.eval.json"

    def test_stderr_empty(self):
        r = _run("sidecar-path", "--spec", "specs/any.spec.md")
        assert r.stderr == ""

    def test_missing_spec_flag_exits_2(self):
        r = _run("sidecar-path")
        assert r.returncode == 2


# ── write-sidecar ─────────────────────────────────────────────────────────────

class TestWriteSidecarCli:
    def test_happy_path_via_payload_file_exits_zero(self, tmp_path):
        spec = tmp_path / "foo.spec.md"
        spec.write_text("# spec\n", encoding="utf-8")
        payload_file = tmp_path / "payload.json"
        payload_file.write_text(json.dumps(_make_sidecar_payload()), encoding="utf-8")
        r = _run("write-sidecar", "--spec", str(spec), "--payload", str(payload_file))
        assert r.returncode == 0

    def test_creates_sidecar_file(self, tmp_path):
        spec = tmp_path / "foo.spec.md"
        spec.write_text("# spec\n", encoding="utf-8")
        payload_file = tmp_path / "payload.json"
        payload_file.write_text(json.dumps(_make_sidecar_payload()), encoding="utf-8")
        _run("write-sidecar", "--spec", str(spec), "--payload", str(payload_file))
        assert (tmp_path / "foo.spec.md.eval.json").exists()

    def test_stdout_is_sidecar_path(self, tmp_path):
        spec = tmp_path / "foo.spec.md"
        spec.write_text("# spec\n", encoding="utf-8")
        payload_file = tmp_path / "payload.json"
        payload_file.write_text(json.dumps(_make_sidecar_payload()), encoding="utf-8")
        r = _run("write-sidecar", "--spec", str(spec), "--payload", str(payload_file))
        assert str(tmp_path / "foo.spec.md.eval.json") in r.stdout

    def test_via_stdin_exits_zero(self, tmp_path):
        spec = tmp_path / "bar.spec.md"
        spec.write_text("# spec\n", encoding="utf-8")
        r = _run("write-sidecar", "--spec", str(spec), "--payload", "-",
                 stdin=json.dumps(_make_sidecar_payload()))
        assert r.returncode == 0

    def test_missing_payload_file_exits_1(self, tmp_path):
        spec = tmp_path / "foo.spec.md"
        spec.write_text("# spec\n", encoding="utf-8")
        r = _run("write-sidecar", "--spec", str(spec), "--payload", str(tmp_path / "no.json"))
        assert r.returncode == 1

    def test_malformed_payload_json_exits_1(self, tmp_path):
        spec = tmp_path / "foo.spec.md"
        spec.write_text("# spec\n", encoding="utf-8")
        r = _run("write-sidecar", "--spec", str(spec), "--payload", "-",
                 stdin="not-json")
        assert r.returncode == 1

    def test_malformed_payload_json_stderr_nonempty(self, tmp_path):
        spec = tmp_path / "foo.spec.md"
        spec.write_text("# spec\n", encoding="utf-8")
        r = _run("write-sidecar", "--spec", str(spec), "--payload", "-",
                 stdin="not-json")
        assert r.stderr != ""

    def test_missing_required_field_exits_1(self, tmp_path):
        spec = tmp_path / "foo.spec.md"
        spec.write_text("# spec\n", encoding="utf-8")
        # payload missing 'evaluator_version'
        bad = {"tiers_run": [1, 2], "policy_hash": "abc", "dismissals": []}
        r = _run("write-sidecar", "--spec", str(spec), "--payload", "-",
                 stdin=json.dumps(bad))
        assert r.returncode == 1

    def test_missing_spec_flag_exits_2(self):
        r = _run("write-sidecar")
        assert r.returncode == 2

    def test_write_sidecar_cli_preserves_findings_summary_from_payload(self, tmp_path):
        """findings_summary in the payload must round-trip to disk unchanged."""
        spec = tmp_path / "foo.spec.md"
        spec.write_text("# spec\n", encoding="utf-8")
        payload = _make_sidecar_payload(
            findings_summary={"block_count": 2, "warn_count": 1, "info_count": 0, "dismissed_t3_count": 0}
        )
        payload_file = tmp_path / "payload.json"
        payload_file.write_text(json.dumps(payload), encoding="utf-8")
        _run("write-sidecar", "--spec", str(spec), "--payload", str(payload_file))
        import json as _json
        on_disk = _json.loads((tmp_path / "foo.spec.md.eval.json").read_text(encoding="utf-8"))
        assert on_disk["findings_summary"] == payload["findings_summary"]


# ── sha256 ────────────────────────────────────────────────────────────────────

class TestSha256Cli:
    def test_happy_path_file_exits_zero(self, tmp_path):
        f = tmp_path / "data.bin"
        f.write_bytes(b"hello world")
        r = _run("sha256", "--file", str(f))
        assert r.returncode == 0

    def test_output_matches_hashlib(self, tmp_path):
        content = b"spectre test content"
        f = tmp_path / "data.bin"
        f.write_bytes(content)
        r = _run("sha256", "--file", str(f))
        expected = hashlib.sha256(content).hexdigest()
        assert r.stdout.strip() == expected

    def test_output_is_64_hex_chars(self, tmp_path):
        f = tmp_path / "data.bin"
        f.write_bytes(b"x")
        r = _run("sha256", "--file", str(f))
        assert len(r.stdout.strip()) == 64

    def test_stdin_mode_exits_zero(self):
        r = _run("sha256", "--stdin", stdin="hello\n")
        assert r.returncode == 0

    def test_stdin_mode_output_matches_hashlib(self):
        content = "hello\n"
        r = _run("sha256", "--stdin", stdin=content)
        expected = hashlib.sha256(content.encode()).hexdigest()
        assert r.stdout.strip() == expected

    def test_nonexistent_file_exits_1(self, tmp_path):
        r = _run("sha256", "--file", str(tmp_path / "no_such_file.bin"))
        assert r.returncode == 1

    def test_nonexistent_file_stderr_nonempty(self, tmp_path):
        r = _run("sha256", "--file", str(tmp_path / "no_such_file.bin"))
        assert r.stderr != ""

    def test_no_source_exits_1(self):
        r = _run("sha256")
        assert r.returncode == 1

    def test_stderr_empty_on_success(self, tmp_path):
        f = tmp_path / "data.bin"
        f.write_bytes(b"ok")
        r = _run("sha256", "--file", str(f))
        assert r.stderr == ""


# ── write-envelope: import-resolution regression (v1.0.2 hotfix) ──────────────


class TestWriteEnvelopeResolvesHandoffEnvelope:
    """Regression for v1.0.2: write-envelope must resolve handoff_envelope via
    the wrapper's PYTHONPATH (plugin root only, no bin/ entry).

    Pre-fix: `importlib.import_module("handoff_envelope")` (bareword) raised
    ModuleNotFoundError every lock because plugin root is on PYTHONPATH but
    `bin/` is not, and `bin/__init__.py` does not exist.

    This test runs `python3 -m bin.eval_metadata write-envelope ...` exactly
    like the wrapper does, with a minimal valid spec + sidecar, and asserts
    that the envelope file is actually written. If the import is reverted to
    bareword, the subcommand dies with ModuleNotFoundError before reaching
    the write, and the envelope path will not exist.
    """

    def test_write_envelope_writes_envelope_file(self, tmp_path):
        spec = tmp_path / "x.spec.md"
        spec.write_text(
            "---\nspec-version: 1.0\nspec-id: x\n---\n# x\n",
            encoding="utf-8",
        )
        sidecar = tmp_path / "x.spec.md.eval.json"
        sidecar.write_text(
            json.dumps(_make_sidecar_payload(spec_id="x")),
            encoding="utf-8",
        )
        envelope_path = tmp_path / "x.spec.md.envelope.json"
        r = _run(
            "write-envelope",
            "--spec", str(spec),
            "--sidecar", str(sidecar),
        )
        # Positive assertion: envelope file exists on disk after the call.
        # Pre-fix, the bareword import raised ModuleNotFoundError before any
        # write happened, so envelope_path.exists() was False.
        assert envelope_path.exists(), f"stdout={r.stdout!r} stderr={r.stderr!r}"
