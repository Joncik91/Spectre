# v2 Plan B — Skill Integration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Wire the Plan A graph + fingerprint infrastructure into the `/vision` and `/implement` skills, replace the v1 regex Risk-Gate with a Persistence-Tier classifier, add ADR generation + draft-to-disk to `/vision`, and ship a Post-execution State Auditor with PBT-lite. Ends in `v0.2.1`.

**Architecture:** Three new stdlib-only modules (`bin/tier.py`, `bin/auditor.py`, `bin/adr.py`) plus extended skill prose. Skills shell out to `bin/*.py` via Bash; modules stay independently testable. Graph + fingerprint touched read-only here — no graph schema changes. The v1 regex Risk-Gate stays in `skills/implement/SKILL.md` as documented prose only until Task 5 swaps it; the Python tier classifier is the source of truth. ADRs are markdown files in a new top-level `decisions/` directory; `/vision`'s confirm flow appends them and the graph manifest gets `supersedes` edges when ADRs override prior decisions. The auditor runs after every successful action+verification, derives a structured check from path captures + an optional `properties:` field, and writes its verdict into the scratchpad.

**Tech Stack:** Python 3.11+ (stdlib only). `re`, `pathlib`, `json`, `ast`, `tempfile` already in scope. `pytest` for tests. No new dependencies.

---

## File Structure

```
bin/tier.py                                            # Persistence-tier classifier (NEW)
bin/auditor.py                                         # Post-action State Auditor + PBT-lite (NEW)
bin/adr.py                                             # ADR file writer + graph supersedes-edge updater (NEW)
bin/_scratchpad.py                                     # Add audit fields to DEFAULT (MODIFY)
skills/vision/SKILL.md                                 # Add Step 0 fingerprint, Step 6 draft-to-disk, Step 6.5 ADR write (MODIFY)
skills/implement/SKILL.md                              # Replace §3.5 regex Risk-Gate with tier classifier; add §5.5 State Auditor (MODIFY)
specs/template.spec.md                                 # Optional `properties:` field per step (MODIFY)
decisions/                                             # ADR markdown files live here (NEW directory; gitignored except .gitkeep)
decisions/.gitkeep                                     # Keeps directory tracked (NEW)
tests/test_tier.py                                     # Tier classifier tests (NEW)
tests/test_auditor.py                                  # Auditor + PBT-lite tests (NEW)
tests/test_adr.py                                      # ADR writer + supersedes edge tests (NEW)
tests/test_scratchpad.py                               # Add audit field tests (MODIFY)
.claude-plugin/plugin.json                             # Bump version 1.0.0 → 1.0.1 (MODIFY)
```

The plugin.json `version` field tracks the plugin's own semver. The repo's git tag is what the user calls "v0.2.1." The plugin.json version is independent — it's bumped to 1.0.1 because Plan B adds user-visible features (tier classifier replacing regex, ADRs, auditor verdicts in scratchpad).

---

## Pre-flight (before Task 1)

- [ ] **Confirm working directory.** From `/home/joncik/apps/Spectre`, run `pwd` to confirm. All paths in this plan are relative to that root.
- [ ] **Confirm v0.2.0 baseline.** Run `git log --oneline -1`. Should show the v0.2.0 tag commit. If not, abort — Plan A must be merged first.
- [ ] **Confirm 108 tests pass.** Run `pytest tests/ -q`. Expected: 108 passed. If fewer, fix before starting.
- [ ] **Create branch.** `git switch -c plan-b-skill-integration` so v0.2.0 master stays clean during Plan B work.

---

### Task 1: Scaffolding — directories + version bump

**Files:**
- Create: `decisions/.gitkeep`
- Modify: `.claude-plugin/plugin.json` (version 1.0.0 → 1.0.1)

- [ ] **Step 1: Create `decisions/` directory with .gitkeep**

```bash
mkdir -p decisions
touch decisions/.gitkeep
```

- [ ] **Step 2: Bump plugin version**

Edit `.claude-plugin/plugin.json`. Change `"version": "1.0.0"` to `"version": "1.0.1"`. Leave other fields unchanged.

- [ ] **Step 3: Commit**

```bash
git add decisions/.gitkeep .claude-plugin/plugin.json
git commit -m "chore: scaffold decisions/ + bump plugin to 1.0.1"
```

---

### Task 2: Persistence-Tier classifier — `bin/tier.py` (test-first)

The v1 Risk-Gate regex is partial-coverage. The tier classifier replaces it: every action gets classified into one of four tiers based on the **paths it touches** plus a **Never Autonomous** intent set. Halt vs silent execution is decided by tier.

**Files:**
- Create: `bin/tier.py`
- Create: `tests/test_tier.py`

**Tier definitions:**

| Tier | Match rule | Default behavior |
|---|---|---|
| `silent` | only paths under `/tmp/`, gitignored paths, scratchpad, `/dev/null`, no filesystem path at all | execute, no halt |
| `repo` | git-tracked files in project root | execute, no halt |
| `host` | any path under `/etc/`, `/usr/`, `/opt/`, `/var/` (excluding `/var/tmp`), `/root/`, systemd unit files, `/boot/` | halt, require yes |
| `network` | command starts with `curl`, `wget`, `ssh`, `scp`, `rsync` to remote, `git push`, `git pull`, `gh`, any DNS mutation (`nsupdate`, `resolvectl`) | halt, require yes |

**Never Autonomous list** (always halt regardless of tier):

1. Top-level dependency addition: `pip install`, `npm install`, `apt install`, `apt-get install`, `cargo add`
2. Schema mutation: `ALTER TABLE`, `DROP TABLE`, `DROP DATABASE`, `migrate`, `migration` substring
3. Permission/security: `chmod`, `chown`, `setcap`, `iptables`, `nft`, `ufw`, `usermod`, `useradd`, `groupmod`, `groupadd`
4. Paid API call: matches `stripe.com`, `api.openai.com`, `api.anthropic.com`, `aws ` (CLI), `gcloud `, `az ` (Azure CLI)
5. External-state network mutation: `gh pr create`, `gh release create`, `webhook`, `dns`, `cloudflare`

The tier classifier returns `(tier, reasons: list[str], never_autonomous_match: str | None)`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_tier.py
"""Tier classifier tests. Each test names one classification axis."""
import pytest
from bin import tier


def test_silent_tier_for_tmp_path():
    t, _, na = tier.classify("touch /tmp/foo")
    assert t == "silent"
    assert na is None


def test_silent_tier_for_no_path():
    t, _, na = tier.classify("echo hello")
    assert t == "silent"
    assert na is None


def test_silent_tier_for_dev_null():
    t, _, na = tier.classify("cat foo > /dev/null")
    assert t == "silent"


def test_repo_tier_for_relative_path():
    t, _, na = tier.classify("touch myfile.txt")
    assert t == "repo"


def test_repo_tier_for_dot_relative_path():
    t, _, na = tier.classify("mkdir -p ./src/widgets")
    assert t == "repo"


def test_host_tier_for_etc_path():
    t, _, na = tier.classify("touch /etc/foo.conf")
    assert t == "host"


def test_host_tier_for_usr_path():
    t, _, na = tier.classify("cp x /usr/local/bin/y")
    assert t == "host"


def test_host_tier_for_var_path_excludes_var_tmp():
    t_var, _, _ = tier.classify("touch /var/log/foo.log")
    assert t_var == "host"
    t_var_tmp, _, _ = tier.classify("touch /var/tmp/foo")
    assert t_var_tmp == "silent"


def test_host_tier_for_systemd_unit():
    t, _, na = tier.classify("touch /etc/systemd/system/foo.service")
    assert t == "host"


def test_network_tier_for_curl():
    t, _, na = tier.classify("curl https://example.com")
    assert t == "network"


def test_network_tier_for_wget():
    t, _, na = tier.classify("wget https://example.com/file")
    assert t == "network"


def test_network_tier_for_git_push():
    t, _, na = tier.classify("git push origin master")
    assert t == "network"


def test_network_tier_for_gh_command():
    t, _, na = tier.classify("gh pr list")
    assert t == "network"


