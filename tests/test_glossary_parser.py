"""tests/test_glossary_parser.py — unit tests for bin/_glossary.py parser."""
from __future__ import annotations

import pathlib
import textwrap

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _parse(text: str) -> dict:
    """Parse a glossary text snippet and return the entry dict."""
    import importlib
    import bin._glossary as _g
    # Reset cache so each test gets a clean parse
    _g._GLOSSARY_CACHE = None
    return _g._parse_glossary(text)


def _load_from_text(text: str, tmp_path: pathlib.Path):
    """Write text to a tmp file, load_glossary from it, return the dict."""
    import bin._glossary as _g
    _g._GLOSSARY_CACHE = None
    p = tmp_path / "glossary.md"
    p.write_text(text, encoding="utf-8")
    result = _g.load_glossary(p)
    return result, p


# ---------------------------------------------------------------------------
# Test: parse_valid_status_entry
# ---------------------------------------------------------------------------

VALID_STATUS = textwrap.dedent("""\
    ## walker.init
    - kind: status
    - dev: Walker state machine initialized; N pending concerns, no stop reason.
    - pm: The interview has started. There are {pending} open questions for you to answer.
    - triggered_by: First /vision invocation on a new spec.
    - user_action: None — Claude will surface the first question next.
    - related: walker.answer, walker.yield, walker.stop
    - since: v0.6.0
""")


def test_parse_valid_status_entry():
    g = _parse(VALID_STATUS)
    assert "walker.init" in g
    e = g["walker.init"]
    assert e.kind == "status"
    assert "Walker state machine" in e.dev
    assert "{pending}" in e.pm
    assert "First /vision" in e.triggered_by
    assert "None" in e.user_action
    assert e.related == ["walker.answer", "walker.yield", "walker.stop"]
    assert e.since == "v0.6.0"
    assert e.key == "walker.init"


# ---------------------------------------------------------------------------
# Test: parse_valid_term_entry
# ---------------------------------------------------------------------------

VALID_TERM = textwrap.dedent("""\
    ## term:walker
    - kind: term
    - dev: State machine that drives the /vision interrogation loop.
    - pm: The interviewer. Asks you questions about what you want built.
    - related: term:concern, term:yield
""")


def test_parse_valid_term_entry():
    g = _parse(VALID_TERM)
    assert "term:walker" in g
    e = g["term:walker"]
    assert e.kind == "term"
    assert "State machine" in e.dev
    assert "interviewer" in e.pm
    assert e.related == ["term:concern", "term:yield"]
    assert e.triggered_by == ""
    assert e.user_action == ""


# ---------------------------------------------------------------------------
# Test: missing_required_field_raises
# ---------------------------------------------------------------------------

MISSING_PM = textwrap.dedent("""\
    ## walker.init
    - kind: status
    - dev: Walker state machine initialized.
    - triggered_by: First /vision invocation.
    - user_action: None.
""")


def test_missing_required_field_raises():
    from bin._glossary import GlossaryError
    with pytest.raises(GlossaryError) as exc_info:
        _parse(MISSING_PM)
    assert exc_info.value.entry_key == "walker.init"
    assert exc_info.value.missing_field == "pm"


# ---------------------------------------------------------------------------
# Test: unknown_field_preserved_in_extra
# ---------------------------------------------------------------------------

WITH_EXTRA_FIELD = textwrap.dedent("""\
    ## walker.init
    - kind: status
    - dev: Walker initialized.
    - pm: The interview has started.
    - triggered_by: /vision.
    - user_action: None.
    - some-future-field: foobar
    - another-unknown: 42
""")


def test_unknown_field_preserved_in_extra():
    g = _parse(WITH_EXTRA_FIELD)
    e = g["walker.init"]
    assert "some-future-field" in e.extra
    assert e.extra["some-future-field"] == "foobar"
    assert "another-unknown" in e.extra
    assert e.extra["another-unknown"] == "42"


