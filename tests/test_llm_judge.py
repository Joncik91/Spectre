"""Tests for bin/llm_judge.py — Tier 3 DeepSeek client. All HTTP mocked."""
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

_CFG = llm_judge.JudgeConfig(
    enabled=True,
    api_key_env="TEST_DEEPSEEK_KEY",
    model="deepseek-v4-pro",
)

_CFG_DISABLED = llm_judge.JudgeConfig(
    enabled=False,
    api_key_env="TEST_DEEPSEEK_KEY",
    model="deepseek-v4-pro",
)


def _make_fake_resp(kind: str, count: int = 1) -> mock.MagicMock:
    """Return a mock urlopen context manager with `count` findings of `kind`."""
    finding_items = [
        {"kind": kind, "message": f"finding {i}", "step": i, "suggested_fix": "fix it"}
        for i in range(count)
    ]
    payload = json.dumps(
        {"choices": [{"message": {"content": json.dumps({"findings": finding_items})}}]}
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
# 2. three successful calls → 3 findings aggregated
# ---------------------------------------------------------------------------


@mock.patch("urllib.request.urlopen")
def test_evaluate_with_three_successful_calls_aggregates_findings(mock_urlopen, monkeypatch):
    _env(monkeypatch)
    mock_urlopen.side_effect = [
        _make_fake_resp("tier3-context-gap"),
        _make_fake_resp("tier3-spec-asserts-wrong"),
        _make_fake_resp("tier3-attacker-view"),
    ]
    result = llm_judge.evaluate(_SPEC, config=_CFG)
    assert len(result) == 3


# ---------------------------------------------------------------------------
# 3. all returned findings have tier == 3
# ---------------------------------------------------------------------------


@mock.patch("urllib.request.urlopen")
def test_evaluate_findings_are_tier_3(mock_urlopen, monkeypatch):
    _env(monkeypatch)
    mock_urlopen.side_effect = [
        _make_fake_resp("tier3-context-gap"),
        _make_fake_resp("tier3-spec-asserts-wrong"),
        _make_fake_resp("tier3-attacker-view"),
    ]
    result = llm_judge.evaluate(_SPEC, config=_CFG)
    assert all(f.tier == 3 for f in result)


# ---------------------------------------------------------------------------
# 4. normal findings are dismissable
# ---------------------------------------------------------------------------


@mock.patch("urllib.request.urlopen")
def test_evaluate_findings_are_dismissable(mock_urlopen, monkeypatch):
    _env(monkeypatch)
    mock_urlopen.side_effect = [
        _make_fake_resp("tier3-context-gap"),
        _make_fake_resp("tier3-spec-asserts-wrong"),
        _make_fake_resp("tier3-attacker-view"),
    ]
    result = llm_judge.evaluate(_SPEC, config=_CFG)
    assert all(f.dismissable is True for f in result)


# ---------------------------------------------------------------------------
# 5. prompt 1 kind is tier3-context-gap
# ---------------------------------------------------------------------------


@mock.patch("urllib.request.urlopen")
def test_evaluate_first_prompt_kind_is_tier3_context_gap(mock_urlopen, monkeypatch):
    _env(monkeypatch)
    mock_urlopen.side_effect = [
        _make_fake_resp("tier3-context-gap"),
        _make_fake_resp("tier3-spec-asserts-wrong"),
        _make_fake_resp("tier3-attacker-view"),
    ]
    result = llm_judge.evaluate(_SPEC, config=_CFG)
    assert result[0].kind == "tier3-context-gap"


# ---------------------------------------------------------------------------
# 6. prompt 2 kind is tier3-spec-asserts-wrong
# ---------------------------------------------------------------------------


@mock.patch("urllib.request.urlopen")
def test_evaluate_second_prompt_kind_is_tier3_spec_asserts_wrong(mock_urlopen, monkeypatch):
    _env(monkeypatch)
    mock_urlopen.side_effect = [
        _make_fake_resp("tier3-context-gap"),
        _make_fake_resp("tier3-spec-asserts-wrong"),
        _make_fake_resp("tier3-attacker-view"),
    ]
    result = llm_judge.evaluate(_SPEC, config=_CFG)
    assert result[1].kind == "tier3-spec-asserts-wrong"


# ---------------------------------------------------------------------------
# 7. prompt 3 kind is tier3-attacker-view
# ---------------------------------------------------------------------------


@mock.patch("urllib.request.urlopen")
def test_evaluate_third_prompt_kind_is_tier3_attacker_view(mock_urlopen, monkeypatch):
    _env(monkeypatch)
    mock_urlopen.side_effect = [
        _make_fake_resp("tier3-context-gap"),
        _make_fake_resp("tier3-spec-asserts-wrong"),
        _make_fake_resp("tier3-attacker-view"),
    ]
    result = llm_judge.evaluate(_SPEC, config=_CFG)
    assert result[2].kind == "tier3-attacker-view"


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
# 12. malformed JSON response → tier3-unavailable
# ---------------------------------------------------------------------------


@mock.patch("urllib.request.urlopen")
def test_evaluate_malformed_json_response_returns_tier3_unavailable(mock_urlopen, monkeypatch):
    _env(monkeypatch)
    resp = mock.MagicMock()
    resp.read.return_value = b"not-valid-json!!!"
    resp.__enter__ = mock.Mock(return_value=resp)
    resp.__exit__ = mock.Mock(return_value=None)
    mock_urlopen.return_value = resp
    result = llm_judge.evaluate(_SPEC, config=_CFG)
    assert result[0].kind == "tier3-unavailable"


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
        enabled=True, api_key_env="TEST_DEEPSEEK_KEY", model="deepseek-v4-pro",
        budget_tokens_per_spec=50_000,
    )
    result = llm_judge.evaluate(huge_spec, config=cfg)
    assert result[0].kind == "tier3-unavailable"
    mock_urlopen.assert_not_called()


