"""CLI tests for bin/cdlc_ledger.py __main__ entrypoint (Phase 2D, issue #13).

Invokes the module via `python3 -m bin.cdlc_ledger <subcommand>` as a subprocess.
"""
import json
import pathlib
import subprocess
import sys


_CMD = [sys.executable, "-m", "bin.cdlc_ledger"]
_REPO = pathlib.Path(__file__).resolve().parent.parent


def _run(*args, cwd=None, input_text=None):
    return subprocess.run(
        _CMD + list(args),
        capture_output=True,
        text=True,
        cwd=cwd or _REPO,
        input=input_text,
    )


class TestAppendCli:
    def test_append_with_payload_kv_exits_zero(self, tmp_path):
        r = _run(
            "append", "--kind", "generate",
            "--project", str(tmp_path),
            "--payload-kv", "spec_slug=hello",
            "--payload-kv", "round_count=4",
        )
        assert r.returncode == 0

    def test_append_writes_ledger_file(self, tmp_path):
        _run(
            "append", "--kind", "implement",
            "--project", str(tmp_path),
            "--payload-kv", "step=3",
        )
        ledger = tmp_path / "state" / "cdlc-ledger.json"
        assert ledger.is_file()

    def test_append_payload_persists_correctly(self, tmp_path):
        _run(
            "append", "--kind", "halt",
            "--project", str(tmp_path),
            "--payload-kv", "fingerprint=abc123",
            "--payload-kv", "label=permission-change: chmod",
        )
        ledger = tmp_path / "state" / "cdlc-ledger.json"
        data = json.loads(ledger.read_text())
        assert data["transitions"][0]["payload"]["fingerprint"] == "abc123"

    def test_append_payload_kind_persists(self, tmp_path):
        _run(
            "append", "--kind", "adapt",
            "--project", str(tmp_path),
            "--payload-kv", "fingerprint=xy",
        )
        ledger = tmp_path / "state" / "cdlc-ledger.json"
        data = json.loads(ledger.read_text())
        assert data["transitions"][0]["kind"] == "adapt"

    def test_append_with_payload_json_string(self, tmp_path):
        r = _run(
            "append", "--kind", "test",
            "--project", str(tmp_path),
            "--payload", '{"step": 7, "spec_slug": "demo"}',
        )
        assert r.returncode == 0

    def test_append_with_payload_json_persists_int(self, tmp_path):
        _run(
            "append", "--kind", "test",
            "--project", str(tmp_path),
            "--payload", '{"step": 7}',
        )
        ledger = tmp_path / "state" / "cdlc-ledger.json"
        data = json.loads(ledger.read_text())
        assert data["transitions"][0]["payload"]["step"] == 7

    def test_append_with_payload_stdin(self, tmp_path):
        r = _run(
            "append", "--kind", "lock",
            "--project", str(tmp_path),
            "--payload", "-",
            input_text='{"slug": "foo"}',
        )
        assert r.returncode == 0

    def test_append_unknown_kind_exits_2(self, tmp_path):
        r = _run(
            "append", "--kind", "bogus",
            "--project", str(tmp_path),
        )
        assert r.returncode == 2

    def test_append_mutual_exclusion_exits_1(self, tmp_path):
        r = _run(
            "append", "--kind", "halt",
            "--project", str(tmp_path),
            "--payload", "{}",
            "--payload-kv", "k=v",
        )
        assert r.returncode == 1

    def test_append_bad_payload_kv_exits_1(self, tmp_path):
        r = _run(
            "append", "--kind", "halt",
            "--project", str(tmp_path),
            "--payload-kv", "no-equals-here",
        )
        assert r.returncode == 1

    def test_append_bad_payload_json_exits_1(self, tmp_path):
        r = _run(
            "append", "--kind", "halt",
            "--project", str(tmp_path),
            "--payload", "{not json",
        )
        assert r.returncode == 1

    def test_append_payload_must_be_object_exits_1(self, tmp_path):
        r = _run(
            "append", "--kind", "halt",
            "--project", str(tmp_path),
            "--payload", "[1, 2, 3]",
        )
        assert r.returncode == 1


class TestReadCli:
    def test_read_empty_project_returns_empty_list(self, tmp_path):
        r = _run("read", "--project", str(tmp_path))
        assert json.loads(r.stdout) == []

    def test_read_after_append_returns_one_transition(self, tmp_path):
        _run(
            "append", "--kind", "implement",
            "--project", str(tmp_path),
            "--payload-kv", "step=1",
        )
        r = _run("read", "--project", str(tmp_path))
        assert len(json.loads(r.stdout)) == 1

    def test_read_round_trip_payload(self, tmp_path):
        _run(
            "append", "--kind", "halt",
            "--project", str(tmp_path),
            "--payload-kv", "fingerprint=ff",
        )
        r = _run("read", "--project", str(tmp_path))
        txs = json.loads(r.stdout)
        assert txs[0]["payload"]["fingerprint"] == "ff"


class TestArgparse:
    def test_no_subcommand_exits_2(self):
        r = _run()
        assert r.returncode == 2
