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
    run_with_flags(author_spec_hash, *, receiver, trust_profile, binding,
                   provenance, force=False) -> str
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

# Must match hashlib.sha256().hexdigest() output — 64 lowercase hex chars.
_AUTHOR_SPEC_HASH_RE = re.compile(r"^[0-9a-f]{64}$")


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


class WizardValidationError(ValueError):
    """Raised by _validate_* functions when input is invalid.

    ``field`` is the canonical field name (receiver, trust_profile, binding,
    provenance, author_spec_hash).  ``message`` is a human-readable explanation
    that ends up in the ``detail=`` field of the error emission.
    """

    def __init__(self, field: str, message: str) -> None:
        super().__init__(message)
        self.field = field
        self.message = message


def write_cache(author_spec_hash: str, answers: dict) -> pathlib.Path:
    """Atomically write the cache JSON at mode 0600. Returns the cache path."""
    if not _AUTHOR_SPEC_HASH_RE.match(author_spec_hash):
        raise ValueError(
            "invalid author-spec hash (must be 64-char lowercase hex)"
        )
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
    if not _AUTHOR_SPEC_HASH_RE.match(author_spec_hash):
        raise ValueError(
            "invalid author-spec hash (must be 64-char lowercase hex)"
        )
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

_RECEIVER_VALUES = frozenset(_RECEIVER_TIERS.values())

_VALID_TRUST_TOKENS = frozenset({
    "untrusted-input",
    "handles-secrets",
    "touches-network",
    "executes-generated-code",
    "none",
})


# ---------------------------------------------------------------------------
# Pure validators — shared by interactive and flag paths
# ---------------------------------------------------------------------------

def _validate_receiver(raw: str) -> str:
    """Validate a receiver value (tier digit or canonical name). Returns canonical string."""
    stripped = raw.strip()
    if stripped in _RECEIVER_TIERS:
        return _RECEIVER_TIERS[stripped]
    if stripped in _RECEIVER_VALUES:
        return stripped
    raise WizardValidationError(
        "receiver",
        f"invalid receiver: {raw!r}. Must be one of: "
        + ", ".join(sorted(_RECEIVER_VALUES))
        + " (or digit 1-4)",
    )


def _validate_trust_profile(raw: str) -> list[str]:
    """Validate and parse a trust-profile string. Returns list of tokens (empty = none).

    The bare string "none" (or empty) collapses to [].  Mixed lists like
    "untrusted-input,none" keep the "none" token as-is (v0.8.0 semantics).
    """
    stripped = raw.strip()
    if not stripped or stripped == "none":
        return []
    tokens = [t.strip() for t in stripped.split(",") if t.strip()]
    for t in tokens:
        if t not in _VALID_TRUST_TOKENS:
            raise WizardValidationError(
                "trust_profile",
                f"unknown trust token: {t!r}. Valid tokens: "
                + ", ".join(sorted(_VALID_TRUST_TOKENS)),
            )
    return tokens


def _validate_contextual_binding(raw: str) -> str:
    """Validate contextual-binding. Must be non-empty."""
    stripped = raw.strip()
    if not stripped:
        raise WizardValidationError(
            "binding", "contextual-binding must not be empty"
        )
    return stripped


def _validate_provenance(raw: str) -> dict:
    """Validate provenance string. Returns parsed dict."""
    stripped = raw.strip()
    if not stripped or stripped == "none":
        return {"kind": "none"}
    parts = stripped.split()
    if len(parts) != 3 or parts[0] != "derived-from":
        raise WizardValidationError(
            "provenance",
            "provenance must be 'none' or 'derived-from <slug> <hex64-sha256>'",
        )
    _, slug, sha = parts
    sha_lower = sha.lower()
    if len(sha_lower) != 64 or not all(c in "0123456789abcdef" for c in sha_lower):
        raise WizardValidationError(
            "provenance",
            f"invalid parent envelope sha256: {sha!r}",
        )
    return {
        "kind": "derived-from",
        "parent-slug": slug,
        "parent-envelope-sha256": sha_lower,
    }


