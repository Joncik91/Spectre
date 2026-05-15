"""CLI tests for bin/spec_evaluator.py __main__ entrypoint.

Invokes the module via `python3 -m bin.spec_evaluator <subcommand>` as a
subprocess so the CLI is tested end-to-end, not via import.

Pragma guard: one assertion per test; no _rejects_/_raises_ without
pytest.raises; no mocked exit.
"""
import json
import os
import pathlib
import subprocess
import sys

import pytest

FIXTURES = pathlib.Path(__file__).parent / "fixtures" / "specs"
GOOD_MINIMAL = FIXTURES / "good_minimal.spec.md"

_CMD = [sys.executable, "-m", "bin.spec_evaluator"]
_REPO = pathlib.Path(__file__).parent.parent


def _run(*args, cwd=None, stdin=None):
    return subprocess.run(
        _CMD + list(args),
        capture_output=True,
        text=True,
        cwd=cwd or _REPO,
        input=stdin,
    )


# ── slug-to-path ──────────────────────────────────────────────────────────────

class TestSlugToPath:
    def test_happy_path_returns_canonical_path(self):
        r = _run("slug-to-path", "--slug", "my-feature")
        assert r.returncode == 0

    def test_output_is_specs_slug_spec_md(self):
        r = _run("slug-to-path", "--slug", "my-feature")
        assert r.stdout.strip() == "specs/my-feature.spec.md"

    def test_stderr_empty_on_success(self):
        r = _run("slug-to-path", "--slug", "foo-bar")
        assert r.stderr == ""

    def test_error_when_slug_flag_missing(self):
        r = _run("slug-to-path")
        assert r.returncode == 2

    def test_slug_with_numbers_works(self):
        r = _run("slug-to-path", "--slug", "spec-v2-123")
        assert r.stdout.strip() == "specs/spec-v2-123.spec.md"

    def test_slug_to_path_exits_1_for_unslugified_input(self):
        r = _run("slug-to-path", "--slug", "My Feature")
        assert r.returncode == 1

    def test_slug_to_path_stderr_nonempty_for_unslugified_input(self):
        r = _run("slug-to-path", "--slug", "My Feature")
        assert r.stderr != ""

    def test_slug_to_path_stderr_suggests_correction_for_unslugified_input(self):
        r = _run("slug-to-path", "--slug", "My Feature")
        assert "my-feature" in r.stderr


# ── evaluate ──────────────────────────────────────────────────────────────────

class TestEvaluateCli:
    def test_happy_path_exits_zero(self, tmp_path):
        r = _run("evaluate", "--spec", str(GOOD_MINIMAL), "--bundle-dir", str(tmp_path))
        assert r.returncode == 0

    def test_output_is_valid_json(self, tmp_path):
        r = _run("evaluate", "--spec", str(GOOD_MINIMAL), "--bundle-dir", str(tmp_path))
        data = json.loads(r.stdout)
        assert isinstance(data, dict)

    def test_output_contains_findings_key(self, tmp_path):
        r = _run("evaluate", "--spec", str(GOOD_MINIMAL), "--bundle-dir", str(tmp_path))
        data = json.loads(r.stdout)
        assert "findings" in data

    def test_output_contains_max_severity_key(self, tmp_path):
        r = _run("evaluate", "--spec", str(GOOD_MINIMAL), "--bundle-dir", str(tmp_path))
        data = json.loads(r.stdout)
        assert "max_severity" in data

    def test_output_contains_sidecar_payload_key(self, tmp_path):
        r = _run("evaluate", "--spec", str(GOOD_MINIMAL), "--bundle-dir", str(tmp_path))
        data = json.loads(r.stdout)
        assert "sidecar_payload" in data

    def test_write_to_output_file(self, tmp_path):
        out_file = tmp_path / "result.json"
        r = _run(
            "evaluate",
            "--spec", str(GOOD_MINIMAL),
            "--bundle-dir", str(tmp_path),
            "--output", str(out_file),
        )
        assert r.returncode == 0

    def test_output_file_contains_valid_json(self, tmp_path):
        out_file = tmp_path / "result.json"
        _run(
            "evaluate",
            "--spec", str(GOOD_MINIMAL),
            "--bundle-dir", str(tmp_path),
            "--output", str(out_file),
        )
        data = json.loads(out_file.read_text(encoding="utf-8"))
        assert "findings" in data

    def test_missing_spec_flag_exits_2(self):
        r = _run("evaluate")
        assert r.returncode == 2

    def test_nonexistent_spec_exits_1(self, tmp_path):
        r = _run("evaluate", "--spec", str(tmp_path / "no_such.spec.md"), "--bundle-dir", str(tmp_path))
        assert r.returncode == 1

    def test_nonexistent_spec_stderr_nonempty(self, tmp_path):
        r = _run("evaluate", "--spec", str(tmp_path / "no_such.spec.md"), "--bundle-dir", str(tmp_path))
        assert r.stderr != ""


