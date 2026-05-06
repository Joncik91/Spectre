"""
test_vision_sidecar_path_consistency.py — regression for issue #12 P3.

Asserts that the canonical sidecar path produced by eval_metadata.sidecar_path_for()
uses append-suffix (.spec.md.eval.json), not replace-suffix (.eval.json).
This prevents skill-prose drift from silently breaking agents that read the sidecar.
"""
import pathlib
import re
import sys

sys.path.insert(0, str(pathlib.Path(__file__).parent.parent / "bin"))

import eval_metadata


def test_sidecar_path_for_appends_eval_json():
    """sidecar_path_for must append .eval.json — not replace the existing suffix."""
    spec = pathlib.Path("specs/my-feature.spec.md")
    expected = pathlib.Path("specs/my-feature.spec.md.eval.json")
    assert eval_metadata.sidecar_path_for(spec) == expected


def test_sidecar_path_for_does_not_use_replace_suffix():
    """Explicitly guard against the replace-suffix footgun: foo.spec.md → foo.eval.json."""
    spec = pathlib.Path("specs/my-feature.spec.md")
    wrong = pathlib.Path("specs/my-feature.eval.json")
    assert eval_metadata.sidecar_path_for(spec) != wrong


def test_sidecar_path_for_preserves_parent_directory():
    spec = pathlib.Path("/project/specs/auth.spec.md")
    result = eval_metadata.sidecar_path_for(spec)
    assert result.parent == pathlib.Path("/project/specs")


def test_sidecar_path_for_works_for_plain_md_spec():
    """Even a plain .md (non-.spec.md) input gets .eval.json appended."""
    spec = pathlib.Path("something.md")
    assert eval_metadata.sidecar_path_for(spec) == pathlib.Path("something.md.eval.json")


def test_write_sidecar_produces_path_consistent_with_sidecar_path_for(tmp_path):
    """write_sidecar return value must equal sidecar_path_for(spec_path)."""
    import findings as findings_mod

    spec = tmp_path / "foo.spec.md"
    spec.write_text("# spec")

    result = eval_metadata.write_sidecar(
        spec,
        evaluator_version="0.4.2.4",
        tiers_run=[1, 2],
        findings=[],
        dismissals=[],
        config_path=None,
        config_hash=None,
        deepseek_model_version=None,
        policy_hash="deadbeef",
    )

    assert result == eval_metadata.sidecar_path_for(spec)
    assert result.name == "foo.spec.md.eval.json"


def test_sidecar_extension_constant_is_eval_json():
    """SIDECAR_EXTENSION must be the exact string '.eval.json'."""
    assert eval_metadata.SIDECAR_EXTENSION == ".eval.json"


# ---------------------------------------------------------------------------
# Skill-prose drift guards — added in follow-up review of #12 P3
# ---------------------------------------------------------------------------

_VISION_SKILL = (
    pathlib.Path(__file__).resolve().parent.parent / "skills" / "vision" / "SKILL.md"
)


def test_skill_prose_uses_append_suffix_form():
    """skills/vision/SKILL.md must reference the append-suffix form at least once."""
    text = _VISION_SKILL.read_text()
    assert ".spec.md.eval.json" in text, (
        "SKILL.md prose no longer mentions '.spec.md.eval.json' — "
        "re-introduce the canonical form or update this test intentionally."
    )


def test_skill_prose_does_not_use_replace_suffix_form():
    """No concrete filename token ending in '.eval.json' may omit the '.spec.md' infix.

    This catches the original #12 P3 bug: prose that says e.g. 'auth.eval.json'
    (replace-suffix) instead of 'auth.spec.md.eval.json' (append-suffix).

    Strategy: scan for '.eval.json' occurrences.  For each, walk back through the
    text to collect the full dot-separated filename token.  If the token ends with
    '.spec.md.eval.json' it is correct; if it is preceded immediately by '>' it is
    pseudo-syntax like '<slug>.spec.md.eval.json' and also allowed; otherwise it is
    the banned replace-suffix form.  A bare '.eval.json' not preceded by a word
    character (e.g. in "with `.eval.json` appended") produces an empty back-token
    and is also excluded.
    """
    text = _VISION_SKILL.read_text()
    bad = []
    for m in re.finditer(r"\.eval\.json", text):
        start = m.start()
        # Walk back over word-chars and dots to get the full filename token
        i = start - 1
        while i >= 0 and (text[i].isalnum() or text[i] in "._-"):
            i -= 1
        token = text[i + 1 : m.end()]
        # Allow: empty prefix, bare ".eval.json" token (no word-char stem — it is
        # generic prose like "with `.eval.json` appended"), pseudo-syntax preceded
        # by ">" (e.g. <slug>.spec.md.eval.json), or correct append-suffix form.
        if (
            not token
            or token == ".eval.json"
            or (i >= 0 and text[i] == ">")
            or token.endswith(".spec.md.eval.json")
        ):
            continue
        bad.append(token)
    assert not bad, (
        "SKILL.md contains replace-suffix '.eval.json' form(s): "
        + ", ".join(repr(b) for b in bad)
    )
