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

_NEVER_AUTONOMOUS: list[tuple[re.Pattern, str]] = [
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
]

_PATH_TOKEN = re.compile(r"(?:^|\s)([./][\w./-]+)")
# Bare relative paths: non-flag words after the first token that contain a dot
# (e.g. myfile.txt, src/foo.py) or look like plain directory/file names used
# as positional arguments (contain a / or . extension).
_BARE_RELATIVE = re.compile(r"(?<=\s)([A-Za-z0-9_][\w/-]*\.[A-Za-z0-9_][^\s]*)")


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
        token = m.group(1).rstrip(",;:")
        if token not in seen:
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
    first = head[0]
    if first in _NETWORK_HEADS:
        return True
    if first == "git" and len(head) > 1 and head[1] in _GIT_NETWORK_VERBS:
        return True
    return False


def _check_never_autonomous(command: str) -> str | None:
    for regex, label in _NEVER_AUTONOMOUS:
        if regex.search(command):
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


def should_halt(tier_value: str, never_autonomous_match: str | None) -> bool:
    """Return True if the runner should halt and require user confirmation."""
    if never_autonomous_match is not None:
        return True
    return tier_value in ("host", "network")
