"""Codebase fingerprinter: extract a symbol map from project files. Stdlib only.

Symbols are dicts with keys: kind, name, file, line, doc.
Output written to state/local-symbols.json by walk_repo().
"""
import ast
import json
import os
import re
import tempfile
from pathlib import Path
from typing import Any


SKIP_DIRS = {".git", "__pycache__", "state", ".venv", "node_modules", ".pytest_cache"}

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


def walk_repo(root: Path) -> list[dict[str, Any]]:
    root = Path(root)
    out: list[dict[str, Any]] = []
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        if any(part in SKIP_DIRS or part.startswith(".") for part in path.relative_to(root).parts[:-1]):
            continue
        suffix = path.suffix.lower()
        if suffix == ".py":
            out.extend(extract_python_symbols(path))
        elif suffix == ".sh":
            out.extend(extract_shell_symbols(path))
        elif suffix == ".md":
            out.extend(extract_markdown_headers(path))
    return out


def save_symbols(path: Path, symbols: list[dict[str, Any]]) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=path.name, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(symbols, f, indent=2)
        os.replace(tmp, path)
    except Exception:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


def main() -> int:
    root = Path.cwd()
    syms = walk_repo(root)
    out_path = root / "state" / "local-symbols.json"
    save_symbols(out_path, syms)
    by_kind: dict[str, int] = {}
    for s in syms:
        by_kind[s["kind"]] = by_kind.get(s["kind"], 0) + 1
    print(f"FINGERPRINT: {len(syms)} symbols across {len(by_kind)} kinds")
    for kind, count in sorted(by_kind.items()):
        print(f"  {kind}: {count}")
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
