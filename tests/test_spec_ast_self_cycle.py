"""Tests for v0.8 §42 self-cycle-produces Tier 1 check in bin/spec_ast.py.

Pragma guard: assertion-style names only. One assertion per test.
Tests asserting absence/emptiness use _returns_empty/_is_none/_no_ naming.
"""
import os
import pathlib
import tempfile

from bin import spec_ast

# ── Shared spec template ──────────────────────────────────────────────────────
# §1-§8 skeleton lives in tests/fixtures/spec_template.py to keep the §8
# receiver-calibration shape consistent across spec_ast satellite test files.

from tests.fixtures.spec_template import write_spec_file as _write_spec_helper


def _write_spec(steps_yaml: str) -> pathlib.Path:
    return _write_spec_helper(
        steps_yaml,
        title="Self-Cycle Test Spec",
        slug="self-cycle-test",
        problem="Testing self-cycle detection in step produces.",
        first_principles="- A step must not consume a file it also declares as its own output.",
        guardrails="- Files must exist before being referenced.",
        success_criteria="- [ ] Self-cycle detected.",
        mutates="/home/joncik/apps/test-spectrere/",
    )


# ── Case 1: self-cycle — action consumes path it also produces, no prior producer ──

_SELF_CYCLE_YAML = """\
- step: 1
  why: "Bootstrap the manifest."
  action: "python3 -m myapp.classifier download --manifest src/myapp/_manifest.toml"
  verification: "test -f src/myapp/_manifest.toml"
  produces:
    - "file:/home/joncik/apps/test-spectrere/src/myapp/_manifest.toml"
  negative-paths:
    - trigger: "download fails"
      handler: "retry once"
"""


def test_self_cycle_emits_finding():
    p = _write_spec(_SELF_CYCLE_YAML)
    try:
        fs = spec_ast.classify(p)
        assert any(f.kind == "self-cycle-produces" for f in fs)
    finally:
        p.unlink(missing_ok=True)


def test_self_cycle_severity_is_block():
    p = _write_spec(_SELF_CYCLE_YAML)
    try:
        fs = spec_ast.classify(p)
        f = next(x for x in fs if x.kind == "self-cycle-produces")
        assert f.severity == "block"
    finally:
        p.unlink(missing_ok=True)


def test_self_cycle_location_step_number_is_correct():
    p = _write_spec(_SELF_CYCLE_YAML)
    try:
        fs = spec_ast.classify(p)
        f = next(x for x in fs if x.kind == "self-cycle-produces")
        assert f.location.step == 1
    finally:
        p.unlink(missing_ok=True)


def test_self_cycle_location_scope_is_step():
    p = _write_spec(_SELF_CYCLE_YAML)
    try:
        fs = spec_ast.classify(p)
        f = next(x for x in fs if x.kind == "self-cycle-produces")
        assert f.location.scope == "step"
    finally:
        p.unlink(missing_ok=True)


# ── Case 2: earlier step produces the file — no finding ─────────────────────

_EARLIER_PRODUCER_YAML = """\
- step: 1
  why: "Generate the manifest by running the scaffolding tool."
  action: "python3 -m myapp.scaffold init"
  verification: "test -f src/myapp/_manifest.toml"
  produces:
    - "file:/home/joncik/apps/test-spectrere/src/myapp/_manifest.toml"
  negative-paths:
    - trigger: "scaffold fails"
      handler: "abort"

- step: 2
  why: "Download classifier artifacts using the already-generated manifest."
  action: "python3 -m myapp.classifier download --manifest src/myapp/_manifest.toml"
  verification: "test -f state/classifier/model.onnx"
  produces:
    - "file:/home/joncik/apps/test-spectrere/state/classifier/model.onnx"
  negative-paths:
    - trigger: "download fails"
      handler: "retry once"
"""


def test_no_self_cycle_when_earlier_step_produces_the_path_returns_empty():
    p = _write_spec(_EARLIER_PRODUCER_YAML)
    try:
        fs = spec_ast.classify(p)
        assert not any(f.kind == "self-cycle-produces" for f in fs)
    finally:
        p.unlink(missing_ok=True)


# ── Case 3: action mentions path not in produces — no finding ────────────────

_PATH_NOT_IN_PRODUCES_YAML = """\
- step: 1
  why: "Read the config."
  action: "python3 -m myapp.runner --config src/myapp/config.toml"
  verification: "test -f src/myapp/config.toml"
  produces:
    - "file:/home/joncik/apps/test-spectrere/src/myapp/output.json"
  negative-paths:
    - trigger: "run fails"
      handler: "abort"
"""


