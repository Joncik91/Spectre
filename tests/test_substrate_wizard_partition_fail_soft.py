"""Tests for v1.3 #9 — vocabulary partition fail-soft UX.

Verifies that _validate_view_trust_profile:
- Returns (profile, findings) rather than raising on misplaced tokens.
- Drops misplaced tokens from the returned profile (semantic firewall).
- Emits one block-severity trust-token-misplaced finding per misplaced token.
- Passes correctly-placed tokens through with no finding.

Pragma: no rejects/raises/refuses/denies in test names without pytest.raises.
All tests bind `result = substrate_wizard._validate_view_trust_profile(...)`.
"""
import pytest

from bin import substrate_wizard
from bin.findings import Finding


def test_misplaced_untrusted_input_in_human_user_view_emits_block_finding():
    """untrusted-input in human-user view → one block trust-token-misplaced; not in profile."""
    result = substrate_wizard._validate_view_trust_profile(
        "human-user", "untrusted-input"
    )
    profile, findings = result
    assert "untrusted-input" not in profile
    assert len(findings) == 1
    f = findings[0]
    assert isinstance(f, Finding)
    assert f.kind == "trust-token-misplaced"
    assert f.severity == "block"
    assert f.tier == 1
    # suggested_fix must point the operator to the correct view
    assert f.suggested_fix is not None
    assert "implementing-agent" in f.suggested_fix


def test_misplaced_accessibility_required_in_implementing_agent_view_emits_block_finding():
    """accessibility-required in implementing-agent view → block finding; not in profile."""
    result = substrate_wizard._validate_view_trust_profile(
        "implementing-agent", "accessibility-required"
    )
    profile, findings = result
    assert "accessibility-required" not in profile
    assert len(findings) == 1
    f = findings[0]
    assert f.kind == "trust-token-misplaced"
    assert f.severity == "block"
    # suggested_fix must reference the human-user view
    assert f.suggested_fix is not None
    assert "human-user" in f.suggested_fix


def test_two_misplaced_tokens_in_one_view_produce_two_block_findings():
    """Two misplaced tokens in one call → two separate block findings; neither in profile."""
    result = substrate_wizard._validate_view_trust_profile(
        "operator", "untrusted-input,accessibility-required"
    )
    profile, findings = result
    assert "untrusted-input" not in profile
    assert "accessibility-required" not in profile
    assert len(findings) == 2
    for f in findings:
        assert f.kind == "trust-token-misplaced"
        assert f.severity == "block"


def test_correctly_placed_token_produces_no_finding_and_appears_in_profile():
    """untrusted-input in implementing-agent view → no findings; token IS in profile."""
    result = substrate_wizard._validate_view_trust_profile(
        "implementing-agent", "untrusted-input"
    )
    profile, findings = result
    assert "untrusted-input" in profile
    assert findings == []


def test_mixed_valid_and_misplaced_tokens_partitions_correctly():
    """One valid + one misplaced → valid in profile, misplaced dropped, one finding."""
    result = substrate_wizard._validate_view_trust_profile(
        "implementing-agent", "untrusted-input,accessibility-required"
    )
    profile, findings = result
    assert "untrusted-input" in profile
    assert "accessibility-required" not in profile
    assert len(findings) == 1
    assert findings[0].kind == "trust-token-misplaced"


def test_none_token_returns_empty_profile_and_no_findings():
    """'none' sentinel → empty profile and no findings (clean path)."""
    result = substrate_wizard._validate_view_trust_profile(
        "implementing-agent", "none"
    )
    profile, findings = result
    assert profile == []
    assert findings == []


def test_empty_raw_returns_empty_profile_and_no_findings():
    """Empty string → empty profile, no findings."""
    result = substrate_wizard._validate_view_trust_profile(
        "human-user", ""
    )
    profile, findings = result
    assert profile == []
    assert findings == []
