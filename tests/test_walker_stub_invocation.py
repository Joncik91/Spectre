"""Tests for walker stub-invocation-detected concern (§50 Contract 2).

Pragma guard: assertion-style names only. One assertion per test.
Tests asserting absence/emptiness use _no_fire/_returns_empty/_is_none naming.

Covers:
- concern fires when step N requires an artifact produced by a stub step M
- concern does NOT fire when M writes a real body
- concern does NOT fire when an intermediate step heals the stub
- concern fires when why: text contains stub keywords
- concern kind, id, receiver shape
- idempotency: no duplicate on re-seed
- dedup when concern already in asked / pending / answered
"""
import pathlib

import pytest

from bin import walker


# ── Helpers ────────────────────────────────────────────────────────────────────


def _state() -> walker.WalkState:
    return walker.WalkState(
        spec_intent="test",
        spec_draft_path=pathlib.Path("/tmp/test.spec.md.draft"),
    )


# _step + _STUB_ACTION shared with tests/test_spec_ast_stub_producer.py
from tests.fixtures.stub_helpers import step as _step, STUB_ACTION as _STUB_ACTION

_REAL_ACTION = (
    "cat > /app/vidence/bootstrap.py <<'EOF'\n"
    "import os\n"
    "def bootstrap():\n"
    "    os.makedirs('.vidence', exist_ok=True)\n"
    "    with open('.vidence/state.json', 'w') as f:\n"
    "        f.write('{}')\n"
    "    return True\n"
    "EOF"
)

_HEAL_ACTION = (
    "cat > /app/vidence/bootstrap.py <<'EOF'\n"
    "import os\n"
    "def bootstrap():\n"
    "    os.makedirs('.vidence', exist_ok=True)\n"
    "    return True\n"
    "EOF"
)


def _stub_concerns(steps: list[dict]) -> list[walker.Concern]:
    return walker.generate_stub_invocation_concerns(_state(), steps)


def _one_concern(steps: list[dict]) -> walker.Concern:
    cs = _stub_concerns(steps)
    assert len(cs) == 1, f"expected 1 concern, got {cs!r}"
    return cs[0]


# ── Concern shape ──────────────────────────────────────────────────────────────


def test_concern_kind_is_stub_invocation_detected():
    steps = [
        _step(1, _STUB_ACTION, produces=["module:vidence.bootstrap"]),
        _step(3, "python3 -m vidence.bootstrap --root .", requires=["module:vidence.bootstrap"]),
    ]
    c = _one_concern(steps)
    assert c.kind == "stub-invocation-detected"


def test_concern_receiver_is_implement():
    steps = [
        _step(1, _STUB_ACTION, produces=["module:vidence.bootstrap"]),
        _step(3, "python3 -m vidence.bootstrap --root .", requires=["module:vidence.bootstrap"]),
    ]
    c = _one_concern(steps)
    assert c.receivers == ["implement"]


def test_concern_id_contains_step_number():
    steps = [
        _step(1, _STUB_ACTION, produces=["module:vidence.bootstrap"]),
        _step(3, "python3 -m vidence.bootstrap --root .", requires=["module:vidence.bootstrap"]),
    ]
    c = _one_concern(steps)
    assert "3" in c.id


def test_concern_summary_mentions_stub_reason():
    steps = [
        _step(1, _STUB_ACTION, produces=["module:vidence.bootstrap"]),
        _step(3, "python3 -m vidence.bootstrap --root .", requires=["module:vidence.bootstrap"]),
    ]
    c = _one_concern(steps)
    assert "stub" in c.summary.lower()


def test_concern_summary_mentions_both_step_numbers():
    steps = [
        _step(1, _STUB_ACTION, produces=["module:vidence.bootstrap"]),
        _step(3, "python3 -m vidence.bootstrap --root .", requires=["module:vidence.bootstrap"]),
    ]
    c = _one_concern(steps)
    # Step 1 (producer) and Step 3 (invoker) both mentioned
    assert "1" in c.summary
    assert "3" in c.summary


def test_concern_depends_on_is_empty():
    steps = [
        _step(1, _STUB_ACTION, produces=["module:vidence.bootstrap"]),
        _step(3, "python3 -m vidence.bootstrap --root .", requires=["module:vidence.bootstrap"]),
    ]
    c = _one_concern(steps)
    assert c.depends_on == []


# ── Core fire conditions ───────────────────────────────────────────────────────


