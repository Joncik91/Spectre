"""Personal-rules adoption tracker. Stdlib + pytest only."""
import os
import pathlib
import tomllib

import pytest

from bin import personal_rules


def test_personal_rules_version_is_0_4_1():
    assert personal_rules.PERSONAL_RULES_VERSION == "0.4.1"


def test_personal_rules_path_default_returns_dotspectre_personal_rules_toml():
    p = personal_rules.personal_rules_path_default()
    assert p == pathlib.Path.home() / ".spectre" / "personal-rules.toml"


def test_default_brake_threshold_is_3():
    assert personal_rules.DEFAULT_BRAKE_THRESHOLD == 3


def test_load_personal_rules_returns_empty_dict_when_file_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(pathlib.Path, "home", lambda: tmp_path)
    result = personal_rules.load_personal_rules()
    assert result == {}


def test_load_personal_rules_returns_dict_when_file_present(tmp_path, monkeypatch):
    monkeypatch.setattr(pathlib.Path, "home", lambda: tmp_path)
    spectre = tmp_path / ".spectre"
    spectre.mkdir()
    (spectre / "personal-rules.toml").write_text(
        'version = "0.4.1"\n[overrides]\n', encoding="utf-8"
    )
    result = personal_rules.load_personal_rules()
    assert isinstance(result, dict)


def test_is_classifier_halt_overridden_returns_false_when_no_file(tmp_path, monkeypatch):
    monkeypatch.setattr(pathlib.Path, "home", lambda: tmp_path)
    result = personal_rules.is_classifier_halt_overridden(
        classifier_label="permission-change: chmod",
        fingerprint="a" * 64,
    )
    assert result is False


def test_is_classifier_halt_overridden_returns_true_when_entry_exists(tmp_path, monkeypatch):
    monkeypatch.setattr(pathlib.Path, "home", lambda: tmp_path)
    spectre = tmp_path / ".spectre"
    spectre.mkdir()
    fp = "a" * 64
    body = (
        'version = "0.4.1"\n'
        '[overrides]\n'
        f'"permission-change: chmod / {fp}" = '
        '{ reason = "fine in tmp", adopted_at = "2026-05-06T12:00:00Z" }\n'
    )
    (spectre / "personal-rules.toml").write_text(body, encoding="utf-8")
    result = personal_rules.is_classifier_halt_overridden(
        classifier_label="permission-change: chmod",
        fingerprint=fp,
    )
    assert result is True


def test_is_classifier_halt_overridden_distinct_fingerprints_independent(tmp_path, monkeypatch):
    monkeypatch.setattr(pathlib.Path, "home", lambda: tmp_path)
    spectre = tmp_path / ".spectre"
    spectre.mkdir()
    fp_a = "a" * 64
    fp_b = "b" * 64
    body = (
        'version = "0.4.1"\n'
        '[overrides]\n'
        f'"permission-change: chmod / {fp_a}" = '
        '{ reason = "x", adopted_at = "2026-05-06T12:00:00Z" }\n'
    )
    (spectre / "personal-rules.toml").write_text(body, encoding="utf-8")
    result = personal_rules.is_classifier_halt_overridden(
        classifier_label="permission-change: chmod",
        fingerprint=fp_b,
    )
    assert result is False


def test_append_adoption_creates_file_with_entry(tmp_path, monkeypatch):
    monkeypatch.setattr(pathlib.Path, "home", lambda: tmp_path)
    fp = "a" * 64
    personal_rules.append_adoption(
        classifier_label="permission-change: chmod",
        fingerprint=fp,
        reason="chmod 755 /tmp/* is fine",
    )
    target = tmp_path / ".spectre" / "personal-rules.toml"
    assert target.exists()


def test_append_adoption_makes_subsequent_lookups_return_true(tmp_path, monkeypatch):
    monkeypatch.setattr(pathlib.Path, "home", lambda: tmp_path)
    fp = "deadbeef" * 8
    personal_rules.append_adoption(
        classifier_label="permission-change: chmod",
        fingerprint=fp,
        reason="x",
    )
    result = personal_rules.is_classifier_halt_overridden(
        classifier_label="permission-change: chmod",
        fingerprint=fp,
    )
    assert result is True


