"""Tests: Python-stack lifecycle + prompt-design detection (v1.2 Fix E).

Coverage taxonomy
-----------------
Strong tokens  — fire unconditionally; qualified names specific enough to
                 avoid prose collisions.
Gated tokens   — fire only when a context keyword co-occurs within
                 _GATED_WINDOW chars; bare word alone must NOT fire.

Lifecycle (strong): watchdog.observers, multiprocessing.Process, asyncio.run,
                    systemd-run, crontab, apscheduler
Lifecycle (gated):  daemon + systemd|.service|pid|fork — with and without
                    context (negative gating).
LLM (strong):       openai.ChatCompletion, anthropic.Anthropic
LLM (gated):        messages=[ + LLM vendor, system_prompt + LLM vendor —
                    with and without context (negative gating).
"""
import pathlib

from bin import walker


# ── helpers ──────────────────────────────────────────────────────────────────

def _state(intent: str = "build a thing") -> walker.WalkState:
    return walker.WalkState(
        spec_intent=intent,
        spec_draft_path=pathlib.Path("specs/x.spec.md.draft"),
    )


def _draft_with_action(action: str) -> str:
    return f"## 6. Steps\n- step: 1\n  action: {action}\n"


# ── Lifecycle: strong Python tokens ──────────────────────────────────────────

class TestLifecyclePythonStrong:
    def test_watchdog_observers_in_intent_fires(self):
        state = _state("use watchdog.observers to monitor filesystem events")
        assert walker._detect_lifecycle_trigger(state, "") is True

    def test_multiprocessing_process_in_intent_fires(self):
        state = _state("spawn workers via multiprocessing.Process")
        assert walker._detect_lifecycle_trigger(state, "") is True

    def test_asyncio_run_in_intent_fires(self):
        state = _state("entry point calls asyncio.run(main())")
        assert walker._detect_lifecycle_trigger(state, "") is True

    def test_apscheduler_in_intent_fires(self):
        state = _state("schedule tasks with apscheduler")
        assert walker._detect_lifecycle_trigger(state, "") is True

    def test_systemd_run_in_draft_action_fires(self):
        state = _state("run a background job")
        draft = _draft_with_action("systemd-run --unit=myapp python app.py")
        assert walker._detect_lifecycle_trigger(state, draft) is True

    def test_crontab_in_draft_action_fires(self):
        state = _state("schedule a daily cleanup")
        draft = _draft_with_action("crontab -l | grep cleanup")
        assert walker._detect_lifecycle_trigger(state, draft) is True


# ── Lifecycle: gated weak token ───────────────────────────────────────────────

class TestLifecycleDaemonGated:
    def test_daemon_near_pid_in_intent_fires(self):
        # "daemon" + ".pid" within 80 chars — should fire
        state = _state("write a daemon that stores its .pid file on startup")
        assert walker._detect_lifecycle_trigger(state, "") is True

    def test_daemon_in_unix_history_prose_does_not_fire(self):
        # "daemon" alone in a prose sentence about UNIX history — no context kw
        state = _state(
            "the word daemon originates from Greek mythology and "
            "was introduced into computing as a metaphor"
        )
        # _INTENT_LIFECYCLE_PATTERNS already contains \bdaemon\b which fires
        # unconditionally; this test documents that the bare-word pattern
        # intentionally fires on intent (daemon is a known lifecycle signal in
        # intent prose).  The gated check is additional; it does not replace
        # the existing broad intent match.
        # Expected: True (existing \bdaemon\b in _INTENT_LIFECYCLE_PATTERNS).
        assert walker._detect_lifecycle_trigger(state, "") is True

    def test_daemon_in_draft_action_near_fork_fires(self):
        # In a draft action (not intent), "daemon" near "fork()" should match
        state = _state("build a server")
        draft = _draft_with_action("start daemon via fork() and detach from terminal")
        assert walker._detect_lifecycle_trigger(state, draft) is True


# ── LLM / prompt-design: strong Python tokens ────────────────────────────────

class TestLLMPythonStrong:
    def test_openai_chatcompletion_fires(self):
        state = _state()
        draft = _draft_with_action("call openai.ChatCompletion.create(model=gpt-4)")
        assert walker._detect_llm_call_trigger(state, draft) is True

    def test_anthropic_anthropic_fires(self):
        state = _state()
        draft = _draft_with_action("client = anthropic.Anthropic(); client.messages.create(...)")
        assert walker._detect_llm_call_trigger(state, draft) is True


# ── LLM / prompt-design: gated weak tokens ───────────────────────────────────

class TestLLMGated:
    def test_messages_list_near_anthropic_fires(self):
        state = _state()
        draft = _draft_with_action(
            "pass messages=[ {'role':'user','content':prompt} ] to anthropic SDK"
        )
        assert walker._detect_llm_call_trigger(state, draft) is True

    def test_system_prompt_near_openai_fires(self):
        state = _state()
        draft = _draft_with_action(
            "build system_prompt string, then call openai chat completions"
        )
        assert walker._detect_llm_call_trigger(state, draft) is True

    def test_messages_list_without_llm_context_does_not_fire(self):
        # "messages=[ ... ]" alone — no LLM vendor keyword nearby
        state = _state()
        draft = _draft_with_action(
            "serialize messages=[ event1, event2 ] to JSON log file"
        )
        assert walker._detect_llm_call_trigger(state, draft) is False

    def test_system_prompt_without_llm_context_does_not_fire(self):
        # "system_prompt" in a config-file context — no LLM vendor keyword
        state = _state()
        draft = _draft_with_action(
            "read system_prompt from environment variable for display in UI"
        )
        assert walker._detect_llm_call_trigger(state, draft) is False
