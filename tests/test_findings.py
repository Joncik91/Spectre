import pytest
from bin import findings


def test_finding_location_scope_step_carries_step_field():
    loc = findings.FindingLocation(scope="step", step=3)
    assert loc.step == 3


def test_finding_location_scope_cross_step_carries_steps_list():
    loc = findings.FindingLocation(scope="cross-step", steps=[2, 5])
    assert loc.steps == [2, 5]


def test_finding_location_scope_spec_wide_step_is_none():
    loc = findings.FindingLocation(scope="spec-wide")
    assert loc.step is None


def test_finding_location_scope_spec_wide_steps_is_none():
    loc = findings.FindingLocation(scope="spec-wide")
    assert loc.steps is None


def test_finding_location_unknown_scope_raises():
    with pytest.raises(ValueError, match="unknown scope"):
        findings.FindingLocation(scope="invalid-scope")


def test_finding_known_kind_accepted():
    f = findings.Finding(
        tier=1,
        kind="missing-why",
        severity="block",
        location=findings.FindingLocation(scope="step", step=2),
        message="Step 2 missing why field",
    )
    assert f.kind == "missing-why"


def test_finding_unknown_kind_raises():
    with pytest.raises(ValueError, match="unknown finding kind"):
        findings.Finding(
            tier=1,
            kind="bogus-kind",
            severity="block",
            location=findings.FindingLocation(scope="step", step=2),
            message="x",
        )


def test_finding_unknown_severity_raises():
    with pytest.raises(ValueError, match="unknown severity"):
        findings.Finding(
            tier=1,
            kind="missing-why",
            severity="critical",
            location=findings.FindingLocation(scope="step", step=2),
            message="x",
        )


def test_finding_unknown_tier_raises():
    with pytest.raises(ValueError, match="unknown tier"):
        findings.Finding(
            tier=4,
            kind="missing-why",
            severity="block",
            location=findings.FindingLocation(scope="step", step=2),
            message="x",
        )


def test_finding_message_over_140_chars_raises():
    with pytest.raises(ValueError, match="message exceeds 140 chars"):
        findings.Finding(
            tier=1,
            kind="missing-why",
            severity="block",
            location=findings.FindingLocation(scope="step", step=2),
            message="x" * 141,
        )


def test_finding_fix_over_140_chars_raises():
    with pytest.raises(ValueError, match="suggested_fix exceeds 140 chars"):
        findings.Finding(
            tier=1,
            kind="missing-why",
            severity="block",
            location=findings.FindingLocation(scope="step", step=2),
            message="x",
            suggested_fix="y" * 141,
        )


def test_finding_dismissable_default_false():
    f = findings.Finding(
        tier=1,
        kind="missing-why",
        severity="block",
        location=findings.FindingLocation(scope="step", step=2),
        message="x",
    )
    assert f.dismissable is False


def test_severity_order_block_greater_than_warn():
    assert findings.SEVERITY_ORDER["block"] > findings.SEVERITY_ORDER["warn"]


def test_severity_order_warn_greater_than_info():
    assert findings.SEVERITY_ORDER["warn"] > findings.SEVERITY_ORDER["info"]


def test_finding_to_dict_round_trips_kind():
    f = findings.Finding(
        tier=2,
        kind="undeclared-resource",
        severity="warn",
        location=findings.FindingLocation(scope="step", step=3, ref="resources"),
        message="port 9100 inferred but not declared",
        suggested_fix="add res-port-9100 to step 3 resources",
        dismissable=False,
    )
    d = findings.to_dict(f)
    f2 = findings.from_dict(d)
    assert f2.kind == f.kind


def test_finding_to_dict_round_trips_severity():
    f = findings.Finding(
        tier=2,
        kind="undeclared-resource",
        severity="warn",
        location=findings.FindingLocation(scope="step", step=3),
        message="port 9100 inferred but not declared",
    )
    d = findings.to_dict(f)
    f2 = findings.from_dict(d)
    assert f2.severity == f.severity


def test_finding_to_dict_round_trips_step():
    f = findings.Finding(
        tier=2,
        kind="undeclared-resource",
        severity="warn",
        location=findings.FindingLocation(scope="step", step=3, ref="resources"),
        message="port 9100 inferred but not declared",
    )
    d = findings.to_dict(f)
    f2 = findings.from_dict(d)
    assert f2.location.step == 3


def test_max_severity_returns_block_when_present():
    fs = [
        findings.Finding(tier=1, kind="missing-why", severity="info", location=findings.FindingLocation(scope="step", step=1), message="a"),
        findings.Finding(tier=2, kind="undeclared-resource", severity="block", location=findings.FindingLocation(scope="step", step=2), message="b"),
        findings.Finding(tier=1, kind="action-not-probed", severity="warn", location=findings.FindingLocation(scope="step", step=3), message="c"),
    ]
    assert findings.max_severity(fs) == "block"


