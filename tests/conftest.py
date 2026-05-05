import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


@pytest.fixture
def plugin_root(tmp_path, monkeypatch):
    (tmp_path / "specs").mkdir()
    (tmp_path / "state").mkdir()
    monkeypatch.chdir(tmp_path)
    return tmp_path


@pytest.fixture
def initial_scratchpad(plugin_root):
    data = {
        "active_spec": None,
        "step": 1,
        "last_command": None,
        "exit_code": None,
        "delta": None,
        "timestamp": None,
        "failed_hypotheses": [],
    }
    path = plugin_root / "state" / "scratchpad.json"
    path.write_text(json.dumps(data))
    return path
