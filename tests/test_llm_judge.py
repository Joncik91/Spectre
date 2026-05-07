"""Tests for bin/llm_judge.py — Tier 3 DeepSeek client. All HTTP mocked.

v0.5.2: updated for structured contradiction-tuple protocol.
"""
import json
import os
import pathlib
import socket
import threading
import time
from unittest import mock
from urllib import error as url_error

import pytest

from bin import llm_judge
from bin import findings


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_SPEC = "# Spec\n## 6. Steps\nstep 1: do something"

# Minimal spec with §8.1 for step-table builder tests.
_SPEC_WITH_STEPS = """\
# Spec

## 6. Steps

```yaml
- step: 1
  why: bootstrap
  action: run pip install foo
  verification: python -c "import foo"
- step: 2
  why: deploy
  action: systemctl start myapp
  verification: systemctl is-active myapp
```

## 8. Receiver Calibration

### 8.1 Hard contract

- mutates: /etc/myapp, /var/lib/myapp
- never-touches: /etc/passwd
- decision-budget: 3
- reboot-survival: no
"""

_CFG = llm_judge.JudgeConfig(
    enabled=True,
    api_key_env="TEST_DEEPSEEK_KEY",
    model="deepseek-v4-flash",
)

_CFG_DISABLED = llm_judge.JudgeConfig(
    enabled=False,
    api_key_env="TEST_DEEPSEEK_KEY",
    model="deepseek-v4-flash",
)


def _make_contradiction_resp(tuples: list[dict]) -> mock.MagicMock:
    """Return a mock urlopen context manager whose content is a JSON array of tuples.

    The API envelope wraps it as choices[0].message.content.
    """
    payload = json.dumps(
        {"choices": [{"message": {"content": json.dumps(tuples)}}]}
    ).encode()
    resp = mock.MagicMock()
    resp.read.return_value = payload
    resp.__enter__ = mock.Mock(return_value=resp)
    resp.__exit__ = mock.Mock(return_value=None)
    return resp


def _make_raw_resp(content: str) -> mock.MagicMock:
    """Return a mock urlopen context manager with raw string content."""
    payload = json.dumps(
        {"choices": [{"message": {"content": content}}]}
    ).encode()
    resp = mock.MagicMock()
    resp.read.return_value = payload
    resp.__enter__ = mock.Mock(return_value=resp)
    resp.__exit__ = mock.Mock(return_value=None)
    return resp


def _env(monkeypatch) -> None:
    monkeypatch.setenv("TEST_DEEPSEEK_KEY", "fake-key-for-tests")


# ---------------------------------------------------------------------------
# 1. disabled config → empty list
# ---------------------------------------------------------------------------


def test_evaluate_disabled_config_returns_empty_list():
    result = llm_judge.evaluate(_SPEC, config=_CFG_DISABLED)
    assert result == []


# ---------------------------------------------------------------------------
# 2. successful single call → findings returned, all tier 3
# ---------------------------------------------------------------------------


@mock.patch("urllib.request.urlopen")
def test_evaluate_single_call_returns_tier3_findings(mock_urlopen, monkeypatch):
    _env(monkeypatch)
    tuples = [
        {"kind": "missing-producer", "consumer_step": 5, "missing": "package:foo",
         "rationale": "step 5 imports foo, no earlier step installs it"},
    ]
    mock_urlopen.return_value = _make_contradiction_resp(tuples)
    result = llm_judge.evaluate(_SPEC, config=_CFG)
    assert len(result) == 1
    assert all(f.tier == 3 for f in result)


# ---------------------------------------------------------------------------
# 3. evaluate makes exactly ONE API call (not three)
# ---------------------------------------------------------------------------


@mock.patch("urllib.request.urlopen")
def test_evaluate_makes_one_api_call(mock_urlopen, monkeypatch):
    _env(monkeypatch)
    mock_urlopen.return_value = _make_contradiction_resp([])
    llm_judge.evaluate(_SPEC, config=_CFG)
    assert mock_urlopen.call_count == 1


# ---------------------------------------------------------------------------
# 4. contradiction findings are dismissable
# ---------------------------------------------------------------------------


@mock.patch("urllib.request.urlopen")
def test_evaluate_contradiction_findings_are_dismissable(mock_urlopen, monkeypatch):
    _env(monkeypatch)
    tuples = [
        {"kind": "ambiguous-contract", "step": 3,
         "ambiguous": "what install means", "rationale": "could be pip or apt"},
    ]
    mock_urlopen.return_value = _make_contradiction_resp(tuples)
    result = llm_judge.evaluate(_SPEC, config=_CFG)
    assert all(f.dismissable is True for f in result)


# ---------------------------------------------------------------------------
# 5. missing-producer tuple → block severity, consumer_step in location
# ---------------------------------------------------------------------------


@mock.patch("urllib.request.urlopen")
def test_evaluate_missing_producer_tuple_produces_block_finding(mock_urlopen, monkeypatch):
    _env(monkeypatch)
    # Use step 1 (exists in _SPEC_WITH_STEPS with "run pip install foo" action).
    tuples = [
        {"kind": "missing-producer", "consumer_step": 1, "missing": "package:foo",
         "rationale": "step 1 verification imports foo, no earlier step produces it"},
    ]
    # Primary call returns the block tuple; cite call returns a matching citation.
    cite_resp = json.dumps([{"index": 0, "step": 1, "citation": "run pip install foo"}])
    mock_urlopen.side_effect = [
        _make_contradiction_resp(tuples),
        _make_raw_resp(cite_resp),
    ]
    result = llm_judge.evaluate(_SPEC_WITH_STEPS, config=_CFG)
    block_findings = [f for f in result if f.kind == "missing-producer"]
    assert len(block_findings) == 1
    f = block_findings[0]
    assert f.kind == "missing-producer"
    assert f.severity == "block"
    assert f.location.step == 1


# ---------------------------------------------------------------------------
# 6. unrecognized tuple → info severity, rationale in message
# ---------------------------------------------------------------------------


