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


def test_import_template_copies_spec_into_project_specs_dir(tmp_path, monkeypatch):
    """import_template(source=<template>, name=<new>) copies the template
    into the active project's specs/ dir, renamed to <new>.spec.md.draft."""
    monkeypatch.setattr(pathlib.Path, "home", lambda: tmp_path / "home")
    monkeypatch.chdir(tmp_path)
    base = tmp_path / "home" / ".spectre" / "templates" / "specs"
    base.mkdir(parents=True)
    template_path = base / "btc-base.spec.md"
    template_path.write_text("# BTC Base\n", encoding="utf-8")

    target_specs = tmp_path / "specs"
    target_specs.mkdir()
    templates.import_template(source_name="btc-base", target_name="my-btc")
    target = target_specs / "my-btc.spec.md.draft"
    assert target.exists()


def test_import_template_preserves_content(tmp_path, monkeypatch):
    monkeypatch.setattr(pathlib.Path, "home", lambda: tmp_path / "home")
    monkeypatch.chdir(tmp_path)
    base = tmp_path / "home" / ".spectre" / "templates" / "specs"
    base.mkdir(parents=True)
    (base / "x.spec.md").write_text("hello world\n", encoding="utf-8")
    (tmp_path / "specs").mkdir()
    templates.import_template(source_name="x", target_name="y")
    content = (tmp_path / "specs" / "y.spec.md.draft").read_text(encoding="utf-8")
    assert "hello world" in content


def test_import_template_raises_when_source_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(pathlib.Path, "home", lambda: tmp_path / "home")
    monkeypatch.chdir(tmp_path)
    (tmp_path / "specs").mkdir()
    with pytest.raises(FileNotFoundError, match="template not found"):
        templates.import_template(source_name="nonexistent", target_name="x")


def test_export_template_copies_project_spec_to_templates_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(pathlib.Path, "home", lambda: tmp_path / "home")
    monkeypatch.chdir(tmp_path)
    src_specs = tmp_path / "specs"
    src_specs.mkdir()
    src_path = src_specs / "btc.spec.md"
    src_path.write_text("# Project BTC\n", encoding="utf-8")

    templates.export_template(source_path=src_path, target_name="btc-base")
    target = tmp_path / "home" / ".spectre" / "templates" / "specs" / "btc-base.spec.md"
    assert target.exists()


def test_export_template_writes_mode_0600(tmp_path, monkeypatch):
    monkeypatch.setattr(pathlib.Path, "home", lambda: tmp_path / "home")
    monkeypatch.chdir(tmp_path)
    src_specs = tmp_path / "specs"
    src_specs.mkdir()
    src_path = src_specs / "btc.spec.md"
    src_path.write_text("# x\n", encoding="utf-8")
    templates.export_template(source_path=src_path, target_name="btc")
    target = tmp_path / "home" / ".spectre" / "templates" / "specs" / "btc.spec.md"
    mode = target.stat().st_mode & 0o777
    assert mode == 0o600


def test_export_template_raises_when_source_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(pathlib.Path, "home", lambda: tmp_path / "home")
    with pytest.raises(FileNotFoundError, match="source spec not found"):
        templates.export_template(
            source_path=pathlib.Path("/nonexistent.spec.md"),
            target_name="x",
        )


def test_import_template_skill_writes_to_skills_dir(tmp_path, monkeypatch):
    """A template with a frontmatter --- block is treated as a skill."""
    monkeypatch.setattr(pathlib.Path, "home", lambda: tmp_path / "home")
    monkeypatch.chdir(tmp_path)
    base = tmp_path / "home" / ".spectre" / "templates" / "skills"
    base.mkdir(parents=True)
    (base / "safe-deploy.md").write_text(
        "---\nname: safe-deploy\n---\n# body\n", encoding="utf-8",
    )
    (tmp_path / "skills").mkdir()
    templates.import_template(source_name="safe-deploy", target_name="my-deploy")
    target = tmp_path / "skills" / "my-deploy.md"
    assert target.exists()


def test_import_template_explicit_kind_routes_correctly(tmp_path, monkeypatch):
    """When both specs/x and skills/x exist, kind= disambiguates."""
    monkeypatch.setattr(pathlib.Path, "home", lambda: tmp_path / "home")
    monkeypatch.chdir(tmp_path)
    base = tmp_path / "home" / ".spectre" / "templates"
    (base / "specs").mkdir(parents=True)
    (base / "skills").mkdir(parents=True)
    (base / "specs" / "x.spec.md").write_text("# spec\n", encoding="utf-8")
    (base / "skills" / "x.md").write_text("# skill\n", encoding="utf-8")
    (tmp_path / "specs").mkdir()
    templates.import_template(source_name="x", target_name="y", kind="spec")
    target = tmp_path / "specs" / "y.spec.md.draft"
    assert target.exists()
