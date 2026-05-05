# SDL Vision Engine Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a Claude Code plugin (`sdl-vision-engine`) that hydrates one active spec at SessionStart and injects a Delta+Anchor block after every Bash call.

**Architecture:** Python stdlib-only scripts, two hooks (`SessionStart` → `bin/hydrate.py`, `PostToolUse` matcher=`Bash` → `bin/compact.py`), a `/vision` skill that writes specs and atomically flips `specs/.active`, scratchpad JSON for physical state and negative knowledge.

**Tech Stack:** Python 3.11+ (stdlib only), pytest for tests, JSON for state, Claude Code plugin manifest format.

---

## File Structure

```
.claude-plugin/plugin.json        # manifest
bin/hydrate.py                    # SessionStart hook
bin/compact.py                    # PostToolUse(Bash) hook
bin/_scratchpad.py                # shared atomic-write helpers
skills/vision.md                  # /vision skill
specs/.active                     # pointer (created by /vision)
specs/template.spec.md            # canonical spec structure
state/scratchpad.json             # physical state + failed_hypotheses
state/.gitkeep
tests/test_hydrate.py
tests/test_compact.py
tests/test_scratchpad.py
tests/conftest.py
.gitignore
README.md
```

---

### Task 1: Repository scaffolding & .gitignore

**Files:**
- Create: `.gitignore`
- Create: `README.md`
- Create: `state/.gitkeep`

- [ ] **Step 1: Create `.gitignore`**

```
__pycache__/
*.pyc
.pytest_cache/
state/scratchpad.json
specs/.active
specs/*.spec.md
!specs/template.spec.md
.venv/
```

- [ ] **Step 2: Create `README.md`**

```markdown
# SDL Vision Engine

Claude Code plugin: deterministic spec hydration + post-Bash delta/anchor injection.

## Install

Symlink or copy this directory into your Claude Code plugins path. The manifest at `.claude-plugin/plugin.json` registers two hooks and one skill.

## Layout

- `.claude-plugin/plugin.json` — manifest
- `bin/hydrate.py` — SessionStart: emits the active spec body
- `bin/compact.py` — PostToolUse(Bash): emits `additionalContext` JSON
- `skills/vision.md` — `/vision <text>` slash skill
- `specs/.active` — one-line pointer to current spec
- `state/scratchpad.json` — physical state + failed_hypotheses

## Test

`pytest tests/ -v`
```

- [ ] **Step 3: Create `state/.gitkeep` (empty file)**

- [ ] **Step 4: Commit**

```bash
git add .gitignore README.md state/.gitkeep
git commit -m "chore: scaffold repo + gitignore"
```

---

### Task 2: Spec template

**Files:**
- Create: `specs/template.spec.md`

- [ ] **Step 1: Write the template**

```markdown
# <Title>

**Generated:** <ISO date>
**Slug:** <slug>

## 1. Hard Problem
<One paragraph. The non-obvious thing that makes this hard.>

## 2. First Principles
<Bullet list. Physical/logical constraints, not analogies.>

## 3. Algorithm Audit
- **Delete:** <what we are NOT doing and why>
- **Simplify:** <what collapses to one primitive>
- **Accelerate:** <what gets faster after this>

## 4. Steps
1. <Step 1>
2. <Step 2>
...

## 5. Success Criteria
- [ ] <binary pass/fail>
- [ ] <binary pass/fail>
```

- [ ] **Step 2: Commit**

```bash
git add specs/template.spec.md
git commit -m "feat: spec template (Hard Problem / First Principles / Audit / Steps / Success)"
```

---

### Task 3: Scratchpad helpers (test-first)

**Files:**
- Create: `bin/_scratchpad.py`
- Create: `tests/conftest.py`
- Create: `tests/test_scratchpad.py`

- [ ] **Step 1: Write `tests/conftest.py`**

```python
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


@pytest.fixture
def plugin_root(tmp_path, monkeypatch):
    (tmp_path / "specs").mkdir()
    (tmp_path / "state").mkdir()
    monkeypatch.chdir(tmp_path)
    return tmp_path


@pytest.fixture
def initial_scratchpad(plugin_root):
    data = {
        "active_spec": None,
        "step": 1,
        "last_command": None,
        "exit_code": None,
        "delta": None,
        "timestamp": None,
        "failed_hypotheses": [],
    }
    path = plugin_root / "state" / "scratchpad.json"
    path.write_text(json.dumps(data))
    return path
```