def test_fires_for_stub_producer_via_heredoc_stub_body():
    """#49 shape: heredoc body with NotImplementedError stub marker."""
    steps = [
        _step(1, _STUB_ACTION, produces=["module:vidence.bootstrap"]),
        _step(3, "python3 -m vidence.bootstrap --root .", requires=["module:vidence.bootstrap"]),
    ]
    assert len(_stub_concerns(steps)) == 1


def test_fires_for_pass_only_body():
    action = (
        "cat > /app/stub.py <<'EOF'\n"
        "def run():\n"
        "    pass\n"
        "EOF"
    )
    steps = [
        _step(1, action, produces=["file:/app/stub.py"]),
        _step(2, "python3 /app/stub.py", requires=["file:/app/stub.py"]),
    ]
    assert len(_stub_concerns(steps)) == 1


def test_fires_for_short_body_with_todo_keyword():
    action = (
        "cat > /app/init.py <<'EOF'\n"
        "# TODO: implement\n"
        "def init():\n"
        "    pass\n"
        "EOF"
    )
    steps = [
        _step(1, action, produces=["file:/app/init.py"]),
        _step(2, "python3 /app/init.py", requires=["file:/app/init.py"]),
    ]
    assert len(_stub_concerns(steps)) == 1


def test_fires_for_why_text_stub_keyword():
    """Stub detected via why: field regardless of action body."""
    steps = [
        _step(
            1,
            "cat > /app/real.py <<'EOF'\nx = 1\nEOF",
            why="This is a stub; replaced by step 3",
            produces=["file:/app/real.py"],
        ),
        _step(2, "python3 /app/real.py", requires=["file:/app/real.py"]),
    ]
    assert len(_stub_concerns(steps)) == 1


def test_fires_for_why_text_placeholder_keyword():
    steps = [
        _step(
            1,
            "cat > /app/x.py <<'EOF'\nx = 1\nEOF",
            why="placeholder until real implementation lands",
            produces=["file:/app/x.py"],
        ),
        _step(2, "python3 /app/x.py", requires=["file:/app/x.py"]),
    ]
    assert len(_stub_concerns(steps)) == 1


def test_fires_for_console_log_stub_js():
    action = (
        "cat > /app/server.js <<'EOF'\n"
        'function start() { console.log("stub"); }\n'
        "EOF"
    )
    steps = [
        _step(1, action, produces=["file:/app/server.js"]),
        _step(2, "node /app/server.js", requires=["file:/app/server.js"]),
    ]
    assert len(_stub_concerns(steps)) == 1


# ── No-fire conditions ────────────────────────────────────────────────────────


def test_no_fire_when_producer_writes_real_body():
    steps = [
        _step(1, _REAL_ACTION, produces=["module:vidence.bootstrap"]),
        _step(3, "python3 -m vidence.bootstrap --root .", requires=["module:vidence.bootstrap"]),
    ]
    assert _stub_concerns(steps) == []


def test_no_fire_when_no_requires():
    steps = [
        _step(1, _STUB_ACTION, produces=["module:vidence.bootstrap"]),
        _step(3, "python3 -m vidence.bootstrap --root ."),
    ]
    assert _stub_concerns(steps) == []


def test_no_fire_when_producer_not_found():
    # Step 3 requires something nothing produces
    steps = [
        _step(1, _STUB_ACTION, produces=["module:vidence.other"]),
        _step(3, "python3 -m vidence.bootstrap --root .", requires=["module:vidence.bootstrap"]),
    ]
    assert _stub_concerns(steps) == []


def test_no_fire_when_healing_step_present():
    """Intermediate step 2 replaces stub body before step 3 invokes it.

    Uses file: contract so the path suffix comparison matches exactly
    (module: contracts produce 'vidence/bootstrap' without .py extension,
    which doesn't suffix-match the heredoc's '/app/vidence/bootstrap.py').
    """
    stub = "cat > /app/stub.py <<'EOF'\ndef run():\n    raise NotImplementedError\nEOF"
    heal = (
        "cat > /app/stub.py <<'EOF'\n"
        "import os\n"
        "def run():\n"
        "    os.makedirs('/tmp/out', exist_ok=True)\n"
        "    return True\n"
        "EOF"
    )
    steps = [
        _step(1, stub, produces=["file:/app/stub.py"]),
        _step(2, heal),
        _step(3, "python3 /app/stub.py", requires=["file:/app/stub.py"]),
    ]
    assert _stub_concerns(steps) == []


def test_no_fire_for_empty_steps():
    assert _stub_concerns([]) == []


