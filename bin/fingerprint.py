"""Codebase fingerprinter: extract a symbol map from project files. Stdlib only.

Symbols are dicts with keys: kind, name, file, line, doc.
Output written to state/local-symbols.json by walk_repo().
"""
import ast
import json
import re
from pathlib import Path
from typing import Any


SHELL_FUNC_RE = re.compile(
    r"^(?:function\s+)?(?P<name>[A-Za-z_][A-Za-z0-9_]*)\s*\(\)\s*\{",
    re.MULTILINE,
)
MD_HEADER_RE = re.compile(r"^(#{1,2})\s+(.+?)\s*$", re.MULTILINE)


def extract_python_symbols(path: Path) -> list[dict[str, Any]]:
    path = Path(path)
    try:
        src = path.read_text(encoding="utf-8")
        tree = ast.parse(src, filename=str(path))
    except (SyntaxError, UnicodeDecodeError, OSError):
        return []
    out: list[dict[str, Any]] = []
    mod_doc = ast.get_docstring(tree) or ""
    out.append({
        "kind": "module",
        "name": path.stem,
        "file": str(path),
        "line": 1,
        "doc": mod_doc,
    })
    for node in tree.body:
        if isinstance(node, ast.FunctionDef):
            out.append({
                "kind": "function",
                "name": node.name,
                "file": str(path),
                "line": node.lineno,
                "doc": ast.get_docstring(node) or "",
            })
        elif isinstance(node, ast.ClassDef):
            out.append({
                "kind": "class",
                "name": node.name,
                "file": str(path),
                "line": node.lineno,
                "doc": ast.get_docstring(node) or "",
            })
    return out


def extract_shell_symbols(path: Path) -> list[dict[str, Any]]:
    path = Path(path)
    try:
        src = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return []
    out: list[dict[str, Any]] = []
    for m in SHELL_FUNC_RE.finditer(src):
        line_no = src[: m.start()].count("\n") + 1
        out.append({
            "kind": "function",
            "name": m.group("name"),
            "file": str(path),
            "line": line_no,
            "doc": "",
        })
    return out


def extract_markdown_headers(path: Path) -> list[dict[str, Any]]:
    path = Path(path)
    try:
        src = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return []
    out: list[dict[str, Any]] = []
    for m in MD_HEADER_RE.finditer(src):
        depth = len(m.group(1))
        line_no = src[: m.start()].count("\n") + 1
        out.append({
            "kind": f"h{depth}",
            "name": m.group(2).strip(),
            "file": str(path),
            "line": line_no,
            "doc": "",
        })
    return out
