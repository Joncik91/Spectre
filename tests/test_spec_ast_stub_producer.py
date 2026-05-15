"""Tests for Tier 1 stub-producer-invoked check (§50 Contract 2).

Pragma guard: assertion-style names only. One assertion per test.
Tests asserting absence/emptiness use _no_fire/_returns_empty/_passes naming.

The internal _check_stub_producer_invoked is called directly for shape
assertions so Pragma can verify real return-value coverage. classify() is
used for end-to-end repro tests.

Covers:
- block finding fires when producer step has stub body (heredoc with markers)
- block finding fires when why: text contains stub keywords
- no finding when producer writes a real body
- no finding when a later step heals the stub before the invoking step
- correct kind, severity, location, message shape from direct call
- Vidence v2 end-to-end repro (#49 shape)
"""
import os
import pathlib
import tempfile

from bin import spec_ast

# §1-§8 skeleton lives in tests/fixtures/spec_template.py.
from tests.fixtures.spec_template import write_spec_file as _write_spec_helper


def _write_spec(steps_yaml: str) -> pathlib.Path:
    return _write_spec_helper(
        steps_yaml,
        title="Stub Producer Test Spec",
        slug="stub-producer-test",
        problem="Testing stub-producer-invoked Tier 1 detection.",
        first_principles="- A step invoking an artifact produced by a stub step must fail at lock time.",
        success_criteria="- [ ] Check passes.",
        mutates="/app/",
    )


SPI = "stub-producer-invoked"


# ── Step helpers for direct _check_stub_producer_invoked calls ────────────────
# Shared with tests/test_walker_stub_invocation.py via tests/fixtures/stub_helpers.

from tests.fixtures.stub_helpers import step as _step, STUB_ACTION as _STUB_ACTION

_REAL_ACTION = (
    "cat > /app/vidence/bootstrap.py <<'EOF'\n"
    "import os\n"
    "def bootstrap(root):\n"
    "    os.makedirs(os.path.join(root, '.vidence'), exist_ok=True)\n"
    "    with open(os.path.join(root, '.vidence', 'state.json'), 'w') as f:\n"
    "        f.write('{}')\n"
    "    return True\n"
    "EOF"
)

_HEAL_ACTION = (
    "cat > /app/vidence/bootstrap.py <<'EOF'\n"
    "import os\n"
    "def bootstrap(root):\n"
    "    os.makedirs(os.path.join(root, '.vidence'), exist_ok=True)\n"
    "    return True\n"
    "EOF"
)


def _spi_findings(steps: list[dict]):
    return [f for f in spec_ast._check_stub_producer_invoked(steps) if f.kind == SPI]


# ── Direct call: shape assertions on a real Finding object ────────────────────


def test_direct_finding_kind_is_stub_producer_invoked():
    steps = [
        _step(1, _STUB_ACTION, produces=["file:/app/vidence/bootstrap.py"]),
        _step(3, "python3 /app/vidence/bootstrap.py",
              requires=["file:/app/vidence/bootstrap.py"]),
    ]
    fs = spec_ast._check_stub_producer_invoked(steps)
    assert fs[0].kind == "stub-producer-invoked"


def test_direct_finding_severity_is_block():
    steps = [
        _step(1, _STUB_ACTION, produces=["file:/app/vidence/bootstrap.py"]),
        _step(3, "python3 /app/vidence/bootstrap.py",
              requires=["file:/app/vidence/bootstrap.py"]),
    ]
    fs = spec_ast._check_stub_producer_invoked(steps)
    assert fs[0].severity == "block"


def test_direct_finding_tier_is_1():
    steps = [
        _step(1, _STUB_ACTION, produces=["file:/app/vidence/bootstrap.py"]),
        _step(3, "python3 /app/vidence/bootstrap.py",
              requires=["file:/app/vidence/bootstrap.py"]),
    ]
    fs = spec_ast._check_stub_producer_invoked(steps)
    assert fs[0].tier == 1


def test_direct_finding_location_step_is_invoking_step():
    steps = [
        _step(1, _STUB_ACTION, produces=["file:/app/vidence/bootstrap.py"]),
        _step(3, "python3 /app/vidence/bootstrap.py",
              requires=["file:/app/vidence/bootstrap.py"]),
    ]
    fs = spec_ast._check_stub_producer_invoked(steps)
    assert fs[0].location.step == 3