def test_no_self_cycle_when_path_not_in_produces_returns_empty():
    p = _write_spec(_PATH_NOT_IN_PRODUCES_YAML)
    try:
        fs = spec_ast.classify(p)
        assert not any(f.kind == "self-cycle-produces" for f in fs)
    finally:
        p.unlink(missing_ok=True)


# ── Case 4: multiple paths in one action, one self-cycle one legitimate ───────

_MULTI_PATH_YAML = """\
- step: 1
  why: "Seed the registry with the base model."
  action: "python3 -m myapp.seeder --manifest src/myapp/_manifest.toml --config src/myapp/config.toml"
  verification: "test -f src/myapp/_manifest.toml"
  produces:
    - "file:/home/joncik/apps/test-spectrere/src/myapp/_manifest.toml"
    - "file:/home/joncik/apps/test-spectrere/state/registry.db"
  negative-paths:
    - trigger: "seed fails"
      handler: "abort"
"""


def test_multi_path_one_self_cycle_emits_exactly_one_finding():
    p = _write_spec(_MULTI_PATH_YAML)
    try:
        fs = spec_ast.classify(p)
        cycle_findings = [f for f in fs if f.kind == "self-cycle-produces"]
        assert len(cycle_findings) == 1
    finally:
        p.unlink(missing_ok=True)


# ── Case 5: relative action path / absolute produces path (gateway repro) ────

_GATEWAY_REPRO_YAML = """\
- step: 3
  why: "Download classifier and verify digest."
  action: "python3 -m llm_routing_gateway.classifier download --target state/classifier/ --manifest src/llm_routing_gateway/classifier/_manifest.toml --verify-digest"
  verification: "test -f src/llm_routing_gateway/classifier/_manifest.toml"
  produces:
    - "file:/home/joncik/apps/test-spectrere/src/llm_routing_gateway/classifier/_manifest.toml"
  negative-paths:
    - trigger: "download fails"
      handler: "retry once then abort"
"""


def test_gateway_repro_relative_action_absolute_produces_emits_finding():
    p = _write_spec(_GATEWAY_REPRO_YAML)
    try:
        fs = spec_ast.classify(p)
        assert any(f.kind == "self-cycle-produces" for f in fs)
    finally:
        p.unlink(missing_ok=True)


def test_gateway_repro_finding_references_correct_step_number():
    p = _write_spec(_GATEWAY_REPRO_YAML)
    try:
        fs = spec_ast.classify(p)
        f = next(x for x in fs if x.kind == "self-cycle-produces")
        assert f.location.step == 3
    finally:
        p.unlink(missing_ok=True)


# ── Case 6: --target is a directory, not a file — no finding ─────────────────
# --target state/classifier/ has no file suffix and is not an input-option flag,
# so it must NOT trigger self-cycle even if the produces entry is under that dir.

_DIRECTORY_TARGET_YAML = """\
- step: 1
  why: "Download model artifacts into the classifier directory."
  action: "python3 -m myapp.downloader --target state/classifier/"
  verification: "test -d state/classifier/"
  produces:
    - "file:/home/joncik/apps/test-spectrere/state/classifier/encoder.onnx"
  negative-paths:
    - trigger: "download fails"
      handler: "abort"
"""


def test_no_self_cycle_for_directory_target_returns_empty():
    p = _write_spec(_DIRECTORY_TARGET_YAML)
    try:
        fs = spec_ast.classify(p)
        assert not any(f.kind == "self-cycle-produces" for f in fs)
    finally:
        p.unlink(missing_ok=True)


# ── Case 7: --opt=value form (joined) emits finding same as --opt value ──────

_JOINED_OPT_YAML = """\
- step: 1
  why: "Joined --opt=value form must also trip the check."
  action: "python3 -m myapp --manifest=src/manifest.toml --go"
  verification: "test -f src/manifest.toml"
  produces:
    - "file:/abs/path/src/manifest.toml"
  negative-paths:
    - trigger: "fail"
      handler: "abort"
"""


def test_joined_option_value_form_emits_finding():
    p = _write_spec(_JOINED_OPT_YAML)
    try:
        fs = spec_ast.classify(p)
        assert any(f.kind == "self-cycle-produces" for f in fs)
    finally:
        p.unlink(missing_ok=True)


