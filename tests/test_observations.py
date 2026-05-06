"""Observe-leg JSONL halt log. Stdlib + pytest only."""
import json
import pathlib
import pytest

from bin import observations


def test_observations_version_is_0_4_1():
    assert observations.OBSERVATIONS_VERSION == "0.4.1"


def test_fingerprint_halt_is_deterministic_for_same_inputs():
    fp_a = observations.fingerprint_halt(action="rm -rf /tmp/foo", classifier_label="destructive-delete: rm -rf")
    fp_b = observations.fingerprint_halt(action="rm -rf /tmp/foo", classifier_label="destructive-delete: rm -rf")
    assert fp_a == fp_b


def test_fingerprint_halt_differs_for_different_actions():
    fp_a = observations.fingerprint_halt(action="rm -rf /tmp/foo", classifier_label="destructive-delete: rm -rf")
    fp_b = observations.fingerprint_halt(action="rm -rf /tmp/bar", classifier_label="destructive-delete: rm -rf")
    assert fp_a != fp_b


def test_fingerprint_halt_differs_for_different_classifier_labels():
    fp_a = observations.fingerprint_halt(action="echo hi", classifier_label="permission-change: chmod")
    fp_b = observations.fingerprint_halt(action="echo hi", classifier_label="destructive-delete: rm -rf")
    assert fp_a != fp_b


def test_fingerprint_halt_returns_64_char_hex_sha256():
    fp = observations.fingerprint_halt(action="x", classifier_label="y")
    assert len(fp) == 64


def test_observations_path_default_returns_dotspectre_observations_jsonl():
    p = observations.observations_path_default()
    assert p == pathlib.Path.home() / ".spectre" / "observations.jsonl"


def test_record_halt_creates_jsonl_file_when_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(pathlib.Path, "home", lambda: tmp_path)
    observations.record_halt(
        kind="tier-gate",
        fingerprint="a" * 64,
        project_path="/home/foo/proj",
        spec_slug="my-spec",
        action="rm -rf /tmp/x",
    )
    target = tmp_path / ".spectre" / "observations.jsonl"
    assert target.exists()


def test_record_halt_appends_one_line_per_call(tmp_path, monkeypatch):
    monkeypatch.setattr(pathlib.Path, "home", lambda: tmp_path)
    observations.record_halt(
        kind="tier-gate", fingerprint="a"*64,
        project_path="/p", spec_slug="s", action="x",
    )
    observations.record_halt(
        kind="tier-gate", fingerprint="b"*64,
        project_path="/p", spec_slug="s", action="y",
    )
    target = tmp_path / ".spectre" / "observations.jsonl"
    lines = [l for l in target.read_text(encoding="utf-8").splitlines() if l.strip()]
    assert len(lines) == 2


def test_record_halt_includes_required_fields(tmp_path, monkeypatch):
    monkeypatch.setattr(pathlib.Path, "home", lambda: tmp_path)
    observations.record_halt(
        kind="tier-gate", fingerprint="abcd" * 16,
        project_path="/home/foo/proj", spec_slug="my-spec",
        action="rm -rf /tmp/x",
    )
    target = tmp_path / ".spectre" / "observations.jsonl"
    record = json.loads(target.read_text(encoding="utf-8").strip())
    actual_keys = set(record.keys())
    assert {"ts", "kind", "fingerprint", "project_path", "spec_slug", "action"}.issubset(actual_keys)


def test_record_halt_timestamp_is_iso_8601_utc(tmp_path, monkeypatch):
    monkeypatch.setattr(pathlib.Path, "home", lambda: tmp_path)
    observations.record_halt(
        kind="tier-gate", fingerprint="a"*64,
        project_path="/p", spec_slug="s", action="x",
    )
    target = tmp_path / ".spectre" / "observations.jsonl"
    record = json.loads(target.read_text(encoding="utf-8").strip())
    assert record["ts"].endswith("+00:00") or record["ts"].endswith("Z")


def test_find_recurrences_returns_empty_when_no_jsonl(tmp_path, monkeypatch):
    monkeypatch.setattr(pathlib.Path, "home", lambda: tmp_path)
    result = observations.find_recurrences(threshold=3)
    assert result == []


def test_find_recurrences_filters_below_threshold(tmp_path, monkeypatch):
    monkeypatch.setattr(pathlib.Path, "home", lambda: tmp_path)
    for _ in range(2):
        observations.record_halt(
            kind="tier-gate", fingerprint="abc" * 21 + "a",
            project_path="/p", spec_slug="s", action="x",
        )
    result = observations.find_recurrences(threshold=3)
    assert result == []


def test_find_recurrences_returns_fingerprints_at_or_above_threshold(tmp_path, monkeypatch):
    monkeypatch.setattr(pathlib.Path, "home", lambda: tmp_path)
    target_fp = "deadbeef" * 8
    for _ in range(3):
        observations.record_halt(
            kind="tier-gate", fingerprint=target_fp,
            project_path="/p", spec_slug="s", action="x",
        )
    result = observations.find_recurrences(threshold=3)
    fps = {r["fingerprint"] for r in result}
    assert target_fp in fps


def test_find_recurrences_filters_by_kind_when_specified(tmp_path, monkeypatch):
    monkeypatch.setattr(pathlib.Path, "home", lambda: tmp_path)
    for _ in range(3):
        observations.record_halt(
            kind="tier-gate", fingerprint="a"*64,
            project_path="/p", spec_slug="s", action="x",
        )
    for _ in range(3):
        observations.record_halt(
            kind="other-kind", fingerprint="b"*64,
            project_path="/p", spec_slug="s", action="x",
        )
    result = observations.find_recurrences(kind="tier-gate", threshold=3)
    kinds = {r["kind"] for r in result}
    assert kinds == {"tier-gate"}