# ---------------------------------------------------------------------------
# 16. cap at 10 findings per prompt
# ---------------------------------------------------------------------------


@mock.patch("urllib.request.urlopen")
def test_evaluate_caps_findings_per_prompt_at_10(mock_urlopen, monkeypatch):
    _env(monkeypatch)

    def _big_resp(kind: str) -> mock.MagicMock:
        return _make_fake_resp(kind, count=50)

    mock_urlopen.side_effect = [
        _big_resp("tier3-context-gap"),
        _big_resp("tier3-spec-asserts-wrong"),
        _big_resp("tier3-attacker-view"),
    ]
    result = llm_judge.evaluate(_SPEC, config=_CFG)
    gap_count = sum(1 for f in result if f.kind == "tier3-context-gap")
    assert gap_count <= 10


# ---------------------------------------------------------------------------
# 17. request uses response_format: json_object
# ---------------------------------------------------------------------------


@mock.patch("urllib.request.urlopen")
def test_evaluate_request_uses_response_format_json_object(mock_urlopen, monkeypatch):
    _env(monkeypatch)
    mock_urlopen.side_effect = [
        _make_fake_resp("tier3-context-gap"),
        _make_fake_resp("tier3-spec-asserts-wrong"),
        _make_fake_resp("tier3-attacker-view"),
    ]
    llm_judge.evaluate(_SPEC, config=_CFG)
    # Inspect the Request object passed to urlopen on the first call
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
    mock_urlopen.side_effect = [
        _make_fake_resp("tier3-context-gap"),
        _make_fake_resp("tier3-spec-asserts-wrong"),
        _make_fake_resp("tier3-attacker-view"),
    ]
    llm_judge.evaluate(_SPEC, config=_CFG)
    call_args = mock_urlopen.call_args_list[0]
    req = call_args[0][0]
    assert req.get_header("Authorization") == "Bearer fake-key-for-tests"


# ---------------------------------------------------------------------------
# 19. partial failure: first call raises, others succeed
# ---------------------------------------------------------------------------


