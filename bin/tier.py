"""Persistence-tier classifier. Replaces v1 regex Risk-Gate.

Classifies a shell command into one of four tiers based on the paths it touches
and the intent of the command. Returns (tier, reasons, never_autonomous_match).

Tier semantics: silent < repo < host < network. Higher tiers default to halt.
The Never Autonomous list is intent-based and overrides tier — e.g. `chmod` on
a /tmp path still halts because permission changes are never autonomous.

Stdlib only.
"""
import re

_HOST_PREFIXES = (
    "/etc/", "/usr/", "/opt/", "/root/", "/boot/",
)
_HOST_VAR_PREFIX = "/var/"
_VAR_TMP_PREFIX = "/var/tmp/"
_TMP_PREFIX = "/tmp/"
_DEV_NULL = "/dev/null"

_NETWORK_HEADS = ("curl", "wget", "ssh", "scp", "rsync", "gh", "nsupdate", "resolvectl")
_GIT_NETWORK_VERBS = ("push", "pull", "fetch", "clone")

_LOOPBACK_RE = re.compile(r"(?:\b127\.0\.0\.1\b|\blocalhost\b|\[::1\]|\b0\.0\.0\.0\b)")
_RFC1918_RE = re.compile(r"\b(?:10\.\d|172\.(?:1[6-9]|2\d|3[01])\.|192\.168\.)")

_NEVER_AUTONOMOUS: list[tuple[re.Pattern, str]] = [
    # Privilege escalation — always halt regardless of what follows.
    (re.compile(r"\bsudo\b"), "permission-change: sudo"),
    # Destructive deletes.
    (re.compile(r"\brm\s+(-[rRfF]+|--recursive|--force)"), "destructive-delete: rm -rf"),
    (re.compile(r"\brm\s+-[a-zA-Z]*[rfRF][a-zA-Z]*\s+/(?:\s|$)"), "destructive-delete: rm of /"),
    (re.compile(r"\bpip\s+install\b"), "dependency-add: pip install"),
    (re.compile(r"\bnpm\s+install\b"), "dependency-add: npm install"),
    (re.compile(r"\bapt(?:-get)?\s+install\b"), "dependency-add: apt-get install"),
    (re.compile(r"\bcargo\s+add\b"), "dependency-add: cargo add"),
    (re.compile(r"\bDROP\s+TABLE\b", re.IGNORECASE), "schema-mutation: DROP TABLE"),
    (re.compile(r"\bDROP\s+DATABASE\b", re.IGNORECASE), "schema-mutation: DROP DATABASE"),
    (re.compile(r"\bALTER\s+TABLE\b", re.IGNORECASE), "schema-mutation: ALTER TABLE"),
    (re.compile(r"\b(migrate|migration)\b"), "schema-mutation: migrate"),
    (re.compile(r"\bchmod\b"), "permission-change: chmod"),
    (re.compile(r"\bchown\b"), "permission-change: chown"),
    (re.compile(r"\bsetcap\b"), "permission-change: setcap"),
    (re.compile(r"\biptables\b"), "permission-change: iptables"),
    (re.compile(r"\bnft\b"), "permission-change: nft"),
    (re.compile(r"\bufw\b"), "permission-change: ufw"),
    (re.compile(r"\b(usermod|useradd|groupmod|groupadd)\b"), "permission-change: user-mgmt"),
    (re.compile(r"\bapi\.openai\.com\b"), "paid-api-call: api.openai.com"),
    (re.compile(r"\bapi\.anthropic\.com\b"), "paid-api-call: api.anthropic.com"),
    (re.compile(r"\bstripe\.com\b"), "paid-api-call: stripe.com"),
    (re.compile(r"\baws\s+\w"), "paid-api-call: aws CLI"),
    (re.compile(r"\bgcloud\s+\w"), "paid-api-call: gcloud CLI"),
    (re.compile(r"\baz\s+\w"), "paid-api-call: az CLI"),
    (re.compile(r"\bgh\s+pr\s+create\b"), "external-state-network: gh pr create"),
    (re.compile(r"\bgh\s+release\s+create\b"), "external-state-network: gh release create"),
    (re.compile(r"\bwebhook\b"), "external-state-network: webhook"),
    (re.compile(r"\bcloudflare\b"), "external-state-network: cloudflare"),
    (re.compile(r"\bsystemctl\s+(?:--\S+\s+)*(start|stop|restart|reload|enable|disable|mask|unmask)\b"), "service-state-mutation: systemctl"),
    (re.compile(r"\bloginctl\s+(?:enable|disable)-linger\b"), "session-policy-mutation: loginctl linger"),
    (re.compile(r"\bhostnamectl\s+set-\w"), "host-state-mutation: hostnamectl"),
    (re.compile(r"\btimedatectl\s+set-\w"), "host-state-mutation: timedatectl"),
    (re.compile(r"\bsysctl\s+(-w|--write)\b"), "kernel-state-mutation: sysctl write"),
]