# ---------------------------------------------------------------------------
# Interactive ask helpers — thin wrappers around validators
# ---------------------------------------------------------------------------

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
    return _validate_receiver(raw)


def _ask_trust_profile(prompt_fn) -> list[str]:
    """Q2: trust profile. Comma-separated tokens or 'none'."""
    raw = prompt_fn(
        "Trust profile (comma-separated, or 'none'):\n"
        "  untrusted-input | handles-secrets | touches-network | executes-generated-code\n"
        "Choice: "
    ).strip()
    return _validate_trust_profile(raw)


def _ask_contextual_binding(prompt_fn) -> str:
    """Q3: one-line description of what this spec is FOR."""
    raw = prompt_fn(
        "Contextual binding (one-line description of what this spec is FOR;\n"
        "the evaluator will refuse to replay it as something else):\n"
    ).strip()
    return _validate_contextual_binding(raw)


def _ask_provenance(prompt_fn) -> dict:
    """Q4: provenance. 'none' or 'derived-from <slug> <parent-envelope-sha256>'."""
    raw = prompt_fn(
        "Provenance:\n"
        "  none — fresh spec\n"
        "  derived-from <slug> <parent-envelope-sha256> — fork of an existing locked spec\n"
        "Choice: "
    ).strip()
    return _validate_provenance(raw)


# v1.0 — per-view trust-profile vocabularies. Each view has its own
# semantic space; the implementing-agent trust tokens (untrusted-input,
# handles-secrets, …) are about taint propagation through the spec, while
# the human-user tokens (accessibility-required, …) are about UX
# obligations the product must satisfy. Cross-pollination would mislead
# the evaluator.
_VIEW_TRUST_TOKENS: dict[str, frozenset[str]] = {
    "implementing-agent": frozenset({
        "untrusted-input",
        "handles-secrets",
        "touches-network",
        "executes-generated-code",
    }),
    "product-input": frozenset({
        "validated-schema",
        "signed-payload",
        "rate-limited",
        "untrusted",
    }),
    "product-output": frozenset({
        "schema-stable",
        "versioned",
        "deprecation-policy",
    }),
    "human-user": frozenset({
        "accessibility-required",
        "i18n-required",
        "screen-reader-compatible",
    }),
    "integrator": frozenset({
        "semver-stable",
        "breaking-change-policy",
        "deprecation-window",
    }),
    "operator": frozenset({
        "paging-required",
        "slo-defined",
        "runbook-required",
    }),
}


def _validate_view_trust_profile(view: str, raw: str) -> list[str]:
    """Per-view trust-profile validator. Tokens must come from the view's
    own vocabulary in _VIEW_TRUST_TOKENS — view A's tokens are not valid
    under view B's profile."""
    stripped = (raw or "").strip()
    if not stripped or stripped == "none":
        return []
    allowed = _VIEW_TRUST_TOKENS.get(view)
    if allowed is None:
        raise WizardValidationError("view", f"unknown view {view!r}")
    tokens = [t.strip() for t in stripped.split(",") if t.strip()]
    for t in tokens:
        if t not in allowed:
            # Disambiguation hint: when the token IS valid in another view,
            # tell the operator instead of just listing the current view's
            # allowed set. Saves an "is it misspelled?" detour.
            other_views = sorted(
                v for v, vocab in _VIEW_TRUST_TOKENS.items() if t in vocab
            )
            hint = (
                f" (Note: {t!r} is valid in view {other_views[0]!r}, not {view!r}.)"
                if other_views
                else ""
            )
            raise WizardValidationError(
                "trust_profile",
                f"unknown trust token for view {view!r}: {t!r}. Valid tokens: "
                + ", ".join(sorted(allowed)) + hint,
            )
    return tokens