def test_direct_finding_location_ref_is_requires():
    steps = [
        _step(1, _STUB_ACTION, produces=["file:/app/vidence/bootstrap.py"]),
        _step(3, "python3 /app/vidence/bootstrap.py",
              requires=["file:/app/vidence/bootstrap.py"]),
    ]
    fs = spec_ast._check_stub_producer_invoked(steps)
    assert fs[0].location.ref == "requires"


def test_direct_finding_message_mentions_stub_reason():
    steps = [
        _step(1, _STUB_ACTION, produces=["file:/app/vidence/bootstrap.py"]),
        _step(3, "python3 /app/vidence/bootstrap.py",
              requires=["file:/app/vidence/bootstrap.py"]),
    ]
    fs = spec_ast._check_stub_producer_invoked(steps)
    assert "stub" in fs[0].message.lower()


def test_direct_finding_suggested_fix_is_non_empty():
    steps = [
        _step(1, _STUB_ACTION, produces=["file:/app/vidence/bootstrap.py"]),
        _step(3, "python3 /app/vidence/bootstrap.py",
              requires=["file:/app/vidence/bootstrap.py"]),
    ]
    fs = spec_ast._check_stub_producer_invoked(steps)
    assert fs[0].suggested_fix and len(fs[0].suggested_fix) > 0


# ── No-fire: real body (direct call) ─────────────────────────────────────────


def test_direct_no_finding_when_real_body():
    steps = [
        _step(1, _REAL_ACTION, produces=["file:/app/vidence/bootstrap.py"]),
        _step(3, "python3 /app/vidence/bootstrap.py",
              requires=["file:/app/vidence/bootstrap.py"]),
    ]
    result = spec_ast._check_stub_producer_invoked(steps)
    assert result == []


def test_direct_no_finding_when_healing_step_present():
    steps = [
        _step(1, _STUB_ACTION, produces=["file:/app/vidence/bootstrap.py"]),
        _step(2, _HEAL_ACTION),
        _step(3, "python3 /app/vidence/bootstrap.py",
              requires=["file:/app/vidence/bootstrap.py"]),
    ]
    result = spec_ast._check_stub_producer_invoked(steps)
    assert result == []


def test_direct_no_finding_when_no_requires():
    steps = [
        _step(1, _STUB_ACTION, produces=["file:/app/vidence/bootstrap.py"]),
        _step(3, "python3 /app/vidence/bootstrap.py"),
    ]
    result = spec_ast._check_stub_producer_invoked(steps)
    assert result == []


# ── Why: text stub keyword triggers finding ───────────────────────────────────


def test_direct_why_stub_keyword_emits_finding():
    steps = [
        _step(
            1,
            "cat > /app/init.py <<'EOF'\nx=1\ny=2\nz=3\nprint(x,y,z)\nEOF",
            why="This is a stub; replaced by step 2.",
            produces=["file:/app/init.py"],
        ),
        _step(3, "python3 /app/init.py", requires=["file:/app/init.py"]),
    ]
    fs = spec_ast._check_stub_producer_invoked(steps)
    assert fs[0].kind == "stub-producer-invoked"


def test_direct_why_placeholder_keyword_emits_finding():
    steps = [
        _step(
            1,
            "cat > /app/init.py <<'EOF'\nx=1\ny=2\nz=3\nprint(x,y,z)\nEOF",
            why="placeholder until real implementation lands",
            produces=["file:/app/init.py"],
        ),
        _step(3, "python3 /app/init.py", requires=["file:/app/init.py"]),
    ]
    fs = spec_ast._check_stub_producer_invoked(steps)
    assert fs[0].severity == "block"


# ── Other stub markers ────────────────────────────────────────────────────────


def test_direct_pass_only_body_emits_finding():
    action = "cat > /app/mod.py <<'EOF'\ndef run():\n    pass\nEOF"
    steps = [
        _step(1, action, produces=["file:/app/mod.py"]),
        _step(2, "python3 /app/mod.py", requires=["file:/app/mod.py"]),
    ]
    fs = spec_ast._check_stub_producer_invoked(steps)
    assert fs[0].kind == "stub-producer-invoked"


