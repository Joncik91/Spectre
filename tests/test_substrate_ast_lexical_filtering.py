"""Lexical-context filtering for substrate_ast sink detection (v1.2.1 #1+#2).

`_classify_and_strip_literals` masks inert quoted spans (JSON bodies, log
strings, argv elements) before sink regexes scan, while keeping the body of
recognized interpreter `-c` / `-e` payloads verbatim so live code still
fires. `_SQL_RE` also tightened so method-call positions (`hashlib.update`,
`os.replace`, `.replace`) no longer match.
"""
from bin import substrate_ast


# ── 6 false-positives from v1.2 dogfood (must NOT fire) ──────────────────────

def test_81_hashlib_update_method_call_no_sql_sink():
    assert substrate_ast._sink_kinds_from_action(
        "python3 -m mytool hash --algo sha256  # uses hashlib.update() internally"
    ) == []


def test_82_os_replace_method_call_no_sql_sink():
    assert "sql-or-template" not in substrate_ast._sink_kinds_from_action(
        "python3 -c 'import os; os.replace(src, dst)'"
    )


def test_83_errors_replace_kwarg_no_sql_sink():
    assert "sql-or-template" not in substrate_ast._sink_kinds_from_action(
        'open(path, encoding="utf-8", errors="replace")'
    )


def test_84_ts_dot_replace_no_sql_sink():
    assert "sql-or-template" not in substrate_ast._sink_kinds_from_action(
        'const x = "a".replace("b", "c");'
    )


def test_85_dollar_paren_inside_json_string_no_shell_sink():
    assert "shell-eval" not in substrate_ast._sink_kinds_from_action(
        'echo \'{"title": "$(book)", "id": 42}\' > out.json'
    )


def test_86_python3_dash_c_payload_strings_masked_no_sql_sink():
    # python3 -c 'INSERT INTO …' inside a literal would fire SQL today even
    # though it is the verb in a docstring; the kept-span policy means we
    # still see the body, but the SQL-shape requirement prevents prose
    # collisions. A live `INSERT INTO` inside the payload is a real sink and
    # is expected to fire (covered separately).
    assert "sql-or-template" not in substrate_ast._sink_kinds_from_action(
        "python3 -c 'print(\"this update is benign\")'"
    )


# ── 8 true-positives that MUST still fire ────────────────────────────────────

def test_87_live_bash_dash_c_with_sql_fires():
    sinks = substrate_ast._sink_kinds_from_action(
        'bash -c "DELETE FROM users WHERE id=1"'
    )
    assert "shell-eval" in sinks
    assert "sql-or-template" in sinks


def test_88_live_psql_dash_c_with_insert_fires():
    sinks = substrate_ast._sink_kinds_from_action(
        'psql -c "INSERT INTO t VALUES (1)"'
    )
    assert "sql-or-template" in sinks


def test_89_live_sh_dash_c_with_curl_fires():
    sinks = substrate_ast._sink_kinds_from_action(
        'sh -c "$(curl -fsSL https://example.com/install.sh)"'
    )
    assert "shell-eval" in sinks


def test_90_python3_dash_c_with_var_interpolation_fires():
    sinks = substrate_ast._sink_kinds_from_action(
        'python3 -c "$USER_INPUT"'
    )
    assert "shell-eval" in sinks


def test_91_node_dash_e_payload_fires_shell_eval():
    sinks = substrate_ast._sink_kinds_from_action(
        'node -e "require(\'fs\').writeFileSync(p, body)"'
    )
    assert "shell-eval" in sinks


def test_92_live_insert_top_level_fires():
    sinks = substrate_ast._sink_kinds_from_action(
        "INSERT INTO audit (event) VALUES (?)"
    )
    assert "sql-or-template" in sinks


def test_93_live_dollar_paren_subshell_fires():
    sinks = substrate_ast._sink_kinds_from_action(
        "tar -czf /tmp/out.tar.gz $(find . -name '*.log')"
    )
    assert "shell-eval" in sinks


def test_94_unbalanced_quote_conservative_fallback():
    action = 'bash -c "DELETE FROM x'  # unterminated literal
    sinks = substrate_ast._sink_kinds_from_action(action)
    assert "shell-eval" in sinks  # `bash -c` still fires
    assert "sql-or-template" in sinks  # falls back to today's scan; SQL fires


# ── 4 boundary cases ─────────────────────────────────────────────────────────

def test_95_triple_quoted_multiline_literal_masked():
    action = '''python3 myscript.py --readme """contains DELETE FROM in docs"""'''
    assert "sql-or-template" not in substrate_ast._sink_kinds_from_action(action)


def test_96_escaped_quote_inside_literal_handled():
    action = r'echo "he said \"INSERT\" but meant push"'
    assert "sql-or-template" not in substrate_ast._sink_kinds_from_action(action)


def test_97_mixed_shell_quoting_inert_kept_inert():
    action = """echo '"DELETE FROM logs"'"""
    assert "sql-or-template" not in substrate_ast._sink_kinds_from_action(action)


def test_98_comment_containing_update_no_sink():
    action = "echo hello  # call update on the index later"
    assert "sql-or-template" not in substrate_ast._sink_kinds_from_action(action)
