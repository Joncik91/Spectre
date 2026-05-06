"""Tests for bin/llm_judge.py — Tier 3 DeepSeek client. All HTTP mocked."""
import json
import os
import pathlib
import socket
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
    mock_urlopen.side_effect = url_error.URLError("Name or service not known")
    result = llm_judge.evaluate(_SPEC, config=_CFG)
    assert result[0].kind == "tier3-unavailable"


# ---------------------------------------------------------------------------
# 11. TimeoutError → tier3-unavailable
# ---------------------------------------------------------------------------


@mock.patch("urllib.request.urlopen")
def test_evaluate_timeout_returns_tier3_unavailable(mock_urlopen, monkeypatch):
    _env(monkeypatch)
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
    mock_urlopen.side_effect = [
        url_error.HTTPError(
            url="https://api.deepseek.com", code=500, msg="Internal Server Error",
            hdrs=None, fp=None,
        ),
        _make_fake_resp("tier3-spec-asserts-wrong"),
        _make_fake_resp("tier3-attacker-view"),
    ]
    result = llm_judge.evaluate(_SPEC, config=_CFG)
    kinds = [f.kind for f in result]
    # One unavailable from the failed call + 2 real findings
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
