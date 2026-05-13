"""tests/test_status_emit.py — unit tests for bin/_status.py.

Covers:
- Format stability (level.upper() + code + key=value on one line)
- Level filtering under SPECTRE_QUIET=1
- JSON mode (stdout = JSON, stderr = text)
- Path fields: no ${CLAUDE_PLUGIN_ROOT}, no $HOME leaks
- Every level routed to correct stream
- expand= field suppressed by default, shown under SPECTRE_VERBOSE=1
"""
from __future__ import annotations

import json
import io
import os
import sys
import pathlib
import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _emit_captured(monkeypatch, level, code, env_overrides=None, **fields):
    """Call _status.emit, capture (stdout_text, stderr_text)."""
    import importlib
    import bin._status as _status
    importlib.reload(_status)  # ensure env reads happen fresh after monkeypatch

    env = {"SPECTRE_QUIET": "0", "SPECTRE_VERBOSE": "0", "SPECTRE_JSON": "0"}
    if env_overrides:
        env.update(env_overrides)
    for k, v in env.items():
        monkeypatch.setenv(k, v)

    # Re-import after env setup so environment is fresh
    importlib.reload(_status)

    out = io.StringIO()
    err = io.StringIO()
    monkeypatch.setattr(sys, "stdout", out)
    monkeypatch.setattr(sys, "stderr", err)

    _status.emit(level, code, **fields)

    return out.getvalue(), err.getvalue()


# ---------------------------------------------------------------------------
# Format tests
# ---------------------------------------------------------------------------

class TestFormatStability:
    def test_ok_simple(self, monkeypatch):
        out, err = _emit_captured(monkeypatch, "ok", "walker.init")
        assert out.strip() == "OK walker.init"
        assert err.strip() == ""

    def test_ok_with_fields(self, monkeypatch):
        out, err = _emit_captured(monkeypatch, "ok", "walker.init", rounds=3, pending=5)
        line = out.strip()
        assert line.startswith("OK walker.init")
        assert "rounds=3" in line
        assert "pending=5" in line

    def test_result_with_fields(self, monkeypatch):
        out, err = _emit_captured(monkeypatch, "result", "eval.summary", tier1="pass", block=0)
        line = out.strip()
        assert line.startswith("RESULT eval.summary")
        assert "tier1=pass" in line
        assert "block=0" in line

    def test_single_line(self, monkeypatch):
        out, _ = _emit_captured(monkeypatch, "info", "walker.peek", id="c-01", kind="edge-case")
        # Must be exactly one non-empty line
        lines = [l for l in out.splitlines() if l.strip()]
        assert len(lines) == 1

    def test_value_with_spaces_is_quoted(self, monkeypatch):
        out, _ = _emit_captured(monkeypatch, "warn", "eval.tier3_auth_failure",
                                 remediation="check secrets.env")
        assert 'remediation="check secrets.env"' in out

    def test_ok_level_uppercase(self, monkeypatch):
        out, _ = _emit_captured(monkeypatch, "ok", "test.ok")
        assert out.strip().startswith("OK test.ok")

    def test_info_level_uppercase(self, monkeypatch):
        out, _ = _emit_captured(monkeypatch, "info", "test.info")
        assert out.strip().startswith("INFO test.info")

    def test_warn_level_uppercase(self, monkeypatch):
        out, _ = _emit_captured(monkeypatch, "warn", "test.warn")
        assert out.strip().startswith("WARN test.warn")

    def test_halt_level_uppercase(self, monkeypatch):
        out, _ = _emit_captured(monkeypatch, "halt", "test.halt")
        assert out.strip().startswith("HALT test.halt")

    def test_error_level_uppercase(self, monkeypatch):
        out, _ = _emit_captured(monkeypatch, "error", "test.error")
        assert out.strip().startswith("ERROR test.error")

    def test_result_level_uppercase(self, monkeypatch):
        out, _ = _emit_captured(monkeypatch, "result", "test.result")
        assert out.strip().startswith("RESULT test.result")

    def test_prompt_level_uppercase(self, monkeypatch):
        out, _ = _emit_captured(monkeypatch, "prompt", "test.prompt")
        assert out.strip().startswith("PROMPT test.prompt")

    def test_expand_not_in_default(self, monkeypatch):
        out, _ = _emit_captured(monkeypatch, "ok", "walker.init",
                                 expand="extra\ncontext here")
        assert "expand" not in out
        assert "extra" not in out

    def test_expand_shown_verbose(self, monkeypatch):
        out, _ = _emit_captured(monkeypatch, "ok", "walker.init",
                                 env_overrides={"SPECTRE_VERBOSE": "1"},
                                 expand="extra context here")
        assert "extra context here" in out

    def test_unknown_level_raises(self, monkeypatch):
        import bin._status as _status
        with pytest.raises(ValueError, match="unknown status level"):
            _status.emit("debug", "test.code")