def test_no_fire_when_single_step_only():
    steps = [_step(1, _STUB_ACTION, produces=["module:vidence.bootstrap"])]
    assert _stub_concerns(steps) == []


# ── Multiple concerns ─────────────────────────────────────────────────────────


def test_fires_once_per_requiring_step():
    """Two requires entries on step 3 → two concerns if both producers are stubs."""
    stub_a = "cat > /app/a.py <<'EOF'\nraise NotImplementedError\nEOF"
    stub_b = "cat > /app/b.py <<'EOF'\nraise NotImplementedError\nEOF"
    steps = [
        _step(1, stub_a, produces=["file:/app/a.py"]),
        _step(2, stub_b, produces=["file:/app/b.py"]),
        _step(3, "python3 /app/a.py && python3 /app/b.py",
              requires=["file:/app/a.py", "file:/app/b.py"]),
    ]
    cs = _stub_concerns(steps)
    assert len(cs) == 2


# ── Idempotency ───────────────────────────────────────────────────────────────


def test_no_duplicate_when_concern_already_in_asked():
    state = _state()
    steps = [
        _step(1, _STUB_ACTION, produces=["module:vidence.bootstrap"]),
        _step(3, "python3 -m vidence.bootstrap --root .", requires=["module:vidence.bootstrap"]),
    ]
    # Pre-seed one concern with the expected id prefix
    first = walker.generate_stub_invocation_concerns(state, steps)
    assert len(first) == 1
    state.asked.append(first[0])
    second = walker.generate_stub_invocation_concerns(state, steps)
    assert second == []


def test_no_duplicate_when_concern_already_in_pending():
    state = _state()
    steps = [
        _step(1, _STUB_ACTION, produces=["module:vidence.bootstrap"]),
        _step(3, "python3 -m vidence.bootstrap --root .", requires=["module:vidence.bootstrap"]),
    ]
    first = walker.generate_stub_invocation_concerns(state, steps)
    state.pending.extend(first)
    second = walker.generate_stub_invocation_concerns(state, steps)
    assert second == []


def test_no_duplicate_when_concern_already_answered():
    state = _state()
    steps = [
        _step(1, _STUB_ACTION, produces=["module:vidence.bootstrap"]),
        _step(3, "python3 -m vidence.bootstrap --root .", requires=["module:vidence.bootstrap"]),
    ]
    first = walker.generate_stub_invocation_concerns(state, steps)
    assert len(first) == 1
    state.answered[first[0].id] = "will fix step 1"
    second = walker.generate_stub_invocation_concerns(state, steps)
    assert second == []


# ── Vidence v2 end-to-end repro shape ─────────────────────────────────────────


def test_vidence_v2_shape_fires_stub_concern():
    """#49 repro: Step 1 writes stub bootstrap.py (absolute path); Step 3 invokes it.

    Note: the heredoc regex requires an absolute path target — relative paths
    like 'vidence/bootstrap.py' are not captured by _walker_extract_write_bodies.
    The end-to-end check uses absolute paths as they appear in real specs.
    """
    steps = [
        _step(
            1,
            "cat > /app/vidence/bootstrap.py <<'EOF'\n"
            "def bootstrap():\n"
            "    raise NotImplementedError\n"
            "EOF",
            produces=["file:/app/vidence/bootstrap.py"],
        ),
        _step(
            3,
            "python3 /app/vidence/bootstrap.py --root .",
            requires=["file:/app/vidence/bootstrap.py"],
        ),
    ]
    cs = walker.generate_stub_invocation_concerns(_state(), steps)
    assert len(cs) == 1


def test_vidence_v2_corrected_shape_no_fire():
    """Step 2 inserts real implementation — no concern for step 3."""
    heal = (
        "cat > /app/vidence/bootstrap.py <<'EOF'\n"
        "import os\n"
        "def bootstrap(root):\n"
        "    os.makedirs(os.path.join(root, '.vidence'), exist_ok=True)\n"
        "    return True\n"
        "EOF"
    )
    steps = [
        _step(
            1,
            "cat > /app/vidence/bootstrap.py <<'EOF'\n"
            "def bootstrap():\n"
            "    raise NotImplementedError\n"
            "EOF",
            produces=["file:/app/vidence/bootstrap.py"],
        ),
        _step(2, heal),
        _step(
            3,
            "python3 /app/vidence/bootstrap.py --root .",
            requires=["file:/app/vidence/bootstrap.py"],
        ),
    ]
    cs = walker.generate_stub_invocation_concerns(_state(), steps)
    assert cs == []