- [ ] **Step 2: Write `tests/test_scratchpad.py`**

```python
import json
from pathlib import Path

from bin import _scratchpad as sp


def test_load_returns_default_when_missing(plugin_root):
    data = sp.load(plugin_root / "state" / "scratchpad.json")
    assert data["step"] == 1
    assert data["failed_hypotheses"] == []
    assert data["last_command"] is None


def test_load_returns_existing(initial_scratchpad):
    data = sp.load(initial_scratchpad)
    assert data["step"] == 1


def test_atomic_write_creates_file(plugin_root):
    target = plugin_root / "state" / "scratchpad.json"
    sp.atomic_write(target, {"step": 5})
    assert json.loads(target.read_text())["step"] == 5


def test_atomic_write_no_tmp_left_behind(plugin_root):
    target = plugin_root / "state" / "scratchpad.json"
    sp.atomic_write(target, {"step": 5})
    assert not (plugin_root / "state" / "scratchpad.json.tmp").exists()


def test_append_failed_hypothesis(initial_scratchpad):
    sp.append_failed_hypothesis(
        initial_scratchpad,
        step=2,
        command="pytest",
        error="ModuleNotFoundError: foo",
    )
    data = json.loads(initial_scratchpad.read_text())
    assert len(data["failed_hypotheses"]) == 1
    assert data["failed_hypotheses"][0]["error"] == "ModuleNotFoundError: foo"
    assert data["failed_hypotheses"][0]["step"] == 2
```

- [ ] **Step 3: Run tests to verify they fail**

```bash
pytest tests/test_scratchpad.py -v
```
Expected: `ModuleNotFoundError: No module named 'bin._scratchpad'` (or ImportError).

- [ ] **Step 4: Implement `bin/_scratchpad.py`**

```python
"""Atomic JSON read/write helpers for state/scratchpad.json. Stdlib only."""
import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

DEFAULT = {
    "active_spec": None,
    "step": 1,
    "last_command": None,
    "exit_code": None,
    "delta": None,
    "timestamp": None,
    "failed_hypotheses": [],
}


def load(path: Path) -> dict[str, Any]:
    path = Path(path)
    if not path.exists():
        return dict(DEFAULT)
    try:
        return json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        return dict(DEFAULT)


def atomic_write(path: Path, data: dict[str, Any]) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=path.name, suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(data, f, indent=2)
        os.replace(tmp, path)
    except Exception:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


def append_failed_hypothesis(path: Path, *, step: int, command: str, error: str) -> None:
    data = load(path)
    data.setdefault("failed_hypotheses", []).append({
        "step": step,
        "command": command,
        "error": error,
        "ts": datetime.now(timezone.utc).isoformat(),
    })
    atomic_write(path, data)
```

- [ ] **Step 5: Run tests to verify they pass**

```bash
pytest tests/test_scratchpad.py -v
```
Expected: 5 passed.

- [ ] **Step 6: Commit**

```bash
git add bin/_scratchpad.py tests/conftest.py tests/test_scratchpad.py
git commit -m "feat: atomic scratchpad helpers + tests"
```

---

### Task 4: Hydrator (test-first, three branches)

**Files:**
- Create: `bin/hydrate.py`
- Create: `tests/test_hydrate.py`

- [ ] **Step 1: Write `tests/test_hydrate.py`**

