"""Codebase fingerprinter: extract a symbol map from project files. Stdlib only.

Symbols are dicts with keys: kind, name, file, line, doc.
Output written to state/local-symbols.json by walk_repo().
"""
import ast
import json
import re
from pathlib import Path
from typing import Any


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