# v1.0 — per-view fingerprint vocabularies
_VIEW_FINGERPRINTS: dict[str, list[str]] = {
    # §8.2 implementing-agent — existing 4-value vocabulary (unchanged).
    "implementing-agent": [
        "claude-code+human",
        "claude-code-autonomous",
        "non-claude-ai",
        "human-only",
    ],
    "product-input": [
        "human-typed",
        "programmatic-trusted",
        "programmatic-untrusted",
        "streamed-event",
        "not-applicable",
    ],
    "product-output": [
        "human-reader",
        "programmatic-consumer",
        "streaming-sink",
        "log-aggregator",
        "not-applicable",
    ],
    "human-user": [
        "cli-power-user",
        "cli-novice",
        "gui-only",
        "no-human-user",
        "not-applicable",
    ],
    "integrator": [
        "library-consumer",
        "api-consumer",
        "webhook-subscriber",
        "sdk-author",
        "no-integrator",
        "not-applicable",
    ],
    "operator": [
        "on-call-engineer",
        "sre-team",
        "self-operated",
        "no-operator",
        "not-applicable",
    ],
}

# View -> §8.x section number
_VIEW_SECTION = {
    "implementing-agent": "8.2",
    "product-input": "8.3",
    "product-output": "8.4",
    "human-user": "8.5",
    "integrator": "8.6",
    "operator": "8.7",
}


def _format_view_block(view: str, answers: dict) -> str:
    """Render answers into a §8.x markdown block for the given view.

    `view` is one of the keys in _VIEW_FINGERPRINTS. `answers` carries
    the same field shape as §8.2 (receiver-fingerprint, trust-profile,
    contextual-binding, provenance optional, ux-contract placeholders).

    When receiver-fingerprint == 'not-applicable', the block degenerates
    to a single not-applicable: <reason> field and the rest of the
    schema is omitted.
    """
    section = _VIEW_SECTION[view]
    receiver = answers["receiver-fingerprint"]
    heading_suffix = {
        "implementing-agent": "Cognitive-substrate contract",
        "product-input": "Product-input substrate",
        "product-output": "Product-output substrate",
        "human-user": "Human-user substrate",
        "integrator": "Integrator substrate",
        "operator": "Operator substrate",
    }[view]

    if receiver == "not-applicable":
        reason = answers.get("not-applicable-reason", "declared out-of-scope by spec author").strip() or "declared out-of-scope by spec author"
        return (
            f"\n### {section} {heading_suffix}\n\n"
            f"- not-applicable: {reason}\n"
        )

    trust = answers["trust-profile"]
    trust_str = ", ".join(trust) if trust else "none"
    binding = answers["contextual-binding"]

    body = [
        f"\n### {section} {heading_suffix}\n",
        "",
        f"- receiver-fingerprint: {receiver}",
        f"- trust-profile: {trust_str}",
        f"- contextual-binding: {binding}",
    ]
    # Provenance is only meaningful for the implementing-agent view (it tracks
    # spec lineage, not per-view metadata). Skip for the other five views.
    if view == "implementing-agent":
        prov = answers["provenance"]
        if prov["kind"] == "none":
            prov_str = "{ kind: none }"
        else:
            prov_str = (
                "{ kind: derived-from, "
                f"parent-slug: {prov['parent-slug']}, "
                f"parent-envelope-sha256: {prov['parent-envelope-sha256']} }}"
            )
        body.append(f"- provenance: {prov_str}")
    body.extend([
        "- ux-contract:",
        "    on-success: <one-line receiver-visible message>",
        "    on-failure: <one-line receiver-visible message + remediation hint>",
        "    log-target: <path or stream>",
        "- assumptions-killed: <considered-and-ruled-out alternatives for this view>",
    ])
    if view == "implementing-agent":
        body.extend([
            "- requires-situated-judgment: <list of step IDs>",
            "- roi-budget: <yield-curve slope target / scaffolding cost ceiling>",
        ])
    return "\n".join(body) + "\n"