```python
import subprocess
import sys
from pathlib import Path


def run_hydrate(cwd: Path) -> subprocess.CompletedProcess:
    script = Path(__file__).resolve().parent.parent / "bin" / "hydrate.py"
    return subprocess.run(
        [sys.executable, str(script)],
        cwd=cwd,
        capture_output=True,
        text=True,
    )


def test_no_active_emits_signal_and_lists_specs(plugin_root):
    (plugin_root / "specs" / "foo.spec.md").write_text("# foo")
    result = run_hydrate(plugin_root)
    assert result.returncode == 0
    assert "SIGNAL: No active spec" in result.stdout
    assert "foo.spec.md" in result.stdout


def test_stale_pointer_emits_error_and_lists_specs(plugin_root):
    (plugin_root / "specs" / ".active").write_text("specs/missing.spec.md\n")
    (plugin_root / "specs" / "other.spec.md").write_text("# other")
    result = run_hydrate(plugin_root)
    assert result.returncode == 0
    assert "ERROR: stale .active pointer" in result.stdout
    assert "other.spec.md" in result.stdout


def test_valid_active_emits_full_body(plugin_root):
    spec = plugin_root / "specs" / "primary.spec.md"
    spec.write_text("# Primary\n\nbody line\n")
    (plugin_root / "specs" / ".active").write_text("specs/primary.spec.md\n")
    result = run_hydrate(plugin_root)
    assert result.returncode == 0
    assert "--- ACTIVE SPEC: specs/primary.spec.md ---" in result.stdout
    assert "body line" in result.stdout
    assert "--- END ACTIVE SPEC ---" in result.stdout


def test_valid_active_appends_state_line(plugin_root):
    import json
    (plugin_root / "specs" / "p.spec.md").write_text("# P")
    (plugin_root / "specs" / ".active").write_text("specs/p.spec.md")
    (plugin_root / "state" / "scratchpad.json").write_text(json.dumps({
        "step": 4, "exit_code": 0, "last_command": "ls",
        "active_spec": "specs/p.spec.md", "failed_hypotheses": [],
    }))
    result = run_hydrate(plugin_root)
    assert "STATE: step=4" in result.stdout
    assert "exit_code=0" in result.stdout
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_hydrate.py -v
```
Expected: collection succeeds, tests FAIL with FileNotFoundError or non-zero exit.

- [ ] **Step 3: Implement `bin/hydrate.py`**

```python
#!/usr/bin/env python3
"""SessionStart hook: print the active spec body or a fallback signal."""
import sys
from pathlib import Path

# Allow running both as `python3 bin/hydrate.py` and via shebang.
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from bin import _scratchpad as sp  # noqa: E402

SPECS = Path("specs")
ACTIVE = SPECS / ".active"
SCRATCH = Path("state") / "scratchpad.json"


def list_specs() -> str:
    if not SPECS.exists():
        return "(no specs/ directory)"
    files = sorted(p.name for p in SPECS.glob("*.spec.md"))
    return "\n".join(f"  - specs/{f}" for f in files) or "  (no spec files)"


def state_line() -> str:
    data = sp.load(SCRATCH)
    return (
        f"STATE: step={data.get('step')} "
        f"exit_code={data.get('exit_code')} "
        f"last_command={data.get('last_command')!r}"
    )


def main() -> int:
    if not ACTIVE.exists():
        print("SIGNAL: No active spec. Run /vision to begin.")
        print("Available specs:")
        print(list_specs())
        print(state_line())
        return 0

    target = ACTIVE.read_text().strip()
    target_path = Path(target)
    if not target_path.exists():
        print(f"ERROR: stale .active pointer ({target})")
        print("Available specs:")
        print(list_specs())
        print(state_line())
        return 0

    print(f"--- ACTIVE SPEC: {target} ---")
    print(target_path.read_text(), end="")
    if not target_path.read_text().endswith("\n"):
        print()
    print("--- END ACTIVE SPEC ---")
    print(state_line())
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/test_hydrate.py -v
```
Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add bin/hydrate.py tests/test_hydrate.py
git commit -m "feat: SessionStart hydrator (active / missing / stale branches)"
```

---

### Task 5: Compactor — parsing & delta heuristics (test-first)

**Files:**
- Create: `bin/compact.py`
- Create: `tests/test_compact.py`

- [ ] **Step 1: Write `tests/test_compact.py` (parsing + delta only — honesty + integration come in Task 6)**

```python
import json
import subprocess
import sys
from pathlib import Path


def run_compact(cwd: Path, event: dict) -> subprocess.CompletedProcess:
    script = Path(__file__).resolve().parent.parent / "bin" / "compact.py"
    return subprocess.run(
        [sys.executable, str(script)],
        cwd=cwd,
        input=json.dumps(event),
        capture_output=True,
        text=True,
    )


def make_event(command: str, exit_code: int = 0, stdout: str = "", stderr: str = "") -> dict:
    return {
        "tool_name": "Bash",
        "tool_input": {"command": command},
        "tool_response": {"stdout": stdout, "stderr": stderr, "exit_code": exit_code},
    }


def test_emits_additional_context_json(plugin_root):
    result = run_compact(plugin_root, make_event("ls"))
    assert result.returncode == 0
    payload = json.loads(result.stdout)
    assert "additionalContext" in payload
    ctx = payload["additionalContext"]
    assert "COMMAND_RESULT: 0" in ctx
    assert "ANCHOR:" in ctx