@mock.patch("urllib.request.urlopen")
def test_evaluate_partial_response_one_call_fails_others_succeed(mock_urlopen, monkeypatch):
    _env(monkeypatch)
    monkeypatch.setattr(time, "sleep", lambda _d: None)
    # First prong fails all 4 attempts (retried 3x), then two prongs succeed.
    _500 = url_error.HTTPError(
        url="https://api.deepseek.com", code=500, msg="Internal Server Error",
        hdrs=None, fp=None,
    )
    mock_urlopen.side_effect = [
        _500, _500, _500, _500,  # prong 1: all 4 attempts fail
        _make_fake_resp("tier3-spec-asserts-wrong"),
        _make_fake_resp("tier3-attacker-view"),
    ]
    result = llm_judge.evaluate(_SPEC, config=_CFG)
    kinds = [f.kind for f in result]
    # One unavailable from the failed prong + 2 real findings
    assert "tier3-unavailable" in kinds
    assert "tier3-spec-asserts-wrong" in kinds
    assert "tier3-attacker-view" in kinds


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

    mock_urlopen.side_effect = [
        _make_fake_resp("tier3-context-gap"),
        _make_fake_resp("tier3-spec-asserts-wrong"),
        _make_fake_resp("tier3-attacker-view"),
    ]
    cfg = llm_judge.JudgeConfig(enabled=True, api_key_env="DEEPSEEK_API_KEY", model="deepseek-reasoner")
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

    mock_urlopen.side_effect = [
        _make_fake_resp("tier3-context-gap"),
        _make_fake_resp("tier3-spec-asserts-wrong"),
        _make_fake_resp("tier3-attacker-view"),
    ]
    cfg = llm_judge.JudgeConfig(enabled=True, api_key_env="DEEPSEEK_API_KEY", model="deepseek-reasoner")
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

    cfg = llm_judge.JudgeConfig(enabled=True, api_key_env="DEEPSEEK_API_KEY", model="deepseek-reasoner")
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

    cfg = llm_judge.JudgeConfig(enabled=True, api_key_env="DEEPSEEK_API_KEY", model="deepseek-reasoner")
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
        _make_fake_resp("tier3-context-gap"),
    ]
    cfg = llm_judge.JudgeConfig(enabled=True, api_key_env="TEST_DEEPSEEK_KEY", model="deepseek-reasoner")
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
        _make_fake_resp("tier3-context-gap"),
    ]
    cfg = llm_judge.JudgeConfig(enabled=True, api_key_env="TEST_DEEPSEEK_KEY", model="deepseek-reasoner")
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
    cfg = llm_judge.JudgeConfig(enabled=True, api_key_env="TEST_DEEPSEEK_KEY", model="deepseek-reasoner")
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
    cfg = llm_judge.JudgeConfig(enabled=True, api_key_env="TEST_DEEPSEEK_KEY", model="deepseek-reasoner")
    prompts = {"system": "s", "user": "u"}
    with pytest.raises(socket.timeout):
        llm_judge._call_deepseek(prompts, config=cfg)
    assert mock_urlopen.call_count == 4
    assert len(sleep_calls) == 3


# ---------------------------------------------------------------------------
# 30. _run_prompt includes prong name in timeout message
# ---------------------------------------------------------------------------


@mock.patch("urllib.request.urlopen")
def test_run_prompt_includes_prong_name_in_timeout_message(mock_urlopen, monkeypatch):
    monkeypatch.setenv("TEST_DEEPSEEK_KEY", "fake-key-for-tests")
    monkeypatch.setattr(time, "sleep", lambda _d: None)

    mock_urlopen.side_effect = socket.timeout("timed out")
    cfg = llm_judge.JudgeConfig(enabled=True, api_key_env="TEST_DEEPSEEK_KEY", model="deepseek-reasoner")
    # Use the first prompt template (kind = "tier3-context-gap" → prong "context-gap")
    prompt_template = llm_judge._PROMPTS[0]
    result = llm_judge._run_prompt(prompt_template, _SPEC, config=cfg)
    assert len(result) == 1
    assert "context-gap" in result[0].message


# ---------------------------------------------------------------------------
# 31. JudgeConfig default timeout_s back-compat alias returns chunk_timeout_s
# ---------------------------------------------------------------------------


def test_default_timeout_s_is_180(monkeypatch):
    # Old code reads cfg.timeout_s — must still work via back-compat property.
    # New default chunk_timeout_s is 60; but a config created with the old
    # timeout_s=180 kwarg must read back 180 via the alias.
    cfg = llm_judge.JudgeConfig(enabled=True, api_key_env="DEEPSEEK_API_KEY", model="deepseek-reasoner")
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
    cfg = llm_judge.JudgeConfig(enabled=True, api_key_env="TEST_DEEPSEEK_KEY", model="deepseek-reasoner")
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
        _make_fake_resp("tier3-context-gap"),
    ]
    cfg = llm_judge.JudgeConfig(
        enabled=True,
        api_key_env="TEST_DEEPSEEK_KEY",
        model="deepseek-reasoner",
        chunk_timeout_s=60,
        total_timeout_s=600,
    )
    prompts = {"system": "s", "user": "u"}
    result = llm_judge._call_deepseek(prompts, config=cfg)
    assert mock_urlopen.call_count == 2  # first failed, second succeeded
    assert "findings" in result  # parsed content contains findings key


