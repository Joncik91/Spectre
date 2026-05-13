"""End-to-end mock test: verifies that a chained step action causes the
DeepSeek user-prompt payload to contain 'action_segments' and both segments.

Flow: build_step_table → step has action_segments → _run_contradiction_prompt
sends step_table JSON in the user message → captured request body includes the
field and both segment strings.
"""
import json
from unittest import mock

import pytest

from bin.llm_judge import JudgeConfig, build_step_table, _run_contradiction_prompt


_CFG = JudgeConfig(
    enabled=True,
    api_key_env="TEST_DEEPSEEK_PAYLOAD_KEY",
    model="deepseek-v4-flash",
)

_EMPTY_RESP_PAYLOAD = json.dumps(
    {"choices": [{"message": {"content": "[]"}}]}
).encode()

_SPEC_WITH_CHAINED_ACTION = """\
## 6. Steps

```yaml
- step: 1
  why: install and compile
  action: pnpm install && pnpm exec tsc
  verification: pnpm test
```
"""


@mock.patch("urllib.request.urlopen")
def test_chained_action_segments_appear_in_deepseek_user_prompt(mock_urlopen, monkeypatch):
    """build_step_table on a chained action → DeepSeek payload includes action_segments."""
    monkeypatch.setenv("TEST_DEEPSEEK_PAYLOAD_KEY", "fake-key")

    captured: list = []
    resp = mock.MagicMock()
    resp.read.return_value = _EMPTY_RESP_PAYLOAD
    resp.__enter__ = mock.Mock(return_value=resp)
    resp.__exit__ = mock.Mock(return_value=None)

    def _capture(req, *args, **kwargs):
        captured.append(req)
        return resp

    mock_urlopen.side_effect = _capture

    step_table = build_step_table(_SPEC_WITH_CHAINED_ACTION)
    _run_contradiction_prompt(step_table, config=_CFG)

    assert len(captured) == 1, "expected exactly one HTTP request"
    body = json.loads(captured[0].data.decode())

    # The user message contains the serialised step_table JSON.
    user_content = body["messages"][1]["content"]

    assert "action_segments" in user_content, (
        "user-prompt payload missing 'action_segments' — step table not including segments"
    )
    assert "pnpm install" in user_content, (
        "first segment 'pnpm install' missing from DeepSeek user-prompt payload"
    )
    assert "pnpm exec tsc" in user_content, (
        "second segment 'pnpm exec tsc' missing from DeepSeek user-prompt payload"
    )
