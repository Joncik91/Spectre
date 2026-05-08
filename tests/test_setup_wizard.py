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


def test_detect_api_key_returns_none_when_env_missing_and_no_openclaw(tmp_path, monkeypatch):
    """Test isolation: monkeypatch HOME so we don't pick up a real
    ~/.spectre/secrets.env on the host (default secrets path is HOME-relative)."""
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.delenv("SPECTRE_SECRETS_FILE", raising=False)
    monkeypatch.setattr(pathlib.Path, "home", lambda: tmp_path)
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
    # v0.6.2: a fresh-schema config (model + split timeouts) skips migration.
    target.write_text(
        "[tier3]\n"
        "enabled = true\n"
        'api_key_env = "DEEPSEEK_API_KEY"\n'
        'model = "deepseek-v4-flash"\n'
        "chunk_timeout_s = 60\n"
        "total_timeout_s = 600\n",
        encoding="utf-8",
    )
    result = setup_wizard.maybe_provision(target)
    assert result == "exists"


# ── 5. maybe_provision: silent setup-skipped when no key found ──────


def test_maybe_provision_returns_setup_skipped_when_no_key(tmp_path, monkeypatch):
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.delenv("SPECTRE_SECRETS_FILE", raising=False)
    monkeypatch.setattr(pathlib.Path, "home", lambda: tmp_path)
    target = tmp_path / "reviewer.toml"
    result = setup_wizard.maybe_provision(target, secrets_file_path=None)
    text = target.read_text(encoding="utf-8")
    assert "enabled = false" in text
    assert result == "setup-skipped"


def test_maybe_provision_no_key_does_not_call_input(tmp_path, monkeypatch):
    """v0.4.2.1+: the no-key path is silent; input() must never be invoked
    (otherwise non-interactive callers raise EOFError on input())."""
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.delenv("SPECTRE_SECRETS_FILE", raising=False)
    monkeypatch.setattr(pathlib.Path, "home", lambda: tmp_path)
    monkeypatch.setattr("builtins.input", lambda *_a, **_k: pytest.fail(
        "input() must not be called on the no-key silent-skip path"
    ))
    target = tmp_path / "reviewer.toml"
    result = setup_wizard.maybe_provision(target, secrets_file_path=None)
    assert result == "setup-skipped"


def test_maybe_provision_no_key_emits_stderr_breadcrumb(tmp_path, monkeypatch, capsys):
    """v0.4.2.1: silent-skip prints one stderr line that names both the env-var
    and the resolved secrets path so the user can act on the breadcrumb."""
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.delenv("SPECTRE_SECRETS_FILE", raising=False)
    monkeypatch.setattr(pathlib.Path, "home", lambda: tmp_path)
    target = tmp_path / "reviewer.toml"
    setup_wizard.maybe_provision(target, secrets_file_path=None)
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "DEEPSEEK_API_KEY" in captured.err
    assert str(tmp_path / ".spectre" / "secrets.env") in captured.err


# ── 6. maybe_provision: silently enables when key is present ─────────────────


def test_maybe_provision_enables_silently_when_key_detected(tmp_path, monkeypatch):
    """v0.4.2.2+: configuring the key in ~/.spectre/secrets.env (or env) is
    itself the opt-in; no in-flow prompt fires. Tier 3 enables silently."""
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-test")
    target = tmp_path / "reviewer.toml"
    result = setup_wizard.maybe_provision(target, secrets_file_path=None)
    text = target.read_text(encoding="utf-8")
    assert "enabled = true" in text
    assert result == "enabled"


def test_maybe_provision_detected_key_does_not_call_input(tmp_path, monkeypatch):
    """v0.4.2.2+: the detected-key path must not invoke input() — otherwise
    non-interactive callers raise EOFError. Closes #10."""
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-test")
    monkeypatch.setattr("builtins.input", lambda *_a, **_k: pytest.fail(
        "input() must not be called on the detected-key path"
    ))
    target = tmp_path / "reviewer.toml"
    result = setup_wizard.maybe_provision(target, secrets_file_path=None)
    assert result == "enabled"


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
    result = setup_wizard.maybe_provision(target)
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


def test_personal_rules_path_default_returns_dotspectre_personal_rules_toml():
    p = setup_wizard.personal_rules_path_default()
    assert p == pathlib.Path.home() / ".spectre" / "personal-rules.toml"


def test_write_personal_rules_config_creates_empty_file(tmp_path):
    target = tmp_path / "personal-rules.toml"
    setup_wizard.write_personal_rules_config(target)
    assert target.exists()


def test_write_personal_rules_config_sets_mode_0600(tmp_path):
    target = tmp_path / "personal-rules.toml"
    setup_wizard.write_personal_rules_config(target)
    mode = target.stat().st_mode & 0o777
    assert mode == 0o600


def test_maybe_provision_personal_rules_writes_default_when_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(pathlib.Path, "home", lambda: tmp_path)
    target = tmp_path / ".spectre" / "personal-rules.toml"
    result = setup_wizard.maybe_provision_personal_rules(target)
    assert result == "created"