@mock.patch("urllib.request.urlopen")
def test_evaluate_unrecognized_tuple_produces_info_finding(mock_urlopen, monkeypatch):
    _env(monkeypatch)
    tuples = [
        {"kind": "unrecognized",
         "description": "spec references external service with no SLA bound",
         "rationale": "gap outside taxonomy"},
    ]
    mock_urlopen.return_value = _make_contradiction_resp(tuples)
    result = llm_judge.evaluate(_SPEC, config=_CFG)
    assert len(result) == 1
    f = result[0]
    assert f.kind == "tier3-contradiction-unrecognized"
    assert f.severity == "info"
    # rationale should be present in message
    assert "gap outside taxonomy" in f.message


# ---------------------------------------------------------------------------
# 7. shallow-ownership tuple → block severity
# ---------------------------------------------------------------------------


@mock.patch("urllib.request.urlopen")
def test_evaluate_shallow_ownership_tuple_produces_block_finding(mock_urlopen, monkeypatch):
    _env(monkeypatch)
    # Use step 2 (exists in _SPEC_WITH_STEPS with "systemctl start myapp" action).
    tuples = [
        {"kind": "shallow-ownership", "step": 2,
         "claimed": "file:server.py",
         "actual": "scaffold only",
         "rationale": "step 2 verification expects systemctl is-active which step 2 never writes"},
    ]
    # Primary call returns block tuple; cite call returns a matching citation.
    cite_resp = json.dumps([{"index": 0, "step": 2, "citation": "systemctl start myapp"}])
    mock_urlopen.side_effect = [
        _make_contradiction_resp(tuples),
        _make_raw_resp(cite_resp),
    ]
    result = llm_judge.evaluate(_SPEC_WITH_STEPS, config=_CFG)
    block_findings = [f for f in result if f.kind == "shallow-ownership"]
    assert len(block_findings) == 1
    assert block_findings[0].severity == "block"


# ---------------------------------------------------------------------------
# 8. HTTPError → tier3-unavailable
# ---------------------------------------------------------------------------


@mock.patch("urllib.request.urlopen")
def test_evaluate_http_error_returns_tier3_unavailable(mock_urlopen, monkeypatch):
    _env(monkeypatch)
    monkeypatch.setattr(time, "sleep", lambda _d: None)
    mock_urlopen.side_effect = url_error.HTTPError(
        url="https://api.deepseek.com", code=429, msg="Too Many Requests",
        hdrs=None, fp=None,
    )
    result = llm_judge.evaluate(_SPEC, config=_CFG)
    assert result[0].kind == "tier3-unavailable"


# ---------------------------------------------------------------------------
# 9. HTTPError sentinel has severity=info
# ---------------------------------------------------------------------------


@mock.patch("urllib.request.urlopen")
def test_evaluate_http_error_severity_info(mock_urlopen, monkeypatch):
    _env(monkeypatch)
    monkeypatch.setattr(time, "sleep", lambda _d: None)
    mock_urlopen.side_effect = url_error.HTTPError(
        url="https://api.deepseek.com", code=401, msg="Unauthorized",
        hdrs=None, fp=None,
    )
    result = llm_judge.evaluate(_SPEC, config=_CFG)
    assert result[0].severity == "info"


# ---------------------------------------------------------------------------
# 10. URLError → tier3-unavailable
# ---------------------------------------------------------------------------


@mock.patch("urllib.request.urlopen")
def test_evaluate_url_error_returns_tier3_unavailable(mock_urlopen, monkeypatch):
    _env(monkeypatch)
    monkeypatch.setattr(time, "sleep", lambda _d: None)
    mock_urlopen.side_effect = url_error.URLError("Name or service not known")
    result = llm_judge.evaluate(_SPEC, config=_CFG)
    assert result[0].kind == "tier3-unavailable"


# ---------------------------------------------------------------------------
# 11. TimeoutError → tier3-unavailable
# ---------------------------------------------------------------------------


@mock.patch("urllib.request.urlopen")
def test_evaluate_timeout_returns_tier3_unavailable(mock_urlopen, monkeypatch):
    _env(monkeypatch)
    monkeypatch.setattr(time, "sleep", lambda _d: None)
    mock_urlopen.side_effect = TimeoutError("timed out")
    result = llm_judge.evaluate(_SPEC, config=_CFG)
    assert result[0].kind == "tier3-unavailable"


# ---------------------------------------------------------------------------
# 12. malformed JSON response → tier3-malformed-response (warn), no crash
# ---------------------------------------------------------------------------


@mock.patch("urllib.request.urlopen")
def test_evaluate_malformed_json_response_produces_malformed_finding(mock_urlopen, monkeypatch):
    _env(monkeypatch)
    resp = mock.MagicMock()
    resp.read.return_value = b"not-valid-json!!!"
    resp.__enter__ = mock.Mock(return_value=resp)
    resp.__exit__ = mock.Mock(return_value=None)
    mock_urlopen.return_value = resp
    result = llm_judge.evaluate(_SPEC, config=_CFG)
    # The API envelope is malformed — _call_deepseek raises json.JSONDecodeError
    # which is caught as a network-level error → tier3-unavailable.
    # (The content-level parse happens after _call_deepseek succeeds.)
    assert result[0].kind in {"tier3-unavailable", "tier3-malformed-response"}
    # Must not crash regardless of which path fires.
    assert len(result) >= 1


# ---------------------------------------------------------------------------
# 13. missing API key → tier3-unavailable
# ---------------------------------------------------------------------------


def test_evaluate_missing_api_key_returns_tier3_unavailable(monkeypatch):
    monkeypatch.delenv("TEST_DEEPSEEK_KEY", raising=False)
    result = llm_judge.evaluate(_SPEC, config=_CFG)
    assert result[0].kind == "tier3-unavailable"


# ---------------------------------------------------------------------------
# 14. tier3-unavailable sentinel is NOT dismissable
# ---------------------------------------------------------------------------