def _validate_view_receiver(view: str, raw: str) -> str:
    """Validate a receiver-fingerprint against the view's vocabulary."""
    cleaned = (raw or "").strip()
    allowed = _VIEW_FINGERPRINTS.get(view)
    if allowed is None:
        raise WizardValidationError("view", f"unknown view {view!r}")
    if cleaned not in allowed:
        raise WizardValidationError(
            "receiver-fingerprint",
            f"for view {view!r} must be one of {allowed}, got {cleaned!r}",
        )
    return cleaned


def run_per_view(
    *,
    view: str,
    receiver: str,
    trust_profile: str = "none",
    binding: str = "",
    not_applicable_reason: str = "",
) -> str:
    """Render one §8.x block from validated flag values.

    Caller (the /vision skill) walks the view_scope dict from WalkState
    and invokes run_per_view once per view. Cache lives outside this
    function — caller is responsible for caching when the receiver
    fingerprint should round-trip across walks (see run_with_flags for
    the §8.2 cache pattern).

    `receiver` must be 'not-applicable' OR a value from the view's
    vocabulary in _VIEW_FINGERPRINTS.
    """
    cleaned_receiver = _validate_view_receiver(view, receiver)
    if cleaned_receiver == "not-applicable":
        return _format_view_block(view, {
            "receiver-fingerprint": cleaned_receiver,
            "not-applicable-reason": not_applicable_reason,
        })
    answers = {
        "receiver-fingerprint": cleaned_receiver,
        "trust-profile": _validate_view_trust_profile(view, trust_profile),
        "contextual-binding": _validate_contextual_binding(binding) if binding else "<one-line description for this view>",
    }
    return _format_view_block(view, answers)


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