# ── Case 8: same path under two allowlisted opts dedupes to one finding ──────

_DUPLICATE_PATH_YAML = """\
- step: 1
  why: "Same path referenced via two options must produce only one finding."
  action: "python3 -m myapp --manifest src/m.toml --config src/m.toml"
  verification: "test -f src/m.toml"
  produces:
    - "file:/abs/path/src/m.toml"
  negative-paths:
    - trigger: "fail"
      handler: "abort"
"""


def test_duplicate_path_across_options_emits_exactly_one_finding():
    p = _write_spec(_DUPLICATE_PATH_YAML)
    try:
        fs = spec_ast.classify(p)
        cycle = [f for f in fs if f.kind == "self-cycle-produces"]
        assert len(cycle) == 1
    finally:
        p.unlink(missing_ok=True)


# ── TestSelfCycleOutputFlags: output-flag exclusion (Fix 4) ──────────────────
# When a path in produces: is preceded by a CLI output flag (-o, --out, etc.)
# in the action, it is an authored output destination, not a consumed input,
# and must NOT trigger a self-cycle-produces finding.

# Case 1: -o flag (short form)
_DASH_O_YAML = """\
- step: 1
  why: "Script writes out.json via -o flag."
  action: "node script.mjs -o out.json"
  verification: "test -f out.json"
  produces:
    - "file:/home/joncik/apps/test-spectrere/out.json"
  negative-paths:
    - trigger: "script fails"
      handler: "abort"
"""


def test_dash_o_flag_legitimizes_output_path_returns_no_self_cycle():
    p = _write_spec(_DASH_O_YAML)
    try:
        fs = spec_ast.classify(p)
        assert not any(f.kind == "self-cycle-produces" for f in fs)
    finally:
        p.unlink(missing_ok=True)


# Case 2: --out flag (long space-separated form)
_DASH_DASH_OUT_YAML = """\
- step: 1
  why: "Script writes out.json via --out flag."
  action: "node script.mjs --out out.json"
  verification: "test -f out.json"
  produces:
    - "file:/home/joncik/apps/test-spectrere/out.json"
  negative-paths:
    - trigger: "script fails"
      handler: "abort"
"""


def test_double_dash_out_flag_legitimizes_output_path_returns_no_self_cycle():
    p = _write_spec(_DASH_DASH_OUT_YAML)
    try:
        fs = spec_ast.classify(p)
        assert not any(f.kind == "self-cycle-produces" for f in fs)
    finally:
        p.unlink(missing_ok=True)


# Case 3: --output flag
_OUTPUT_FLAG_YAML = """\
- step: 1
  why: "Script writes out.json via --output flag."
  action: "node script.mjs --output out.json"
  verification: "test -f out.json"
  produces:
    - "file:/home/joncik/apps/test-spectrere/out.json"
  negative-paths:
    - trigger: "script fails"
      handler: "abort"
"""


def test_output_flag_legitimizes_output_path_returns_no_self_cycle():
    p = _write_spec(_OUTPUT_FLAG_YAML)
    try:
        fs = spec_ast.classify(p)
        assert not any(f.kind == "self-cycle-produces" for f in fs)
    finally:
        p.unlink(missing_ok=True)


# Case 4: --out=path equals-form
_OUT_EQUALS_YAML = """\
- step: 1
  why: "Script writes out.json via --out=path equals form."
  action: "node script.mjs --out=out.json"
  verification: "test -f out.json"
  produces:
    - "file:/home/joncik/apps/test-spectrere/out.json"
  negative-paths:
    - trigger: "script fails"
      handler: "abort"
"""


def test_out_equals_form_legitimizes_output_path_returns_no_self_cycle():
    p = _write_spec(_OUT_EQUALS_YAML)
    try:
        fs = spec_ast.classify(p)
        assert not any(f.kind == "self-cycle-produces" for f in fs)
    finally:
        p.unlink(missing_ok=True)


# Case 5: --outfile flag
_OUTFILE_FLAG_YAML = """\
- step: 1
  why: "Script writes out.json via --outfile flag."
  action: "node script.mjs --outfile out.json"
  verification: "test -f out.json"
  produces:
    - "file:/home/joncik/apps/test-spectrere/out.json"
  negative-paths:
    - trigger: "script fails"
      handler: "abort"
"""


def test_outfile_flag_legitimizes_output_path_returns_no_self_cycle():
    p = _write_spec(_OUTFILE_FLAG_YAML)
    try:
        fs = spec_ast.classify(p)
        assert not any(f.kind == "self-cycle-produces" for f in fs)
    finally:
        p.unlink(missing_ok=True)