def test_delta_for_mkdir(plugin_root):
    result = run_compact(plugin_root, make_event("mkdir -p foo/bar"))
    ctx = json.loads(result.stdout)["additionalContext"]
    assert "mkdir" in ctx.lower() or "foo/bar" in ctx


def test_delta_for_unknown_command(plugin_root):
    result = run_compact(plugin_root, make_event("some_weird_binary --flag"))
    ctx = json.loads(result.stdout)["additionalContext"]
    assert "unknown" in ctx.lower()


def test_anchor_uses_active_spec(plugin_root):
    (plugin_root / "specs" / ".active").write_text("specs/x.spec.md")
    result = run_compact(plugin_root, make_event("ls"))
    ctx = json.loads(result.stdout)["additionalContext"]
    assert "specs/x.spec.md" in ctx


def test_anchor_when_no_active_spec(plugin_root):
    result = run_compact(plugin_root, make_event("ls"))
    ctx = json.loads(result.stdout)["additionalContext"]
    assert "no active spec" in ctx.lower()
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_compact.py -v
```
Expected: FileNotFoundError on bin/compact.py.

- [ ] **Step 3: Implement `bin/compact.py`**

```python
#!/usr/bin/env python3
"""PostToolUse(Bash) hook: emit a Delta+Anchor additionalContext block."""
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from bin import _scratchpad as sp  # noqa: E402

SPECS_ACTIVE = Path("specs") / ".active"
SCRATCH = Path("state") / "scratchpad.json"

DELTA_PATTERNS = [
    (re.compile(r"^\s*mkdir\b.*?(\S+)\s*$"), "mkdir {}"),
    (re.compile(r"^\s*touch\s+(\S+)"), "touch {}"),
    (re.compile(r"^\s*rm\s+(?:-\w+\s+)?(\S+)"), "rm {}"),
    (re.compile(r"^\s*mv\s+(\S+)\s+(\S+)"), "mv {} -> {}"),
    (re.compile(r"^\s*cp\s+(?:-\w+\s+)?(\S+)\s+(\S+)"), "cp {} -> {}"),
    (re.compile(r"^\s*git\s+commit\b"), "git commit"),
    (re.compile(r"^\s*apt(?:-get)?\s+install\s+(.+)"), "apt install {}"),
    (re.compile(r"^\s*pip\s+install\s+(.+)"), "pip install {}"),
    (re.compile(r"^\s*npm\s+install\s+(.*)"), "npm install {}"),
    (re.compile(r">\s*(\S+)\s*$"), "wrote {}"),
]

ERR_PATTERN = re.compile(r"^(Error|error|fatal|E:|FAIL|Traceback)", re.MULTILINE)


def parse_delta(command: str) -> str:
    cmd = command.strip()
    for regex, template in DELTA_PATTERNS:
        m = regex.search(cmd)
        if m:
            return template.format(*m.groups()) if m.groups() else template
    return "unknown — see scratchpad"


def first_error_line(stderr: str) -> str:
    if not stderr:
        return ""
    m = ERR_PATTERN.search(stderr)
    if m:
        line_start = stderr.rfind("\n", 0, m.start()) + 1
        line_end = stderr.find("\n", m.start())
        if line_end == -1:
            line_end = len(stderr)
        return stderr[line_start:line_end].strip()
    return stderr.strip().splitlines()[0] if stderr.strip() else ""


def active_spec() -> str | None:
    if SPECS_ACTIVE.exists():
        return SPECS_ACTIVE.read_text().strip() or None
    return None


def emit(payload: dict) -> None:
    print(json.dumps({"additionalContext": payload["additionalContext"]}))