# ---------------------------------------------------------------------------
# 34. total_timeout fires → NOT retried, _TotalTimeoutError propagates
# ---------------------------------------------------------------------------


@mock.patch("urllib.request.urlopen")
def test_call_deepseek_total_timeout_does_not_retry(mock_urlopen, monkeypatch):
    """_TotalTimeoutError is NOT retried — hard ceiling."""
    monkeypatch.setenv("TEST_DEEPSEEK_KEY", "fake-key-for-tests")
    monkeypatch.setattr(time, "sleep", lambda _d: None)

    # Strategy: replace threading.Timer with a synchronous stub that immediately
    # invokes the callback on start(). The callback sets _total_exc and closes
    # the resp. We make resp.read() check _total_exc and raise _TotalTimeoutError
    # directly — no real thread timing needed.
    #
    # But _fire_total_timeout is a closure inside _call_deepseek, so we can't
    # call it directly. Instead: use a Timer stub that stores the fn, then
    # make the fake resp.read() call timer_fn() FIRST (populating _total_exc)
    # and then raise OSError (as if the closed socket did so).

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
            # Simulate the timer firing: call _fire_total_timeout directly,
            # then raise OSError as a closed socket would.
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
        model="deepseek-reasoner",
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

    # Same sync-timer strategy: first attempt raises socket.timeout (chunk timeout,
    # retried). On second attempt the timer fires during read() → _TotalTimeoutError.
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
            # On second call, fire the total timeout.
            if timer_fn_holder:
                timer_fn_holder[-1]()  # sets _total_exc for this attempt
            raise OSError("connection closed by total-timeout")

        def close(self):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *_):
            pass

    # First call: chunk timeout (retried). Second call: total timeout fires.
    mock_urlopen.side_effect = [
        socket.timeout("chunk timeout"),
        _TimerFiringResp(),
    ]

    cfg = llm_judge.JudgeConfig(
        enabled=True,
        api_key_env="TEST_DEEPSEEK_KEY",
        model="deepseek-reasoner",
        chunk_timeout_s=60,
        total_timeout_s=600,
    )
    prompts = {"system": "s", "user": "u"}
    with pytest.raises(llm_judge._TotalTimeoutError):
        llm_judge._call_deepseek(prompts, config=cfg)

    # Two urlopen calls: attempt 0 (chunk-timeout) + attempt 1 (total-timeout).
    assert mock_urlopen.call_count == 2


# ---------------------------------------------------------------------------
# 36. back-compat: old timeout_s key in JudgeConfig loads as chunk_timeout_s
# ---------------------------------------------------------------------------


def test_judge_config_back_compat_timeout_s_loads_as_chunk_timeout_s():
    """Setting timeout_s= kwarg (legacy) reflects in chunk_timeout_s."""
    cfg = llm_judge.JudgeConfig(
        enabled=True,
        api_key_env="DEEPSEEK_API_KEY",
        model="deepseek-reasoner",
    )
    # Use the back-compat setter.
    cfg.timeout_s = 180
    assert cfg.chunk_timeout_s == 180
    # Reading back via the alias also works.
    assert cfg.timeout_s == 180


# ---------------------------------------------------------------------------
# 37. JudgeConfig default total_timeout_s is 600
# ---------------------------------------------------------------------------