@mock.patch("urllib.request.urlopen")
def test_evaluate_unavailable_finding_is_dismissable_false(mock_urlopen, monkeypatch):
    _env(monkeypatch)
    mock_urlopen.side_effect = url_error.URLError("connection refused")
    result = llm_judge.evaluate(_SPEC, config=_CFG)
    assert result[0].dismissable is False


# ---------------------------------------------------------------------------
# 15. over-budget → skip calls, return tier3-unavailable
# ---------------------------------------------------------------------------


@mock.patch("urllib.request.urlopen")
def test_evaluate_over_budget_skips_calls_and_returns_unavailable(mock_urlopen, monkeypatch):
    _env(monkeypatch)
    # budget_tokens_per_spec default 50000 → spec must exceed 200000 chars
    huge_spec = "x" * 200_001
    cfg = llm_judge.JudgeConfig(
        enabled=True, api_key_env="TEST_DEEPSEEK_KEY", model="deepseek-v4-flash",
        budget_tokens_per_spec=50_000,
    )
    result = llm_judge.evaluate(huge_spec, config=cfg)
    assert result[0].kind == "tier3-unavailable"
    mock_urlopen.assert_not_called()


# ---------------------------------------------------------------------------
# 16. cap at 20 tuples per spec
# ---------------------------------------------------------------------------


@mock.patch("urllib.request.urlopen")
def test_evaluate_caps_findings_at_20(mock_urlopen, monkeypatch):
    _env(monkeypatch)
    # Return 50 tuples — should be capped at 20.
    tuples = [
        {"kind": "missing-producer", "consumer_step": i, "missing": f"pkg:{i}",
         "rationale": f"rationale {i}"}
        for i in range(1, 51)
    ]
    mock_urlopen.return_value = _make_contradiction_resp(tuples)
    result = llm_judge.evaluate(_SPEC, config=_CFG)
    assert len(result) <= 20


# ---------------------------------------------------------------------------
# 17. request uses response_format: json_object
# ---------------------------------------------------------------------------


@mock.patch("urllib.request.urlopen")
def test_evaluate_request_uses_response_format_json_object(mock_urlopen, monkeypatch):
    _env(monkeypatch)
    mock_urlopen.return_value = _make_contradiction_resp([])
    llm_judge.evaluate(_SPEC, config=_CFG)
    call_args = mock_urlopen.call_args_list[0]
    req = call_args[0][0]  # positional first arg is the Request object
    body = json.loads(req.data.decode("utf-8"))
    assert body.get("response_format") == {"type": "json_object"}


# ---------------------------------------------------------------------------
# 18. request uses Bearer auth header
# ---------------------------------------------------------------------------


@mock.patch("urllib.request.urlopen")
def test_evaluate_request_uses_bearer_auth(mock_urlopen, monkeypatch):
    _env(monkeypatch)
    mock_urlopen.return_value = _make_contradiction_resp([])
    llm_judge.evaluate(_SPEC, config=_CFG)
    call_args = mock_urlopen.call_args_list[0]
    req = call_args[0][0]
    assert req.get_header("Authorization") == "Bearer fake-key-for-tests"


# ---------------------------------------------------------------------------
# 19. content-level malformed JSON in DeepSeek response body → tier3-malformed-response
# ---------------------------------------------------------------------------


@mock.patch("urllib.request.urlopen")
def test_evaluate_content_level_malformed_json_produces_malformed_finding(mock_urlopen, monkeypatch):
    """DeepSeek returns valid API envelope but body is not a JSON array."""
    _env(monkeypatch)
    # The API envelope is valid, but the content is not parseable as contradiction tuples.
    mock_urlopen.return_value = _make_raw_resp("This is prose text, not JSON.")
    result = llm_judge.evaluate(_SPEC, config=_CFG)
    assert len(result) == 1
    assert result[0].kind == "tier3-malformed-response"
    assert result[0].severity == "warn"
    assert result[0].dismissable is False


# ---------------------------------------------------------------------------
# 20. unexpected exception → tier3-unavailable sentinel (never propagates)
# ---------------------------------------------------------------------------


@mock.patch("urllib.request.urlopen")
def test_evaluate_handles_unexpected_exception_as_tier3_unavailable(mock_urlopen, monkeypatch):
    _env(monkeypatch)
    mock_urlopen.side_effect = Exception("unexpected chaos")
    result = llm_judge.evaluate(_SPEC, config=_CFG)
    assert result[0].kind == "tier3-unavailable"


# ---------------------------------------------------------------------------
# 21. secrets.env fallback — key found in file when env var unset
# ---------------------------------------------------------------------------


@mock.patch("urllib.request.urlopen")
def test_tier3_reads_secrets_env_when_envvar_unset(mock_urlopen, monkeypatch, tmp_path):
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    secrets_file = tmp_path / "secrets.env"
    secrets_file.write_text("DEEPSEEK_API_KEY=test-key-value\n", encoding="utf-8")
    monkeypatch.setenv("SPECTRE_SECRETS_FILE", str(secrets_file))

    mock_urlopen.return_value = _make_contradiction_resp([])
    cfg = llm_judge.JudgeConfig(enabled=True, api_key_env="DEEPSEEK_API_KEY", model="deepseek-v4-flash")
    result = llm_judge.evaluate(_SPEC, config=cfg)
    # Tier 3 ran — no no-api-key sentinel among results.
    assert not any(f.kind == "tier3-unavailable" for f in result)


# ---------------------------------------------------------------------------
# 22. secrets.env fallback — quoted values are stripped
# ---------------------------------------------------------------------------


