"""Personal-rules adoption tracker. Stdlib + pytest only."""
import os
import pathlib
import tomllib

import pytest

from bin import personal_rules


def test_personal_rules_version_is_0_4_1():
    assert personal_rules.PERSONAL_RULES_VERSION == "0.4.1"


def test_personal_rules_path_default_returns_dotspectre_personal_rules_toml():
    p = personal_rules.personal_rules_path_default()
    assert p == pathlib.Path.home() / ".spectre" / "personal-rules.toml"


def test_default_brake_threshold_is_3():
    assert personal_rules.DEFAULT_BRAKE_THRESHOLD == 3


def test_load_personal_rules_returns_empty_dict_when_file_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(pathlib.Path, "home", lambda: tmp_path)
    result = personal_rules.load_personal_rules()
    assert result == {}


def test_load_personal_rules_returns_dict_when_file_present(tmp_path, monkeypatch):
    monkeypatch.setattr(pathlib.Path, "home", lambda: tmp_path)
    spectre = tmp_path / ".spectre"
    spectre.mkdir()
    (spectre / "personal-rules.toml").write_text(
        'version = "0.4.1"\n[overrides]\n', encoding="utf-8"
    )
    result = personal_rules.load_personal_rules()
    assert isinstance(result, dict)
