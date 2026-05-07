"""Tests for Tier 3 CoT faithfulness check (v0.6 priority 3).

All HTTP calls are mocked. Tests cover:
- Citation found in spec → tuple stays block
- Citation not found → tuple demoted to warn/tier3-unfaithful-contradiction
- Null citation → tuple demoted
- Malformed cite JSON → block tuples kept, tier3-faithfulness-malformed added
- No block tuples → no second API call
- Multiple block tuples → single batched call
- Mixed block+warn tuples → only block tuples verified; warn pass through
"""
import json
from unittest import mock

import pytest

from bin import llm_judge
from bin import findings


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------

# Spec with two steps so the step lookup is populated.
_SPEC = """\
# Test Spec

## 6. Steps

```yaml
- step: 5
  why: install dependency
  action: pip install yt-readable
  verification: python -c "from yt_readable.server import app"
- step: 6
  why: start service
  action: systemctl start yt-readable
  verification: systemctl is-active yt-readable
```
"""

_CFG = llm_judge.JudgeConfig(
    enabled=True,
    api_key_env="TEST_DEEPSEEK_KEY",
    model="deepseek-v4-flash",
)


def _api_resp(content: str) -> mock.MagicMock:
    """Wrap *content* in the DeepSeek API envelope."""
    payload = json.dumps(
        {"choices": [{"message": {"content": content}}]}
    ).encode()
    resp = mock.MagicMock()
    resp.read.return_value = payload
    resp.__enter__ = mock.Mock(return_value=resp)
    resp.__exit__ = mock.Mock(return_value=None)
    return resp


def _contradiction_resp(tuples: list[dict]) -> mock.MagicMock:
    return _api_resp(json.dumps(tuples))


def _cite_resp(citations: list[dict]) -> mock.MagicMock:
    return _api_resp(json.dumps(citations))


def _env(monkeypatch) -> None:
    monkeypatch.setenv("TEST_DEEPSEEK_KEY", "fake-key-for-tests")


# ---------------------------------------------------------------------------
# 1. Citation found in spec text → tuple stays block
# ---------------------------------------------------------------------------


@mock.patch("urllib.request.urlopen")
def test_faithfulness_citation_found_tuple_stays_block(mock_urlopen, monkeypatch):
    """Citation substring matches step action → block finding preserved."""
    _env(monkeypatch)
    primary_tuples = [
        {"kind": "missing-producer", "consumer_step": 5, "missing": "yt-readable",
         "rationale": "step 5 imports yt_readable.server but no earlier step installs it"},
    ]
    # "from yt_readable.server" appears verbatim in step 5's verification text.
    citations = [{"index": 0, "step": 5, "citation": "from yt_readable.server"}]
    mock_urlopen.side_effect = [
        _contradiction_resp(primary_tuples),
        _cite_resp(citations),
    ]

    result = llm_judge.evaluate(_SPEC, config=_CFG)

    block_findings = [f for f in result if f.kind == "missing-producer"]
    assert len(block_findings) == 1
    assert block_findings[0].severity == "block"


# ---------------------------------------------------------------------------
# 2. Citation not found in spec text → tuple demoted to warn
# ---------------------------------------------------------------------------


@mock.patch("urllib.request.urlopen")
def test_faithfulness_citation_not_found_tuple_demoted(mock_urlopen, monkeypatch):
    """Citation substring NOT in spec step text → tuple demoted to tier3-unfaithful-contradiction."""
    _env(monkeypatch)
    primary_tuples = [
        {"kind": "missing-producer", "consumer_step": 5, "missing": "yt-readable",
         "rationale": "step 5 imports yt_readable.server but no earlier step installs it"},
    ]
    # Deliberately wrong citation — text not in the spec.
    citations = [{"index": 0, "step": 5, "citation": "nonsense text not in spec at all"}]
    mock_urlopen.side_effect = [
        _contradiction_resp(primary_tuples),
        _cite_resp(citations),
    ]

    result = llm_judge.evaluate(_SPEC, config=_CFG)

    demoted = [f for f in result if f.kind == "tier3-unfaithful-contradiction"]
    assert len(demoted) == 1
    assert demoted[0].severity == "warn"
    assert demoted[0].dismissable is True
    # Original block finding should not be present.
    assert not any(f.kind == "missing-producer" for f in result)