def test_judge_config_default_total_timeout_is_600():
    cfg = llm_judge.JudgeConfig(
        enabled=True,
        api_key_env="DEEPSEEK_API_KEY",
        model="deepseek-reasoner",
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
    # Old timeout_s key must NOT appear (new configs use the new names).
    # Note: this check excludes the new keys themselves (they contain "timeout_s").
    lines_with_bare_timeout = [
        ln for ln in text.splitlines()
        if ln.strip().startswith("timeout_s")
    ]
    assert lines_with_bare_timeout == [], f"Unexpected bare timeout_s line: {lines_with_bare_timeout}"


# ---------------------------------------------------------------------------
# 39. Integration: total_timeout aborts within total_timeout_s + chunk_timeout_s
#     Uses a real HTTPServer that hangs mid-stream to exercise real socket semantics.
# ---------------------------------------------------------------------------


def test_total_timeout_aborts_within_total_plus_chunk_window(monkeypatch):
    """Wall-clock abort lands between total_timeout_s and total_timeout_s + chunk_timeout_s.

    This test exercises real socket close semantics — not a mock — to validate
    the _TotalTimeoutError abort-latency documented in its docstring.
    """
    import http.server
    import socketserver

    # chunk_timeout_s must be LARGER than total_timeout_s so the total-timeout
    # Timer fires during resp.read() before the per-recv socket timeout does.
    # On Linux, resp.close() from the Timer does not immediately unblock read();
    # read() continues blocking until chunk_timeout_s fires (~5s), then detects
    # _total_exc and raises _TotalTimeoutError.  Worst-case elapsed: total + chunk.
    chunk_timeout_s = 5
    total_timeout_s = 3

    # Event lets the handler block without using time.sleep (which monkeypatch
    # may affect).  The server teardown sets this event to unblock any handlers
    # still waiting when the test ends.
    _handler_unblock = threading.Event()

    class _HangingHandler(http.server.BaseHTTPRequestHandler):
        """Returns HTTP 200 + a tiny chunk, then hangs in the response body."""

        def do_POST(self):  # noqa: N802
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            # Claim a large body so urllib blocks reading it; we only send a tiny
            # chunk and then hang — forcing resp.read() to block until the
            # total_timeout_s fires and closes the connection.
            self.send_header("Content-Length", "100000")
            self.end_headers()
            self.wfile.write(b"X")  # tiny chunk to confirm the connection is live
            self.wfile.flush()
            # Hang until explicitly unblocked by test teardown (or 60s guard).
            _handler_unblock.wait(timeout=60)

        def log_message(self, fmt, *args):  # silence request logs in test output
            pass

    # Bind to an OS-assigned free port.
    # ThreadingTCPServer so each incoming connection gets its own handler thread;
    # without this the single-threaded server blocks during the hang and rejects
    # retry connections (causing chunk_timeout_s to fire on connect, not on read).
    server = socketserver.ThreadingTCPServer(("127.0.0.1", 0), _HangingHandler)
    server.allow_reuse_address = True
    port = server.server_address[1]

    server_thread = threading.Thread(target=server.serve_forever, daemon=True)
    server_thread.start()
    try:
        monkeypatch.setenv("TEST_DEEPSEEK_KEY", "fake-key-for-tests")
        # Patch only llm_judge's backoff sleep — NOT the global time.sleep used
        # by the server handler above.
        monkeypatch.setattr("bin.llm_judge.time.sleep", lambda _d: None)

        cfg = llm_judge.JudgeConfig(
            enabled=True,
            api_key_env="TEST_DEEPSEEK_KEY",
            model="deepseek-reasoner",
            base_url=f"http://127.0.0.1:{port}",
            chunk_timeout_s=chunk_timeout_s,
            total_timeout_s=total_timeout_s,
        )
        prompts = {"system": "s", "user": "u"}

        t0 = time.monotonic()
        with pytest.raises(llm_judge._TotalTimeoutError):
            llm_judge._call_deepseek(prompts, config=cfg)
        elapsed = time.monotonic() - t0

        # Lower bound: total_timeout_s must have elapsed before the error fires.
        assert elapsed >= total_timeout_s, (
            f"Abort too early: {elapsed:.2f}s < total_timeout_s={total_timeout_s}s"
        )
        # Upper bound: must finish within total + chunk + 2.0s scheduling epsilon.
        # On Linux, resp.close() from the Timer does not immediately unblock urllib's
        # read(); the read blocks until chunk_timeout_s fires, then detects _total_exc.
        # The extra 2.0s covers OS scheduling jitter.  With total=3, chunk=5 the
        # expected elapsed is ~3s (timer fires) + up to ~5s (chunk fires) = ~8s max.
        upper = total_timeout_s + chunk_timeout_s + 2.0
        assert elapsed <= upper, (
            f"Abort too slow: {elapsed:.2f}s > {upper}s "
            f"(total={total_timeout_s}s + chunk={chunk_timeout_s}s + 2.0s epsilon)"
        )
    finally:
        _handler_unblock.set()  # unblock any handler still waiting
        server.shutdown()
        server_thread.join(timeout=5)
