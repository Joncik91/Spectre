"""Tests for bin/llm_judge._segment_action — POSIX shell chain tokenizer.

Covers: &&, ;, || separators; quote protection; subshell protection; heredoc
protection; pipe non-separator; malformed-quote; empty/whitespace; edge cases.
"""
import pytest

from bin.llm_judge import _segment_action


class TestSegmentAction:
    # ── Basic separator splitting ────────────────────────────────────────────

    def test_simple_double_amp_split(self):
        assert _segment_action("a && b") == ["a", "b"]

    def test_semicolon_split(self):
        assert _segment_action("a ; b") == ["a", "b"]

    def test_double_pipe_split(self):
        assert _segment_action("a || b") == ["a", "b"]

    def test_mixed_chain(self):
        assert _segment_action("a && b ; c") == ["a", "b", "c"]

    # ── Pipe is NOT a separator ──────────────────────────────────────────────

    def test_pipe_is_not_separator(self):
        result = _segment_action("cmd | jq .")
        assert result == ["cmd | jq ."]

    # ── Quote protection ────────────────────────────────────────────────────

    def test_single_quoted_amp_stays_intact(self):
        result = _segment_action("echo 'a && b'")
        assert result == ["echo 'a && b'"]

    def test_double_quoted_amp_stays_intact(self):
        result = _segment_action('echo "a && b"')
        assert result == ['echo "a && b"']

    def test_single_quoted_semicolon_stays_intact(self):
        result = _segment_action("echo 'a ; b'")
        assert result == ["echo 'a ; b'"]

    # ── Subshell protection ─────────────────────────────────────────────────

    def test_subshell_dollar_paren(self):
        result = _segment_action("echo $(a && b)")
        assert result == ["echo $(a && b)"]

    def test_backtick_subshell(self):
        result = _segment_action("echo `a && b`")
        assert result == ["echo `a && b`"]

    # ── Heredoc protection ──────────────────────────────────────────────────

    def test_heredoc_amp_stays_intact(self):
        # The && inside the heredoc body must not produce a split.
        action = "cat <<EOF\na && b\nEOF"
        result = _segment_action(action)
        assert result is not None
        assert len(result) == 1

    # ── find -exec \; is NOT a separator ────────────────────────────────────

    def test_find_exec_does_not_split(self):
        # \; is consumed by the backslash escape handler, not treated as sep.
        result = _segment_action(r"find . -exec rm {} \;")
        assert result is not None
        assert len(result) == 1

    # ── Malformed / empty inputs ────────────────────────────────────────────

    def test_malformed_quote_returns_none(self):
        assert _segment_action("echo 'unterminated") is None

    def test_malformed_double_quote_returns_none(self):
        assert _segment_action('echo "unterminated') is None

    def test_empty_string_returns_none(self):
        assert _segment_action("") is None

    def test_whitespace_only_returns_none(self):
        assert _segment_action("   ") is None

    # ── Single command ───────────────────────────────────────────────────────

    def test_single_command_returns_list(self):
        assert _segment_action("pnpm test") == ["pnpm test"]

    # ── Mixed pipes and separators ───────────────────────────────────────────

    def test_chained_with_pipes(self):
        # The pipe is inside the first segment; && is a top-level separator.
        result = _segment_action("a | tee log && b")
        assert result == ["a | tee log", "b"]

    # ── Whitespace normalisation ────────────────────────────────────────────

    def test_leading_trailing_whitespace(self):
        result = _segment_action(" a && b ")
        assert result == ["a", "b"]

    # ── Consecutive separators — design choice: empty segments are dropped ──

    def test_consecutive_separators(self):
        # "a ;; b" — treat as a single separator boundary; empty middle dropped.
        result = _segment_action("a ;; b")
        assert result == ["a", "b"]

    # ── Real-world case from issue #59 ──────────────────────────────────────

    def test_pnpm_install_and_tsc(self):
        result = _segment_action("pnpm install && pnpm exec tsc -p tsconfig.json")
        assert result == ["pnpm install", "pnpm exec tsc -p tsconfig.json"]

    def test_three_part_chain(self):
        result = _segment_action("npm ci && npm run build && npm test")
        assert result == ["npm ci", "npm run build", "npm test"]

    def test_quoted_and_then_chained(self):
        # Quoted arg with && inside quote, then a real separator outside.
        result = _segment_action('echo "a && b" && true')
        assert result == ['echo "a && b"', "true"]