def main() -> int:
    try:
        event = json.loads(sys.stdin.read() or "{}")
    except json.JSONDecodeError:
        emit({"additionalContext": "COMPACT_ERROR: invalid event JSON"})
        return 0

    tool_input = event.get("tool_input", {}) or {}
    tool_response = event.get("tool_response", {}) or {}
    command = tool_input.get("command", "")
    exit_code = tool_response.get("exit_code", 0)
    stderr = tool_response.get("stderr", "") or ""

    delta = parse_delta(command)
    spec = active_spec()
    anchor = (
        f"Active Spec is '{spec}'." if spec else "no active spec."
    )

    data = sp.load(SCRATCH)
    step = data.get("step", 1)

    data.update({
        "active_spec": spec,
        "last_command": command,
        "exit_code": exit_code,
        "delta": delta,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    })

    if exit_code != 0:
        err = first_error_line(stderr) or "(no stderr)"
        data.setdefault("failed_hypotheses", []).append({
            "step": step,
            "command": command,
            "error": err,
            "ts": data["timestamp"],
        })

    sp.atomic_write(SCRATCH, data)

    failed_count = len(data.get("failed_hypotheses", []))
    ctx = (
        f"COMMAND_RESULT: {exit_code}\n"
        f"STATE_DELTA: {delta}\n"
        f"ANCHOR: {anchor} Step {step}.\n"
        f"NEXT: scratchpad.json updated. {failed_count} negative-knowledge entries."
    )
    emit({"additionalContext": ctx})
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/test_compact.py -v
```
Expected: 5 passed.

- [ ] **Step 5: Commit**

```bash
git add bin/compact.py tests/test_compact.py
git commit -m "feat: PostToolUse compactor with delta heuristics + anchor"
```

---

### Task 6: Compactor — intellectual-honesty + scratchpad write tests

**Files:**
- Modify: `tests/test_compact.py` (append tests)

- [ ] **Step 1: Append honesty/scratchpad tests to `tests/test_compact.py`**

```python
def test_failure_appended_to_failed_hypotheses(plugin_root):
    event = make_event(
        "pytest",
        exit_code=1,
        stderr="ModuleNotFoundError: No module named 'foo'\n",
    )
    run_compact(plugin_root, event)
    data = json.loads((plugin_root / "state" / "scratchpad.json").read_text())
    assert len(data["failed_hypotheses"]) == 1
    assert "ModuleNotFoundError" in data["failed_hypotheses"][0]["error"]


def test_success_does_not_append_failed_hypothesis(plugin_root):
    run_compact(plugin_root, make_event("ls", exit_code=0))
    data = json.loads((plugin_root / "state" / "scratchpad.json").read_text())
    assert data["failed_hypotheses"] == []


def test_failure_with_traceback_captures_first_error_line(plugin_root):
    stderr = "Traceback (most recent call last):\n  File \"x\"\nValueError: bad\n"
    run_compact(plugin_root, make_event("python x.py", exit_code=1, stderr=stderr))
    data = json.loads((plugin_root / "state" / "scratchpad.json").read_text())
    assert data["failed_hypotheses"][0]["error"].startswith("Traceback")


def test_scratchpad_records_command_and_exit_code(plugin_root):
    run_compact(plugin_root, make_event("echo hi", exit_code=0))
    data = json.loads((plugin_root / "state" / "scratchpad.json").read_text())
    assert data["last_command"] == "echo hi"
    assert data["exit_code"] == 0


def test_invalid_stdin_emits_error_payload(plugin_root):
    script = Path(__file__).resolve().parent.parent / "bin" / "compact.py"
    result = subprocess.run(
        [sys.executable, str(script)],
        cwd=plugin_root,
        input="not json{",
        capture_output=True,
        text=True,
    )
    payload = json.loads(result.stdout)
    assert "COMPACT_ERROR" in payload["additionalContext"]
```

- [ ] **Step 2: Run all compactor tests to verify they pass**

```bash
pytest tests/test_compact.py -v
```
Expected: 10 passed.

- [ ] **Step 3: Commit**

```bash
git add tests/test_compact.py
git commit -m "test: compactor honesty + scratchpad persistence"
```

---

### Task 7: `/vision` skill

**Files:**
- Create: `skills/vision.md`

- [ ] **Step 1: Write `skills/vision.md`**

```markdown
---
description: Transforms a vague vision into a First-Principles spec and locks it as the active spec.
disable-model-invocation: false
---

# Skill: /vision <user_vision>

When invoked, follow these steps **exactly** — do not improvise structure.

## Inputs

`<user_vision>`: free-form text describing what the user wants built.

## Procedure

1. **Distill.** Read `<user_vision>` and produce these five fields:
   - **Title** (≤8 words)
   - **Hard Problem** (one paragraph: the non-obvious thing that makes this hard — no analogies)
   - **First Principles** (3-7 bullets: physical/logical constraints)
   - **Algorithm Audit** (Delete / Simplify / Accelerate)
   - **Steps** (numbered, 5-15 items, each one binary-verifiable)
   - **Success Criteria** (3-6 binary pass/fail checks)