@mock.patch("urllib.request.urlopen")
def test_tier3_strips_quotes_from_secrets_env_value(mock_urlopen, monkeypatch, tmp_path):
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    secrets_file = tmp_path / "secrets.env"
    secrets_file.write_text('DEEPSEEK_API_KEY="quoted-value"\n', encoding="utf-8")
    monkeypatch.setenv("SPECTRE_SECRETS_FILE", str(secrets_file))

    cfg = llm_judge.JudgeConfig(enabled=True, api_key_env="DEEPSEEK_API_KEY", model="deepseek-v4-flash")
    # Verify the resolved key value is unquoted.
    key_result = llm_judge.resolve_api_key("DEEPSEEK_API_KEY")
    assert key_result is not None and key_result[0] == "quoted-value"


# ---------------------------------------------------------------------------
# 23. no-api-key when neither env nor file has the key
# ---------------------------------------------------------------------------


def test_tier3_skipped_no_api_key_when_neither_env_nor_file_has_key(monkeypatch, tmp_path):
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    nonexistent = tmp_path / "does_not_exist.env"
    monkeypatch.setenv("SPECTRE_SECRETS_FILE", str(nonexistent))

    cfg = llm_judge.JudgeConfig(enabled=True, api_key_env="DEEPSEEK_API_KEY", model="deepseek-v4-flash")
    result = llm_judge.evaluate(_SPEC, config=cfg)
    assert result[0].kind == "tier3-unavailable"


# ---------------------------------------------------------------------------
# 24. env var takes precedence over secrets file (env wins)
# ---------------------------------------------------------------------------


@mock.patch("urllib.request.urlopen")
def test_tier3_envvar_takes_precedence_over_secrets_file(mock_urlopen, monkeypatch, tmp_path):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "env-key-wins")
    secrets_file = tmp_path / "secrets.env"
    secrets_file.write_text("DEEPSEEK_API_KEY=file-key-loses\n", encoding="utf-8")
    monkeypatch.setenv("SPECTRE_SECRETS_FILE", str(secrets_file))

    key_result = llm_judge.resolve_api_key("DEEPSEEK_API_KEY")
    assert key_result is not None and key_result == ("env-key-wins", "env")


# ---------------------------------------------------------------------------
# 25. no-api-key sentinel message contains "no-api-key"
# ---------------------------------------------------------------------------


def test_tier3_renders_distinct_no_api_key_skip_reason(monkeypatch, tmp_path):
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    nonexistent = tmp_path / "does_not_exist.env"
    monkeypatch.setenv("SPECTRE_SECRETS_FILE", str(nonexistent))

    cfg = llm_judge.JudgeConfig(enabled=True, api_key_env="DEEPSEEK_API_KEY", model="deepseek-v4-flash")
    result = llm_judge.evaluate(_SPEC, config=cfg)
    assert "no-api-key" in result[0].message


# ---------------------------------------------------------------------------
# 26. _call_deepseek retries socket.timeout twice then succeeds (3 attempts)
# ---------------------------------------------------------------------------


@mock.patch("urllib.request.urlopen")
def test_call_deepseek_retries_on_socket_timeout(mock_urlopen, monkeypatch):
    monkeypatch.setenv("TEST_DEEPSEEK_KEY", "fake-key-for-tests")
    sleep_calls: list[float] = []
    monkeypatch.setattr(time, "sleep", lambda d: sleep_calls.append(d))

    mock_urlopen.side_effect = [
        socket.timeout("timed out"),
        socket.timeout("timed out"),
        _make_contradiction_resp([]),
    ]
    cfg = llm_judge.JudgeConfig(enabled=True, api_key_env="TEST_DEEPSEEK_KEY", model="deepseek-v4-flash")
    prompts = {"system": "s", "user": "u"}
    result = llm_judge._call_deepseek(prompts, config=cfg)
    assert mock_urlopen.call_count == 3
    assert len(sleep_calls) == 2


# ---------------------------------------------------------------------------
# 27. _call_deepseek retries HTTP 503 twice then succeeds
# ---------------------------------------------------------------------------


@mock.patch("urllib.request.urlopen")
def test_call_deepseek_retries_on_http_503(mock_urlopen, monkeypatch):
    monkeypatch.setenv("TEST_DEEPSEEK_KEY", "fake-key-for-tests")
    sleep_calls: list[float] = []
    monkeypatch.setattr(time, "sleep", lambda d: sleep_calls.append(d))

    _503 = url_error.HTTPError(url="https://api.deepseek.com", code=503, msg="Service Unavailable", hdrs=None, fp=None)
    mock_urlopen.side_effect = [
        _503,
        _503,
        _make_contradiction_resp([]),
    ]
    cfg = llm_judge.JudgeConfig(enabled=True, api_key_env="TEST_DEEPSEEK_KEY", model="deepseek-v4-flash")
    prompts = {"system": "s", "user": "u"}
    result = llm_judge._call_deepseek(prompts, config=cfg)
    assert mock_urlopen.call_count == 3
    assert len(sleep_calls) == 2


# ---------------------------------------------------------------------------
# 28. _call_deepseek does NOT retry HTTP 401 — single attempt, error propagates
# ---------------------------------------------------------------------------


@mock.patch("urllib.request.urlopen")
def test_call_deepseek_does_not_retry_on_http_401(mock_urlopen, monkeypatch):
    monkeypatch.setenv("TEST_DEEPSEEK_KEY", "fake-key-for-tests")
    sleep_calls: list[float] = []
    monkeypatch.setattr(time, "sleep", lambda d: sleep_calls.append(d))

    mock_urlopen.side_effect = url_error.HTTPError(
        url="https://api.deepseek.com", code=401, msg="Unauthorized", hdrs=None, fp=None
    )
    cfg = llm_judge.JudgeConfig(enabled=True, api_key_env="TEST_DEEPSEEK_KEY", model="deepseek-v4-flash")
    prompts = {"system": "s", "user": "u"}
    with pytest.raises(url_error.HTTPError):
        llm_judge._call_deepseek(prompts, config=cfg)
    assert mock_urlopen.call_count == 1
    assert sleep_calls == []


# ---------------------------------------------------------------------------
# 29. _call_deepseek gives up after 3 retries (4 total attempts)
# ---------------------------------------------------------------------------


