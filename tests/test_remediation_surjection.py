"""tests/test_remediation_surjection.py — invariant: every warn/halt/error emit has remediation=.

AST-walks every .py in bin/. For each _status.emit(level, code, ...) call:
  - Skips if level is a variable (not a string literal) — dynamic level, can't statically prove.
  - If level is "warn", "halt", or "error": asserts remediation= kwarg is present.
  - Collects all violations into a list; fails once at the end with a readable report.

Allowlist: intentionally empty. Aim: zero sites without a self-serve recovery hint.
"""
from __future__ import annotations

import ast
import pathlib

import pytest


_BIN_DIR = pathlib.Path(__file__).resolve().parent.parent / "bin"

# Explicit allowlist for sites that are intentionally exempt (should remain empty).
# Entry format: "bin/filename.py:<lineno>" — add a comment explaining why if ever used.
_ALLOWED_WITHOUT_REMEDIATION: frozenset[str] = frozenset()


class TestRemediationSurjection:
    def test_every_warn_halt_error_emit_has_remediation(self) -> None:
        """Every _status.emit with level warn/halt/error must carry a remediation= kwarg."""
        violations: list[str] = []

        for py in sorted(_BIN_DIR.glob("*.py")):
            try:
                tree = ast.parse(py.read_text(encoding="utf-8"))
            except SyntaxError:
                continue

            for node in ast.walk(tree):
                if not isinstance(node, ast.Call):
                    continue

                # Match _status.emit(...) or _s.emit(...) — attribute call
                func = node.func
                if not (isinstance(func, ast.Attribute) and func.attr == "emit"):
                    continue

                # emit(level, code, ...) — need at least 2 positional args
                if len(node.args) < 2:
                    continue

                level = node.args[0]
                # Skip dynamic-level calls (level is a variable, not a literal)
                if not isinstance(level, ast.Constant):
                    continue

                if level.value not in ("warn", "halt", "error"):
                    continue

                code_arg = node.args[1]
                code = (
                    code_arg.value
                    if isinstance(code_arg, ast.Constant)
                    else "<dynamic>"
                )

                has_remediation = any(
                    kw.arg == "remediation" for kw in node.keywords
                )

                if not has_remediation:
                    site_key = f"bin/{py.name}:{node.lineno}"
                    if site_key not in _ALLOWED_WITHOUT_REMEDIATION:
                        violations.append(
                            f"{py.relative_to(_BIN_DIR.parent)}:{node.lineno}"
                            f"  {level.value!r} {code!r}"
                        )

        assert not violations, (
            f"Missing remediation= at {len(violations)} site(s):\n  "
            + "\n  ".join(violations)
        )