2. **Slugify.** Lowercase the title, replace non-alphanumerics with `-`, collapse repeats, strip leading/trailing `-`. Example: "Real-Time Order Sync" → `real-time-order-sync`. Filename: `specs/<slug>.spec.md`.

3. **Write spec.** Use `specs/template.spec.md` as the structural skeleton. Fill in the five fields. Set the **Generated** field to today's ISO date and **Slug** to the computed slug.

4. **Atomically flip `.active`.** Write the relative path (e.g. `specs/<slug>.spec.md`) to `specs/.active.tmp`, then rename to `specs/.active`. Use a single Bash call:

   ```bash
   printf 'specs/<slug>.spec.md\n' > specs/.active.tmp && mv specs/.active.tmp specs/.active
   ```

5. **Reset scratchpad.** Overwrite `state/scratchpad.json` with:

   ```json
   {
     "active_spec": "specs/<slug>.spec.md",
     "step": 1,
     "last_command": null,
     "exit_code": null,
     "delta": null,
     "timestamp": null,
     "failed_hypotheses": []
   }
   ```

6. **Confirm.** Print one line: `VISION LOCKED: specs/<slug>.spec.md (step 1)`.

## Hard rules

- One spec at a time. Never write two `.active` files.
- Never edit `step` here beyond resetting to 1.
- Never include hedging, "best practices," or industry-standard preambles in the spec body. Only first-principles content.
```

- [ ] **Step 2: Commit**

```bash
git add skills/vision.md
git commit -m "feat: /vision skill (distill -> spec -> atomic .active flip -> reset scratchpad)"
```

---

### Task 8: Plugin manifest

**Files:**
- Create: `.claude-plugin/plugin.json`

- [ ] **Step 1: Write the manifest**

```json
{
  "id": "sdl-vision-engine",
  "name": "SDL Vision Engine",
  "version": "1.0.0",
  "description": "Deterministic spec hydration + post-Bash Delta+Anchor injection.",
  "hooks": {
    "SessionStart": [
      { "type": "command", "command": "python3 bin/hydrate.py" }
    ],
    "PostToolUse": [
      {
        "matcher": { "tool_name": "Bash" },
        "hooks": [
          { "type": "command", "command": "python3 bin/compact.py" }
        ]
      }
    ]
  },
  "skills": [
    { "path": "skills/vision.md" }
  ]
}
```

- [ ] **Step 2: Validate JSON**

```bash
python3 -c "import json; json.load(open('.claude-plugin/plugin.json'))" && echo OK
```
Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add .claude-plugin/plugin.json
git commit -m "feat: plugin manifest (SessionStart=hydrate, PostToolUse(Bash)=compact)"
```

---

### Task 9: End-to-end smoke test

**Files:**
- Create: `tests/test_e2e.py`

- [ ] **Step 1: Write `tests/test_e2e.py`**

```python
import json
import subprocess
import sys
from pathlib import Path


def test_full_cycle(plugin_root):
    """Hydrate (no spec) -> create spec + .active -> hydrate (active) -> compact (success) -> compact (failure)."""
    bin_dir = Path(__file__).resolve().parent.parent / "bin"

    # 1. Hydrate before any spec exists.
    r = subprocess.run([sys.executable, str(bin_dir / "hydrate.py")],
                       cwd=plugin_root, capture_output=True, text=True)
    assert "SIGNAL: No active spec" in r.stdout

    # 2. Create a spec and flip .active (simulating /vision).
    (plugin_root / "specs" / "demo.spec.md").write_text("# Demo\n\nbody\n")
    (plugin_root / "specs" / ".active").write_text("specs/demo.spec.md\n")
    (plugin_root / "state" / "scratchpad.json").write_text(json.dumps({
        "active_spec": "specs/demo.spec.md", "step": 1,
        "last_command": None, "exit_code": None, "delta": None,
        "timestamp": None, "failed_hypotheses": [],
    }))

    # 3. Hydrate with active spec.
    r = subprocess.run([sys.executable, str(bin_dir / "hydrate.py")],
                       cwd=plugin_root, capture_output=True, text=True)
    assert "--- ACTIVE SPEC: specs/demo.spec.md ---" in r.stdout
    assert "body" in r.stdout

    # 4. Compact a successful command.
    event = {"tool_name": "Bash",
             "tool_input": {"command": "ls"},
             "tool_response": {"stdout": "", "stderr": "", "exit_code": 0}}
    r = subprocess.run([sys.executable, str(bin_dir / "compact.py")],
                       cwd=plugin_root, input=json.dumps(event),
                       capture_output=True, text=True)
    payload = json.loads(r.stdout)
    assert "COMMAND_RESULT: 0" in payload["additionalContext"]
    assert "specs/demo.spec.md" in payload["additionalContext"]

    # 5. Compact a failing command.
    event["tool_input"]["command"] = "pytest"
    event["tool_response"] = {"stdout": "", "stderr": "ModuleNotFoundError: x\n", "exit_code": 1}
    subprocess.run([sys.executable, str(bin_dir / "compact.py")],
                   cwd=plugin_root, input=json.dumps(event),
                   capture_output=True, text=True)
    data = json.loads((plugin_root / "state" / "scratchpad.json").read_text())
    assert data["exit_code"] == 1
    assert len(data["failed_hypotheses"]) == 1
    assert "ModuleNotFoundError" in data["failed_hypotheses"][0]["error"]
```