def run_with_flags(
    author_spec_hash: str,
    *,
    receiver: str,
    trust_profile: str,
    binding: str,
    provenance: str,
    force: bool = False,
) -> str:
    """Non-interactive run using flag values.

    Cache hit takes precedence unless force=True.
    Validates all four inputs via the _validate_* helpers.
    Raises WizardValidationError on invalid input.
    Returns the §8.2 markdown block.
    """
    if not force:
        cached = read_cache(author_spec_hash)
        if cached is not None:
            return _format_82_block(cached)

    answers = {
        "receiver-fingerprint": _validate_receiver(receiver),
        "trust-profile": _validate_trust_profile(trust_profile),
        "contextual-binding": _validate_contextual_binding(binding),
        "provenance": _validate_provenance(provenance),
    }
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
    p_run = sub.add_parser("run", help="Run the wizard (interactive or via flags).")
    p_run.add_argument("--author-spec-hash", required=True)
    p_run.add_argument(
        "--receiver",
        default=None,
        help="Receiver fingerprint (non-interactive).",
    )
    p_run.add_argument(
        "--trust-profile",
        default=None,
        dest="trust_profile",
        help=(
            "Comma-separated trust tokens or 'none' or empty string. "
            "Valid tokens: untrusted-input, handles-secrets, touches-network, "
            "executes-generated-code."
        ),
    )
    p_run.add_argument(
        "--binding",
        default=None,
        help="Contextual binding — one-line description of what this spec is FOR.",
    )
    p_run.add_argument(
        "--provenance",
        default=None,
        help="'none' or 'derived-from <slug> <hex64-sha256>'.",
    )
    p_run.add_argument(
        "--force",
        action="store_true",
        default=False,
        help="Bypass cache even if a fresh entry exists.",
    )

    p_pv = sub.add_parser(
        "run-per-view",
        help="Render a single §8.x block for one non-agent view (§§8.3-8.7).",
    )
    p_pv.add_argument(
        "--view",
        required=True,
        help="View name: product-input | product-output | human-user | integrator | operator.",
    )
    p_pv.add_argument(
        "--receiver",
        required=True,
        help="Receiver-fingerprint from the view's vocabulary, or 'not-applicable'.",
    )
    p_pv.add_argument(
        "--trust-profile",
        default="none",
        dest="trust_profile",
        help="Comma-separated trust tokens or 'none'. Vocabulary is per-view.",
    )
    p_pv.add_argument(
        "--binding",
        default="",
        help="Contextual binding — one-line description of what this view is FOR.",
    )
    p_pv.add_argument(
        "--not-applicable-reason",
        default="",
        dest="not_applicable_reason",
        help="One-line reason; required when --receiver is 'not-applicable'.",
    )

    args = parser.parse_args()

    if args.cmd == "run":
        # Validate --author-spec-hash before anything else.
        if not _AUTHOR_SPEC_HASH_RE.match(args.author_spec_hash):
            _status.emit(
                "error",
                "wizard.substrate",
                dest="stderr",
                reason="invalid_author_spec_hash",
                value=args.author_spec_hash[:16],
                remediation="author-spec-hash must be 64-char lowercase hex",
            )
            return 1

        flags = {
            "--receiver": args.receiver,
            "--trust-profile": args.trust_profile,
            "--binding": args.binding,
            "--provenance": args.provenance,
        }
        provided = {k for k, v in flags.items() if v is not None}
        missing = sorted(set(flags) - provided)

        if len(provided) == 4:
            # All flags supplied — non-interactive path.
            try:
                block = run_with_flags(
                    args.author_spec_hash,
                    receiver=args.receiver,
                    trust_profile=args.trust_profile,
                    binding=args.binding,
                    provenance=args.provenance,
                    force=args.force,
                )
            except WizardValidationError as exc:
                _status.emit(
                    "error",
                    "wizard.substrate",
                    dest="stderr",
                    reason=f"invalid_{exc.field}",
                    detail=exc.message,
                    remediation="re-run with corrected flag value for the field listed above",
                )
                return 1
            sys.stdout.write(block)
            sys.stdout.flush()
            return 0

        elif provided:
            # Partial flags — always error, never fall through to interactive.
            _status.emit(
                "error",
                "wizard.substrate",
                dest="stderr",
                reason="missing_flags",
                missing=",".join(f.lstrip("-") for f in missing),
                remediation="re-run with all flags: --receiver, --trust-profile, --binding, --provenance",
            )
            return 1

        else:
            # Zero flags — interactive only if TTY available.
            if not sys.stdin.isatty():
                all_flags = sorted(flags.keys())
                _status.emit(
                    "error",
                    "wizard.substrate",
                    dest="stderr",
                    reason="missing_flags",
                    missing=",".join(f.lstrip("-") for f in all_flags),
                    remediation="re-run with all flags: --receiver, --trust-profile, --binding, --provenance",
                )
                return 1
            try:
                block = run(args.author_spec_hash, prompt_fn=_stdin_prompt)
            except RuntimeError as exc:
                _status.emit(
                    "error", "wizard.substrate", dest="stderr", reason=str(exc),
                    remediation="verify DEEPSEEK_API_KEY is set and the DeepSeek API is reachable, then retry /vision",
                )
                return 1
            sys.stdout.write(block)
            sys.stdout.flush()
            return 0

    if args.cmd == "run-per-view":
        if args.receiver == "not-applicable" and not args.not_applicable_reason.strip():
            _status.emit(
                "error",
                "wizard.substrate",
                dest="stderr",
                reason="missing_not_applicable_reason",
                remediation="re-run with --not-applicable-reason '<one-line reason>' when --receiver is 'not-applicable'",
            )
            return 1
        try:
            block = run_per_view(
                view=args.view,
                receiver=args.receiver,
                trust_profile=args.trust_profile,
                binding=args.binding,
                not_applicable_reason=args.not_applicable_reason,
            )
        except WizardValidationError as exc:
            _status.emit(
                "error",
                "wizard.substrate",
                dest="stderr",
                reason=f"invalid_{exc.field}",
                detail=exc.message,
                remediation="re-run with corrected flag value for the field listed above",
            )
            return 1
        sys.stdout.write(block)
        sys.stdout.flush()
        return 0

    return 2


if __name__ == "__main__":
    raise SystemExit(_main())
