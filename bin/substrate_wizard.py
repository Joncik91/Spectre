"""v0.7 cognitive-substrate wizard. Stdlib only.

Fires 4 mandatory questions at /vision Step 0.5, generates the §8.2 block,
caches answers at ~/.spectre/substrate-cache/<author-spec-hash>.json.

The author-spec hash is over the draft body MINUS the auto-injected ### 8.2
block, so wizard injection doesn't invalidate its own cache (Copilot review
point 3).

Public API:
    SUBSTRATE_WIZARD_VERSION = "0.7"
    cache_dir_default() -> Path
    cache_path_for_hash(author_spec_hash) -> Path
    compute_author_spec_hash(spec_body) -> str
    write_cache(author_spec_hash, answers) -> Path
    read_cache(author_spec_hash) -> dict | None
    run(author_spec_hash, *, prompt_fn) -> str  (Task 3)
"""
from __future__ import annotations

import hashlib
import json
import os
import pathlib
import re
import tempfile

SUBSTRATE_WIZARD_VERSION = "0.7"

_82_BLOCK_RE = re.compile(r"\n###\s+8\.2\b.*?(?=\n##\s|\Z)", re.DOTALL)


def cache_dir_default() -> pathlib.Path:
    """Canonical cache dir: ~/.spectre/substrate-cache/."""
    return pathlib.Path.home() / ".spectre" / "substrate-cache"


def cache_path_for_hash(author_spec_hash: str) -> pathlib.Path:
    """Return the path of the cache file for a given author-spec hash."""
    return cache_dir_default() / f"{author_spec_hash}.json"


def compute_author_spec_hash(spec_body: str) -> str:
    """SHA-256 over the draft body MINUS the auto-injected ### 8.2 block.

    Stripping §8.2 means wizard injection doesn't invalidate its own cache.
    """
    stripped = _82_BLOCK_RE.sub("", spec_body)
    return hashlib.sha256(stripped.encode("utf-8")).hexdigest()


def write_cache(author_spec_hash: str, answers: dict) -> pathlib.Path:
    """Atomically write the cache JSON at mode 0600. Returns the cache path."""
    target = cache_path_for_hash(author_spec_hash)
    target.parent.mkdir(parents=True, exist_ok=True)
    body = json.dumps(
        {"schema_version": SUBSTRATE_WIZARD_VERSION, "answers": answers},
        sort_keys=True,
        separators=(",", ":"),
    )
    fd, tmp_path = tempfile.mkstemp(
        prefix=target.name + ".", dir=str(target.parent), suffix=".tmp"
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(body)
        os.chmod(tmp_path, 0o600)
        os.replace(tmp_path, target)
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise
    return target


def read_cache(author_spec_hash: str) -> dict | None:
    """Return cached answers if schema matches; None otherwise."""
    target = cache_path_for_hash(author_spec_hash)
    if not target.exists():
        return None
    try:
        body = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if body.get("schema_version") != SUBSTRATE_WIZARD_VERSION:
        return None
    return body.get("answers")
