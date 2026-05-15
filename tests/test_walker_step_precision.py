"""Tests for Fix B: generate_step_precision_concerns in bin/walker.py.

Covers four vague-action shapes:
  1. pip install without version pin.
  2. python -m <pkg> with no subcommand args.
  3. Bare URL with no version-pin verification token.
  4. Bare model ID alongside LLM vendor SDK call.
Plus one non-vague control per shape.

Pragma guard: assertion-style names only. One assertion per test.
Tests asserting absence/emptiness use _returns_empty/_is_none/_no_ naming.
"""
import pathlib

from bin import walker


# ── Helpers ───────────────────────────────────────────────────────────────────


def _state() -> walker.WalkState:
    return walker.WalkState(
        spec_intent="test",
        spec_draft_path=pathlib.Path("/tmp/test.spec.md.draft"),
    )


def _step(n: int, action: str) -> dict:
    return {
        "step": n,
        "why": "test",
        "action": action,
        "produces": ["file:/tmp/out.json"],
        "requires": [],
        "negative_paths": [],
    }


def _precision_concerns(steps: list[dict]) -> list[walker.Concern]:
    return walker.generate_step_precision_concerns(_state(), steps)


# ── Shape 1: pip install without version pin ──────────────────────────────────


def test_pip_install_unversioned_emits_concern():
    steps = [_step(1, "pip install requests flask")]
    cs = _precision_concerns(steps)
    assert any("precision-pip-1" == c.id for c in cs)


def test_pip_install_with_pinned_version_returns_no_concern():
    steps = [_step(1, "pip install requests==2.31.0 flask==3.0.0")]
    cs = _precision_concerns(steps)
    assert not any(c.id.startswith("precision-pip-") for c in cs)


def test_pip_install_with_constraint_file_returns_no_concern():
    steps = [_step(1, "pip install -r requirements.txt -c constraints.txt")]
    cs = _precision_concerns(steps)
    assert not any(c.id.startswith("precision-pip-") for c in cs)


def test_pip_install_concern_kind_is_edge_case():
    steps = [_step(1, "pip install mypackage")]
    cs = _precision_concerns(steps)
    pip_c = next((c for c in cs if c.id.startswith("precision-pip-")), None)
    assert pip_c is not None and pip_c.kind == "edge-case"


def test_pip_install_concern_receiver_is_human():
    steps = [_step(1, "pip install mypackage")]
    cs = _precision_concerns(steps)
    pip_c = next((c for c in cs if c.id.startswith("precision-pip-")), None)
    assert pip_c is not None and "human" in pip_c.receivers


# ── Shape 2: python -m <pkg> with no subcommand args ─────────────────────────


def test_python_m_bare_no_args_emits_concern():
    steps = [_step(2, "python3 -m myapp")]
    cs = _precision_concerns(steps)
    assert any("precision-python-m-2" == c.id for c in cs)


def test_python_m_with_subcommand_returns_no_concern():
    steps = [_step(2, "python3 -m myapp serve --port 8080")]
    cs = _precision_concerns(steps)
    assert not any(c.id.startswith("precision-python-m-") for c in cs)


def test_python_m_bare_concern_mentions_subcommand():
    steps = [_step(2, "python3 -m myapp")]
    cs = _precision_concerns(steps)
    c = next((c for c in cs if c.id.startswith("precision-python-m-")), None)
    assert c is not None and "subcommand" in c.summary.lower()


# ── Shape 3: Bare URL with no version-pin token ───────────────────────────────


def test_bare_url_no_version_emits_concern():
    steps = [_step(3, "curl -fsSL https://get.docker.com | sh")]
    cs = _precision_concerns(steps)
    assert any("precision-url-3" == c.id for c in cs)


def test_url_with_version_tag_returns_no_concern():
    steps = [_step(3, "curl -fsSL https://example.com/v2.3.1/install.sh | sh")]
    cs = _precision_concerns(steps)
    assert not any(c.id.startswith("precision-url-") for c in cs)


def test_bare_url_concern_mentions_version_pin():
    steps = [_step(3, "curl -fsSL https://get.example.com | sh")]
    cs = _precision_concerns(steps)
    c = next((c for c in cs if c.id.startswith("precision-url-")), None)
    assert c is not None and "version" in c.summary.lower()


# ── Shape 4: Bare model ID alongside LLM vendor SDK ──────────────────────────


def test_bare_model_id_with_vendor_sdk_emits_concern():
    steps = [_step(4, "python3 run.py  # calls client.messages.create model=claude-opus-4")]
    cs = _precision_concerns(steps)
    assert any("precision-model-4" == c.id for c in cs)


def test_model_id_without_vendor_sdk_returns_no_concern():
    # A bare model string but no LLM vendor SDK keyword — no concern.
    steps = [_step(4, "python3 run.py --model gpt-4o --output result.json")]
    cs = _precision_concerns(steps)
    assert not any(c.id.startswith("precision-model-") for c in cs)


def test_bare_model_concern_kind_is_edge_case():
    steps = [_step(4, "client.messages.create(model='claude-opus-4')")]
    cs = _precision_concerns(steps)
    c = next((c for c in cs if c.id.startswith("precision-model-")), None)
    assert c is not None and c.kind == "edge-case"


# ── Idempotency ───────────────────────────────────────────────────────────────


def test_precision_concern_is_idempotent_when_already_answered():
    state = _state()
    steps = [_step(1, "pip install requests")]
    # Pre-populate the answered dict with the concern id.
    state.answered["precision-pip-1"] = "pinned to 2.31.0"
    cs = walker.generate_step_precision_concerns(state, steps)
    assert not any(c.id == "precision-pip-1" for c in cs)


# ── Multi-step: each step gets its own concern id ────────────────────────────


def test_multiple_steps_each_get_unique_concern_ids():
    steps = [
        _step(1, "pip install requests"),
        _step(2, "pip install flask"),
    ]
    cs = _precision_concerns(steps)
    ids = {c.id for c in cs if c.id.startswith("precision-pip-")}
    assert len(ids) == 2
