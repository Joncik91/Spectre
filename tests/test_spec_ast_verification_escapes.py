"""Tests for Fix K (v1.1.1): YAML quote-style aware unescape in step
parsing. Prior behavior used `.strip('"').strip("'")` which left literal
backslash-quote sequences in the value, causing shlex+ast in
`_extract_python_c_bodies` to flag legitimate `python3 -c "..."` bodies
as SyntaxError (verification-syntax block findings).
"""

from __future__ import annotations

import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from bin import spec_ast


def test_unquote_yaml_scalar_handles_escaped_double_quote():
    assert spec_ast._unquote_yaml_scalar('"hello \\"world\\""') == 'hello "world"'


def test_unquote_yaml_scalar_handles_escaped_backslash():
    assert spec_ast._unquote_yaml_scalar('"a\\\\b"') == "a\\b"


def test_unquote_yaml_scalar_handles_escaped_newline():
    assert spec_ast._unquote_yaml_scalar('"line1\\nline2"') == "line1\nline2"


def test_unquote_yaml_scalar_single_quoted_doubled_apostrophe():
    assert spec_ast._unquote_yaml_scalar("'it''s'") == "it's"


def test_unquote_yaml_scalar_bare_value_preserved():
    assert spec_ast._unquote_yaml_scalar("true") == "true"


def test_unquote_yaml_scalar_unknown_escape_preserved_verbatim():
    # \q is not in our table; we keep it verbatim rather than raise so a
    # broken spec parses far enough to surface the downstream finding.
    assert spec_ast._unquote_yaml_scalar('"a\\qb"') == "a\\qb"


def test_verification_with_escaped_python_c_does_not_flag_syntax(tmp_path):
    """Fix K end-to-end: a step whose verification field uses
    `python3 -c "..."` with YAML-escaped inner quotes parses cleanly and
    does NOT emit verification-syntax-error.
    """
    body = (
        "# Test\n"
        "**Generated:** 2026-05-15\n"
        "**Slug:** escape-test\n\n"
        "## 1. Hard Problem\nProbe.\n\n"
        "## 2. First Principles\n- only stdlib\n\n"
        "## 6. Steps\n\n"
        "```yaml\n"
        '- step: 1\n'
        '  why: "verify a python import"\n'
        '  action: "touch /tmp/x"\n'
        '  verification: "python3 -c \\"import sys; sys.exit(0)\\""\n'
        "```\n\n"
        "## 8. Receiver Calibration\n### 8.1 Hard contract\n"
        "- mutates: [/tmp/x]\n"
        "- never-touches: [/etc]\n"
        "- decision-budget: 0 paid calls\n"
        "- reboot-survival: stateless\n"
    )
    spec_path = tmp_path / "escape.spec.md"
    spec_path.write_text(body)
    fs = spec_ast.classify(spec_path)
    assert not any(f.kind == "verification-syntax-error" for f in fs)
