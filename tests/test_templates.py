"""Distribute leg — reusable template artifacts. Stdlib + pytest only."""
import pathlib
import pytest

from bin import templates


def test_templates_version_is_0_4_2():
    assert templates.TEMPLATES_VERSION == "0.4.2"


def test_templates_dir_default_returns_dotspectre_templates(tmp_path, monkeypatch):
    monkeypatch.setattr(pathlib.Path, "home", lambda: tmp_path)
    p = templates.templates_dir_default()
    assert p == tmp_path / ".spectre" / "templates"


def test_list_templates_returns_empty_when_dir_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(pathlib.Path, "home", lambda: tmp_path)
    assert templates.list_templates() == []


def test_list_templates_returns_specs_in_specs_subdir(tmp_path, monkeypatch):
    monkeypatch.setattr(pathlib.Path, "home", lambda: tmp_path)
    specs_dir = tmp_path / ".spectre" / "templates" / "specs"
    specs_dir.mkdir(parents=True)
    (specs_dir / "btc-poller-base.spec.md").write_text("# Base\n", encoding="utf-8")
    result = templates.list_templates()
    names = [t["name"] for t in result]
    assert "btc-poller-base" in names


def test_list_templates_returns_skills_in_skills_subdir(tmp_path, monkeypatch):
    monkeypatch.setattr(pathlib.Path, "home", lambda: tmp_path)
    skills_dir = tmp_path / ".spectre" / "templates" / "skills"
    skills_dir.mkdir(parents=True)
    (skills_dir / "safe-deploy.md").write_text("---\nname: x\n---\n", encoding="utf-8")
    result = templates.list_templates()
    kinds = {t["kind"] for t in result}
    assert "skill" in kinds


def test_list_templates_distinguishes_specs_from_skills(tmp_path, monkeypatch):
    monkeypatch.setattr(pathlib.Path, "home", lambda: tmp_path)
    base = tmp_path / ".spectre" / "templates"
    (base / "specs").mkdir(parents=True)
    (base / "skills").mkdir(parents=True)
    (base / "specs" / "a.spec.md").write_text("# a\n", encoding="utf-8")
    (base / "skills" / "b.md").write_text("---\nname: b\n---\n", encoding="utf-8")
    result = templates.list_templates()
    spec_names = {t["name"] for t in result if t["kind"] == "spec"}
    skill_names = {t["name"] for t in result if t["kind"] == "skill"}
    assert spec_names == {"a"}
    # NOTE: this is one of the allowed two-assertion exceptions (verifying the
    # split into two disjoint sets is one behavior).
    assert skill_names == {"b"}
