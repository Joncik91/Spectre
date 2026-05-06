"""Adapt's auto-template-patch proposer. Stdlib + pytest only."""
import pathlib
import pytest

from bin import template_patcher


def test_patcher_version_is_0_4_2():
    assert template_patcher.PATCHER_VERSION == "0.4.2"


def test_default_recurrence_threshold_is_3():
    assert template_patcher.DEFAULT_RECURRENCE_THRESHOLD == 3


def test_detect_patch_candidates_returns_empty_when_no_observations(tmp_path, monkeypatch):
    monkeypatch.setattr(pathlib.Path, "home", lambda: tmp_path)
    monkeypatch.chdir(tmp_path)
    result = template_patcher.detect_patch_candidates()
    assert result == []


def test_detect_patch_candidates_returns_empty_when_below_threshold(tmp_path, monkeypatch):
    """Two halts of the same fingerprint — below default threshold of 3."""
    from bin import observations
    monkeypatch.setattr(pathlib.Path, "home", lambda: tmp_path)
    monkeypatch.chdir(tmp_path)
    for _ in range(2):
        observations.record_halt(
            kind="tier-gate", fingerprint="a"*64,
            project_path="/p", spec_slug="s", action="x",
        )
    result = template_patcher.detect_patch_candidates()
    assert result == []


def test_detect_patch_candidates_returns_recurring_fingerprint(tmp_path, monkeypatch):
    """Three halts of the same fingerprint — meets threshold."""
    from bin import observations
    monkeypatch.setattr(pathlib.Path, "home", lambda: tmp_path)
    monkeypatch.chdir(tmp_path)
    for _ in range(3):
        observations.record_halt(
            kind="tier-gate", fingerprint="b"*64,
            project_path="/p", spec_slug="s", action="x",
        )
    result = template_patcher.detect_patch_candidates()
    fps = {c["fingerprint"] for c in result}
    assert "b"*64 in fps


def test_detect_patch_candidates_skips_already_adopted(tmp_path, monkeypatch):
    """If user already adopted a personal-rule for this fingerprint,
    the patcher does NOT propose a template-patch — adoption already
    expresses the user's preference."""
    from bin import observations, personal_rules
    monkeypatch.setattr(pathlib.Path, "home", lambda: tmp_path)
    monkeypatch.chdir(tmp_path)
    fp = "c" * 64
    label = "permission-change: chmod"
    for _ in range(3):
        observations.record_halt(
            kind="tier-gate", fingerprint=fp,
            project_path="/p", spec_slug="s", action="x",
            classifier_label=label,
        )
    personal_rules.append_adoption(
        classifier_label=label, fingerprint=fp, reason="r",
    )
    result = template_patcher.detect_patch_candidates()
    fps = {c["fingerprint"] for c in result}
    assert fp not in fps


def test_propose_patch_writes_to_proposed_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(pathlib.Path, "home", lambda: tmp_path)
    candidate = {
        "fingerprint": "d" * 64,
        "classifier_label": "permission-change: chmod",
        "kind": "tier-gate",
        "count": 4,
        "action": "chmod 755 /tmp/foo",
        "spec_slug": "test-spec",
    }
    target = template_patcher.propose_patch(candidate)
    expected_dir = tmp_path / ".spectre" / "template-patches" / "proposed"
    assert target.parent == expected_dir


def test_propose_patch_filename_is_fingerprint_short_slug(tmp_path, monkeypatch):
    """The patch filename includes a short fingerprint hash for uniqueness."""
    monkeypatch.setattr(pathlib.Path, "home", lambda: tmp_path)
    candidate = {
        "fingerprint": "abcd" * 16,
        "classifier_label": "x",
        "kind": "tier-gate",
        "count": 3,
        "action": "y",
        "spec_slug": "z",
    }
    target = template_patcher.propose_patch(candidate)
    assert "abcd" in target.name


def test_propose_patch_writes_markdown_with_candidate_metadata(tmp_path, monkeypatch):
    monkeypatch.setattr(pathlib.Path, "home", lambda: tmp_path)
    candidate = {
        "fingerprint": "e" * 64,
        "classifier_label": "permission-change: chmod",
        "kind": "tier-gate",
        "count": 5,
        "action": "chmod 755 /tmp/x",
        "spec_slug": "my-spec",
    }
    target = template_patcher.propose_patch(candidate)
    body = target.read_text(encoding="utf-8")
    assert "permission-change: chmod" in body


def test_propose_patch_sets_mode_0600(tmp_path, monkeypatch):
    monkeypatch.setattr(pathlib.Path, "home", lambda: tmp_path)
    candidate = {
        "fingerprint": "f"*64, "classifier_label": "x",
        "kind": "tier-gate", "count": 3, "action": "y", "spec_slug": "z",
    }
    target = template_patcher.propose_patch(candidate)
    mode = target.stat().st_mode & 0o777
    assert mode == 0o600


def test_list_proposed_patches_returns_empty_when_dir_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(pathlib.Path, "home", lambda: tmp_path)
    result = template_patcher.list_proposed_patches()
    assert result == []


def test_list_proposed_patches_returns_files_in_proposed_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(pathlib.Path, "home", lambda: tmp_path)
    proposed_dir = tmp_path / ".spectre" / "template-patches" / "proposed"
    proposed_dir.mkdir(parents=True)
    (proposed_dir / "patch-a.md").write_text("# a\n", encoding="utf-8")
    (proposed_dir / "patch-b.md").write_text("# b\n", encoding="utf-8")
    result = template_patcher.list_proposed_patches()
    assert len(result) == 2