# ── clear-bundle ──────────────────────────────────────────────────────────────

class TestClearBundleCli:
    def test_happy_path_existing_bundle_exits_zero(self, tmp_path):
        bundle = tmp_path / ".eval-bundle.json"
        bundle.write_text("{}", encoding="utf-8")
        r = _run("clear-bundle", "--bundle", str(bundle))
        assert r.returncode == 0

    def test_bundle_is_removed_after_clear(self, tmp_path):
        bundle = tmp_path / ".eval-bundle.json"
        bundle.write_text("{}", encoding="utf-8")
        _run("clear-bundle", "--bundle", str(bundle))
        assert not bundle.exists()

    def test_idempotent_missing_bundle_exits_zero(self, tmp_path):
        r = _run("clear-bundle", "--bundle", str(tmp_path / "no_bundle.json"))
        assert r.returncode == 0

    def test_stderr_empty_on_clear(self, tmp_path):
        bundle = tmp_path / ".eval-bundle.json"
        bundle.write_text("{}", encoding="utf-8")
        r = _run("clear-bundle", "--bundle", str(bundle))
        assert r.stderr == ""


# ── Fix H: --project flag ─────────────────────────────────────────────────────

class TestProjectFlag:
    """Fix H: --project PATH re-roots all relative path resolution."""

    def test_project_flag_accepted_by_evaluate(self):
        """--project flag is recognised (no argparse error)."""
        r = _run(
            "evaluate",
            "--project", str(FIXTURES),
            "--spec", "non-existent.spec.md",
            "--bundle-dir", "/tmp",
        )
        # Exit 1 (spec missing) is fine — 2 would mean argparse rejected the flag.
        assert r.returncode != 2

    def test_project_flag_resolves_spec_relative_to_project(self, tmp_path):
        """Invoked from /tmp with --project <fixtures dir>; evaluator finds the spec."""
        bundle_dir = tmp_path / "bundle"
        bundle_dir.mkdir()
        env = {**os.environ, "PYTHONPATH": str(_REPO)}
        r = subprocess.run(
            _CMD + [
                "evaluate",
                "--project", str(FIXTURES),
                "--spec", "good_minimal.spec.md",
                "--bundle-dir", str(bundle_dir),
            ],
            capture_output=True,
            text=True,
            cwd="/tmp",  # intentionally different from fixtures dir
            env=env,
        )
        assert r.returncode == 0

    def test_project_flag_result_matches_cwd_invocation(self, tmp_path):
        """evaluate --project <fixtures> from /tmp equals evaluate from <fixtures>."""
        bundle_a = tmp_path / "a"
        bundle_b = tmp_path / "b"
        bundle_a.mkdir(); bundle_b.mkdir()

        r_cwd = _run(
            "evaluate",
            "--spec", str(GOOD_MINIMAL),
            "--bundle-dir", str(bundle_a),
        )
        env = {**os.environ, "PYTHONPATH": str(_REPO)}
        r_proj = subprocess.run(
            _CMD + [
                "evaluate",
                "--project", str(FIXTURES),
                "--spec", "good_minimal.spec.md",
                "--bundle-dir", str(bundle_b),
            ],
            capture_output=True, text=True, cwd="/tmp", env=env,
        )
        assert r_cwd.returncode == 0
        assert r_proj.returncode == 0
        data_cwd = json.loads(r_cwd.stdout)
        data_proj = json.loads(r_proj.stdout)
        assert data_cwd["max_severity"] == data_proj["max_severity"]

    def test_absolute_spec_path_unaffected_by_project_flag(self, tmp_path):
        """Absolute --spec ignores --project (absolute paths pass through)."""
        bundle_dir = tmp_path / "bundle"
        bundle_dir.mkdir()
        env = {**os.environ, "PYTHONPATH": str(_REPO)}
        r = subprocess.run(
            _CMD + [
                "evaluate",
                "--project", "/nonexistent/root",
                "--spec", str(GOOD_MINIMAL),  # absolute path
                "--bundle-dir", str(bundle_dir),
            ],
            capture_output=True, text=True, cwd="/tmp", env=env,
        )
        assert r.returncode == 0