# Labels for rules whose regexes should NOT match inside quoted strings.
_VERB_SENSITIVE_LABELS = {
    "permission-change: sudo",
    "permission-change: chmod",
    "permission-change: chown",
    "permission-change: setcap",
    "permission-change: iptables",
    "permission-change: nft",
    "permission-change: ufw",
    "permission-change: user-mgmt",
    "destructive-delete: rm -rf",
    "destructive-delete: rm of /",
    "dependency-add: pip install",
    "dependency-add: npm install",
    "dependency-add: apt-get install",
    "dependency-add: cargo add",
    "service-state-mutation: systemctl",
    "session-policy-mutation: loginctl linger",
    "host-state-mutation: hostnamectl",
    "host-state-mutation: timedatectl",
    "kernel-state-mutation: sysctl write",
}

_QUOTED_STRING_RE = re.compile(r'''(?:"[^"]*"|'[^']*')''')


def _strip_quoted_strings(command: str) -> str:
    """Remove single- or double-quoted substrings so verb regexes don't fire inside them."""
    return _QUOTED_STRING_RE.sub("", command)


_PATH_TOKEN = re.compile(r"(?:^|\s)([./][\w./-]+)")
# Bare relative paths: tokens that contain a slash (e.g. src/foo, tests/) or
# have a .extension (e.g. myfile.txt, src/foo.py).
_BARE_RELATIVE = re.compile(
    r"(?<=\s)([A-Za-z0-9_][\w-]*(?:/[\w.-]+)+)"  # contains a slash
    r"|(?<=\s)([A-Za-z0-9_][\w/-]*\.[A-Za-z0-9_][^\s]*)"  # has a .extension
)


def _extract_paths(command: str) -> list[str]:
    """Return all path-like tokens in the command, preserving order."""
    out: list[str] = []
    seen: set[str] = set()
    for m in _PATH_TOKEN.finditer(command):
        token = m.group(1).rstrip(",;:")
        if token not in seen:
            seen.add(token)
            out.append(token)
    # Also capture bare relative paths like "myfile.txt" or "src/foo.py"
    for m in _BARE_RELATIVE.finditer(command):
        token = (m.group(1) or m.group(2) or "").rstrip(",;:")
        if token and token not in seen:
            seen.add(token)
            out.append(token)
    return out


def _path_tier(path: str) -> str:
    """Return the tier for a single path string."""
    if path == _DEV_NULL:
        return "silent"
    if path.startswith(_VAR_TMP_PREFIX) or path == "/var/tmp":
        return "silent"
    if path.startswith(_TMP_PREFIX) or path == "/tmp":
        return "silent"
    for prefix in _HOST_PREFIXES:
        if path.startswith(prefix):
            return "host"
    if path.startswith(_HOST_VAR_PREFIX):
        return "host"
    return "repo"


def _is_network(command: str) -> bool:
    head = command.strip().split()
    if not head:
        return False
    # Skip a leading sudo so `sudo curl` is still classified network-tier.
    idx = 1 if head[0] == "sudo" and len(head) > 1 else 0
    if idx >= len(head):
        return False
    first = head[idx]
    is_net_head = first in _NETWORK_HEADS or (
        first == "git" and idx + 1 < len(head) and head[idx + 1] in _GIT_NETWORK_VERBS
    )
    if not is_net_head:
        return False
    # Loopback / RFC1918 destinations stay local — downgrade so file-tier rules apply.
    # Variable URLs ($VAR / ${VAR}) keep network classification: false-positive is the safe default.
    if _LOOPBACK_RE.search(command) or _RFC1918_RE.search(command):
        return False
    return True