# ---------------------------------------------------------------------------
# 3. Null citation (step=null, citation=null) → tuple demoted
# ---------------------------------------------------------------------------


@mock.patch("urllib.request.urlopen")
def test_faithfulness_null_citation_demotes_tuple(mock_urlopen, monkeypatch):
    """Model returns null citation → tuple demoted to tier3-unfaithful-contradiction."""
    _env(monkeypatch)
    primary_tuples = [
        {"kind": "shallow-ownership", "step": 5, "claimed": "yt-readable installed",
         "actual": "never verified",
         "rationale": "step 5 claims install but verification is absent"},
    ]
    citations = [{"index": 0, "step": None, "citation": None}]
    mock_urlopen.side_effect = [
        _contradiction_resp(primary_tuples),
        _cite_resp(citations),
    ]

    result = llm_judge.evaluate(_SPEC, config=_CFG)

    demoted = [f for f in result if f.kind == "tier3-unfaithful-contradiction"]
    assert len(demoted) == 1
    assert demoted[0].severity == "warn"


# ---------------------------------------------------------------------------
# 4. Malformed cite JSON → block tuples kept, tier3-faithfulness-malformed added
# ---------------------------------------------------------------------------


@mock.patch("urllib.request.urlopen")
def test_faithfulness_malformed_cite_json_keeps_block_and_adds_warn(mock_urlopen, monkeypatch):
    """Malformed cite response → block tuples unchanged; tier3-faithfulness-malformed appended."""
    _env(monkeypatch)
    primary_tuples = [
        {"kind": "missing-producer", "consumer_step": 5, "missing": "yt-readable",
         "rationale": "step 5 imports yt_readable.server but no earlier step installs it"},
    ]
    mock_urlopen.side_effect = [
        _contradiction_resp(primary_tuples),
        _api_resp("not valid JSON at all !!!"),
    ]

    result = llm_judge.evaluate(_SPEC, config=_CFG)

    # Original block finding must still be present.
    block_findings = [f for f in result if f.kind == "missing-producer"]
    assert len(block_findings) == 1
    assert block_findings[0].severity == "block"
    # Malformed sentinel must be present.
    malformed = [f for f in result if f.kind == "tier3-faithfulness-malformed"]
    assert len(malformed) == 1
    assert malformed[0].severity == "warn"
    assert malformed[0].dismissable is False


# ---------------------------------------------------------------------------
# 5. No block tuples → no second API call
# ---------------------------------------------------------------------------


@mock.patch("urllib.request.urlopen")
def test_faithfulness_no_block_tuples_no_second_call(mock_urlopen, monkeypatch):
    """When primary response has no block-severity tuples, cite pass is skipped entirely."""
    _env(monkeypatch)
    # ambiguous-contract is warn severity — not a block kind.
    primary_tuples = [
        {"kind": "ambiguous-contract", "step": 5,
         "ambiguous": "which pip to use",
         "rationale": "could be pip3 or python -m pip"},
    ]
    mock_urlopen.return_value = _contradiction_resp(primary_tuples)

    result = llm_judge.evaluate(_SPEC, config=_CFG)

    # Exactly one urlopen call — no second cite call.
    assert mock_urlopen.call_count == 1
    assert len(result) == 1
    assert result[0].kind == "ambiguous-contract"
    assert result[0].severity == "warn"


# ---------------------------------------------------------------------------
# 6. Multiple block tuples → single batched call (not one per tuple)
# ---------------------------------------------------------------------------


@mock.patch("urllib.request.urlopen")
def test_faithfulness_multiple_block_tuples_single_batched_call(mock_urlopen, monkeypatch):
    """Two block tuples result in exactly two urlopen calls total (1 primary + 1 batched cite)."""
    _env(monkeypatch)
    primary_tuples = [
        {"kind": "missing-producer", "consumer_step": 5, "missing": "yt-readable",
         "rationale": "first block tuple"},
        {"kind": "shallow-ownership", "step": 5, "claimed": "yt-readable",
         "actual": "never verified", "rationale": "second block tuple"},
    ]
    # Both citations match spec text.
    citations = [
        {"index": 0, "step": 5, "citation": "pip install yt-readable"},
        {"index": 1, "step": 5, "citation": "from yt_readable.server"},
    ]
    mock_urlopen.side_effect = [
        _contradiction_resp(primary_tuples),
        _cite_resp(citations),
    ]

    result = llm_judge.evaluate(_SPEC, config=_CFG)

    # Total urlopen calls = 2 (one primary + one batched cite — NOT one per tuple).
    assert mock_urlopen.call_count == 2
    # Both block findings preserved.
    block_findings = [f for f in result if f.severity == "block"]
    assert len(block_findings) == 2


