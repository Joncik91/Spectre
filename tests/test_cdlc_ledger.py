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