def test_max_severity_empty_list_returns_info():
    assert findings.max_severity([]) == "info"


def test_fingerprint_excludes_message_wording():
    f1 = findings.Finding(
        tier=1,
        kind="missing-why",
        severity="block",
        location=findings.FindingLocation(scope="step", step=2, ref="why"),
        message="Step 2 missing the why field",
    )
    f2 = findings.Finding(
        tier=1,
        kind="missing-why",
        severity="block",
        location=findings.FindingLocation(scope="step", step=2, ref="why"),
        message="Why field not found in step 2",
    )
    assert findings.fingerprint(f1) == findings.fingerprint(f2)


def test_fingerprint_changes_when_kind_changes():
    f1 = findings.Finding(
        tier=1,
        kind="missing-why",
        severity="block",
        location=findings.FindingLocation(scope="step", step=2),
        message="x",
    )
    f2 = findings.Finding(
        tier=1,
        kind="soft-verification",
        severity="block",
        location=findings.FindingLocation(scope="step", step=2),
        message="x",
    )
    assert findings.fingerprint(f1) != findings.fingerprint(f2)


def test_fingerprint_changes_when_step_changes():
    f1 = findings.Finding(
        tier=1,
        kind="missing-why",
        severity="block",
        location=findings.FindingLocation(scope="step", step=2),
        message="x",
    )
    f2 = findings.Finding(
        tier=1,
        kind="missing-why",
        severity="block",
        location=findings.FindingLocation(scope="step", step=3),
        message="x",
    )
    assert findings.fingerprint(f1) != findings.fingerprint(f2)


def test_fingerprint_includes_sorted_steps():
    f1 = findings.Finding(
        tier=1,
        kind="cross-step-inconsistency",
        severity="warn",
        location=findings.FindingLocation(scope="cross-step", steps=[5, 2]),
        message="x",
    )
    f2 = findings.Finding(
        tier=1,
        kind="cross-step-inconsistency",
        severity="warn",
        location=findings.FindingLocation(scope="cross-step", steps=[2, 5]),
        message="x",
    )
    assert findings.fingerprint(f1) == findings.fingerprint(f2)


def test_fingerprint_is_sha256_hex():
    f = findings.Finding(
        tier=1,
        kind="missing-why",
        severity="block",
        location=findings.FindingLocation(scope="step", step=2),
        message="x",
    )
    fp = findings.fingerprint(f)
    assert len(fp) == 64
    assert all(c in "0123456789abcdef" for c in fp)


def test_known_kinds_includes_tier3_unavailable():
    assert "tier3-unavailable" in findings.KNOWN_KINDS


def test_finding_to_dict_full_round_trip_preserves_all_fields():
    """Full-fidelity round-trip: from_dict(to_dict(f)) equals f across all fields."""
    from dataclasses import asdict
    f = findings.Finding(
        tier=2,
        kind="undeclared-resource",
        severity="warn",
        location=findings.FindingLocation(scope="step", step=3, ref="resources"),
        message="port 9100 inferred but not declared",
        suggested_fix="add res-port-9100 to step 3 resources:",
        dismissable=True,
    )
    f2 = findings.from_dict(findings.to_dict(f))
    assert asdict(f2) == asdict(f)


def test_finding_round_trip_preserves_none_suggested_fix():
    """Regression: suggested_fix=None must survive round-trip as None."""
    from dataclasses import asdict
    f = findings.Finding(
        tier=1,
        kind="missing-why",
        severity="block",
        location=findings.FindingLocation(scope="step", step=2, ref="why"),
        message="Step 2 missing why",
    )
    f2 = findings.from_dict(findings.to_dict(f))
    assert asdict(f2) == asdict(f)
    assert f2.suggested_fix is None


def test_fingerprint_changes_when_tier_changes():
    """Different tiers must produce different fingerprints (dismissal-pipeline integrity)."""
    f1 = findings.Finding(
        tier=1, kind="missing-why", severity="block",
        location=findings.FindingLocation(scope="step", step=3, ref="why"),
        message="m",
    )
    f2 = findings.Finding(
        tier=2, kind="missing-why", severity="block",
        location=findings.FindingLocation(scope="step", step=3, ref="why"),
        message="m",
    )
    assert findings.fingerprint(f1) != findings.fingerprint(f2)


def test_fingerprint_distinguishes_empty_steps_from_none():
    """steps=[] must NOT collapse to steps=None in fingerprint."""
    f_empty = findings.Finding(
        tier=1, kind="cross-step-inconsistency", severity="warn",
        location=findings.FindingLocation(scope="cross-step", steps=[]),
        message="m",
    )
    f_none = findings.Finding(
        tier=1, kind="cross-step-inconsistency", severity="warn",
        location=findings.FindingLocation(scope="cross-step", steps=None),
        message="m",
    )
    assert findings.fingerprint(f_empty) != findings.fingerprint(f_none)