@mock.patch("urllib.request.urlopen")
def test_call_deepseek_gives_up_after_3_retries(mock_urlopen, monkeypatch):
    monkeypatch.setenv("TEST_DEEPSEEK_KEY", "fake-key-for-tests")
    sleep_calls: list[float] = []
    monkeypatch.setattr(time, "sleep", lambda d: sleep_calls.append(d))

    mock_urlopen.side_effect = socket.timeout("always times out")
    cfg = llm_judge.JudgeConfig(enabled=True, api_key_env="TEST_DEEPSEEK_KEY", model="deepseek-v4-flash")
    prompts = {"system": "s", "user": "u"}
    with pytest.raises(socket.timeout):
        llm_judge._call_deepseek(prompts, config=cfg)
    assert mock_urlopen.call_count == 4
    assert len(sleep_calls) == 3


# ---------------------------------------------------------------------------
# 30. _run_contradiction_prompt: socket.timeout → tier3-unavailable with message
# ---------------------------------------------------------------------------


@mock.patch("urllib.request.urlopen")
def test_run_contradiction_prompt_timeout_returns_unavailable(mock_urlopen, monkeypatch):
    monkeypatch.setenv("TEST_DEEPSEEK_KEY", "fake-key-for-tests")
    monkeypatch.setattr(time, "sleep", lambda _d: None)

    mock_urlopen.side_effect = socket.timeout("timed out")
    cfg = llm_judge.JudgeConfig(enabled=True, api_key_env="TEST_DEEPSEEK_KEY", model="deepseek-v4-flash")
    step_table = llm_judge.build_step_table(_SPEC)
    result = llm_judge._run_contradiction_prompt(step_table, config=cfg)
    assert len(result) == 1
    assert result[0].kind == "tier3-unavailable"
    assert "contradiction-prompt" in result[0].message


# ---------------------------------------------------------------------------
# 31. JudgeConfig default timeout_s back-compat alias returns chunk_timeout_s
# ---------------------------------------------------------------------------


def test_default_timeout_s_is_180(monkeypatch):
    # Old code reads cfg.timeout_s — must still work via back-compat property.
    cfg = llm_judge.JudgeConfig(enabled=True, api_key_env="DEEPSEEK_API_KEY", model="deepseek-v4-flash")
    # Default chunk_timeout_s=60; the alias reflects it.
    assert cfg.timeout_s == cfg.chunk_timeout_s


# ---------------------------------------------------------------------------
# 32. backoff sleep durations are capped at _MAX_BACKOFF_S (60s)
# ---------------------------------------------------------------------------


@mock.patch("urllib.request.urlopen")
def test_backoff_capped_at_60_seconds(mock_urlopen, monkeypatch):
    monkeypatch.setenv("TEST_DEEPSEEK_KEY", "fake-key-for-tests")
    sleep_calls: list[float] = []
    monkeypatch.setattr(time, "sleep", lambda d: sleep_calls.append(d))
    # Patch random.uniform to 0 so we only measure the base delay
    monkeypatch.setattr("bin.llm_judge.random.uniform", lambda _a, _b: 0.0)

    mock_urlopen.side_effect = socket.timeout("always times out")
    cfg = llm_judge.JudgeConfig(enabled=True, api_key_env="TEST_DEEPSEEK_KEY", model="deepseek-v4-flash")
    prompts = {"system": "s", "user": "u"}
    with pytest.raises(socket.timeout):
        llm_judge._call_deepseek(prompts, config=cfg)
    # Without cap: 2^1=2, 2^2=4, 2^3=8 — all under 60. Verify all ≤ 60.
    assert all(d <= llm_judge._MAX_BACKOFF_S for d in sleep_calls)
    assert len(sleep_calls) == 3


# ---------------------------------------------------------------------------
# 33. chunk_timeout fires → retries (preserves #12 P2 behavior)
# ---------------------------------------------------------------------------


@mock.patch("urllib.request.urlopen")
def test_call_deepseek_chunk_timeout_does_retry(mock_urlopen, monkeypatch):
    """socket.timeout (per-chunk recv) IS retried — #12 P2 behavior preserved."""
    monkeypatch.setenv("TEST_DEEPSEEK_KEY", "fake-key-for-tests")
    monkeypatch.setattr(time, "sleep", lambda _d: None)

    mock_urlopen.side_effect = [
        socket.timeout("chunk timeout"),
        _make_contradiction_resp([]),
    ]
    cfg = llm_judge.JudgeConfig(
        enabled=True,
        api_key_env="TEST_DEEPSEEK_KEY",
        model="deepseek-v4-flash",
        chunk_timeout_s=60,
        total_timeout_s=600,
    )
    prompts = {"system": "s", "user": "u"}
    result = llm_judge._call_deepseek(prompts, config=cfg)
    assert mock_urlopen.call_count == 2  # first failed, second succeeded
    # result is the content string (JSON array)
    assert isinstance(result, str)


# ---------------------------------------------------------------------------
# 34. total_timeout fires → NOT retried, _TotalTimeoutError propagates
# ---------------------------------------------------------------------------


@mock.patch("urllib.request.urlopen")
def test_call_deepseek_total_timeout_does_not_retry(mock_urlopen, monkeypatch):
    """_TotalTimeoutError is NOT retried — hard ceiling."""
    monkeypatch.setenv("TEST_DEEPSEEK_KEY", "fake-key-for-tests")
    monkeypatch.setattr(time, "sleep", lambda _d: None)

    timer_fn_holder: list = []

    class _SyncTimer:
        def __init__(self, interval, fn, *args, **kwargs):
            timer_fn_holder.append(fn)
            self.daemon = True

        def start(self):
            pass  # don't auto-fire — let resp.read() trigger it

        def cancel(self):
            pass

    monkeypatch.setattr("bin.llm_judge.threading.Timer", _SyncTimer)

    class _FakeResp:
        def read(self):
            if timer_fn_holder:
                timer_fn_holder[0]()  # sets _total_exc
            raise OSError("connection closed by timer")

        def close(self):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *_):
            pass

    mock_urlopen.return_value = _FakeResp()

    cfg = llm_judge.JudgeConfig(
        enabled=True,
        api_key_env="TEST_DEEPSEEK_KEY",
        model="deepseek-v4-flash",
        chunk_timeout_s=60,
        total_timeout_s=600,
    )
    prompts = {"system": "s", "user": "u"}
    with pytest.raises(llm_judge._TotalTimeoutError):
        llm_judge._call_deepseek(prompts, config=cfg)

    # Must NOT have retried — only 1 urlopen call.
    assert mock_urlopen.call_count == 1


