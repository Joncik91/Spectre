"""Per-project CDLC transition log. Stdlib + pytest only."""
import json
import pathlib
import pytest

from bin import cdlc_ledger


def test_ledger_version_is_0_4_2():
    assert cdlc_ledger.LEDGER_VERSION == "0.4.2"


def test_known_transition_kinds_includes_six_lifecycle_stages():
    assert set(cdlc_ledger.KNOWN_TRANSITION_KINDS) == {
        "generate", "test", "lock", "implement", "halt", "adapt",
    }


def test_cdlc_ledger_path_default_returns_state_cdlc_ledger_json(tmp_path):
    p = cdlc_ledger.cdlc_ledger_path_default(tmp_path)
    assert p == tmp_path / "state" / "cdlc-ledger.json"


def test_cdlc_ledger_path_default_accepts_pathlib_path(tmp_path):
    p = cdlc_ledger.cdlc_ledger_path_default(pathlib.Path(tmp_path))
    assert isinstance(p, pathlib.Path)


def test_append_transition_creates_ledger_when_missing(tmp_path):
    cdlc_ledger.append_transition(
        kind="generate",
        payload={"spec_slug": "x", "round_count": 1},
        project_path=tmp_path,
    )
    target = tmp_path / "state" / "cdlc-ledger.json"
    assert target.exists()


def test_append_transition_writes_valid_json(tmp_path):
    cdlc_ledger.append_transition(
        kind="lock",
        payload={"spec_slug": "x"},
        project_path=tmp_path,
    )
    target = tmp_path / "state" / "cdlc-ledger.json"
    data = json.loads(target.read_text(encoding="utf-8"))
    assert data["version"] == cdlc_ledger.LEDGER_VERSION


def test_append_transition_appends_to_transitions_list(tmp_path):
    cdlc_ledger.append_transition(
        kind="generate", payload={"a": 1}, project_path=tmp_path,
    )
    cdlc_ledger.append_transition(
        kind="lock", payload={"b": 2}, project_path=tmp_path,
    )
    target = tmp_path / "state" / "cdlc-ledger.json"
    data = json.loads(target.read_text(encoding="utf-8"))
    assert len(data["transitions"]) == 2


def test_append_transition_records_iso_8601_utc_timestamp(tmp_path):
    cdlc_ledger.append_transition(
        kind="generate", payload={}, project_path=tmp_path,
    )
    target = tmp_path / "state" / "cdlc-ledger.json"
    data = json.loads(target.read_text(encoding="utf-8"))
    ts = data["transitions"][0]["ts"]
    assert ts.endswith("+00:00")


def test_append_transition_rejects_unknown_kind(tmp_path):
    with pytest.raises(ValueError, match="unknown transition kind"):
        cdlc_ledger.append_transition(
            kind="not-a-real-kind",
            payload={},
            project_path=tmp_path,
        )


def test_read_ledger_returns_empty_list_when_missing(tmp_path):
    result = cdlc_ledger.read_ledger(project_path=tmp_path)
    assert result == []


def test_read_ledger_returns_transitions_in_append_order(tmp_path):
    cdlc_ledger.append_transition(
        kind="generate", payload={"i": 1}, project_path=tmp_path,
    )
    cdlc_ledger.append_transition(
        kind="lock", payload={"i": 2}, project_path=tmp_path,
    )
    result = cdlc_ledger.read_ledger(project_path=tmp_path)
    payloads_in_order = [t["payload"]["i"] for t in result]
    assert payloads_in_order == [1, 2]