def test_append_adoption_preserves_existing_entries(tmp_path, monkeypatch):
    monkeypatch.setattr(pathlib.Path, "home", lambda: tmp_path)
    fp_a = "a" * 64
    fp_b = "b" * 64
    personal_rules.append_adoption(
        classifier_label="permission-change: chmod", fingerprint=fp_a, reason="x"
    )
    personal_rules.append_adoption(
        classifier_label="dependency-add: pip install", fingerprint=fp_b, reason="y"
    )
    result = personal_rules.is_classifier_halt_overridden(
        classifier_label="permission-change: chmod",
        fingerprint=fp_a,
    )
    assert result is True


def test_append_adoption_writes_mode_0600(tmp_path, monkeypatch):
    monkeypatch.setattr(pathlib.Path, "home", lambda: tmp_path)
    personal_rules.append_adoption(
        classifier_label="x", fingerprint="a"*64, reason="r"
    )
    target = tmp_path / ".spectre" / "personal-rules.toml"
    mode = target.stat().st_mode & 0o777
    assert mode == 0o600


def test_append_adoption_handles_newline_in_reason(tmp_path, monkeypatch):
    """Reasons containing literal newlines must round-trip cleanly via the
    TOML writer. Without proper control-char escaping, the inline table
    would be malformed and load_personal_rules would silently lose the
    entry on next read."""
    monkeypatch.setattr(pathlib.Path, "home", lambda: tmp_path)
    fp = "a" * 64
    multiline_reason = "first line\nsecond line\twith tab"
    personal_rules.append_adoption(
        classifier_label="permission-change: chmod",
        fingerprint=fp,
        reason=multiline_reason,
    )
    # Round-trip: the next is_classifier_halt_overridden must succeed.
    result = personal_rules.is_classifier_halt_overridden(
        classifier_label="permission-change: chmod",
        fingerprint=fp,
    )
    assert result is True


def test_append_adoption_handles_quote_in_reason(tmp_path, monkeypatch):
    """Reasons with literal double-quotes must round-trip via TOML escape."""
    monkeypatch.setattr(pathlib.Path, "home", lambda: tmp_path)
    fp = "b" * 64
    personal_rules.append_adoption(
        classifier_label="x",
        fingerprint=fp,
        reason='reason with "quotes" and \\backslashes\\',
    )
    result = personal_rules.is_classifier_halt_overridden(
        classifier_label="x",
        fingerprint=fp,
    )
    assert result is True


def test_adoption_count_this_session_starts_at_zero(monkeypatch, tmp_path):
    monkeypatch.setattr(pathlib.Path, "home", lambda: tmp_path)
    personal_rules.reset_session_counter()
    assert personal_rules.adoption_count_this_session() == 0


def test_adoption_count_this_session_increments_on_append_adoption(monkeypatch, tmp_path):
    monkeypatch.setattr(pathlib.Path, "home", lambda: tmp_path)
    personal_rules.reset_session_counter()
    personal_rules.append_adoption(
        classifier_label="x", fingerprint="a"*64, reason="r1"
    )
    assert personal_rules.adoption_count_this_session() == 1


def test_adoption_count_this_session_counts_multiple_adoptions(monkeypatch, tmp_path):
    monkeypatch.setattr(pathlib.Path, "home", lambda: tmp_path)
    personal_rules.reset_session_counter()
    personal_rules.append_adoption(classifier_label="x", fingerprint="a"*64, reason="r")
    personal_rules.append_adoption(classifier_label="y", fingerprint="b"*64, reason="r")
    personal_rules.append_adoption(classifier_label="z", fingerprint="c"*64, reason="r")
    assert personal_rules.adoption_count_this_session() == 3