# ---------------------------------------------------------------------------
# 35. total_timeout takes precedence even after partial success
# ---------------------------------------------------------------------------


@mock.patch("urllib.request.urlopen")
def test_call_deepseek_total_timeout_takes_precedence_over_chunk_count(mock_urlopen, monkeypatch):
    """Even if chunk-timeout retry would succeed, _TotalTimeoutError aborts at 2nd attempt."""
    monkeypatch.setenv("TEST_DEEPSEEK_KEY", "fake-key-for-tests")
    monkeypatch.setattr(time, "sleep", lambda _d: None)

    timer_fn_holder: list = []

    class _SyncTimer:
        def __init__(self, interval, fn, *args, **kwargs):
            timer_fn_holder.append(fn)
            self.daemon = True

        def start(self):
            pass

        def cancel(self):
            pass

    monkeypatch.setattr("bin.llm_judge.threading.Timer", _SyncTimer)

    call_count = [0]

    class _TimerFiringResp:
        def read(self):
            if timer_fn_holder:
                timer_fn_holder[-1]()  # sets _total_exc for this attempt
            raise OSError("connection closed by total-timeout")

        def close(self):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *_):
            pass

    mock_urlopen.side_effect = [
        socket.timeout("chunk timeout"),
        _TimerFiringResp(),
    ]

    cfg = llm_judge.JudgeConfig(
        enabled=True,
        api_key_env="TEST_DEEPSEEK_KEY",
        model="deepseek-v4-flash",
        chunk_timeout_s=60,
        total_timeout_s=600,
    )
    prompts = {"system": "s", "user": "u"}
    with pytest.raises(llm_judge._TotalTimeoutError):
        llm_judge._call_deepseek(prompts, config=cfg)

    assert mock_urlopen.call_count == 2


# ---------------------------------------------------------------------------
# 36. back-compat: old timeout_s key in JudgeConfig loads as chunk_timeout_s
# ---------------------------------------------------------------------------


def test_judge_config_back_compat_timeout_s_loads_as_chunk_timeout_s():
    """Setting timeout_s= kwarg (legacy) reflects in chunk_timeout_s."""
    cfg = llm_judge.JudgeConfig(
        enabled=True,
        api_key_env="DEEPSEEK_API_KEY",
        model="deepseek-v4-flash",
    )
    cfg.timeout_s = 180
    assert cfg.chunk_timeout_s == 180
    assert cfg.timeout_s == 180


# ---------------------------------------------------------------------------
# 37. JudgeConfig default total_timeout_s is 600
# ---------------------------------------------------------------------------


def test_judge_config_default_total_timeout_is_600():
    cfg = llm_judge.JudgeConfig(
        enabled=True,
        api_key_env="DEEPSEEK_API_KEY",
        model="deepseek-v4-flash",
    )
    assert cfg.total_timeout_s == 600


# ---------------------------------------------------------------------------
# 38. setup_wizard.write_config emits both chunk_timeout_s and total_timeout_s
# ---------------------------------------------------------------------------


def test_setup_wizard_writes_both_timeouts(tmp_path):
    """write_config must write chunk_timeout_s and total_timeout_s to TOML."""
    from bin import setup_wizard

    target = tmp_path / "reviewer.toml"
    setup_wizard.write_config(target, enabled=True, api_key_env="DEEPSEEK_API_KEY")
    text = target.read_text(encoding="utf-8")
    assert "chunk_timeout_s = 60" in text
    assert "total_timeout_s = 600" in text
    lines_with_bare_timeout = [
        ln for ln in text.splitlines()
        if ln.strip().startswith("timeout_s")
    ]
    assert lines_with_bare_timeout == [], f"Unexpected bare timeout_s line: {lines_with_bare_timeout}"


# ---------------------------------------------------------------------------
# 39. Integration: total_timeout aborts within total_timeout_s + chunk_timeout_s
# ---------------------------------------------------------------------------


def test_total_timeout_aborts_within_total_plus_chunk_window(monkeypatch):
    """Wall-clock abort lands between total_timeout_s and total_timeout_s + chunk_timeout_s."""
    import http.server
    import socketserver

    chunk_timeout_s = 5
    total_timeout_s = 3

    _handler_unblock = threading.Event()

    class _HangingHandler(http.server.BaseHTTPRequestHandler):
        """Returns HTTP 200 + a tiny chunk, then hangs in the response body."""

        def do_POST(self):  # noqa: N802
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", "100000")
            self.end_headers()
            self.wfile.write(b"X")
            self.wfile.flush()
            _handler_unblock.wait(timeout=60)

        def log_message(self, fmt, *args):
            pass

    server = socketserver.ThreadingTCPServer(("127.0.0.1", 0), _HangingHandler)
    server.allow_reuse_address = True
    port = server.server_address[1]

    server_thread = threading.Thread(target=server.serve_forever, daemon=True)
    server_thread.start()
    try:
        monkeypatch.setenv("TEST_DEEPSEEK_KEY", "fake-key-for-tests")
        monkeypatch.setattr("bin.llm_judge.time.sleep", lambda _d: None)

        cfg = llm_judge.JudgeConfig(
            enabled=True,
            api_key_env="TEST_DEEPSEEK_KEY",
            model="deepseek-v4-flash",
            base_url=f"http://127.0.0.1:{port}",
            chunk_timeout_s=chunk_timeout_s,
            total_timeout_s=total_timeout_s,
        )
        prompts = {"system": "s", "user": "u"}

        t0 = time.monotonic()
        with pytest.raises(llm_judge._TotalTimeoutError):
            llm_judge._call_deepseek(prompts, config=cfg)
        elapsed = time.monotonic() - t0

        assert elapsed >= total_timeout_s, (
            f"Abort too early: {elapsed:.2f}s < total_timeout_s={total_timeout_s}s"
        )
        upper = total_timeout_s + chunk_timeout_s + 2.0
        assert elapsed <= upper, (
            f"Abort too slow: {elapsed:.2f}s > {upper}s "
            f"(total={total_timeout_s}s + chunk={chunk_timeout_s}s + 2.0s epsilon)"
        )
    finally:
        _handler_unblock.set()
        server.shutdown()
        server_thread.join(timeout=5)


