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


# ── 5. maybe_provision: writes disabled config when no key found ──────────────


def test_maybe_provision_writes_disabled_when_no_key_found(tmp_path, monkeypatch):
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    target = tmp_path / "reviewer.toml"
    result = setup_wizard.maybe_provision(
        target, secrets_file_path=None, prompt_fn=lambda _msg: "yes"
    )
    text = target.read_text(encoding="utf-8")
    assert "enabled = false" in text
    assert result == "no-key"


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