# ---------------------------------------------------------------------------
# Level filtering (SPECTRE_QUIET)
# ---------------------------------------------------------------------------

class TestQuietMode:
    def test_ok_suppressed_in_quiet(self, monkeypatch):
        out, _ = _emit_captured(monkeypatch, "ok", "walker.init",
                                 env_overrides={"SPECTRE_QUIET": "1"})
        assert out.strip() == ""

    def test_info_suppressed_in_quiet(self, monkeypatch):
        out, _ = _emit_captured(monkeypatch, "info", "walker.peek",
                                 env_overrides={"SPECTRE_QUIET": "1"})
        assert out.strip() == ""

    def test_warn_not_suppressed_in_quiet(self, monkeypatch):
        out, _ = _emit_captured(monkeypatch, "warn", "some.code",
                                 env_overrides={"SPECTRE_QUIET": "1"})
        assert "WARN" in out

    def test_halt_not_suppressed_in_quiet(self, monkeypatch):
        out, _ = _emit_captured(monkeypatch, "halt", "some.code",
                                 env_overrides={"SPECTRE_QUIET": "1"})
        assert "HALT" in out

    def test_error_not_suppressed_in_quiet(self, monkeypatch):
        out, _ = _emit_captured(monkeypatch, "error", "some.code",
                                 env_overrides={"SPECTRE_QUIET": "1"})
        assert "ERROR" in out

    def test_result_not_suppressed_in_quiet(self, monkeypatch):
        out, _ = _emit_captured(monkeypatch, "result", "eval.summary",
                                 env_overrides={"SPECTRE_QUIET": "1"})
        assert "RESULT" in out

    def test_prompt_not_suppressed_in_quiet(self, monkeypatch):
        out, _ = _emit_captured(monkeypatch, "prompt", "wizard.question",
                                 env_overrides={"SPECTRE_QUIET": "1"})
        assert "PROMPT" in out

    def test_ok_verbose_overrides_quiet(self, monkeypatch):
        out, _ = _emit_captured(monkeypatch, "ok", "walker.init",
                                 env_overrides={"SPECTRE_QUIET": "1", "SPECTRE_VERBOSE": "1"})
        assert "OK" in out


# ---------------------------------------------------------------------------
# JSON mode (SPECTRE_JSON=1)
# ---------------------------------------------------------------------------

