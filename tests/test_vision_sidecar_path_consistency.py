"""
test_vision_sidecar_path_consistency.py — regression for issue #12 P3.

Asserts that the canonical sidecar path produced by eval_metadata.sidecar_path_for()
uses append-suffix (.spec.md.eval.json), not replace-suffix (.eval.json).
This prevents skill-prose drift from silently breaking agents that read the sidecar.
"""
import pathlib
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