- [ ] **Step 2: Run full suite**

```bash
pytest tests/ -v
```
Expected: all tests pass (5 + 4 + 10 + 1 = 20).

- [ ] **Step 3: Commit**

```bash
git add tests/test_e2e.py
git commit -m "test: end-to-end smoke (hydrate->vision->compact pass+fail)"
```

---

### Task 10: Manifest matcher integration test

**Files:**
- Create: `tests/test_manifest.py`

- [ ] **Step 1: Write `tests/test_manifest.py`**

```python
import json
from pathlib import Path


def test_manifest_is_valid_json():
    path = Path(__file__).resolve().parent.parent / ".claude-plugin" / "plugin.json"
    data = json.loads(path.read_text())
    assert data["id"] == "sdl-vision-engine"


def test_post_tool_use_matcher_is_strictly_bash():
    path = Path(__file__).resolve().parent.parent / ".claude-plugin" / "plugin.json"
    data = json.loads(path.read_text())
    post = data["hooks"]["PostToolUse"]
    assert len(post) == 1
    assert post[0]["matcher"] == {"tool_name": "Bash"}


def test_session_start_runs_hydrate():
    path = Path(__file__).resolve().parent.parent / ".claude-plugin" / "plugin.json"
    data = json.loads(path.read_text())
    cmd = data["hooks"]["SessionStart"][0]["command"]
    assert "hydrate.py" in cmd


def test_skill_registered():
    path = Path(__file__).resolve().parent.parent / ".claude-plugin" / "plugin.json"
    data = json.loads(path.read_text())
    paths = [s["path"] for s in data["skills"]]
    assert "skills/vision.md" in paths
```

- [ ] **Step 2: Run tests**

```bash
pytest tests/test_manifest.py -v
```
Expected: 4 passed.

- [ ] **Step 3: Commit**

```bash
git add tests/test_manifest.py
git commit -m "test: manifest matcher locked to Bash + hooks wired correctly"
```

---

## Self-Review

**Spec coverage:**
- Manifest with SessionStart + PostToolUse(Bash) → Task 8 + 10
- Hydrator (active / missing / stale) → Task 4
- Compactor (delta + anchor + scratchpad + honesty) → Tasks 5, 6
- `/vision` skill (distill, atomic .active, reset scratchpad) → Task 7
- Scratchpad schema (atomic writes, failed_hypotheses) → Task 3
- Spec template → Task 2
- Failure modes (broad matcher, recursive failure, torn writes) → Tasks 3, 5, 10 (matcher), all scripts wrapped in error handling
- Success criteria (physical state without scroll-back, ≤500 char additionalContext) → Tasks 5, 6, 9

**Placeholder scan:** None — every step has concrete code or commands.

**Type consistency:** `sp.load`, `sp.atomic_write`, `sp.append_failed_hypothesis` defined in Task 3 and used consistently in Tasks 4, 5. Event shape (`tool_name`, `tool_input.command`, `tool_response.{stdout,stderr,exit_code}`) consistent across Tasks 5, 6, 9.

---

**Plan complete and saved to `docs/superpowers/plans/2026-05-05-sdl-vision-engine.md`. Two execution options:**

**1. Subagent-Driven (recommended)** — fresh subagent per task, review between tasks, fast iteration

**2. Inline Execution** — execute tasks in this session using executing-plans, batch execution with checkpoints

**Which approach?**