def test_direct_todo_implement_marker_emits_finding():
    action = "cat > /app/mod.py <<'EOF'\n# TODO: implement\ndef run():\n    pass\nEOF"
    steps = [
        _step(1, action, produces=["file:/app/mod.py"]),
        _step(2, "python3 /app/mod.py", requires=["file:/app/mod.py"]),
    ]
    fs = spec_ast._check_stub_producer_invoked(steps)
    assert fs[0].tier == 1


# ── Vidence v2 end-to-end repro (#49 shape) via classify() ───────────────────

# Note: _parse_steps_section captures only the inline portion of 'action:' fields
# (W2 limitation — multi-line YAML literal blocks parse as just '|'). For the
# heredoc regex to match, the action value must be a single YAML quoted string
# containing actual embedded newlines. We use _write_spec_raw() to write file
# content where the action field embeds real newlines inside the quoted value.


def _write_spec_raw(content: str) -> pathlib.Path:
    """Write raw spec content directly (bypassing _HEADER/_FOOTER template)."""
    fd, path = tempfile.mkstemp(suffix=".spec.md")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(content)
    return pathlib.Path(path)


from tests.fixtures.spec_template import make_spec_text as _make_spec_text


_VIDENCE_V2_STEPS_STUB = (
    "- step: 1\n"
    "  why: \"Write bootstrap stub — placeholder until step 3 is implemented.\"\n"
    "  action: \"cat > /app/vidence/bootstrap.py <<'EOF'\\ndef bootstrap():\\n    pass\\nEOF\"\n"
    "  verification: \"test -f /app/vidence/bootstrap.py\"\n"
    "  produces:\n"
    "    - \"file:/app/vidence/bootstrap.py\"\n"
    "  negative-paths:\n"
    "    - trigger: \"disk full\"\n"
    "      handler: \"escalate\"\n"
    "- step: 3\n"
    "  why: \"Run bootstrap.\"\n"
    "  action: \"python3 /app/vidence/bootstrap.py --root .\"\n"
    "  verification: \"test -d .vidence\"\n"
    "  requires:\n"
    "    - \"file:/app/vidence/bootstrap.py\"\n"
    "  negative-paths:\n"
    "    - trigger: \"disk full\"\n"
    "      handler: \"escalate\"\n"
)

_VIDENCE_V2_STEPS_CORRECTED = _VIDENCE_V2_STEPS_STUB.replace(
    "Write bootstrap stub — placeholder until step 3 is implemented.",
    "Write the initial bootstrap module.",
).replace(
    # v1.1.1 Fix K: after the YAML escape fix, the heredoc regex correctly
    # extracts the body, so the body itself must not look like a stub. The
    # plain `def bootstrap(): pass` body in the original `_STUB` block IS
    # a stub by `_body_is_stub`; the corrected spec needs a real body to
    # avoid `stub-producer-invoked` for the right reason.
    "def bootstrap():\\n    pass",
    "def bootstrap():\\n    import os\\n    os.makedirs('.vidence', exist_ok=True)",
)


_SPEC_KW = dict(
    title="Stub Producer Test Spec",
    slug="stub-producer-test",
    problem="Testing stub-producer-invoked Tier 1 detection.",
    first_principles="- A step invoking an artifact produced by a stub step must fail at lock time.",
    success_criteria="- [ ] Check passes.",
    mutates="/app/",
)


def _vidence_v2_spec() -> str:
    """Vidence v2 (#49) spec: Step 1 has 'stub' in why:, Step 3 requires it."""
    return _make_spec_text(_VIDENCE_V2_STEPS_STUB, **_SPEC_KW)


def _vidence_v2_corrected_spec() -> str:
    """Vidence v2 corrected: step 1 why: has no stub keywords; classify() passes."""
    return _make_spec_text(_VIDENCE_V2_STEPS_CORRECTED, **_SPEC_KW)


def test_vidence_v2_classify_emits_stub_producer_invoked():
    """#49 repro: classify() on stub spec must emit stub-producer-invoked."""
    p = _write_spec_raw(_vidence_v2_spec())
    fs = [f for f in spec_ast.classify(p) if f.kind == SPI]
    assert fs[0].kind == SPI


def test_vidence_v2_corrected_classify_no_stub_finding():
    """With healing step 2, classify() must not emit stub-producer-invoked."""
    p = _write_spec_raw(_vidence_v2_corrected_spec())
    fs = [f for f in spec_ast.classify(p) if f.kind == SPI]
    assert fs == []