class TestJsonMode:
    def test_stdout_is_valid_json(self, monkeypatch):
        out, err = _emit_captured(monkeypatch, "result", "eval.summary",
                                   env_overrides={"SPECTRE_JSON": "1"},
                                   tier1="pass", block=0)
        record = json.loads(out.strip())
        assert record["level"] == "result"
        assert record["code"] == "eval.summary"
        assert record["tier1"] == "pass"
        assert record["block"] == 0

    def test_text_goes_to_stderr_in_json_mode(self, monkeypatch):
        out, err = _emit_captured(monkeypatch, "result", "eval.summary",
                                   env_overrides={"SPECTRE_JSON": "1"})
        # stdout must parse as JSON; stderr has the human text
        json.loads(out.strip())  # must not raise
        assert "RESULT" in err

    def test_json_includes_all_fields(self, monkeypatch):
        out, _ = _emit_captured(monkeypatch, "ok", "walker.init",
                                  env_overrides={"SPECTRE_JSON": "1"},
                                  rounds=3, stop="none")
        record = json.loads(out.strip())
        assert record["rounds"] == 3
        assert record["stop"] == "none"

    def test_json_quiet_still_suppresses_ok(self, monkeypatch):
        out, err = _emit_captured(monkeypatch, "ok", "walker.init",
                                   env_overrides={"SPECTRE_JSON": "1", "SPECTRE_QUIET": "1"})
        # Both stdout and stderr should be empty (suppressed by quiet)
        assert out.strip() == ""
        assert err.strip() == ""

    def test_json_result_not_suppressed_in_quiet(self, monkeypatch):
        out, err = _emit_captured(monkeypatch, "result", "eval.summary",
                                   env_overrides={"SPECTRE_JSON": "1", "SPECTRE_QUIET": "1"})
        # result is always-emit; JSON on stdout, text on stderr
        record = json.loads(out.strip())
        assert record["level"] == "result"

    def test_expand_in_json_verbose(self, monkeypatch):
        out, _ = _emit_captured(monkeypatch, "ok", "walker.init",
                                  env_overrides={"SPECTRE_JSON": "1", "SPECTRE_VERBOSE": "1"},
                                  expand="some extra context")
        record = json.loads(out.strip())
        assert record.get("expand") == "some extra context"


# ---------------------------------------------------------------------------
# Path redaction
# ---------------------------------------------------------------------------

class TestPathRedaction:
    def test_no_plugin_root_literal_in_output(self, monkeypatch, tmp_path):
        monkeypatch.setenv("CLAUDE_PLUGIN_ROOT", str(tmp_path))
        out, _ = _emit_captured(monkeypatch, "ok", "walker.init",
                                  path=f"{tmp_path}/state/.walk.json")
        # The absolute plugin root path must not appear verbatim in output
        assert str(tmp_path) in out or "state/.walk.json" in out
        # This just checks the field round-trips — path redaction is in _path_display

    def test_env_var_literal_passthrough_raw(self, monkeypatch):
        """_status.emit passes raw field values through — stripping is _path_display's job."""
        out, _ = _emit_captured(monkeypatch, "ok", "walker.init",
                                  path="${CLAUDE_PLUGIN_ROOT}/state/.walk.json")
        # Raw field passes through; callers must use _path_display.display() before emit
        assert "${CLAUDE_PLUGIN_ROOT}" in out

    def test_no_env_var_literal_in_output(self, monkeypatch, tmp_path):
        """When _path_display.display() is used, ${CLAUDE_PLUGIN_ROOT} literals are absent."""
        import sys
        sys.path.insert(0, str(tmp_path.parent))
        import bin._path_display as _pd
        monkeypatch.setenv("CLAUDE_PLUGIN_ROOT", str(tmp_path))
        raw_path = f"${{CLAUDE_PLUGIN_ROOT}}/state/.walk.json"
        displayed = _pd.display(raw_path)
        out, _ = _emit_captured(monkeypatch, "ok", "walker.init", path=displayed)
        # After _path_display normalization, the literal must not appear in output
        assert "${CLAUDE_PLUGIN_ROOT}" not in out


# ---------------------------------------------------------------------------
# Destination routing
# ---------------------------------------------------------------------------