# Case 6: -O2 is gcc optimization, NOT an output flag — -o out.json is the output
# Verifies that -O2 is not mistaken for the -O output flag (set has '-O' exactly,
# and '-O2' != '-O').
_GCC_O2_YAML = """\
- step: 1
  why: "Compile with -O2 optimization; -o out.json is the real output flag."
  action: "gcc -O2 script.c -o out.json"
  verification: "test -f out.json"
  produces:
    - "file:/home/joncik/apps/test-spectrere/out.json"
  negative-paths:
    - trigger: "compile fails"
      handler: "abort"
"""


def test_O2_optimization_flag_does_not_interfere_with_dash_o_output_returns_no_self_cycle():
    p = _write_spec(_GCC_O2_YAML)
    try:
        fs = spec_ast.classify(p)
        assert not any(f.kind == "self-cycle-produces" for f in fs)
    finally:
        p.unlink(missing_ok=True)


# Case 7: --out with no following argument — flag cannot legitimize anything
_OUT_NO_ARG_YAML = """\
- step: 1
  why: "Flag with no arg cannot legitimize out.json in produces."
  action: "node script.mjs --out"
  verification: "test -f out.json"
  produces:
    - "file:/home/joncik/apps/test-spectrere/out.json"
  negative-paths:
    - trigger: "script fails"
      handler: "abort"
"""


def test_out_flag_with_no_arg_does_not_legitimize_unrelated_produces_path():
    p = _write_spec(_OUT_NO_ARG_YAML)
    try:
        fs = spec_ast.classify(p)
        # out.json is absent from the action string entirely — no token to cycle on.
        # The flag-with-no-arg must not crash or produce phantom authored exclusions.
        assert not any(f.kind == "self-cycle-produces" for f in fs)
    finally:
        p.unlink(missing_ok=True)


# Case 8: bare positional in action, no output flag — cycle must fire
# Uses .json suffix so _extract_action_path_tokens picks it up as a file token.
_BARE_POSITIONAL_YAML = """\
- step: 1
  why: "report.json appears as bare positional in action — no flag to legitimize it."
  action: "node process.mjs report.json"
  verification: "test -f report.json"
  produces:
    - "file:/home/joncik/apps/test-spectrere/report.json"
  negative-paths:
    - trigger: "process fails"
      handler: "abort"
"""


def test_bare_positional_path_in_action_emits_self_cycle_finding():
    p = _write_spec(_BARE_POSITIONAL_YAML)
    try:
        fs = spec_ast.classify(p)
        assert any(f.kind == "self-cycle-produces" for f in fs)
    finally:
        p.unlink(missing_ok=True)


# Case 9: Vidence repro — --target with GitHub Actions output path
_VIDENCE_REPRO_YAML = """\
- step: 19
  why: "Scaffold the GitHub Action definition file."
  action: "node scripts/scaffold-github-action.mjs --target .github/actions/x/action.yml"
  verification: "test -f .github/actions/x/action.yml"
  produces:
    - "file:/home/joncik/apps/test-spectrere/.github/actions/x/action.yml"
  negative-paths:
    - trigger: "scaffold fails"
      handler: "abort"
"""


def test_target_flag_with_github_actions_path_legitimizes_output_returns_no_self_cycle():
    p = _write_spec(_VIDENCE_REPRO_YAML)
    try:
        fs = spec_ast.classify(p)
        assert not any(f.kind == "self-cycle-produces" for f in fs)
    finally:
        p.unlink(missing_ok=True)


# Case 10: --dest flag
_DEST_FLAG_YAML = """\
- step: 19
  why: "Scaffold the GitHub Action definition file via --dest."
  action: "node scripts/scaffold-github-action.mjs --dest .github/actions/x/action.yml"
  verification: "test -f .github/actions/x/action.yml"
  produces:
    - "file:/home/joncik/apps/test-spectrere/.github/actions/x/action.yml"
  negative-paths:
    - trigger: "scaffold fails"
      handler: "abort"
"""


def test_dest_flag_legitimizes_output_path_returns_no_self_cycle():
    p = _write_spec(_DEST_FLAG_YAML)
    try:
        fs = spec_ast.classify(p)
        assert not any(f.kind == "self-cycle-produces" for f in fs)
    finally:
        p.unlink(missing_ok=True)