def test_maybe_provision_personal_rules_skips_when_file_exists(tmp_path, monkeypatch):
    monkeypatch.setattr(pathlib.Path, "home", lambda: tmp_path)
    spectre = tmp_path / ".spectre"
    spectre.mkdir()
    target = spectre / "personal-rules.toml"
    target.write_text("# pre-existing\n", encoding="utf-8")
    result = setup_wizard.maybe_provision_personal_rules(target)
    assert result == "exists"


def test_maybe_provision_templates_dir_creates_subdirs(tmp_path, monkeypatch):
    monkeypatch.setattr(pathlib.Path, "home", lambda: tmp_path)
    setup_wizard.maybe_provision_templates_dir()
    assert (tmp_path / ".spectre" / "templates" / "specs").is_dir()


def test_maybe_provision_templates_dir_skills_subdir(tmp_path, monkeypatch):
    monkeypatch.setattr(pathlib.Path, "home", lambda: tmp_path)
    setup_wizard.maybe_provision_templates_dir()
    assert (tmp_path / ".spectre" / "templates" / "skills").is_dir()


def test_maybe_provision_template_patches_dir_creates_three_subdirs(tmp_path, monkeypatch):
    monkeypatch.setattr(pathlib.Path, "home", lambda: tmp_path)
    setup_wizard.maybe_provision_template_patches_dir()
    base = tmp_path / ".spectre" / "template-patches"
    assert (base / "proposed").is_dir()


def test_maybe_provision_template_patches_dir_creates_accepted_and_rejected(tmp_path, monkeypatch):
    monkeypatch.setattr(pathlib.Path, "home", lambda: tmp_path)
    setup_wizard.maybe_provision_template_patches_dir()
    base = tmp_path / ".spectre" / "template-patches"
    actual = {p.name for p in base.iterdir() if p.is_dir()}
    assert actual == {"proposed", "accepted", "rejected"}


# ── v0.6.2 (#37) — stale reviewer.toml auto-migration ─────────────────────────


def test_stale_deepseek_reasoner_config_is_migrated(tmp_path):
    """v0.5.0-era config with model = 'deepseek-reasoner' must be migrated."""
    target = tmp_path / "reviewer.toml"
    target.write_text(
        "[tier3]\n"
        "enabled = true\n"
        'api_key_env = "DEEPSEEK_API_KEY"\n'
        'model = "deepseek-reasoner"\n'
        "timeout_s = 30\n",
        encoding="utf-8",
    )
    result = setup_wizard.maybe_provision(target)
    assert result == "migrated"
    body = target.read_text(encoding="utf-8")
    assert 'model = "deepseek-v4-flash"' in body
    assert "chunk_timeout_s = 60" in body
    assert "total_timeout_s = 600" in body
    assert "enabled = true" in body  # preserved


def test_pre_v051_single_timeout_config_is_migrated(tmp_path):
    """Pre-#25 config without chunk_timeout_s/total_timeout_s must be migrated."""
    target = tmp_path / "reviewer.toml"
    target.write_text(
        "[tier3]\n"
        "enabled = true\n"
        'api_key_env = "DEEPSEEK_API_KEY"\n'
        'model = "deepseek-v4-flash"\n'
        "timeout_s = 45\n",
        encoding="utf-8",
    )
    result = setup_wizard.maybe_provision(target)
    assert result == "migrated"


def test_migration_creates_backup_file(tmp_path):
    """Migration backs the original up to reviewer.toml.bak-<timestamp>."""
    target = tmp_path / "reviewer.toml"
    target.write_text(
        "[tier3]\nenabled = false\n"
        'model = "deepseek-reasoner"\ntimeout_s = 30\n',
        encoding="utf-8",
    )
    setup_wizard.maybe_provision(target)
    backups = list(tmp_path.glob("reviewer.toml.bak-*"))
    assert len(backups) == 1


def test_fresh_v062_config_is_not_migrated(tmp_path):
    """A fresh v0.6.2 config (split timeouts + flash model) is left alone."""
    target = tmp_path / "reviewer.toml"
    target.write_text(
        "[tier3]\n"
        "enabled = true\n"
        'api_key_env = "DEEPSEEK_API_KEY"\n'
        'model = "deepseek-v4-flash"\n'
        "chunk_timeout_s = 60\n"
        "total_timeout_s = 600\n",
        encoding="utf-8",
    )
    result = setup_wizard.maybe_provision(target)
    assert result == "exists"


def test_migration_preserves_disabled_flag(tmp_path):
    """If the user had Tier 3 disabled, migration keeps it disabled."""
    target = tmp_path / "reviewer.toml"
    target.write_text(
        "[tier3]\nenabled = false\n"
        'model = "deepseek-reasoner"\ntimeout_s = 30\n',
        encoding="utf-8",
    )
    setup_wizard.maybe_provision(target)
    body = target.read_text(encoding="utf-8")
    assert "enabled = false" in body