# ---------------------------------------------------------------------------
# 7. Mixed block+warn tuples → only block verified; warn pass through
# ---------------------------------------------------------------------------


@mock.patch("urllib.request.urlopen")
def test_faithfulness_mixed_tuples_only_block_verified(mock_urlopen, monkeypatch):
    """Warn-severity tuples are unaffected by the cite pass; only block kinds go for verification."""
    _env(monkeypatch)
    primary_tuples = [
        # warn — not verified
        {"kind": "ambiguous-contract", "step": 5,
         "ambiguous": "which pip", "rationale": "warn tuple"},
        # block — verified
        {"kind": "missing-producer", "consumer_step": 5, "missing": "yt-readable",
         "rationale": "block tuple"},
        # info — not verified
        {"kind": "negative-path-omission", "step": 5,
         "rationale": "info tuple"},
    ]
    # Only the block tuple gets a cite entry; citation matches spec.
    citations = [
        {"index": 0, "step": 5, "citation": "pip install yt-readable"},
    ]
    mock_urlopen.side_effect = [
        _contradiction_resp(primary_tuples),
        _cite_resp(citations),
    ]

    result = llm_judge.evaluate(_SPEC, config=_CFG)

    # Two urlopen calls: primary + one batched cite (only 1 block tuple).
    assert mock_urlopen.call_count == 2

    # Warn tuple unaffected.
    ambiguous = [f for f in result if f.kind == "ambiguous-contract"]
    assert len(ambiguous) == 1
    assert ambiguous[0].severity == "warn"

    # Info tuple unaffected.
    info_findings = [f for f in result if f.kind == "negative-path-omission"]
    assert len(info_findings) == 1
    assert info_findings[0].severity == "info"

    # Block tuple preserved (citation matched).
    block_findings = [f for f in result if f.kind == "missing-producer"]
    assert len(block_findings) == 1
    assert block_findings[0].severity == "block"


# ---------------------------------------------------------------------------
# 8. Case-insensitive citation match
# ---------------------------------------------------------------------------


@mock.patch("urllib.request.urlopen")
def test_faithfulness_citation_match_is_case_insensitive(mock_urlopen, monkeypatch):
    """Citation match against spec text is case-insensitive."""
    _env(monkeypatch)
    primary_tuples = [
        {"kind": "missing-producer", "consumer_step": 5, "missing": "yt-readable",
         "rationale": "step 5 imports it"},
    ]
    # Uppercase citation — the spec has lowercase "pip install yt-readable".
    citations = [{"index": 0, "step": 5, "citation": "PIP INSTALL YT-READABLE"}]
    mock_urlopen.side_effect = [
        _contradiction_resp(primary_tuples),
        _cite_resp(citations),
    ]

    result = llm_judge.evaluate(_SPEC, config=_CFG)

    # Citation matches case-insensitively → tuple stays block.
    block_findings = [f for f in result if f.kind == "missing-producer"]
    assert len(block_findings) == 1
    assert block_findings[0].severity == "block"


# ---------------------------------------------------------------------------
# 9. New kinds are registered in findings.KNOWN_KINDS + TIER3_CONTRADICTION_SEVERITY
# ---------------------------------------------------------------------------


def test_faithfulness_kinds_registered():
    """tier3-unfaithful-contradiction and tier3-faithfulness-malformed are registered."""
    assert "tier3-unfaithful-contradiction" in findings.KNOWN_KINDS
    assert "tier3-faithfulness-malformed" in findings.KNOWN_KINDS
    assert findings.TIER3_CONTRADICTION_SEVERITY["tier3-unfaithful-contradiction"] == "warn"
    assert findings.TIER3_CONTRADICTION_SEVERITY["tier3-faithfulness-malformed"] == "warn"
