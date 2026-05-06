"""Tests for bin/setup_wizard.py — first-run reviewer.toml provisioning. Stdlib only."""
import os
import pathlib
import pytest

from bin import setup_wizard


# ── 1. detect_api_key from env var ─────────────────────────────────────────────


def test_detect_api_key_finds_env_var(monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-test-1234")
    found = setup_wizard.detect_api_key(env_var_name="DEEPSEEK_API_KEY", secrets_file_path=None)
    assert found == ("env", "DEEPSEEK_API_KEY")


def test_detect_api_key_returns_none_when_env_missing_and_no_openclaw(monkeypatch):
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    found = setup_wizard.detect_api_key(env_var_name="DEEPSEEK_API_KEY", secrets_file_path=None)
    assert found is None


def test_detect_api_key_finds_secrets_file(tmp_path, monkeypatch):
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.delenv("SPECTRE_SECRETS_FILE", raising=False)
    env_file = tmp_path / ".env"
    env_file.write_text("OTHER_KEY=foo\nDEEPSEEK_API_KEY=sk-from-store\n", encoding="utf-8")
    found = setup_wizard.detect_api_key(env_var_name="DEEPSEEK_API_KEY", secrets_file_path=env_file)
    assert found == ("secrets-file", str(env_file))


def test_detect_api_key_uses_spectre_secrets_file_env_var(tmp_path, monkeypatch):
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    env_file = tmp_path / "myenv"
    env_file.write_text("DEEPSEEK_API_KEY=sk-via-envvar\n", encoding="utf-8")
    monkeypatch.setenv("SPECTRE_SECRETS_FILE", str(env_file))
    found = setup_wizard.detect_api_key(env_var_name="DEEPSEEK_API_KEY", secrets_file_path=None)
    assert found == ("secrets-file", str(env_file))


def test_detect_api_key_skips_secrets_file_when_key_absent(tmp_path, monkeypatch):
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    env_file = tmp_path / ".env"
    env_file.write_text("UNRELATED=value\n", encoding="utf-8")
    found = setup_wizard.detect_api_key(env_var_name="DEEPSEEK_API_KEY", secrets_file_path=env_file)
    assert found is None


# ── 2. write_config writes valid TOML ─────────────────────────────────────────


def test_write_config_creates_file_at_path(tmp_path):
    target = tmp_path / "reviewer.toml"
    setup_wizard.write_config(target, enabled=True, api_key_env="DEEPSEEK_API_KEY")
    assert target.exists()


def test_write_config_sets_mode_0600(tmp_path):
    target = tmp_path / "reviewer.toml"
    setup_wizard.write_config(target, enabled=True, api_key_env="DEEPSEEK_API_KEY")
    mode = target.stat().st_mode & 0o777
    assert mode == 0o600


def test_write_config_creates_parent_directory(tmp_path):
    target = tmp_path / "nested" / "subdir" / "reviewer.toml"
    setup_wizard.write_config(target, enabled=False, api_key_env="DEEPSEEK_API_KEY")
    assert target.exists()


def test_write_config_writes_enabled_true_flag(tmp_path):
    target = tmp_path / "reviewer.toml"
    setup_wizard.write_config(target, enabled=True, api_key_env="DEEPSEEK_API_KEY")
    text = target.read_text(encoding="utf-8")
    assert "enabled = true" in text


def test_write_config_writes_enabled_false_flag(tmp_path):
    target = tmp_path / "reviewer.toml"
    setup_wizard.write_config(target, enabled=False, api_key_env="DEEPSEEK_API_KEY")
    text = target.read_text(encoding="utf-8")
    assert "enabled = false" in text


def test_write_config_includes_api_key_env_name(tmp_path):
    target = tmp_path / "reviewer.toml"
    setup_wizard.write_config(target, enabled=True, api_key_env="MY_CUSTOM_KEY")
    text = target.read_text(encoding="utf-8")
    assert 'api_key_env = "MY_CUSTOM_KEY"' in text


def test_write_config_uses_atomic_write(tmp_path):
    """Verify atomicity by checking no .tmp leftover."""
    target = tmp_path / "reviewer.toml"
    setup_wizard.write_config(target, enabled=True, api_key_env="DEEPSEEK_API_KEY")
    siblings = list(target.parent.iterdir())
    assert all(not s.name.endswith(".tmp") for s in siblings)


# ── 3. config_path_default ────────────────────────────────────────────────────


def test_config_path_default_returns_home_relative_path():
    p = setup_wizard.config_path_default()
    assert p == pathlib.Path.home() / ".spectre" / "reviewer.toml"


# ── 4. maybe_provision: skip when config exists ───────────────────────────────


def test_maybe_provision_skips_when_config_exists(tmp_path):
    target = tmp_path / "reviewer.toml"
    target.write_text("[tier3]\nenabled = true\n", encoding="utf-8")
    result = setup_wizard.maybe_provision(target, prompt_fn=lambda _msg: "yes")
    assert result == "exists"


# ── 5. maybe_provision: setup-skipped path when user declines key setup ──────


def test_maybe_provision_returns_setup_skipped_when_user_skips(tmp_path, monkeypatch):
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.delenv("SPECTRE_SECRETS_FILE", raising=False)
    monkeypatch.setattr(pathlib.Path, "home", lambda: tmp_path)
    target = tmp_path / "reviewer.toml"
    result = setup_wizard.maybe_provision(
        target, secrets_file_path=None, prompt_fn=lambda _msg: "skip"
    )
    text = target.read_text(encoding="utf-8")
    assert "enabled = false" in text
    assert result == "setup-skipped"


# ── 6. maybe_provision: enables on yes when key present ───────────────────────


def test_maybe_provision_enables_on_user_yes(tmp_path, monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-test")
    target = tmp_path / "reviewer.toml"
    result = setup_wizard.maybe_provision(
        target, secrets_file_path=None, prompt_fn=lambda _msg: "yes"
    )
    text = target.read_text(encoding="utf-8")
    assert "enabled = true" in text
    assert result == "enabled"


def test_maybe_provision_disables_on_user_no(tmp_path, monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-test")
    target = tmp_path / "reviewer.toml"
    result = setup_wizard.maybe_provision(
        target, secrets_file_path=None, prompt_fn=lambda _msg: "no"
    )
    text = target.read_text(encoding="utf-8")
    assert "enabled = false" in text
    assert result == "declined"


# ── v0.3.2: ~/.spectre/secrets.env as canonical key store ────────────────────


def test_secrets_path_default_returns_dotspectre_secrets_env():
    """Canonical secrets location for v0.3.2."""
    p = setup_wizard.secrets_path_default()
    assert p == pathlib.Path.home() / ".spectre" / "secrets.env"


def test_detect_api_key_finds_spectre_secrets_env(tmp_path, monkeypatch):
    """Default path: ~/.spectre/secrets.env (passed as secrets_file_path)."""
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.delenv("SPECTRE_SECRETS_FILE", raising=False)
    secrets_dir = tmp_path / ".spectre"
    secrets_dir.mkdir()
    secrets_file = secrets_dir / "secrets.env"
    secrets_file.write_text("DEEPSEEK_API_KEY=sk-from-spectre-dir\n", encoding="utf-8")
    found = setup_wizard.detect_api_key(
        env_var_name="DEEPSEEK_API_KEY", secrets_file_path=secrets_file
    )
    assert found == ("secrets-file", str(secrets_file))


def test_maybe_provision_probes_spectre_secrets_env_when_no_arg(tmp_path, monkeypatch):
    """When secrets_file_path is None, the wizard auto-probes ~/.spectre/secrets.env."""
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.delenv("SPECTRE_SECRETS_FILE", raising=False)
    monkeypatch.setattr(pathlib.Path, "home", lambda: tmp_path)
    secrets_dir = tmp_path / ".spectre"
    secrets_dir.mkdir()
    (secrets_dir / "secrets.env").write_text("DEEPSEEK_API_KEY=sk-auto\n", encoding="utf-8")
    target = tmp_path / "reviewer.toml"
    result = setup_wizard.maybe_provision(target, prompt_fn=lambda _msg: "yes")
    assert result == "enabled"


def test_maybe_provision_retry_finds_key_after_user_drops_file(tmp_path, monkeypatch):
    """retry → wizard re-probes ~/.spectre/secrets.env. If user dropped the file,
    detection succeeds and the opt-in prompt fires."""
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.delenv("SPECTRE_SECRETS_FILE", raising=False)
    monkeypatch.setattr(pathlib.Path, "home", lambda: tmp_path)
    secrets_dir = tmp_path / ".spectre"
    secrets_dir.mkdir()
    secrets_file = secrets_dir / "secrets.env"
    target = tmp_path / "reviewer.toml"

    state = {"call": 0}
    def fake_prompt(_msg: str) -> str:
        if state["call"] == 0:
            secrets_file.write_text("DEEPSEEK_API_KEY=sk-just-dropped\n", encoding="utf-8")
            state["call"] += 1
            return "retry"
        return "yes"

    result = setup_wizard.maybe_provision(target, prompt_fn=fake_prompt)
    assert result == "enabled"


def test_walker_path_default_returns_dotspectre_walker_toml():
    p = setup_wizard.walker_path_default()
    assert p == pathlib.Path.home() / ".spectre" / "walker.toml"


def test_write_walker_config_creates_file_with_defaults(tmp_path):
    target = tmp_path / "walker.toml"
    setup_wizard.write_walker_config(target)
    assert target.exists()
    text = target.read_text(encoding="utf-8")
    assert "max_rounds = 30" in text


def test_write_walker_config_sets_mode_0600(tmp_path):
    target = tmp_path / "walker.toml"
    setup_wizard.write_walker_config(target)
    mode = target.stat().st_mode & 0o777
    assert mode == 0o600


def test_maybe_provision_walker_skips_when_file_exists(tmp_path, monkeypatch):
    monkeypatch.setattr(pathlib.Path, "home", lambda: tmp_path)
    spectre_dir = tmp_path / ".spectre"
    spectre_dir.mkdir()
    target = spectre_dir / "walker.toml"
    target.write_text("# pre-existing\n", encoding="utf-8")
    result = setup_wizard.maybe_provision_walker(target)
    assert result == "exists"
    assert target.read_text(encoding="utf-8") == "# pre-existing\n"


def test_maybe_provision_walker_writes_default_when_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(pathlib.Path, "home", lambda: tmp_path)
    target = tmp_path / ".spectre" / "walker.toml"
    result = setup_wizard.maybe_provision_walker(target)
    assert result == "created"
    assert target.exists()
