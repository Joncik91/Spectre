"""Tests for v0.7 Tier 3 adversarial-pathway rubric."""
import json
from unittest import mock

import pytest

from bin import findings, llm_judge


_SPEC = "# Test\n## 1. Hard Problem\nfoo\n## 6. Steps\n```yaml\n- step: 1\n  why: x\n  action: curl https://example.com\n  verification: true\n```\n"

_CFG = llm_judge.JudgeConfig(
    enabled=True,
    api_key_env="DEEPSEEK_API_KEY",
    model="deepseek-v4-flash",
    base_url="https://api.deepseek.com/v1",
    budget_tokens_per_spec=50_000,
)


def _env(monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-fake")


def _api_resp(content: str) -> mock.MagicMock:
    """Return a mock urlopen context manager with the given content."""
    payload = json.dumps(
        {"choices": [{"message": {"content": content}}]}
    ).encode()
    resp = mock.MagicMock()
    resp.read.return_value = payload
    resp.__enter__ = mock.Mock(return_value=resp)
    resp.__exit__ = mock.Mock(return_value=None)
    return resp


def test_system_prompt_contains_adversarial_pathway_rubric():
    """The Tier 3 prompt explicitly mentions adversarial-pathway / exploit."""
    prompt = llm_judge._CONTRADICTION_SYSTEM_PROMPT
    assert "adversarial-pathway" in prompt or "exploit" in prompt.lower()


@mock.patch("urllib.request.urlopen")
def test_adversarial_pathway_finding_emitted(mock_urlopen, monkeypatch):
    """A DeepSeek response with an adversarial-pathway tuple emits a Finding."""
    _env(monkeypatch)
    tuples = [{
        "kind": "adversarial-pathway",
        "step": 1,
        "rationale": "Step 1 fetches arbitrary URL with no signature check.",
    }]
    # adversarial-pathway is block severity but NOT in _BLOCK_CONTRADICTION_KINDS,
    # so no second cite-and-verify call is made — single urlopen call only.
    mock_urlopen.return_value = _api_resp(json.dumps(tuples))

    result = llm_judge.evaluate(_SPEC, config=_CFG)
    kinds = [f.kind for f in result]
    assert "adversarial-pathway" in kinds


def test_known_kind_for_adversarial_pathway():
    """findings.KNOWN_KINDS already contains adversarial-pathway."""
    assert "adversarial-pathway" in findings.KNOWN_KINDS