def test_brake_threshold_enforces_at_3_by_default(monkeypatch, tmp_path):
    """The skill checks adoption_count_this_session() >= DEFAULT_BRAKE_THRESHOLD
    to know when to stop prompting. The constant exists as a public surface."""
    assert personal_rules.DEFAULT_BRAKE_THRESHOLD == 3


# ─── Persistent-counter tests (v0.4.1 senior-review fix) ──────────────────────
#
# The SKILL.md heredoc invokes `python3 - <<'PY' ... PY`, which forks a fresh
# Python process every adoption prompt. Module-level state (the in-memory
# _SESSION_ADOPTION_COUNT) resets to 0 on every fork, so the 3-adoption brake
# never fires in production. The persistent helpers below disk-back the counter
# under tracks.<track>.session_adoption_count in state/scratchpad.json.


def test_adoption_count_persistent_starts_at_zero(tmp_path):
    """Fresh project (no scratchpad.json yet) reads as zero, not an error."""
    scratchpad_path = tmp_path / "state" / "scratchpad.json"
    assert personal_rules.adoption_count_this_session_persistent(scratchpad_path) == 0


def test_append_adoption_increments_persistent_counter(tmp_path, monkeypatch):
    """append_adoption must bump the on-disk counter so the next forked
    Python process sees the incremented value (the SKILL.md production path)."""
    monkeypatch.setattr(pathlib.Path, "home", lambda: tmp_path)
    scratchpad_path = tmp_path / "state" / "scratchpad.json"
    assert personal_rules.adoption_count_this_session_persistent(scratchpad_path) == 0
    personal_rules.append_adoption(
        classifier_label="permission-change: chmod",
        fingerprint="a" * 64,
        reason="ok in tmp",
        scratchpad_path=scratchpad_path,
    )
    assert personal_rules.adoption_count_this_session_persistent(scratchpad_path) == 1
    personal_rules.append_adoption(
        classifier_label="dependency-add: pip install",
        fingerprint="b" * 64,
        reason="dev dep",
        scratchpad_path=scratchpad_path,
    )
    assert personal_rules.adoption_count_this_session_persistent(scratchpad_path) == 2


def test_persistent_counter_survives_module_reload(tmp_path, monkeypatch):
    """Simulate the SKILL.md `python3 - <<'PY'` fork by reloading the
    personal_rules module — that wipes _SESSION_ADOPTION_COUNT but the
    persistent counter must survive."""
    import importlib

    monkeypatch.setattr(pathlib.Path, "home", lambda: tmp_path)
    scratchpad_path = tmp_path / "state" / "scratchpad.json"
    personal_rules.append_adoption(
        classifier_label="x",
        fingerprint="a" * 64,
        reason="r",
        scratchpad_path=scratchpad_path,
    )
    # In-memory counter is now 1; reload nukes it.
    reloaded = importlib.reload(personal_rules)
    assert reloaded.adoption_count_this_session() == 0  # in-memory wiped (proves reload worked)
    # Persistent counter still 1.
    assert reloaded.adoption_count_this_session_persistent(scratchpad_path) == 1


def test_persistent_counter_resets_via_helper(tmp_path, monkeypatch):
    """reset_session_adoption_count_persistent zeroes the on-disk value so
    test fixtures can assert on a fresh state without hand-editing JSON."""
    monkeypatch.setattr(pathlib.Path, "home", lambda: tmp_path)
    scratchpad_path = tmp_path / "state" / "scratchpad.json"
    personal_rules.append_adoption(
        classifier_label="x", fingerprint="a"*64, reason="r",
        scratchpad_path=scratchpad_path,
    )
    personal_rules.append_adoption(
        classifier_label="y", fingerprint="b"*64, reason="r",
        scratchpad_path=scratchpad_path,
    )
    assert personal_rules.adoption_count_this_session_persistent(scratchpad_path) == 2
    personal_rules.reset_session_adoption_count_persistent(scratchpad_path)
    assert personal_rules.adoption_count_this_session_persistent(scratchpad_path) == 0