# ---------------------------------------------------------------------------
# Test: related_parsed_as_list
# ---------------------------------------------------------------------------

WITH_RELATED_LIST = textwrap.dedent("""\
    ## walker.init
    - kind: status
    - dev: Walker initialized.
    - pm: The interview has started.
    - triggered_by: /vision.
    - user_action: None.
    - related: a, b, c
""")


def test_related_parsed_as_list():
    g = _parse(WITH_RELATED_LIST)
    assert g["walker.init"].related == ["a", "b", "c"]


# ---------------------------------------------------------------------------
# Test: empty_related_is_empty_list
# ---------------------------------------------------------------------------

WITH_EMPTY_RELATED = textwrap.dedent("""\
    ## term:walker
    - kind: term
    - dev: The walker.
    - pm: The interviewer.
    - related:
""")


def test_empty_related_is_empty_list():
    g = _parse(WITH_EMPTY_RELATED)
    assert g["term:walker"].related == []


# ---------------------------------------------------------------------------
# Test: placeholder_substitution_present_fields
# ---------------------------------------------------------------------------

def test_placeholder_substitution_present_fields():
    from bin._glossary import Entry, render_pm_sentence
    entry = Entry(key="x", kind="status", dev="d", pm="hello {name}")
    result = render_pm_sentence(entry, {"name": "world"})
    assert result == "hello world"


# ---------------------------------------------------------------------------
# Test: placeholder_substitution_missing_field
# ---------------------------------------------------------------------------

def test_placeholder_substitution_missing_field():
    from bin._glossary import Entry, render_pm_sentence
    entry = Entry(key="x", kind="status", dev="d", pm="hello {name} and {other}")
    # Missing key → empty string at that position, no crash
    result = render_pm_sentence(entry, {"name": "world"})
    assert "world" in result
    assert "{other}" not in result  # placeholder replaced with empty
    assert result == "hello world and "


# ---------------------------------------------------------------------------
# Test: load_caches_at_module_level
# ---------------------------------------------------------------------------

def test_load_caches_at_module_level(tmp_path):
    import bin._glossary as _g
    _g._GLOSSARY_CACHE = None
    text = VALID_STATUS + "\n" + VALID_TERM
    g1, p = _load_from_text(text, tmp_path)
    # Modify the file — second call should return same cached dict
    p.write_text(VALID_TERM, encoding="utf-8")
    g2 = _g.load_glossary(p)
    assert g1 is g2


# ---------------------------------------------------------------------------
# Test: lookup_returns_none_for_missing_code
# ---------------------------------------------------------------------------

def test_lookup_returns_none_for_missing_code(tmp_path):
    import bin._glossary as _g
    _g._GLOSSARY_CACHE = None
    _load_from_text(VALID_STATUS, tmp_path)
    # lookup calls _get_glossary which uses cached path
    result = _g.lookup("does.not.exist")
    assert result is None


# ---------------------------------------------------------------------------
# Test: lookup_term_handles_prefix
# ---------------------------------------------------------------------------

def test_lookup_term_handles_prefix(tmp_path):
    import bin._glossary as _g
    _g._GLOSSARY_CACHE = None
    _load_from_text(VALID_STATUS + "\n" + VALID_TERM, tmp_path)
    # lookup_term("walker") should find term:walker
    entry = _g.lookup_term("walker")
    assert entry is not None
    assert entry.key == "term:walker"


# ---------------------------------------------------------------------------
# Test: all_codes_excludes_terms
# ---------------------------------------------------------------------------

def test_all_codes_excludes_terms(tmp_path):
    import bin._glossary as _g
    _g._GLOSSARY_CACHE = None
    _load_from_text(VALID_STATUS + "\n" + VALID_TERM, tmp_path)
    codes = _g.all_codes()
    assert "walker.init" in codes
    # term:walker should NOT appear in all_codes()
    assert "term:walker" not in codes
    assert "walker" not in codes
