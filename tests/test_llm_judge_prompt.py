"""Verifies that _CONTRADICTION_SYSTEM_PROMPT is actually sent to DeepSeek with
rule #7 content intact.

Strategy: call _run_contradiction_prompt (the real production function) with a
mock urlopen that captures the request body. Assert the captured system prompt
contains the rule #7 phrases — proving the string reaches the wire, not just
that the module-level constant has certain chars.
"""
import json
from unittest import mock

import pytest

from bin.llm_judge import JudgeConfig, _run_contradiction_prompt


_CFG = JudgeConfig(
    enabled=True,
    api_key_env="TEST_DEEPSEEK_API_KEY",
    model="deepseek-v4-flash",
)

_EMPTY_RESP_PAYLOAD = json.dumps(
    {"choices": [{"message": {"content": "[]"}}]}
).encode()


def _make_urlopen_mock(captured: list) -> mock.MagicMock:
    """Return a urlopen mock that records the Request object and returns []."""
    resp = mock.MagicMock()
    resp.read.return_value = _EMPTY_RESP_PAYLOAD
    resp.__enter__ = mock.Mock(return_value=resp)
    resp.__exit__ = mock.Mock(return_value=None)

    def _side_effect(req, *args, **kwargs):
        captured.append(req)
        return resp

    return mock.MagicMock(side_effect=_side_effect)


@mock.patch("urllib.request.urlopen")
def test_system_prompt_documents_action_segments(mock_urlopen, monkeypatch):
    """The system prompt sent to DeepSeek must include rule #7 key phrases."""
    monkeypatch.setenv("TEST_DEEPSEEK_API_KEY", "fake-key")
    captured: list = []
    mock_urlopen.side_effect = _make_urlopen_mock(captured).side_effect

    step_table = {
        "steps": [
            {
                "step": 1,
                "why": "install and compile",
                "action_summary": "pnpm install && pnpm exec tsc",
                "action_segments": ["pnpm install", "pnpm exec tsc"],
                "verification_summary": "pnpm test",
                "produces": [],
                "requires": [],
            }
        ],
        "physics_guardrails": [],
        "mutates": [],
        "never_touches": [],
    }

    _run_contradiction_prompt(step_table, config=_CFG)

    assert len(captured) == 1, "expected exactly one HTTP request"
    body = json.loads(captured[0].data.decode())
    system_content = body["messages"][0]["content"]

    assert "action_segments" in system_content, (
        "system prompt sent to DeepSeek is missing 'action_segments' — rule #7 was removed"
    )
    assert "distinct sub-action" in system_content, (
        "system prompt sent to DeepSeek is missing 'distinct sub-action' — rule #7 phrase changed"
    )
