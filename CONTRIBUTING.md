# Contributing

Thanks for your interest. Spectre has strong opinions about its own code; this document is the short version.

## Hard rules

1. **Stdlib only in `bin/`.** No `pip install`, no third-party imports in production code. The plugin must run on a vanilla Python 3.11+ install. Tests may use `pytest` (and only `pytest`).
2. **Python 3.11+.** PEP 604 union syntax (`X | None`), PEP 585 generics (`list[str]`), `dataclasses`, `pathlib.Path` everywhere.
3. **No `__init__.py` files in `bin/` or `tests/`.** Modules are run directly or imported via `sys.path` manipulation in tests.
4. **Atomic file I/O.** Every write to `specs/`, `state/`, or `decisions/` goes through `mkstemp` + `os.replace`. Use `bin/_scratchpad.py:atomic_write` or copy its pattern.
5. **One test file per production module.** `bin/foo.py` ↔ `tests/test_foo.py`. Integration suites live alongside (`test_*_integration.py`, `test_e2e.py`).

## Test discipline

- **TDD by default.** Write the failing test, run it, watch it fail, write the minimum code to pass, run it again. Commits should reflect this rhythm.
- **Real production functions in tests.** No mocks of internal modules. The only mocked surface is `urllib.request.urlopen` in `tests/test_llm_judge.py` (DeepSeek API).
- **One assertion per behavior.** Don't bundle five `assert`s into one test and call it `test_everything_works`. If a loop generates assertions, split into named cases.
- **Pragma test-gaming guard.** Tests with `rejects/raises/refuses/denies` in the name **must** use `pytest.raises`. The PreToolUse(Edit) hook blocks edits that violate this — there is no way to silently merge a fake test.
- **No hardcoded constants on both sides of an assertion.** `assert MY_CONST == 5` where `MY_CONST = 5` is a dead test. Use real production values or computed expectations.
- **Fixtures over setup boilerplate.** `tests/conftest.py` provides `plugin_root` (clean tmpdir with `specs/`, `state/`) and `initial_scratchpad` (writes a v1 scratchpad). Reuse them.

```bash
pytest tests/                          # full suite, ~5s
pytest tests/test_spec_evaluator.py    # one module
pytest tests/ -v -k dismiss            # filter by name
pytest tests/ -x                       # stop at first failure
```

## Commit hygiene

- **Conventional commits.** `feat:`, `fix:`, `docs:`, `refactor:`, `test:`, `chore:`. Scope optional but appreciated for multi-skill changes (`feat(vision): …`).
- **Frequent commits.** A failing test, a passing test, a refactor — three commits, not one. Easier to review and easier to revert.
- **One commit, one concern.** Don't bundle a bug fix with a refactor with a doc tweak. Split.
- **Trailers only when relevant.** `Co-Authored-By:` for pair work or AI assistance, `Fixes #N` for issue closures. No emoji in commit messages unless explicitly requested.

## Pull request flow

1. **Branch from `master`.** `feat/<short-slug>` or `fix/<short-slug>`.
2. **Write the test first.** PRs without tests for new behavior are sent back. PRs with tests but no code-of-interest are also sent back (probably a vacuous test — see Pragma rule above).
3. **Run the full suite locally.** `pytest tests/` must pass before push.
4. **PR description names the failure mode.** What was broken, what the fix changes, how to verify. The CHANGELOG entry usually drops out of the PR description.
5. **Pre-merge:** rebase on `master`, squash if the branch is messy, fast-forward into `master`. No merge commits in `master` history unless a release branch needs preserving.

## Architecture changes

If your change adds a new `bin/` module, a new skill, or a new hook:

1. **Open a discussion first.** A short issue describing the failure mode you're addressing and the proposed shape. Three-paragraph plan beats three-day rewrite.
2. **Write a brief in `docs/superpowers/specs/`.** Same format as existing v0.2.x / v0.3 / v0.5.2 / v0.6.0 briefs: hard problem, first principles, design, risks, deferred work.
3. **Write a plan in `docs/superpowers/plans/`.** Step-by-step implementation with TDD discipline. Use the existing plans as templates.
4. **Get the brief peer-reviewed.** Either by another maintainer or by an explicitly different model. This is established practice: the v0.3.0 evaluator was reviewed by Copilot/GPT-5.4 before merge; the v0.5.2 design (issue #32 + comments) went through the same Copilot/GPT-5.4 peer-review loop. The adversarial-reviewer principle applies to the codebase itself, not just specs.
5. **Then implement.** Subagent-driven if you have the tooling for it; fresh-context-per-task if you don't.

## What we won't accept

- **New third-party dependencies in `bin/`.** Stdlib has been enough for v0.1.0 → v0.7.1; it will be enough going forward.
- **`async`/`await` for the sake of it.** The supervisor uses `select()` because that's the right primitive. Async is fine where it's a clear win; not as a default.
- **Silent feature additions.** Every new behavior needs documentation in `README.md` (if user-visible) or `docs/ARCHITECTURE.md` (if internal). PRs without doc updates get sent back.
- **Tests that don't fail when the code is wrong.** If you can comment out the production code and the test still passes, the test is a liability.

## Code of conduct

Be precise, not nice. If a reviewer says "this is wrong because X", the answer is either "fix it" or "X is wrong because Y". The answer is not "I disagree but will change it anyway." Bad code that ships because nobody pushed back is the worst outcome.

## Questions

Open an issue: <https://github.com/Joncik91/Spectre/issues>.