def _check_never_autonomous(command: str) -> str | None:
    scrubbed = _strip_quoted_strings(command)
    for regex, label in _NEVER_AUTONOMOUS:
        haystack = scrubbed if label in _VERB_SENSITIVE_LABELS else command
        if regex.search(haystack):
            return label
    return None


_TIER_RANK = {"silent": 0, "repo": 1, "host": 2, "network": 3}


def classify(command: str) -> tuple[str, list[str], str | None]:
    """Classify a command into a persistence tier.

    Returns (tier, reasons, never_autonomous_match).
    - tier: one of "silent", "repo", "host", "network"
    - reasons: human-readable rationale strings
    - never_autonomous_match: label string if Never Autonomous list matched, else None
    """
    reasons: list[str] = []
    if _is_network(command):
        reasons.append("command head is a network verb")
        na = _check_never_autonomous(command)
        return ("network", reasons, na)

    paths = _extract_paths(command)
    if not paths:
        tier_value = "silent"
        reasons.append("no filesystem path detected")
    else:
        max_rank = 0
        for p in paths:
            t = _path_tier(p)
            r = _TIER_RANK[t]
            if r > max_rank:
                max_rank = r
                reasons = [f"path {p!r} → {t}"]
            elif r == max_rank:
                reasons.append(f"path {p!r} → {t}")
        tier_value = next(name for name, rank in _TIER_RANK.items() if rank == max_rank)

    na = _check_never_autonomous(command)
    return (tier_value, reasons, na)


def fingerprint_for_action(*, action: str, classifier_label: str) -> str:
    """Same SHA-256 fingerprint format that observations.fingerprint_halt produces.
    Lives here so /implement skill prose can compute the fingerprint without
    importing observations directly (decouples the call site)."""
    from bin import observations as _observations
    return _observations.fingerprint_halt(action=action, classifier_label=classifier_label)


def should_halt(
    tier_value: str,
    never_autonomous_match: str | None,
    *,
    action: str | None = None,
    reasons: list[str] | None = None,
    spec_locked_paths: frozenset[str] = frozenset(),
) -> bool:
    """Return True if the runner should halt and require user confirmation.

    v0.4.1: consult personal-rules.toml. A personal-rules entry can downgrade
    a halt to a non-halt UNLESS:
      - never_autonomous_match is non-None (those are non-overridable).
      - The action's classifier reasons reference a path in spec_locked_paths
        (the active spec's §8.1 declaration). Spec-locked rules are immune.

    Backward-compat: callers passing only (tier_value, never_autonomous_match)
    get the v0.4.0 behavior — no personal-rules consultation.
    """
    if never_autonomous_match is not None:
        return True

    base_should_halt = tier_value in ("host", "network")

    # v0.4.0-compat: no action means no personal-rules consultation.
    if not base_should_halt or action is None or reasons is None:
        return base_should_halt

    # §8.1 immunity: if any reason references a spec-locked path, personal
    # rules cannot override.
    for reason in reasons:
        for locked_path in spec_locked_paths:
            if locked_path in reason:
                return True

    # Consult personal rules. Use the first reason as the canonical label.
    if not reasons:
        return base_should_halt
    label = reasons[0]
    from bin import personal_rules as _personal
    fp = fingerprint_for_action(action=action, classifier_label=label)
    if _personal.is_classifier_halt_overridden(classifier_label=label, fingerprint=fp):
        return False
    return base_should_halt


# ── CLI entrypoint ────────────────────────────────────────────────────────────

def _read_locked_paths(spec_path) -> frozenset:
    """Read §8.1 locked paths from a spec file. Returns empty set if missing.

    Mirrors the §3.5 heredoc body: combines `mutates` + `never_touches` from
    `coverage_gate.parse_81_block`. Lazy import so the classify() hot path
    doesn't pay for the regex compile in coverage_gate at module import.
    """
    import pathlib as _pathlib
    from bin import coverage_gate as _coverage_gate

    p = _pathlib.Path(spec_path)
    if not p.is_file():
        return frozenset()
    text = p.read_text(encoding="utf-8")
    parsed = _coverage_gate.parse_81_block(text)
    locked: set[str] = set()
    locked.update(parsed.get("mutates", []))
    locked.update(parsed.get("never_touches", []))
    return frozenset(locked)


