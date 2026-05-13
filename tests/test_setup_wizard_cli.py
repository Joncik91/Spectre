"""CLI tests for bin/setup_wizard.py __main__ entrypoint (Phase 2D, issue #13)."""
import os
import pathlib
import subprocess
import sys


_CMD = [sys.executable, "-m", "bin.setup_wizard"]
_REPO = pathlib.Path(__file__).resolve().parent.parent


def _run(*args, cwd=None, env=None):
    base_env = os.environ.copy()
    base_env["PYTHONPATH"] = str(_REPO)
    if env:
        base_env.update(env)
    return subprocess.run(
        _CMD + list(args),
        capture_output=True,
        text=True,
        cwd=cwd if cwd is not None else _REPO,
        env=base_env,
    )


def _isolate(tmp_path):
    return {
        "HOME": str(tmp_path),
        # Keep the wizard from reading the host's API key.
        "DEEPSEEK_API_KEY": "",
        "SPECTRE_SECRETS_FILE": "",
    }


class TestProvisionCli:
    def test_provision_no_key_exits_zero(self, tmp_path):
        r = _run(
            "provision", "--secrets-file", str(tmp_path / "missing.env"),
            env=_isolate(tmp_path),
        )
        assert r.returncode == 0

    def test_provision_no_key_prints_setup_skipped(self, tmp_path):
        r = _run(
            "provision", "--secrets-file", str(tmp_path / "missing.env"),
            env=_isolate(tmp_path),
        )
        assert "wizard.setup" in r.stdout and "result=setup-skipped" in r.stdout

    def test_provision_creates_reviewer_toml_no_key(self, tmp_path):
        target = tmp_path / "reviewer.toml"
        _run(
            "provision",
            "--target", str(target),
            "--secrets-file", str(tmp_path / "missing.env"),
            env=_isolate(tmp_path),
        )
        assert target.is_file()

    def test_provision_disabled_when_no_key(self, tmp_path):
        target = tmp_path / "reviewer.toml"
        _run(
            "provision",
            "--target", str(target),
            "--secrets-file", str(tmp_path / "missing.env"),
            env=_isolate(tmp_path),
        )
        text = target.read_text()
        assert "enabled = false" in text

    def test_provision_existing_file_returns_exists(self, tmp_path):
        target = tmp_path / "reviewer.toml"
        target.write_text(
            "# existing\n[tier3]\n"
            "enabled = true\n"
            'api_key_env = "DEEPSEEK_API_KEY"\n'
            'model = "deepseek-v4-flash"\n'
            "chunk_timeout_s = 60\n"
            "total_timeout_s = 600\n"
        )
        r = _run(
            "provision",
            "--target", str(target),
            "--secrets-file", str(tmp_path / "missing.env"),
            env=_isolate(tmp_path),
        )
        assert "wizard.setup" in r.stdout and "result=exists" in r.stdout

    def test_provision_with_env_key_enables(self, tmp_path):
        target = tmp_path / "reviewer.toml"
        env = _isolate(tmp_path)
        env["DEEPSEEK_API_KEY"] = "sk-test-foo"
        r = _run(
            "provision",
            "--target", str(target),
            "--secrets-file", str(tmp_path / "missing.env"),
            env=env,
        )
        assert "wizard.setup" in r.stdout and "result=enabled" in r.stdout

    def test_provision_with_secrets_file_enables(self, tmp_path):
        target = tmp_path / "reviewer.toml"
        secrets = tmp_path / "secrets.env"
        secrets.write_text("DEEPSEEK_API_KEY=sk-test-secret\n")
        r = _run(
            "provision",
            "--target", str(target),
            "--secrets-file", str(secrets),
            env=_isolate(tmp_path),
        )
        assert "wizard.setup" in r.stdout and "result=enabled" in r.stdout

    def test_provision_writes_target_path_in_output(self, tmp_path):
        target = tmp_path / "reviewer.toml"
        r = _run(
            "provision",
            "--target", str(target),
            "--secrets-file", str(tmp_path / "missing.env"),
            env=_isolate(tmp_path),
        )
        assert str(target) in r.stdout


class TestArgparse:
    def test_no_subcommand_exits_2(self):
        r = _run()
        assert r.returncode == 2
