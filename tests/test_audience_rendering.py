"""tests/test_audience_rendering.py — SPECTRE_AUDIENCE=pm dual-channel rendering tests."""
from __future__ import annotations

import io
import importlib
import json
import pathlib
import sys
import textwrap

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _reload_modules(monkeypatch, env: dict[str, str]):
    """Set env vars, reload _status and _glossary modules, return fresh _status."""
    # Clear all relevant env vars first
    for key in ("SPECTRE_AUDIENCE", "SPECTRE_JSON", "SPECTRE_GLOSSARY",
                 "SPECTRE_QUIET", "SPECTRE_VERBOSE", "SPECTRE_GLOSSARY_PATH"):
        monkeypatch.delenv(key, raising=False)
    for k, v in env.items():
        monkeypatch.setenv(k, v)

    # Reload _glossary to clear cache
    import bin._glossary as _g
    _g._GLOSSARY_CACHE = None
    _g._GLOSSARY_CACHE_PATH = None
    importlib.reload(_g)

    import bin._status as _s
    importlib.reload(_s)
    return _s


def _capture(monkeypatch, _status_mod, level, code, **fields):
    """Call _status.emit and capture (stdout_text, stderr_text)."""
    out = io.StringIO()
    err = io.StringIO()
    monkeypatch.setattr(sys, "stdout", out)
    monkeypatch.setattr(sys, "stderr", err)
    _status_mod.emit(level, code, **fields)
    return out.getvalue(), err.getvalue()


# ---------------------------------------------------------------------------
# Tests: text mode
# ---------------------------------------------------------------------------

def test_unset_audience_no_second_line(monkeypatch):
    """Default audience (unset) → single status line, no PM line."""
    _s = _reload_modules(monkeypatch, {})
    out, err = _capture(monkeypatch, _s, "ok", "walker.init",
                        rounds=1, pending=3, stop="none")
    lines = [l for l in out.splitlines() if l.strip()]
    assert len(lines) == 1
    assert lines[0].startswith("OK walker.init")


def test_pm_audience_emits_second_line(monkeypatch):
    """SPECTRE_AUDIENCE=pm → 2 lines; second is indented."""
    _s = _reload_modules(monkeypatch, {"SPECTRE_AUDIENCE": "pm"})
    out, err = _capture(monkeypatch, _s, "ok", "walker.init",
                        rounds=1, pending=3, stop="none")
    lines = out.splitlines()
    assert len(lines) >= 2
    assert lines[0].startswith("OK walker.init")
    assert lines[1].startswith("  ")  # indented PM line


def test_pm_substitutes_placeholders(monkeypatch, tmp_path):
    """PM sentence substitutes {field} placeholders from emit kwargs."""
    # Create a minimal fixture glossary with a known pm field
    fixture = textwrap.dedent("""\
        ## walker.init
        - kind: status
        - dev: Walker initialized.
        - pm: The interview has started. There are {pending} open questions for you to answer.
        - triggered_by: /vision.
        - user_action: None.
        - related: walker.answer
        - since: v0.4.0
    """)
    p = tmp_path / "glossary.md"
    p.write_text(fixture, encoding="utf-8")
    monkeypatch.setenv("SPECTRE_GLOSSARY_PATH", str(p))

    _s = _reload_modules(monkeypatch, {
        "SPECTRE_AUDIENCE": "pm",
        "SPECTRE_GLOSSARY_PATH": str(p),
    })
    out, err = _capture(monkeypatch, _s, "ok", "walker.init",
                        rounds=1, pending=5, stop="none")
    lines = out.splitlines()
    assert len(lines) >= 2
    assert "5" in lines[1], f"Expected pending=5 substituted in PM line, got: {lines[1]!r}"
    assert "open questions" in lines[1]


def test_pm_missing_glossary_entry_emits_fallback_comment(monkeypatch, tmp_path):
    """Emit a code not in glossary → 2nd line is the fallback comment form."""
    # Empty glossary
    p = tmp_path / "glossary.md"
    p.write_text("# empty\n", encoding="utf-8")
    monkeypatch.setenv("SPECTRE_GLOSSARY_PATH", str(p))

    _s = _reload_modules(monkeypatch, {
        "SPECTRE_AUDIENCE": "pm",
        "SPECTRE_GLOSSARY_PATH": str(p),
    })
    out, err = _capture(monkeypatch, _s, "ok", "walker.init", rounds=1)
    lines = out.splitlines()
    assert len(lines) >= 2
    assert "(no glossary entry for walker.init)" in lines[1]


def test_glossary_load_error_does_not_crash_emit(monkeypatch, tmp_path):
    """Point glossary path at a malformed file; emit still completes without exception."""
    # Write malformed glossary — parser raises GlossaryError
    bad = textwrap.dedent("""\
        ## walker.init
        - kind: status
        - dev: Walker initialized.
        - triggered_by: /vision.
        - user_action: None.
    """)
    # Missing required 'pm' field → GlossaryError
    p = tmp_path / "glossary.md"
    p.write_text(bad, encoding="utf-8")
    monkeypatch.setenv("SPECTRE_GLOSSARY_PATH", str(p))

    _s = _reload_modules(monkeypatch, {
        "SPECTRE_AUDIENCE": "pm",
        "SPECTRE_GLOSSARY_PATH": str(p),
    })
    # Should not raise
    out, err = _capture(monkeypatch, _s, "ok", "walker.init", rounds=1)
    lines = out.splitlines()
    assert len(lines) >= 1
    assert lines[0].startswith("OK walker.init")
    # Second line is the fallback (lookup returns None due to parse error)
    if len(lines) >= 2:
        assert lines[1].startswith("  ")


# ---------------------------------------------------------------------------
# Tests: JSON mode
# ---------------------------------------------------------------------------

def test_json_mode_no_pm_key_when_audience_unset(monkeypatch):
    """JSON mode without SPECTRE_AUDIENCE=pm and without SPECTRE_GLOSSARY=1 → no pm key."""
    _s = _reload_modules(monkeypatch, {"SPECTRE_JSON": "1"})
    out, err = _capture(monkeypatch, _s, "ok", "walker.init",
                        rounds=1, pending=3, stop="none")
    record = json.loads(out.strip())
    assert "pm" not in record


def test_json_mode_pm_key_when_audience_pm(monkeypatch):
    """SPECTRE_JSON=1 + SPECTRE_AUDIENCE=pm → pm key present in JSON record."""
    _s = _reload_modules(monkeypatch, {"SPECTRE_JSON": "1", "SPECTRE_AUDIENCE": "pm"})
    out, err = _capture(monkeypatch, _s, "ok", "walker.init",
                        rounds=1, pending=3, stop="none")
    record = json.loads(out.strip())
    assert "pm" in record
    assert isinstance(record["pm"], str)
    assert len(record["pm"]) > 0


def test_json_mode_pm_key_when_glossary_env_set(monkeypatch):
    """SPECTRE_JSON=1 + SPECTRE_GLOSSARY=1 (no SPECTRE_AUDIENCE=pm) → pm key present."""
    _s = _reload_modules(monkeypatch, {"SPECTRE_JSON": "1", "SPECTRE_GLOSSARY": "1"})
    out, err = _capture(monkeypatch, _s, "ok", "walker.init",
                        rounds=1, pending=3, stop="none")
    record = json.loads(out.strip())
    assert "pm" in record
    assert isinstance(record["pm"], str)
    assert len(record["pm"]) > 0