if __name__ == "__main__":
    import argparse
    import json
    import pathlib
    import sys

    parser = argparse.ArgumentParser(
        prog="tier",
        description="Persistence-tier classifier CLI — classify, should-halt, evaluate-action.",
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    # ── classify ──────────────────────────────────────────────────────────────
    p_cls = sub.add_parser(
        "classify",
        help=(
            "Classify a command into a persistence tier. Prints `TIER: <t>`, "
            "one `reason: <r>` line per reason, and (if matched) "
            "`NEVER_AUTONOMOUS: <label>`."
        ),
    )
    p_cls.add_argument(
        "--action",
        required=True,
        help="The shell command / action text to classify.",
    )

    # ── should-halt ───────────────────────────────────────────────────────────
    p_sh = sub.add_parser(
        "should-halt",
        help=(
            "Run classify + should_halt for an action. Prints `HALT: true` / "
            "`HALT: false` to stdout. Exit 0 always (parse stdout for the "
            "answer; non-zero indicates a runtime error)."
        ),
    )
    p_sh.add_argument("--action", required=True, help="The action text to evaluate.")
    p_sh.add_argument(
        "--spec",
        default=None,
        help="Active spec path; §8.1 locked paths are loaded from it.",
    )

    # ── evaluate-action ───────────────────────────────────────────────────────
    p_eval = sub.add_parser(
        "evaluate-action",
        help=(
            "Single-call orchestration for §3.5: classify the action, read "
            "§8.1 locked paths from --spec (if given), decide should_halt, and "
            "print the §3.5 prose-format output (`TIER:`, `reason:`, "
            "`NEVER_AUTONOMOUS:`, `HALT:` lines). With --json, prints a single "
            "JSON object instead."
        ),
    )
    p_eval.add_argument("--action", required=True, help="The action text to evaluate.")
    p_eval.add_argument(
        "--spec",
        default=None,
        help="Active spec path; §8.1 locked paths are loaded from it.",
    )
    p_eval.add_argument(
        "--json",
        action="store_true",
        help='Emit JSON: {"tier","reasons","never_autonomous","halt","spec_locked_paths"}.',
    )

    args = parser.parse_args()

    if args.cmd == "classify":
        try:
            t, reasons, na = classify(args.action)
        except Exception as exc:  # noqa: BLE001
            print(f"ERROR: {exc}", file=sys.stderr)
            sys.exit(1)
        print(f"TIER: {t}")
        for r in reasons:
            print(f"  reason: {r}")
        if na:
            print(f"NEVER_AUTONOMOUS: {na}")

    elif args.cmd == "should-halt":
        try:
            t, reasons, na = classify(args.action)
            locked = _read_locked_paths(args.spec) if args.spec else frozenset()
            halt = should_halt(
                t,
                na,
                action=args.action,
                reasons=reasons,
                spec_locked_paths=locked,
            )
        except Exception as exc:  # noqa: BLE001
            print(f"ERROR: {exc}", file=sys.stderr)
            sys.exit(1)
        print(f"HALT: {'true' if halt else 'false'}")

    elif args.cmd == "evaluate-action":
        try:
            t, reasons, na = classify(args.action)
            locked = _read_locked_paths(args.spec) if args.spec else frozenset()
            halt = should_halt(
                t,
                na,
                action=args.action,
                reasons=reasons,
                spec_locked_paths=locked,
            )
        except Exception as exc:  # noqa: BLE001
            print(f"ERROR: {exc}", file=sys.stderr)
            sys.exit(1)

        if args.json:
            payload = {
                "tier": t,
                "reasons": reasons,
                "never_autonomous": na,
                "halt": halt,
                "spec_locked_paths": sorted(locked),
            }
            print(json.dumps(payload, indent=2))
        else:
            print(f"TIER: {t}")
            for r in reasons:
                print(f"  reason: {r}")
            if na:
                print(f"NEVER_AUTONOMOUS: {na}")
            print(f"HALT: {'true' if halt else 'false'}")
