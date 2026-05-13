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

_82_BLOCK_RE = re.compile(r"\n\n?###\s+8\.2\b.*?(?=\n##\s|\n\Z|\Z)", re.DOTALL)


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


_RECEIVER_TIERS = {
    "1": "claude-code+human",
    "2": "claude-code-autonomous",
    "3": "non-claude-ai",
    "4": "human-only",
}

_VALID_TRUST_TOKENS = frozenset({
    "untrusted-input",
    "handles-secrets",
    "touches-network",
    "executes-generated-code",
    "none",
})


def _ask_receiver(prompt_fn) -> str:
    """Q1: receiver fingerprint. Returns canonical string."""
    raw = prompt_fn(
        "Receiver?\n"
        "  1) claude-code+human (default — Claude Code with human reviewing halts)\n"
        "  2) claude-code-autonomous (Claude Code, no human in loop)\n"
        "  3) non-claude-ai (Codex / Cursor / other vendor)\n"
        "  4) human-only (no AI implementer)\n"
        "Choice [1]: "
    ).strip() or "1"
    if raw not in _RECEIVER_TIERS:
        raise ValueError(f"invalid receiver tier: {raw!r}")
    return _RECEIVER_TIERS[raw]


def _ask_trust_profile(prompt_fn) -> list[str]:
    """Q2: trust profile. Comma-separated tokens or 'none'."""
    raw = prompt_fn(
        "Trust profile (comma-separated, or 'none'):\n"
        "  untrusted-input | handles-secrets | touches-network | executes-generated-code\n"
        "Choice: "
    ).strip()
    if not raw or raw == "none":
        return []
    tokens = [t.strip() for t in raw.split(",") if t.strip()]
    for t in tokens:
        if t not in _VALID_TRUST_TOKENS:
            raise ValueError(f"unknown trust token: {t!r}")
    return tokens


def _ask_contextual_binding(prompt_fn) -> str:
    """Q3: one-line description of what this spec is FOR."""
    raw = prompt_fn(
        "Contextual binding (one-line description of what this spec is FOR;\n"
        "the evaluator will refuse to replay it as something else):\n"
    ).strip()
    if not raw:
        raise ValueError("contextual-binding must not be empty")
    return raw


def _ask_provenance(prompt_fn) -> dict:
    """Q4: provenance. 'none' or 'derived-from <slug> <parent-envelope-sha256>'."""
    raw = prompt_fn(
        "Provenance:\n"
        "  none — fresh spec\n"
        "  derived-from <slug> <parent-envelope-sha256> — fork of an existing locked spec\n"
        "Choice: "
    ).strip()
    if not raw or raw == "none":
        return {"kind": "none"}
    parts = raw.split()
    if len(parts) != 3 or parts[0] != "derived-from":
        raise ValueError(
            "provenance must be 'none' or 'derived-from <slug> <hex64-sha256>'"
        )
    _, slug, sha = parts
    if len(sha) != 64 or not all(c in "0123456789abcdef" for c in sha.lower()):
        raise ValueError(f"invalid parent envelope sha256: {sha!r}")
    return {
        "kind": "derived-from",
        "parent-slug": slug,
        "parent-envelope-sha256": sha.lower(),
    }


def _format_82_block(answers: dict) -> str:
    """Render answers into a §8.2 markdown block (canonical schema)."""
    receiver = answers["receiver-fingerprint"]
    trust = answers["trust-profile"]
    trust_str = ", ".join(trust) if trust else "none"
    binding = answers["contextual-binding"]
    prov = answers["provenance"]
    if prov["kind"] == "none":
        prov_str = "{ kind: none }"
    else:
        prov_str = (
            "{ kind: derived-from, "
            f"parent-slug: {prov['parent-slug']}, "
            f"parent-envelope-sha256: {prov['parent-envelope-sha256']} }}"
        )
    return (
        "\n### 8.2 Cognitive-substrate contract\n\n"
        f"- receiver-fingerprint: {receiver}\n"
        f"- trust-profile: {trust_str}\n"
        f"- contextual-binding: {binding}\n"
        f"- provenance: {prov_str}\n"
        "- ux-contract:\n"
        "    on-success: <one-line operator-visible message>\n"
        "    on-failure: <one-line operator-visible message + remediation hint>\n"
        "    log-target: <path or stream>\n"
        "- assumptions-killed: <list of considered-and-ruled-out alternatives>\n"
        "- requires-situated-judgment: <list of step IDs>\n"
        "- roi-budget: <yield-curve slope target / scaffolding cost ceiling>\n"
    )


def run(author_spec_hash: str, *, prompt_fn) -> str:
    """Fire the 4 mandatory questions; return §8.2 markdown.

    Uses cached answers when fresh. Raises RuntimeError('deferred') if
    prompt_fn raises EOFError (non-interactive caller).
    """
    cached = read_cache(author_spec_hash)
    if cached is not None:
        return _format_82_block(cached)
    try:
        answers = {
            "receiver-fingerprint": _ask_receiver(prompt_fn),
            "trust-profile": _ask_trust_profile(prompt_fn),
            "contextual-binding": _ask_contextual_binding(prompt_fn),
            "provenance": _ask_provenance(prompt_fn),
        }
    except EOFError as exc:
        raise RuntimeError(
            "substrate-wizard deferred: non-interactive caller (EOF). "
            "Re-run /vision interactively to lock §8.2."
        ) from exc
    write_cache(author_spec_hash, answers)
    return _format_82_block(answers)


def _stdin_prompt(question: str) -> str:
    """Default prompt_fn for the CLI: print question to stderr, read stdin."""
    import sys
    sys.stderr.write(question)
    sys.stderr.flush()
    line = sys.stdin.readline()
    if not line:
        raise EOFError()
    return line.rstrip("\n")


def _main() -> int:
    import argparse
    import sys
    from bin import _status
    parser = argparse.ArgumentParser(prog="substrate_wizard")
    sub = parser.add_subparsers(dest="cmd", required=True)
    p_run = sub.add_parser("run", help="Run the wizard interactively.")
    p_run.add_argument("--author-spec-hash", required=True)
    args = parser.parse_args()
    if args.cmd == "run":
        try:
            block = run(args.author_spec_hash, prompt_fn=_stdin_prompt)
        except RuntimeError as exc:
            _status.emit("error", "wizard.substrate", dest="stderr", reason=str(exc))
            return 1
        sys.stdout.write(block)
        sys.stdout.flush()
        return 0
    return 2


if __name__ == "__main__":
    raise SystemExit(_main())