# ---------------------------------------------------------------------------
# 40. build_step_table: spec with no contracts → empty produces/requires
# ---------------------------------------------------------------------------


def test_build_step_table_no_contracts_empty_produces_requires():
    """Spec without priority-3 contracts → produces/requires are empty lists."""
    table = llm_judge.build_step_table(_SPEC_WITH_STEPS)
    assert "steps" in table
    assert len(table["steps"]) == 2
    step1 = next(s for s in table["steps"] if s["step"] == 1)
    step2 = next(s for s in table["steps"] if s["step"] == 2)
    assert step1["produces"] == []
    assert step1["requires"] == []
    assert step2["produces"] == []
    assert step2["requires"] == []


# ---------------------------------------------------------------------------
# 41. build_step_table: step_objects with produces/requires → populated entries
# ---------------------------------------------------------------------------


def test_build_step_table_step_objects_populate_produces_requires():
    """Priority-3 step objects provide produces/requires fields."""
    # Simulate step objects as simple dicts (matching the getattr/dict logic).
    step_objects = [
        {"step": 1, "produces": ["package:foo", "file:/app/config.py"], "requires": []},
        {"step": 2, "produces": [], "requires": ["package:foo"]},
    ]
    table = llm_judge.build_step_table(_SPEC_WITH_STEPS, step_objects=step_objects)
    step1 = next(s for s in table["steps"] if s["step"] == 1)
    step2 = next(s for s in table["steps"] if s["step"] == 2)
    assert step1["produces"] == ["package:foo", "file:/app/config.py"]
    assert step1["requires"] == []
    assert step2["requires"] == ["package:foo"]


# ---------------------------------------------------------------------------
# 42. build_step_table: dataclass-style step objects (getattr path)
# ---------------------------------------------------------------------------


def test_build_step_table_dataclass_step_objects():
    """Dataclass-style objects with produces/requires via getattr."""
    from dataclasses import dataclass

    @dataclass
    class FakeStep:
        step: int
        produces: list
        requires: list

    step_objects = [
        FakeStep(step=1, produces=["artifact:x"], requires=[]),
        FakeStep(step=2, produces=[], requires=["artifact:x"]),
    ]
    table = llm_judge.build_step_table(_SPEC_WITH_STEPS, step_objects=step_objects)
    step1 = next(s for s in table["steps"] if s["step"] == 1)
    assert step1["produces"] == ["artifact:x"]


# ---------------------------------------------------------------------------
# 43. build_step_table: step objects without produces/requires (pre-priority-3)
# ---------------------------------------------------------------------------


def test_build_step_table_step_objects_missing_fields_graceful():
    """Step objects that predate priority-3 (no produces/requires) → empty lists."""
    from dataclasses import dataclass

    @dataclass
    class LegacyStep:
        step: int
        action: str

    step_objects = [
        LegacyStep(step=1, action="something"),
        LegacyStep(step=2, action="other"),
    ]
    table = llm_judge.build_step_table(_SPEC_WITH_STEPS, step_objects=step_objects)
    assert len(table["steps"]) == 2
    step1 = next(s for s in table["steps"] if s["step"] == 1)
    step2 = next(s for s in table["steps"] if s["step"] == 2)
    assert step1["produces"] == []
    assert step1["requires"] == []
    assert step2["produces"] == []
    assert step2["requires"] == []


# ---------------------------------------------------------------------------
# 44. build_step_table: §8.1 fields are extracted into table
# ---------------------------------------------------------------------------


def test_build_step_table_extracts_calibration_section():
    """mutates/never_touches extracted from §8.1 into the step table."""
    table = llm_judge.build_step_table(_SPEC_WITH_STEPS)
    assert "/etc/myapp" in table["mutates"] or any("/etc/myapp" in m for m in table["mutates"])
    assert "/etc/passwd" in table["never_touches"] or any("/etc/passwd" in m for m in table["never_touches"])


# ---------------------------------------------------------------------------
# 45. severity mapping: all taxonomy kinds map to documented severity
# ---------------------------------------------------------------------------


def test_severity_mapping_all_taxonomy_kinds():
    """Every kind in the contradiction taxonomy maps to the documented severity."""
    sev = findings.TIER3_CONTRADICTION_SEVERITY
    assert sev["missing-producer"] == "block"
    assert sev["shallow-ownership"] == "block"
    assert sev["ambiguous-contract"] == "warn"
    assert sev["negative-path-omission"] == "info"
    assert sev["idempotency-risk"] == "info"
    assert sev["migration-on-existing-state"] == "info"
    assert sev["partial-failure-window"] == "warn"
    assert sev["concurrency-race"] == "info"
    assert sev["verification-false-positive"] == "warn"
    assert sev["tier3-contradiction-unrecognized"] == "info"
    assert sev["tier3-malformed-response"] == "warn"


# ---------------------------------------------------------------------------
# 46. _parse_contradiction_findings: missing-producer includes consumer_step
# ---------------------------------------------------------------------------