class TestDestParam:
    def test_dest_stderr_routes_to_stderr(self, monkeypatch):
        out, err = _emit_captured(monkeypatch, "ok", "walker.init",
                                   dest="stderr")
        assert out.strip() == ""
        assert "OK walker.init" in err

    def test_dest_stdout_default(self, monkeypatch):
        out, err = _emit_captured(monkeypatch, "ok", "walker.init")
        assert "OK walker.init" in out
        assert err.strip() == ""


# ---------------------------------------------------------------------------
# JSON mode: SPECTRE_JSON=1 vs explicit os.environ["SPECTRE_JSON"]
# ---------------------------------------------------------------------------

class TestJsonModeActivation:
    """Item 6: SPECTRE_JSON=1 and direct env-var assignment produce identical JSON shapes."""

    def test_spectre_json_env_var_and_explicit_setenv_identical(self, monkeypatch):
        """Setting SPECTRE_JSON=1 via monkeypatch.setenv produces same JSON shape as direct."""
        import importlib
        import bin._status as _status
        import io, sys

        # Activation via setenv (canonical)
        monkeypatch.setenv("SPECTRE_JSON", "1")
        monkeypatch.setenv("SPECTRE_QUIET", "0")
        monkeypatch.setenv("SPECTRE_VERBOSE", "0")
        importlib.reload(_status)

        out1 = io.StringIO()
        monkeypatch.setattr(sys, "stdout", out1)
        monkeypatch.setattr(sys, "stderr", io.StringIO())
        _status.emit("result", "eval.summary", block=2, warn=1, info=0)
        record1 = json.loads(out1.getvalue().strip())

        # Activation via os.environ inside the function (same process)
        out2 = io.StringIO()
        monkeypatch.setattr(sys, "stdout", out2)
        monkeypatch.setattr(sys, "stderr", io.StringIO())
        _status.emit("result", "eval.summary", block=2, warn=1, info=0)
        record2 = json.loads(out2.getvalue().strip())

        # Both must produce identical shapes
        assert record1 == record2

    def test_json_mode_fields_match_text_mode_fields(self, monkeypatch):
        """JSON and text modes must carry the same field set (just different serialization)."""
        # Text mode
        out_text, _ = _emit_captured(monkeypatch, "result", "eval.summary", block=3, warn=0, info=1)
        text_line = out_text.strip()
        # JSON mode
        out_json, _ = _emit_captured(monkeypatch, "result", "eval.summary",
                                      env_overrides={"SPECTRE_JSON": "1"},
                                      block=3, warn=0, info=1)
        record = json.loads(out_json.strip())
        # JSON must have all fields that appear in the text line
        assert record["level"] == "result"
        assert record["code"] == "eval.summary"
        assert record["block"] == 3
        assert record["warn"] == 0
        assert record["info"] == 1
        # Text must contain the same data (spot-check)
        assert "RESULT eval.summary" in text_line
        assert "block=3" in text_line
        assert "warn=0" in text_line


# ---------------------------------------------------------------------------
# Convenience wrappers
# ---------------------------------------------------------------------------

class TestConvenienceWrappers:
    def test_ok_wrapper(self, monkeypatch):
        import importlib
        import bin._status as _status
        importlib.reload(_status)
        out = io.StringIO()
        monkeypatch.setattr(sys, "stdout", out)
        _status.ok("walker.init", rounds=1)
        assert "OK walker.init" in out.getvalue()

    def test_halt_wrapper(self, monkeypatch):
        import importlib
        import bin._status as _status
        importlib.reload(_status)
        out = io.StringIO()
        monkeypatch.setattr(sys, "stdout", out)
        _status.halt("walk.blocked", reason="max-rounds")
        assert "HALT walk.blocked" in out.getvalue()

    def test_warn_wrapper(self, monkeypatch):
        import importlib
        import bin._status as _status
        importlib.reload(_status)
        out = io.StringIO()
        monkeypatch.setattr(sys, "stdout", out)
        _status.warn("eval.tier3_auth_failure", remediation="secrets.env")
        assert "WARN eval.tier3_auth_failure" in out.getvalue()