def test_never_autonomous_pip_install_overrides_silent():
    t, _, na = tier.classify("pip install requests")
    assert na == "dependency-add: pip install"


def test_never_autonomous_chmod_in_silent_tier():
    t, _, na = tier.classify("chmod 644 /tmp/foo")
    assert t == "silent"
    assert na == "permission-change: chmod"


def test_never_autonomous_apt_install():
    t, _, na = tier.classify("apt-get install -y nginx")
    assert na == "dependency-add: apt-get install"


def test_never_autonomous_drop_table():
    t, _, na = tier.classify("psql -c 'DROP TABLE users;'")
    assert na == "schema-mutation: DROP TABLE"


def test_never_autonomous_iptables():
    t, _, na = tier.classify("iptables -A INPUT -j DROP")
    assert na == "permission-change: iptables"


def test_never_autonomous_paid_api_openai():
    t, _, na = tier.classify("curl https://api.openai.com/v1/chat/completions")
    assert na == "paid-api-call: api.openai.com"


def test_never_autonomous_gh_pr_create():
    t, _, na = tier.classify("gh pr create --title foo")
    assert na == "external-state-network: gh pr create"


def test_classify_returns_tuple_shape():
    result = tier.classify("touch /tmp/foo")
    assert isinstance(result, tuple)
    assert len(result) == 3
    assert isinstance(result[0], str)
    assert isinstance(result[1], list)
    assert result[2] is None or isinstance(result[2], str)


def test_should_halt_silent_returns_false():
    assert tier.should_halt("silent", None) is False


def test_should_halt_repo_returns_false():
    assert tier.should_halt("repo", None) is False


def test_should_halt_host_returns_true():
    assert tier.should_halt("host", None) is True


def test_should_halt_network_returns_true():
    assert tier.should_halt("network", None) is True


def test_should_halt_with_never_autonomous_overrides_silent():
    assert tier.should_halt("silent", "dependency-add: pip install") is True


def test_should_halt_with_never_autonomous_overrides_repo():
    assert tier.should_halt("repo", "permission-change: chmod") is True
```

- [ ] **Step 2: Run tests — verify they all fail**

```bash
pytest tests/test_tier.py -q
```

Expected: errors importing `bin.tier` (module does not exist).

- [ ] **Step 3: Implement `bin/tier.py`**

```python
"""Persistence-tier classifier. Replaces v1 regex Risk-Gate.

Classifies a shell command into one of four tiers based on the paths it touches
and the intent of the command. Returns (tier, reasons, never_autonomous_match).

Tier semantics: silent < repo < host < network. Higher tiers default to halt.
The Never Autonomous list is intent-based and overrides tier — e.g. `chmod` on
a /tmp path still halts because permission changes are never autonomous.

Stdlib only.
"""
import re

# Tier path-prefix rules. Order matters — first match wins, so put longest prefix first.
# /var/tmp must come before /var/ to be matched as silent rather than host.
_HOST_PREFIXES = (
    "/etc/", "/usr/", "/opt/", "/root/", "/boot/",
)
_HOST_VAR_PREFIX = "/var/"
_VAR_TMP_PREFIX = "/var/tmp/"
_TMP_PREFIX = "/tmp/"
_DEV_NULL = "/dev/null"

_NETWORK_HEADS = ("curl", "wget", "ssh", "scp", "rsync", "gh", "nsupdate", "resolvectl")
_GIT_NETWORK_VERBS = ("push", "pull", "fetch", "clone")

# Never Autonomous matchers. Each is (regex, label_prefix, label_suffix).
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

# Path-extraction regex. We grab whitespace-separated tokens that look like paths
# (start with `/`, `./`, or contain `/`). Conservative — false positives ok, false negatives bad.
_PATH_TOKEN = re.compile(r"(?:^|\s)([./][\w./-]+)")


def _extract_paths(command: str) -> list[str]:
    """Return all path-like tokens in the command, preserving order."""
    out: list[str] = []
    for m in _PATH_TOKEN.finditer(command):
        token = m.group(1)
        # Strip trailing punctuation not part of a path.
        token = token.rstrip(",;:")
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
```

- [ ] **Step 4: Run tests — verify they pass**

```bash
pytest tests/test_tier.py -q
```

Expected: all tests pass.

- [ ] **Step 5: Commit**

```bash
git add bin/tier.py tests/test_tier.py
git commit -m "feat(tier): persistence-tier classifier (silent/repo/host/network) + never-autonomous list"
```

---

### Task 3: Replace v1 regex Risk-Gate with tier classifier in `/implement`

**Files:**
- Modify: `skills/implement/SKILL.md` (replace §Step 3.5 prose)

The v1 §Step 3.5 lists 10 hard-coded regex verbs. Replace it with prose that calls `bin/tier.py` via Bash. Skill-level tests don't exist (skills are markdown prose) — verification is reading the file and confirming the prose change.

- [ ] **Step 1: Read the current §Step 3.5**

`skills/implement/SKILL.md` lines 65–92 contain the v1 regex Risk-Gate. Replace those lines.

- [ ] **Step 2: Write the new §Step 3.5 prose**

Replace the entire `### Step 3.5 — Risk-Gate (Yellow tier)` section through the `If no match → continue silently to Step 3.7.` line with this new prose:

```markdown
### Step 3.5 — Persistence-Tier classifier

Classify `current_action` by tier before executing. Run:

```bash
python3 - <<'PY'
import sys
sys.path.insert(0, ".")
from bin import tier
t, reasons, na = tier.classify("""<current_action>""")
halt = tier.should_halt(t, na)
print(f"TIER: {t}")
for r in reasons:
    print(f"  reason: {r}")
if na:
    print(f"NEVER_AUTONOMOUS: {na}")
print(f"HALT: {halt}")
PY
```

Interpret the output:

- `TIER: silent` and no `NEVER_AUTONOMOUS` → continue to Step 3.7 silently.
- `TIER: repo` and no `NEVER_AUTONOMOUS` → continue to Step 3.7 silently.
- `TIER: host`, `TIER: network`, OR any `NEVER_AUTONOMOUS:` line → halt with:

```
TIER GATE Step <N>: <action>
Tier: <silent|repo|host|network>
Reasons:
  - <reason 1>
  - <reason 2>
Never autonomous: <label if any, else "n/a">
Reasoning: <one-line first-principles "why this halts — what state changes irreversibly or beyond the repo">
Proceed? (yes / halt / skip)
```

- `yes` → continue to Step 3.7 then Step 4 (execute).
- `halt` → stop. No scratchpad change.
- `skip` → advance `step` by 1 (no execution, no verification). Use only when the step was already done out-of-band; rare.

The `bin/tier.py` classifier is the source of truth — never substitute your own judgment about whether something is "safe enough." If the classifier says halt, halt.
```

Use the Edit tool. The `old_string` covers from `### Step 3.5 — Risk-Gate (Yellow tier)` through the line `If no match → continue silently to Step 3.7.` inclusive.

- [ ] **Step 3: Verify the file**

```bash
grep -n "Step 3.5" skills/implement/SKILL.md
```

Expected: one match with the new heading text.

```bash
grep -n "Risk-Gate (Yellow tier)" skills/implement/SKILL.md
```

Expected: no matches (the v1 heading is gone).

- [ ] **Step 4: Commit**

```bash
git add skills/implement/SKILL.md
git commit -m "feat(implement): replace v1 regex Risk-Gate with tier classifier in §3.5"
```

---

### Task 4: ADR writer + supersedes-edge updater — `bin/adr.py` (test-first)

ADRs are markdown files at `decisions/<NNNN>-<slug>.md` with frontmatter `id`, `title`, `date`, `status`, `supersedes`. `bin/adr.py` provides:

1. `next_id(decisions_dir)` — returns the next 4-digit ID (`0001`, `0002`, ..., `0042`).
2. `slugify(title)` — title → kebab-case slug.
3. `write_adr(decisions_dir, *, title, date, body, supersedes=None)` — writes the file atomically, returns the new path.
4. `update_graph_for_supersedes(graph_path, *, new_adr_id, old_adr_id)` — appends a `supersedes` edge from new ADR node to old ADR node in the graph manifest. If the graph manifest does not exist, no-op (caller's responsibility to create graph first).

ADRs are not graph nodes themselves in this Plan — the supersedes-edge wiring is forward-compatible scaffolding for v2's full ADR-as-node story. For now, the function only acts when both `new_adr_id` and `old_adr_id` correspond to existing nodes.

**Files:**
- Create: `bin/adr.py`
- Create: `tests/test_adr.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_adr.py
"""ADR writer and supersedes-edge tests."""
import json
from pathlib import Path

import pytest

from bin import adr, graph


def test_next_id_returns_0001_when_directory_empty(tmp_path):
    d = tmp_path / "decisions"
    d.mkdir()
    assert adr.next_id(d) == "0001"


def test_next_id_returns_0002_when_one_adr_exists(tmp_path):
    d = tmp_path / "decisions"
    d.mkdir()
    (d / "0001-foo.md").write_text("---\nid: 0001\n---\n")
    assert adr.next_id(d) == "0002"


def test_next_id_handles_gaps(tmp_path):
    d = tmp_path / "decisions"
    d.mkdir()
    (d / "0001-a.md").write_text("---\n")
    (d / "0005-b.md").write_text("---\n")
    assert adr.next_id(d) == "0006"


def test_next_id_ignores_non_adr_files(tmp_path):
    d = tmp_path / "decisions"
    d.mkdir()
    (d / ".gitkeep").write_text("")
    (d / "README.md").write_text("# Decisions")
    assert adr.next_id(d) == "0001"


def test_slugify_basic():
    assert adr.slugify("Use Postgres 16 for primary store") == "use-postgres-16-for-primary-store"


def test_slugify_strips_non_alphanumerics():
    assert adr.slugify("foo: bar/baz!") == "foo-bar-baz"


def test_slugify_collapses_repeats():
    assert adr.slugify("a   b") == "a-b"


def test_slugify_strips_leading_trailing_dashes():
    assert adr.slugify("---hello---") == "hello"


def test_write_adr_creates_file(tmp_path):
    d = tmp_path / "decisions"
    d.mkdir()
    p = adr.write_adr(d, title="Pick Postgres", date="2026-05-05", body="Body text.")
    assert p.exists()
    assert p.name == "0001-pick-postgres.md"


def test_write_adr_frontmatter_shape(tmp_path):
    d = tmp_path / "decisions"
    d.mkdir()
    p = adr.write_adr(d, title="Pick Postgres", date="2026-05-05", body="Body text.")
    text = p.read_text(encoding="utf-8")
    assert text.startswith("---\n")
    assert "id: 0001\n" in text
    assert 'title: "Pick Postgres"\n' in text
    assert "date: 2026-05-05\n" in text
    assert "status: accepted\n" in text
    assert "supersedes: null\n" in text
    assert "\n---\n\nBody text.\n" in text


def test_write_adr_with_supersedes(tmp_path):
    d = tmp_path / "decisions"
    d.mkdir()
    adr.write_adr(d, title="First", date="2026-05-04", body="A.")
    p = adr.write_adr(
        d, title="Second", date="2026-05-05", body="B.", supersedes="0001"
    )
    text = p.read_text(encoding="utf-8")
    assert "supersedes: 0001\n" in text


def test_write_adr_marks_superseded_status_on_old(tmp_path):
    d = tmp_path / "decisions"
    d.mkdir()
    p1 = adr.write_adr(d, title="First", date="2026-05-04", body="A.")
    adr.write_adr(d, title="Second", date="2026-05-05", body="B.", supersedes="0001")
    text = p1.read_text(encoding="utf-8")
    assert "status: superseded\n" in text


def test_write_adr_atomic(tmp_path):
    d = tmp_path / "decisions"
    d.mkdir()
    adr.write_adr(d, title="Foo", date="2026-05-05", body="Body.")
    leftovers = list(d.glob("*.tmp"))
    assert leftovers == []


def test_update_graph_for_supersedes_appends_edge(tmp_path):
    g = tmp_path / "specs" / ".graph.md"
    g.parent.mkdir()
    nodes = [
        graph.Node(id="adr-0001", type="invariant", title="Old"),
        graph.Node(id="adr-0002", type="invariant", title="New"),
    ]
    graph.save_graph(g, nodes)
    adr.update_graph_for_supersedes(g, new_adr_id="adr-0002", old_adr_id="adr-0001")
    reloaded = graph.load_graph(g)
    new_node = graph.get_node(reloaded, "adr-0002")
    assert new_node is not None
    assert {"target": "adr-0001", "type": "supersedes"} in new_node.edges


def test_update_graph_for_supersedes_marks_old_superseded(tmp_path):
    g = tmp_path / "specs" / ".graph.md"
    g.parent.mkdir()
    nodes = [
        graph.Node(id="adr-0001", type="invariant", title="Old"),
        graph.Node(id="adr-0002", type="invariant", title="New"),
    ]
    graph.save_graph(g, nodes)
    adr.update_graph_for_supersedes(g, new_adr_id="adr-0002", old_adr_id="adr-0001")
    reloaded = graph.load_graph(g)
    old = graph.get_node(reloaded, "adr-0001")
    assert old is not None
    assert old.status == "superseded"


def test_update_graph_for_supersedes_noop_when_graph_missing(tmp_path):
    g = tmp_path / "specs" / ".graph.md"
    # Do not create the graph file.
    adr.update_graph_for_supersedes(g, new_adr_id="adr-0002", old_adr_id="adr-0001")
    # No exception, no file created.
    assert not g.exists()


def test_update_graph_for_supersedes_noop_when_node_missing(tmp_path):
    g = tmp_path / "specs" / ".graph.md"
    g.parent.mkdir()
    nodes = [graph.Node(id="adr-0001", type="invariant", title="Old")]
    graph.save_graph(g, nodes)
    adr.update_graph_for_supersedes(g, new_adr_id="adr-0099", old_adr_id="adr-0001")
    reloaded = graph.load_graph(g)
    old = graph.get_node(reloaded, "adr-0001")
    # Old should be unchanged because new node does not exist.
    assert old is not None
    assert old.status == "active"
```

- [ ] **Step 2: Run tests — verify they fail**

```bash
pytest tests/test_adr.py -q
```

Expected: import error (module does not exist).

- [ ] **Step 3: Implement `bin/adr.py`**

```python
"""ADR file writer + graph supersedes-edge updater. Stdlib only.

ADRs live at decisions/<NNNN>-<slug>.md with frontmatter:
  id, title, date, status (accepted | superseded), supersedes (null or NNNN).

Atomic writes via tempfile.mkstemp + os.replace.
"""
import os
import re
import tempfile
from pathlib import Path

from bin import graph

_ADR_FILENAME_RE = re.compile(r"^(\d{4})-[\w-]+\.md$")


def slugify(title: str) -> str:
    """Lowercase, replace non-alphanumerics with `-`, collapse repeats, strip ends."""
    s = title.lower()
    s = re.sub(r"[^a-z0-9]+", "-", s)
    s = re.sub(r"-+", "-", s)
    return s.strip("-")


def next_id(decisions_dir: Path) -> str:
    """Return the next 4-digit ADR id."""
    decisions_dir = Path(decisions_dir)
    max_id = 0
    if decisions_dir.exists():
        for entry in decisions_dir.iterdir():
            if not entry.is_file():
                continue
            m = _ADR_FILENAME_RE.match(entry.name)
            if not m:
                continue
            n = int(m.group(1))
            if n > max_id:
                max_id = n
    return f"{max_id + 1:04d}"


def _atomic_write_text(path: Path, text: str) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=path.name, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
        os.replace(tmp, path)
    except Exception:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


def _mark_superseded(decisions_dir: Path, old_id: str) -> None:
    """Flip the old ADR's status: from accepted to superseded."""
    for entry in Path(decisions_dir).iterdir():
        m = _ADR_FILENAME_RE.match(entry.name)
        if not m or m.group(1) != old_id:
            continue
        text = entry.read_text(encoding="utf-8")
        new_text = re.sub(
            r"^status:\s*accepted\s*$",
            "status: superseded",
            text,
            count=1,
            flags=re.MULTILINE,
        )
        _atomic_write_text(entry, new_text)
        return


def write_adr(
    decisions_dir: Path,
    *,
    title: str,
    date: str,
    body: str,
    supersedes: str | None = None,
) -> Path:
    """Write an ADR file. Return the new path.

    If supersedes is set, also flips the old ADR's status to "superseded".
    """
    decisions_dir = Path(decisions_dir)
    decisions_dir.mkdir(parents=True, exist_ok=True)
    new_id = next_id(decisions_dir)
    slug = slugify(title)
    filename = f"{new_id}-{slug}.md"
    path = decisions_dir / filename
    supersedes_value = supersedes if supersedes is not None else "null"
    text = (
        "---\n"
        f"id: {new_id}\n"
        f'title: "{title}"\n'
        f"date: {date}\n"
        "status: accepted\n"
        f"supersedes: {supersedes_value}\n"
        "---\n"
        f"\n{body}\n"
    )
    _atomic_write_text(path, text)
    if supersedes is not None:
        _mark_superseded(decisions_dir, supersedes)
    return path


def update_graph_for_supersedes(
    graph_path: Path,
    *,
    new_adr_id: str,
    old_adr_id: str,
) -> None:
    """Append a supersedes edge from new ADR node to old ADR node and mark old as superseded.

    No-op if the graph manifest does not exist OR either node id is absent.
    Caller is responsible for creating the graph first.
    """
    graph_path = Path(graph_path)
    if not graph_path.exists():
        return
    nodes = graph.load_graph(graph_path)
    new_node = graph.get_node(nodes, new_adr_id)
    old_node = graph.get_node(nodes, old_adr_id)
    if new_node is None or old_node is None:
        return
    new_node.add_edge(target=old_adr_id, edge_type="supersedes")
    old_node.status = "superseded"
    graph.save_graph(graph_path, nodes)
```

- [ ] **Step 4: Run tests — verify they pass**

```bash
pytest tests/test_adr.py -q
```

Expected: all 14 tests pass.

- [ ] **Step 5: Commit**

```bash
git add bin/adr.py tests/test_adr.py
git commit -m "feat(adr): ADR writer + graph supersedes-edge updater"
```

---

### Task 5: State Auditor + PBT-lite — `bin/auditor.py` (test-first)

The Auditor runs after every successful action+verification. It derives a structured check from the action's path captures, plus runs any `properties:` declared in the spec step. PBT-lite means: no Hypothesis dependency; we hand-roll four check types (type, schema, length, range).

**Audit checks (auto-derived from action shape):**

1. File created (action wrote to a path) → `path_exists` + (if path ends `.json`) `json_parses` + (if path ends `.py`) `python_ast_parses`.
2. Service started (action used `systemctl start|restart|enable`) → `systemctl_is_active` (best-effort; OK to skip if not on this host).
3. No structured check derivable → return `("noop", "no structured check derivable")`.

**PBT-lite check types** (declared in spec step `properties:` field):

```yaml
- step: 3
  properties:
    - kind: type
      target: "/tmp/foo.json"
      expected: dict
    - kind: length
      target_field: "rows"
      min: 1
      max: 10
    - kind: range
      target_field: "price_usd"
      min: 0
      max: 1000000
```

The auditor reads the JSON file at `target`, then validates each property. Returns a list of `AuditResult` dataclass objects — `kind`, `passed: bool`, `message: str`.

**Files:**
- Create: `bin/auditor.py`
- Create: `tests/test_auditor.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_auditor.py
"""State Auditor + PBT-lite tests."""
import json
from pathlib import Path

import pytest

from bin import auditor


def test_audit_path_exists_passes(tmp_path):
    p = tmp_path / "foo.txt"
    p.write_text("hi")
    results = auditor.audit_action(
        f"touch {p}", paths_touched=[str(p)], properties=None
    )
    assert any(r.kind == "path_exists" and r.passed for r in results)


def test_audit_path_exists_fails(tmp_path):
    p = tmp_path / "missing.txt"
    results = auditor.audit_action(
        f"touch {p}", paths_touched=[str(p)], properties=None
    )
    fails = [r for r in results if r.kind == "path_exists" and not r.passed]
    assert len(fails) == 1


def test_audit_json_parses_for_dot_json_path(tmp_path):
    p = tmp_path / "out.json"
    p.write_text('{"k": 1}')
    results = auditor.audit_action(
        f"echo {{}} > {p}", paths_touched=[str(p)], properties=None
    )
    assert any(r.kind == "json_parses" and r.passed for r in results)


def test_audit_json_parses_fails_on_bad_json(tmp_path):
    p = tmp_path / "out.json"
    p.write_text("not json {")
    results = auditor.audit_action(
        f"echo {{}} > {p}", paths_touched=[str(p)], properties=None
    )
    fails = [r for r in results if r.kind == "json_parses" and not r.passed]
    assert len(fails) == 1


def test_audit_python_ast_parses_for_dot_py_path(tmp_path):
    p = tmp_path / "ok.py"
    p.write_text("x = 1\ndef foo():\n    return x\n")
    results = auditor.audit_action(
        f"python3 {p}", paths_touched=[str(p)], properties=None
    )
    assert any(r.kind == "python_ast_parses" and r.passed for r in results)


def test_audit_python_ast_parses_fails_on_syntax_error(tmp_path):
    p = tmp_path / "bad.py"
    p.write_text("def (no_name:\n")
    results = auditor.audit_action(
        f"python3 {p}", paths_touched=[str(p)], properties=None
    )
    fails = [r for r in results if r.kind == "python_ast_parses" and not r.passed]
    assert len(fails) == 1


def test_audit_noop_when_no_paths_and_no_properties():
    results = auditor.audit_action("echo hi", paths_touched=[], properties=None)
    assert len(results) == 1
    assert results[0].kind == "noop"


def test_pbt_type_check_passes(tmp_path):
    p = tmp_path / "data.json"
    p.write_text('{"k": 1}')
    props = [{"kind": "type", "target": str(p), "expected": "dict"}]
    results = auditor.audit_action(
        f"echo {{}} > {p}", paths_touched=[str(p)], properties=props
    )
    type_results = [r for r in results if r.kind == "type"]
    assert len(type_results) == 1
    assert type_results[0].passed


def test_pbt_type_check_fails_on_wrong_type(tmp_path):
    p = tmp_path / "data.json"
    p.write_text("[1, 2, 3]")
    props = [{"kind": "type", "target": str(p), "expected": "dict"}]
    results = auditor.audit_action(
        f"echo [] > {p}", paths_touched=[str(p)], properties=props
    )
    type_results = [r for r in results if r.kind == "type"]
    assert len(type_results) == 1
    assert not type_results[0].passed


def test_pbt_length_check_passes(tmp_path):
    p = tmp_path / "data.json"
    p.write_text('{"rows": [1, 2, 3]}')
    props = [{"kind": "length", "target": str(p), "target_field": "rows", "min": 1, "max": 10}]
    results = auditor.audit_action(
        f"echo {{}} > {p}", paths_touched=[str(p)], properties=props
    )
    length_results = [r for r in results if r.kind == "length"]
    assert len(length_results) == 1
    assert length_results[0].passed


def test_pbt_length_check_fails_below_min(tmp_path):
    p = tmp_path / "data.json"
    p.write_text('{"rows": []}')
    props = [{"kind": "length", "target": str(p), "target_field": "rows", "min": 1, "max": 10}]
    results = auditor.audit_action(
        f"echo {{}} > {p}", paths_touched=[str(p)], properties=props
    )
    length_results = [r for r in results if r.kind == "length"]
    assert len(length_results) == 1
    assert not length_results[0].passed


def test_pbt_length_check_fails_above_max(tmp_path):
    p = tmp_path / "data.json"
    p.write_text('{"rows": [1,2,3,4,5,6,7,8,9,10,11]}')
    props = [{"kind": "length", "target": str(p), "target_field": "rows", "min": 1, "max": 10}]
    results = auditor.audit_action(
        f"echo {{}} > {p}", paths_touched=[str(p)], properties=props
    )
    length_results = [r for r in results if r.kind == "length"]
    assert len(length_results) == 1
    assert not length_results[0].passed


def test_pbt_range_check_passes(tmp_path):
    p = tmp_path / "data.json"
    p.write_text('{"price_usd": 50000}')
    props = [{"kind": "range", "target": str(p), "target_field": "price_usd", "min": 0, "max": 1000000}]
    results = auditor.audit_action(
        f"echo {{}} > {p}", paths_touched=[str(p)], properties=props
    )
    range_results = [r for r in results if r.kind == "range"]
    assert len(range_results) == 1
    assert range_results[0].passed


def test_pbt_range_check_fails_outside_range(tmp_path):
    p = tmp_path / "data.json"
    p.write_text('{"price_usd": -5}')
    props = [{"kind": "range", "target": str(p), "target_field": "price_usd", "min": 0, "max": 1000000}]
    results = auditor.audit_action(
        f"echo {{}} > {p}", paths_touched=[str(p)], properties=props
    )
    range_results = [r for r in results if r.kind == "range"]
    assert len(range_results) == 1
    assert not range_results[0].passed


def test_pbt_schema_check_passes_when_keys_present(tmp_path):
    p = tmp_path / "data.json"
    p.write_text('{"a": 1, "b": 2, "c": 3}')
    props = [{"kind": "schema", "target": str(p), "required_keys": ["a", "b"]}]
    results = auditor.audit_action(
        f"echo {{}} > {p}", paths_touched=[str(p)], properties=props
    )
    schema_results = [r for r in results if r.kind == "schema"]
    assert len(schema_results) == 1
    assert schema_results[0].passed


def test_pbt_schema_check_fails_when_key_missing(tmp_path):
    p = tmp_path / "data.json"
    p.write_text('{"a": 1}')
    props = [{"kind": "schema", "target": str(p), "required_keys": ["a", "b"]}]
    results = auditor.audit_action(
        f"echo {{}} > {p}", paths_touched=[str(p)], properties=props
    )
    schema_results = [r for r in results if r.kind == "schema"]
    assert len(schema_results) == 1
    assert not schema_results[0].passed


def test_audit_returns_dataclass_with_kind_passed_message(tmp_path):
    p = tmp_path / "foo.txt"
    p.write_text("hi")
    results = auditor.audit_action(
        f"touch {p}", paths_touched=[str(p)], properties=None
    )
    assert all(hasattr(r, "kind") for r in results)
    assert all(hasattr(r, "passed") for r in results)
    assert all(hasattr(r, "message") for r in results)


def test_pbt_unknown_kind_returns_failed_result(tmp_path):
    p = tmp_path / "data.json"
    p.write_text("{}")
    props = [{"kind": "magic", "target": str(p)}]
    results = auditor.audit_action(
        f"echo {{}} > {p}", paths_touched=[str(p)], properties=props
    )
    magic_results = [r for r in results if r.kind == "magic"]
    assert len(magic_results) == 1
    assert not magic_results[0].passed
    assert "unknown" in magic_results[0].message.lower()
```

- [ ] **Step 2: Run tests — verify they fail**

```bash
pytest tests/test_auditor.py -q
```

Expected: import error.

- [ ] **Step 3: Implement `bin/auditor.py`**

```python
"""Post-execution State Auditor + PBT-lite checks. Stdlib only.

The auditor runs after a step's action+verification both pass. It derives
structural checks from the action's path captures and (optionally) runs a
list of property-based checks declared on the spec step.

Returns a list of AuditResult dataclasses with kind, passed, message.
"""
import ast
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass
class AuditResult:
    kind: str
    passed: bool
    message: str


_TYPE_MAP: dict[str, type] = {
    "dict": dict,
    "list": list,
    "str": str,
    "int": int,
    "float": float,
    "bool": bool,
}


def _audit_path_exists(path: str) -> AuditResult:
    p = Path(path)
    exists = p.exists()
    return AuditResult(
        kind="path_exists",
        passed=exists,
        message=f"{path}: {'exists' if exists else 'missing'}",
    )


def _audit_json_parses(path: str) -> AuditResult:
    p = Path(path)
    if not p.exists():
        return AuditResult(kind="json_parses", passed=False, message=f"{path}: missing")
    try:
        json.loads(p.read_text(encoding="utf-8"))
        return AuditResult(kind="json_parses", passed=True, message=f"{path}: valid JSON")
    except (json.JSONDecodeError, OSError, UnicodeDecodeError) as e:
        return AuditResult(kind="json_parses", passed=False, message=f"{path}: {e}")


def _audit_python_ast_parses(path: str) -> AuditResult:
    p = Path(path)
    if not p.exists():
        return AuditResult(
            kind="python_ast_parses", passed=False, message=f"{path}: missing"
        )
    try:
        ast.parse(p.read_text(encoding="utf-8"), filename=str(p))
        return AuditResult(
            kind="python_ast_parses", passed=True, message=f"{path}: valid Python"
        )
    except (SyntaxError, OSError, UnicodeDecodeError) as e:
        return AuditResult(
            kind="python_ast_parses", passed=False, message=f"{path}: {e}"
        )


def _load_json(target: str) -> tuple[bool, Any, str]:
    p = Path(target)
    if not p.exists():
        return False, None, f"{target}: missing"
    try:
        return True, json.loads(p.read_text(encoding="utf-8")), ""
    except (json.JSONDecodeError, OSError, UnicodeDecodeError) as e:
        return False, None, f"{target}: {e}"


def _resolve_field(data: Any, field_path: str) -> tuple[bool, Any]:
    """Resolve a dotted field path on a JSON object. Returns (found, value)."""
    cur = data
    for part in field_path.split("."):
        if isinstance(cur, dict) and part in cur:
            cur = cur[part]
        else:
            return False, None
    return True, cur


def _check_type(prop: dict[str, Any]) -> AuditResult:
    target = prop.get("target", "")
    expected = prop.get("expected", "")
    ok, data, err = _load_json(target)
    if not ok:
        return AuditResult(kind="type", passed=False, message=err)
    expected_type = _TYPE_MAP.get(expected)
    if expected_type is None:
        return AuditResult(
            kind="type", passed=False, message=f"unknown type literal: {expected}"
        )
    passed = isinstance(data, expected_type)
    return AuditResult(
        kind="type",
        passed=passed,
        message=f"{target}: expected {expected}, got {type(data).__name__}",
    )


def _check_schema(prop: dict[str, Any]) -> AuditResult:
    target = prop.get("target", "")
    required = prop.get("required_keys", [])
    ok, data, err = _load_json(target)
    if not ok:
        return AuditResult(kind="schema", passed=False, message=err)
    if not isinstance(data, dict):
        return AuditResult(
            kind="schema",
            passed=False,
            message=f"{target}: top-level not a dict",
        )
    missing = [k for k in required if k not in data]
    passed = not missing
    return AuditResult(
        kind="schema",
        passed=passed,
        message=f"{target}: missing keys {missing}" if missing else f"{target}: all keys present",
    )


def _check_length(prop: dict[str, Any]) -> AuditResult:
    target = prop.get("target", "")
    field_path = prop.get("target_field", "")
    min_v = prop.get("min", 0)
    max_v = prop.get("max")
    ok, data, err = _load_json(target)
    if not ok:
        return AuditResult(kind="length", passed=False, message=err)
    found, value = _resolve_field(data, field_path)
    if not found:
        return AuditResult(
            kind="length", passed=False, message=f"{target}: field {field_path!r} missing"
        )
    try:
        n = len(value)
    except TypeError:
        return AuditResult(
            kind="length",
            passed=False,
            message=f"{target}.{field_path}: value has no length",
        )
    if n < min_v:
        return AuditResult(
            kind="length",
            passed=False,
            message=f"{target}.{field_path}: length {n} < min {min_v}",
        )
    if max_v is not None and n > max_v:
        return AuditResult(
            kind="length",
            passed=False,
            message=f"{target}.{field_path}: length {n} > max {max_v}",
        )
    return AuditResult(
        kind="length",
        passed=True,
        message=f"{target}.{field_path}: length {n} within [{min_v}, {max_v}]",
    )


def _check_range(prop: dict[str, Any]) -> AuditResult:
    target = prop.get("target", "")
    field_path = prop.get("target_field", "")
    min_v = prop.get("min")
    max_v = prop.get("max")
    ok, data, err = _load_json(target)
    if not ok:
        return AuditResult(kind="range", passed=False, message=err)
    found, value = _resolve_field(data, field_path)
    if not found:
        return AuditResult(
            kind="range", passed=False, message=f"{target}: field {field_path!r} missing"
        )
    if not isinstance(value, (int, float)):
        return AuditResult(
            kind="range",
            passed=False,
            message=f"{target}.{field_path}: value not numeric",
        )
    if min_v is not None and value < min_v:
        return AuditResult(
            kind="range",
            passed=False,
            message=f"{target}.{field_path}: {value} < min {min_v}",
        )
    if max_v is not None and value > max_v:
        return AuditResult(
            kind="range",
            passed=False,
            message=f"{target}.{field_path}: {value} > max {max_v}",
        )
    return AuditResult(
        kind="range",
        passed=True,
        message=f"{target}.{field_path}: {value} within [{min_v}, {max_v}]",
    )


_PBT_DISPATCH = {
    "type": _check_type,
    "schema": _check_schema,
    "length": _check_length,
    "range": _check_range,
}


def audit_action(
    command: str,
    *,
    paths_touched: list[str],
    properties: list[dict[str, Any]] | None,
) -> list[AuditResult]:
    """Run all derived structural checks + PBT-lite checks.

    Returns a list of AuditResult dataclasses. Empty paths_touched + no
    properties → returns a single noop result.
    """
    results: list[AuditResult] = []
    if not paths_touched and not properties:
        return [AuditResult(kind="noop", passed=True, message="no structured check derivable")]
    for path in paths_touched:
        results.append(_audit_path_exists(path))
        if path.endswith(".json"):
            results.append(_audit_json_parses(path))
        elif path.endswith(".py"):
            results.append(_audit_python_ast_parses(path))
    if properties:
        for prop in properties:
            kind = prop.get("kind", "")
            check = _PBT_DISPATCH.get(kind)
            if check is None:
                results.append(
                    AuditResult(
                        kind=kind,
                        passed=False,
                        message=f"unknown property kind: {kind!r}",
                    )
                )
                continue
            results.append(check(prop))
    return results
```

- [ ] **Step 4: Run tests — verify they pass**

```bash
pytest tests/test_auditor.py -q
```

Expected: all 18 tests pass.

- [ ] **Step 5: Commit**

```bash
git add bin/auditor.py tests/test_auditor.py
git commit -m "feat(auditor): post-action State Auditor with PBT-lite (type/schema/length/range)"
```

---

### Task 6: Wire auditor into scratchpad — update `_scratchpad.py` DEFAULT + tests

The auditor's verdicts need to land in the scratchpad so the next compact's `additionalContext` carries the audit summary.

**Files:**
- Modify: `bin/_scratchpad.py`
- Modify: `tests/test_scratchpad.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_scratchpad.py`:

```python
def test_default_includes_last_audit_kinds():
    from bin import _scratchpad as sp
    assert "last_audit_kinds" in sp.DEFAULT
    assert sp.DEFAULT["last_audit_kinds"] == []


def test_default_includes_last_audit_passed():
    from bin import _scratchpad as sp
    assert "last_audit_passed" in sp.DEFAULT
    assert sp.DEFAULT["last_audit_passed"] is None


def test_default_includes_last_audit_failures():
    from bin import _scratchpad as sp
    assert "last_audit_failures" in sp.DEFAULT
    assert sp.DEFAULT["last_audit_failures"] == []
```

- [ ] **Step 2: Run tests — verify they fail**

```bash
pytest tests/test_scratchpad.py::test_default_includes_last_audit_kinds tests/test_scratchpad.py::test_default_includes_last_audit_passed tests/test_scratchpad.py::test_default_includes_last_audit_failures -q
```

Expected: 3 failures (keys missing).

- [ ] **Step 3: Update DEFAULT in `bin/_scratchpad.py`**

Add three keys to DEFAULT:

```python
DEFAULT = {
    "active_spec": None,
    "step": 1,
    "last_command": None,
    "exit_code": None,
    "delta": None,
    "timestamp": None,
    "failed_hypotheses": [],
    "paths_touched": [],
    "last_drift_check_step": 0,
    "last_audit_kinds": [],
    "last_audit_passed": None,
    "last_audit_failures": [],
}
```

- [ ] **Step 4: Run tests — verify they pass**

```bash
pytest tests/test_scratchpad.py -q
```

Expected: all tests pass (3 new + existing).

- [ ] **Step 5: Commit**

```bash
git add bin/_scratchpad.py tests/test_scratchpad.py
git commit -m "feat(scratchpad): add last_audit_kinds/passed/failures to DEFAULT"
```

---

### Task 7: Add State Auditor §5.5 to `/implement` skill

The auditor runs **after** the original verification passes (Step 5), **before** the step counter advances in Step 6 Path A. Auditor verdict is informational on first pass — it does NOT block step advance. Failed audits land in scratchpad's `last_audit_failures` for human review and surface in the next compact `additionalContext`.

**Why informational, not blocking:** The auditor's checks may have false positives (e.g. a path the action created but immediately renamed). If we made it blocking, we'd be re-litigating the spec's own verification. The auditor's value is **reporting** structural drift across many steps, not gating individual ones. v3 may promote audit to a halt condition.

**Files:**
- Modify: `skills/implement/SKILL.md`

- [ ] **Step 1: Read current §Step 6 Path A in `skills/implement/SKILL.md`**

Lines around `**Path A — verification exits 0:**`. The current sequence is: print PASSED → update scratchpad → run §6.5 Drift checkpoint → print Ready → halt.

- [ ] **Step 2: Insert §Step 5.5 prose before §Step 6**

Use Edit. Insert this section between the existing `### Step 5 — Verification gate` block and `### Step 6 — Branch on verification result`:

```markdown
### Step 5.5 — State Auditor (informational)

After verification passes but before the step advances, run the State Auditor for structural sanity:

```bash
python3 - <<'PY'
import json, sys
sys.path.insert(0, ".")
from bin import auditor

with open("state/scratchpad.json") as f:
    sp = json.load(f)
paths = sp.get("paths_touched", [])
# properties: parse from the active spec's current step `properties:` field if present.
# If absent, properties=None.
properties = None  # populated by skill prose at runtime if step has properties: yaml block
results = auditor.audit_action("<current_action>", paths_touched=paths, properties=properties)
out = {
    "kinds": [r.kind for r in results],
    "passed": all(r.passed for r in results),
    "failures": [{"kind": r.kind, "message": r.message} for r in results if not r.passed],
}
sp["last_audit_kinds"] = out["kinds"]
sp["last_audit_passed"] = out["passed"]
sp["last_audit_failures"] = out["failures"]
with open("state/scratchpad.json", "w") as f:
    json.dump(sp, f, indent=2)
print(f"AUDIT: {len(results)} checks, passed={out['passed']}")
for f in out["failures"]:
    print(f"  FAIL: {f['kind']} — {f['message']}")
PY
```

If the active spec's current step has a `properties:` YAML block, populate `properties` with that list of dicts before invoking the auditor.

The audit is **informational on first pass — it does NOT block step advance.** Failed audits land in scratchpad and surface in the next compact's `additionalContext`. If audits fail repeatedly across multiple steps in the same spec, halt and tell the user the spec needs `properties:` declarations or the actions are creating malformed artifacts.
```

- [ ] **Step 3: Verify the file**

```bash
grep -n "Step 5.5" skills/implement/SKILL.md
```

Expected: one match.

```bash
grep -n "AUDIT:" skills/implement/SKILL.md
```

Expected: at least one match (the prose includes the print line).

- [ ] **Step 4: Commit**

```bash
git add skills/implement/SKILL.md
git commit -m "feat(implement): wire State Auditor into §5.5 (informational, post-verify)"
```

---

### Task 8: Add `properties:` field to spec template

**Files:**
- Modify: `specs/template.spec.md`

- [ ] **Step 1: Update template prose**

Edit the §6 Steps prose to mention the optional `properties:` field. Replace the current schema block with:

```yaml
- step: 1
  why: "<one-line justification grounded in first principles>"
  action: "<command>"
  verification: "<post-condition check command>"
  properties:                     # OPTIONAL — auditor runs PBT-lite checks if present
    - kind: type                  # type | schema | length | range
      target: "/path/to/output.json"
      expected: dict
    - kind: length
      target: "/path/to/output.json"
      target_field: "rows"
      min: 1
      max: 10

- step: 2
  why: "<one-line justification grounded in first principles>"
  action: "<command>"
  verification: "<post-condition check command>"
```

Update the bullet list above the YAML to include:

```markdown
- `properties:` (optional) — list of PBT-lite assertions the State Auditor will check after the original verification passes. Each property has `kind:` (type/schema/length/range), `target:` (path to a JSON file), and kind-specific fields. See `bin/auditor.py` for the supported shapes.
```

- [ ] **Step 2: Verify**

```bash
grep -n "properties:" specs/template.spec.md
```

Expected: at least 2 matches.

- [ ] **Step 3: Commit**

```bash
git add specs/template.spec.md
git commit -m "feat(template): document optional properties: field for PBT-lite auditor checks"
```

---

### Task 9: Wire fingerprint + draft-to-disk + ADR into `/vision`

This is the largest skill prose change. Three additions:

1. **Step 0 (silent):** Run `bin/fingerprint.py` before drafting. Read `state/local-symbols.json`. If a symbol from the user's current vision matches existing function names, surface the prior art in the First-Principles Summary.
2. **Step 6 (replace):** Draft-to-disk. Write the spec to `specs/<slug>.spec.md.draft` immediately. User reads on disk, replies `yes` / `refine "<change>"` / `cancel`. Closes the double-token-output friction.
3. **Step 6.5 (new):** ADR generation. If the locked spec contains a step with `decision:` in its `why:` field, write an ADR via `bin/adr.py`. If the spec's First-Principles bullets contradict an earlier ADR, mark the new ADR's `supersedes:` to point at the old.

**Files:**
- Modify: `skills/vision/SKILL.md`

- [ ] **Step 1: Insert §Step 0 — Codebase Fingerprint**

Before `### Step 1 — Receive`, insert:

```markdown
### Step 0 — Codebase Fingerprint (silent, internal)

Before treating the user's text as a Spark, run the fingerprinter to check for prior art:

```bash
python3 bin/fingerprint.py 2>&1 | tail -5
```

This writes `state/local-symbols.json`. Read it:

```bash
cat state/local-symbols.json | python3 -c "import json, sys; d=json.load(sys.stdin); print(json.dumps(d[:50], indent=2))"
```

When you draft the First-Principles Summary in Step 3, scan the symbol map for any function/class/module whose name is conceptually related to the user's vision (e.g. user wants "fetch BTC price" — search for "fetch", "price", "http", "bitcoin", "btc"). If you find a candidate, mention it in the **Algorithm Audit (Delete)** section: "We will NOT reinvent <symbol_name> at <file>:<line> — we will reuse it as the basis for step N."

The "never reinvent the wheel" rule is enforced by construction here. Skipping this step violates the rule silently.
```

- [ ] **Step 2: Replace §Step 6 — Slugify + Write + Lock with draft-to-disk flow**

Replace the current `### Step 6 — Slugify + Write + Lock` block (entire content from heading to start of `### Step 7 — Transition signal`). New content:

```markdown
### Step 6 — Draft-to-disk

The user said `yes` in Step 5. Do NOT print the full spec body again — write it directly to disk so the user can review in their editor.

1. **Anchor to the user's project cwd FIRST.** Run `pwd` to capture the absolute path (e.g. `/home/foo/myproject`). Call this `$PROJECT`. All file paths in the rest of this step are `$PROJECT/specs/...` and `$PROJECT/state/...`. If `$PROJECT` looks like a plugin cache (`/root/.claude/plugins/`, `${CLAUDE_PLUGIN_ROOT}`, or contains `plugins/cache/`), HALT and tell the user to restart Claude Code from their project directory.
2. `mkdir -p "$PROJECT/specs" "$PROJECT/state" "$PROJECT/decisions"` to ensure the dirs exist.
3. Slugify the title: lowercase, replace non-alphanumerics with `-`, collapse repeats, strip leading/trailing `-`.
4. Set frontmatter `Generated:` to today's ISO date and `Slug:` to the computed slug.
5. **Write the draft file at `$PROJECT/specs/<slug>.spec.md.draft`.** Use atomic write (write to `.tmp` then `mv`).
6. Print exactly one line:

```
DRAFT: specs/<slug>.spec.md.draft (N steps). Reply: yes / refine "<change>" / cancel
```

7. **Wait for the user.**
   - `yes` → continue to Step 6.5.
   - `refine "<change>"` → reopen the draft file, apply the requested change, atomically rewrite the .draft file, re-emit the one-line confirmation. Repeat until `yes`.
   - `cancel` → delete the .draft file, halt, write nothing else.

The draft-to-disk pattern eliminates the double-token-output friction (printing the full spec inline AND writing the file). The user reviews in their editor; we hold the file in disk-only state until confirmed.

### Step 6.5 — ADR generation (conditional)

Scan the locked spec's `## 2. First Principles` bullets and step `why:` lines for explicit decision markers. A decision marker is any line that:

- starts with `decision:` (case-insensitive), OR
- contains the phrase `we choose <X> because`, OR
- contains the phrase `<X> over <Y>` with a comparative justification.

For each decision found:

1. Run:

```bash
python3 - <<'PY'
import sys
sys.path.insert(0, ".")
from bin import adr
from pathlib import Path
p = adr.write_adr(
    Path("decisions"),
    title="<extracted decision title>",
    date="<today ISO>",
    body="<one paragraph: the decision + the why from the spec>",
    supersedes=None,  # set to "NNNN" if this contradicts an existing ADR
)
print(f"ADR: {p}")
PY
```

2. **Supersedes detection.** Before writing each ADR, scan `decisions/*.md` for an existing ADR whose title or body contradicts the new decision (e.g. new ADR says "Use Postgres 16" and an existing ADR says "Use SQLite"). If found, pass `supersedes="<old_id>"`. If unsure, do NOT supersede — false positives are worse than missing supersedes (a missed supersedes can be retro-fixed; a wrong supersedes invalidates downstream work).

3. **Graph wiring.** If `specs/.graph.md` exists AND both new and old ADRs are represented as nodes, run:

```bash
python3 - <<'PY'
import sys
sys.path.insert(0, ".")
from bin import adr
from pathlib import Path
adr.update_graph_for_supersedes(
    Path("specs/.graph.md"),
    new_adr_id="adr-NNNN",
    old_adr_id="adr-MMMM",
)
PY
```

In v0.2.1 the graph manifest may not have ADR nodes yet. The `update_graph_for_supersedes` call is a no-op when nodes are absent, so it is safe to always invoke.

### Step 6.7 — Lock the spec

Now that the user confirmed and ADRs are written:

1. Atomic rename: `mv "$PROJECT/specs/<slug>.spec.md.draft" "$PROJECT/specs/<slug>.spec.md"`.
2. Atomically flip `.active`:

   ```bash
   printf 'specs/<slug>.spec.md\n' > "$PROJECT/specs/.active.tmp" && mv "$PROJECT/specs/.active.tmp" "$PROJECT/specs/.active"
   ```

3. Reset `$PROJECT/state/scratchpad.json` to:

   ```json
   {
     "active_spec": "specs/<slug>.spec.md",
     "step": 1,
     "last_command": null,
     "exit_code": null,
     "delta": null,
     "timestamp": null,
     "failed_hypotheses": [],
     "paths_touched": [],
     "last_drift_check_step": 0,
     "last_audit_kinds": [],
     "last_audit_passed": null,
     "last_audit_failures": []
   }
   ```
```

- [ ] **Step 3: Verify the file**

```bash
grep -n "Step 0 — Codebase Fingerprint" skills/vision/SKILL.md
```

Expected: one match.

```bash
grep -n "Step 6 — Draft-to-disk" skills/vision/SKILL.md
```

Expected: one match.

```bash
grep -n "Step 6.5 — ADR" skills/vision/SKILL.md
```

Expected: one match.

```bash
grep -n "Step 6.7 — Lock" skills/vision/SKILL.md
```

Expected: one match.

- [ ] **Step 4: Commit**

```bash
git add skills/vision/SKILL.md
git commit -m "feat(vision): add §0 fingerprint, §6 draft-to-disk, §6.5 ADR generation"
```

---

### Task 10: End-to-end smoke test

Validate the full v0.2.1 surface in a temp dir.

- [ ] **Step 1: Run the full test suite**

```bash
pytest tests/ -q
```

Expected: 108 (Plan A) + ~28 (tier) + ~14 (adr) + ~18 (auditor) + 3 (scratchpad audit fields) = ~171 passed. If less, fix.

- [ ] **Step 2: Manual fingerprint sanity check**

```bash
cd /home/joncik/apps/Spectre
python3 bin/fingerprint.py | tail
ls -la state/local-symbols.json
python3 -c "import json; d=json.load(open('state/local-symbols.json')); print(f'symbols: {len(d)}'); print(d[0])"
```

Expected: prints `FINGERPRINT: N symbols across K kinds` and the first symbol entry.

- [ ] **Step 3: Manual tier classifier sanity check**

```bash
python3 -c "
from bin import tier
for cmd in ['touch /tmp/foo', 'touch myfile.txt', 'curl https://example.com', 'pip install requests', 'chmod 644 /tmp/foo']:
    t, r, na = tier.classify(cmd)
    h = tier.should_halt(t, na)
    print(f'{cmd!r:50} → tier={t:<8} halt={h} na={na}')
"
```

Expected: silent/repo/network/silent+na/silent+na with halt False/False/True/True/True.

- [ ] **Step 4: Manual ADR write sanity check**

```bash
python3 -c "
from bin import adr
from pathlib import Path
import tempfile, os
d = Path(tempfile.mkdtemp()) / 'decisions'
d.mkdir()
p = adr.write_adr(d, title='Test ADR', date='2026-05-05', body='Body text.')
print(f'wrote: {p}')
print(p.read_text())
"
```

Expected: file written with frontmatter; `id: 0001`, `title: \"Test ADR\"`, status accepted.

- [ ] **Step 5: Manual auditor sanity check**

```bash
python3 -c "
from bin import auditor
import tempfile, os
from pathlib import Path
d = Path(tempfile.mkdtemp())
p = d / 'data.json'
p.write_text('{\"rows\": [1,2,3]}')
results = auditor.audit_action(
    f'echo {{}} > {p}',
    paths_touched=[str(p)],
    properties=[{'kind': 'length', 'target': str(p), 'target_field': 'rows', 'min': 1, 'max': 10}],
)
for r in results:
    print(f'{r.kind:20} passed={r.passed} {r.message}')
"
```

Expected: 3 results — `path_exists` passed, `json_parses` passed, `length` passed.

- [ ] **Step 6: Commit a CHANGELOG entry**

Create `CHANGELOG.md` if absent, otherwise append:

```markdown
## v0.2.1 — 2026-05-05

**Plan B — Skill integration.**

Added:
- `bin/tier.py` — Persistence-tier classifier (silent/repo/host/network) replacing v1 regex Risk-Gate
- `bin/auditor.py` — Post-action State Auditor with PBT-lite (type/schema/length/range)
- `bin/adr.py` — ADR file writer + graph supersedes-edge updater
- `decisions/` directory for ADR markdown files

Changed:
- `skills/implement/SKILL.md` §3.5: regex Risk-Gate → tier classifier
- `skills/implement/SKILL.md` §5.5: new informational State Auditor pass
- `skills/vision/SKILL.md` §0: codebase fingerprint runs before drafting
- `skills/vision/SKILL.md` §6: draft-to-disk replaces inline spec print
- `skills/vision/SKILL.md` §6.5: ADR generation in confirm flow
- `specs/template.spec.md`: optional `properties:` field documented
- `bin/_scratchpad.py`: `last_audit_kinds`, `last_audit_passed`, `last_audit_failures` in DEFAULT
- `.claude-plugin/plugin.json`: version 1.0.0 → 1.0.1

Tests: ~171 passing (108 Plan A + 28 tier + 14 adr + 18 auditor + 3 scratchpad).

Deferred to Plan C (v0.2.2): supervisor process, Resource locks, multi-track scratchpad.
```

- [ ] **Step 7: Commit + push branch**

```bash
git add CHANGELOG.md
git commit -m "docs: CHANGELOG entry for v0.2.1"
git push -u origin plan-b-skill-integration
```

---

### Task 11: Tag v0.2.1

After the branch merges to master (PR review, CI green, etc. — out of scope for this plan).

- [ ] **Step 1: Switch to master + pull**

```bash
git switch master
git pull --ff-only
```

- [ ] **Step 2: Tag**

```bash
git tag -a v0.2.1 -m "v0.2.1 — Plan B Skill Integration

- bin/tier.py persistence-tier classifier replaces v1 regex Risk-Gate
- bin/auditor.py post-action State Auditor with PBT-lite
- bin/adr.py ADR writer + graph supersedes wiring
- skills/vision: §0 fingerprint, §6 draft-to-disk, §6.5 ADR generation
- skills/implement: §3.5 tier gate, §5.5 audit pass
- decisions/ directory + CHANGELOG.md
- ~171 tests passing
"
git push origin v0.2.1
```

- [ ] **Step 3: GitHub release**

```bash
gh release create v0.2.1 --title "v0.2.1 — Skill Integration (Plan B)" --notes-from-tag
```

---

## Out of scope (deferred to Plan C / v0.2.2)

- Supervisor process for parallel `/implement <track>`
- Resource locks (port, DB, API quota)
- Multi-track scratchpad migration
- Cross-track dependency graph
- Reboot-recovery for Resource locks

## Out of scope (deferred to v3)

- TLA+ formal methods
- Linux capabilities sandboxing
- Cross-machine state sync (Raft consensus)
- Auto-generated PBT properties (user must declare)
- ADR semantic-contradiction detection beyond simple title/body string match

## Self-review

**Spec coverage check:** Plan A had `decisions/` as ADR markdown, Persistence-Tier classifier, draft-to-disk, ADR generation, State Auditor with PBT-lite, codebase fingerprint mandatory in `/vision`. Tier classifier (Task 2), ADR writer (Task 4), Auditor (Task 5), scratchpad wiring (Task 6), implement skill audit pass (Task 7), template properties (Task 8), vision fingerprint+draft+ADR (Task 9). All present. ✓

**Placeholder scan:** No "TBD" or "implement later." Code blocks are complete. Test bodies are concrete. ✓

**Type consistency:** `tier.classify` returns `(str, list[str], str | None)` — used in Task 3 prose and Task 10 sanity. `audit_action(command, *, paths_touched, properties)` — used in Task 7 prose. `adr.write_adr(decisions_dir, *, title, date, body, supersedes=None)` — used in Task 9 prose. ✓

**Risks:**
- Step 9's `decision:` regex extraction is fuzzy (string matching). False positives possible. Mitigation: prose tells the agent to be conservative — when in doubt, do NOT supersede.
- Auditor is informational only. If users expect blocking behavior they'll be confused. Mitigation: prose in §5.5 explicitly calls out informational status.
- Tier classifier path-extraction regex is conservative (false positives ok). Mitigation: tests cover the common cases; edge cases will surface in real use and feed into v0.2.2 hardening.

**Single decision before next plan:** Plan C must commit on supervisor process location (A8 host daemon vs per-project). That decision is irreversible-direction — if we pick wrong, it's a rewrite.