def test_parse_contradiction_findings_missing_producer_consumer_step():
    """consumer_step field drives the step location for missing-producer."""
    content = json.dumps([
        {"kind": "missing-producer", "consumer_step": 7, "missing": "db-schema",
         "rationale": "step 7 runs migration but schema never created"}
    ])
    result = llm_judge._parse_contradiction_findings(content)
    assert len(result) == 1
    assert result[0].kind == "missing-producer"
    assert result[0].location.step == 7
    assert "db-schema" in result[0].message


# ---------------------------------------------------------------------------
# 47. _parse_contradiction_findings: dict-wrapped response ({"contradictions": [...]})
# ---------------------------------------------------------------------------


def test_parse_contradiction_findings_accepts_dict_wrapper():
    """DeepSeek sometimes wraps array in a dict — parser handles it."""
    content = json.dumps({
        "contradictions": [
            {"kind": "ambiguous-contract", "step": 2,
             "ambiguous": "install dependencies",
             "rationale": "could be pip or apt-get"}
        ]
    })
    result = llm_judge._parse_contradiction_findings(content)
    assert len(result) == 1
    assert result[0].kind == "ambiguous-contract"


# ---------------------------------------------------------------------------
# 48. _parse_contradiction_findings: unknown kind → tier3-contradiction-unrecognized
# ---------------------------------------------------------------------------


def test_parse_contradiction_findings_unknown_kind_mapped_to_unrecognized():
    """An unknown kind value from the model is mapped to tier3-contradiction-unrecognized."""
    content = json.dumps([
        {"kind": "invented-by-model", "step": 1,
         "rationale": "some rationale here"}
    ])
    result = llm_judge._parse_contradiction_findings(content)
    assert len(result) == 1
    assert result[0].kind == "tier3-contradiction-unrecognized"


# ---------------------------------------------------------------------------
# 49. evaluate: system prompt sent to DeepSeek contains key taxonomy kinds
# ---------------------------------------------------------------------------


@mock.patch("urllib.request.urlopen")
def test_evaluate_system_prompt_contains_taxonomy_kinds(mock_urlopen, monkeypatch):
    """System prompt must list key taxonomy kinds (not prose boilerplate)."""
    _env(monkeypatch)
    mock_urlopen.return_value = _make_contradiction_resp([])
    llm_judge.evaluate(_SPEC, config=_CFG)
    call_args = mock_urlopen.call_args_list[0]
    req = call_args[0][0]
    body = json.loads(req.data.decode("utf-8"))
    system_prompt = body["messages"][0]["content"]
    assert "missing-producer" in system_prompt
    assert "shallow-ownership" in system_prompt
    assert "ambiguous-contract" in system_prompt


# ---------------------------------------------------------------------------
# 50. evaluate: user message contains step table JSON (not raw spec text)
# ---------------------------------------------------------------------------


@mock.patch("urllib.request.urlopen")
def test_evaluate_user_message_contains_step_table_json(mock_urlopen, monkeypatch):
    """User message must include the structured step table, not raw spec text."""
    _env(monkeypatch)
    mock_urlopen.return_value = _make_contradiction_resp([])
    llm_judge.evaluate(_SPEC_WITH_STEPS, config=_CFG)
    call_args = mock_urlopen.call_args_list[0]
    req = call_args[0][0]
    body = json.loads(req.data.decode("utf-8"))
    user_msg = body["messages"][1]["content"]
    # Step table JSON should contain the structured keys
    assert '"steps"' in user_msg
    assert '"action_summary"' in user_msg


# ---------------------------------------------------------------------------
# 51. build_step_table: 5000-char action is truncated to ≤ ~1050 chars with suffix
# ---------------------------------------------------------------------------


def test_build_step_table_truncates_long_action():
    """A 5000-char action field must be truncated to ≤ _STEP_FIELD_TRUNCATE + suffix."""
    long_action = "x" * 5000
    spec = f"""\
# Spec

## 6. Steps

```yaml
- step: 1
  why: test truncation
  action: {long_action}
  verification: check it
```
"""
    table = llm_judge.build_step_table(spec)
    step1 = next(s for s in table["steps"] if s["step"] == 1)
    action_summary = step1["action_summary"]
    # Must be capped: 1000 chars + suffix overhead (≤ ~1050 total)
    assert len(action_summary) <= llm_judge._STEP_FIELD_TRUNCATE + 50
    # Suffix must be present to signal incompleteness
    assert "truncated" in action_summary
    assert "4000 more chars" in action_summary


# ---------------------------------------------------------------------------
# 52. build_step_table: 5000-char verification is truncated with suffix
# ---------------------------------------------------------------------------


def test_build_step_table_truncates_long_verification():
    """A 5000-char verification field must be truncated similarly."""
    long_ver = "y" * 5000
    spec = f"""\
# Spec

## 6. Steps

```yaml
- step: 1
  why: test truncation
  action: short action
  verification: {long_ver}
```
"""
    table = llm_judge.build_step_table(spec)
    step1 = next(s for s in table["steps"] if s["step"] == 1)
    ver_summary = step1["verification_summary"]
    assert len(ver_summary) <= llm_judge._STEP_FIELD_TRUNCATE + 50
    assert "truncated" in ver_summary


# ---------------------------------------------------------------------------
# 53. build_step_table: short fields pass through verbatim (no truncation)
# ---------------------------------------------------------------------------


def test_build_step_table_short_fields_pass_through_verbatim():
    """Fields under the cap must not be modified."""
    table = llm_judge.build_step_table(_SPEC_WITH_STEPS)
    step1 = next(s for s in table["steps"] if s["step"] == 1)
    # action from _SPEC_WITH_STEPS is "run pip install foo" — well under cap
    assert step1["action_summary"] == "run pip install foo"
    assert "truncated" not in step1["action_summary"]
    # verification from _SPEC_WITH_STEPS is 'python -c "import foo"'
    # The parser strips trailing quotes, so the value ends without the closing "
    assert "import foo" in step1["verification_summary"]
    assert "truncated" not in step1["verification_summary"]
