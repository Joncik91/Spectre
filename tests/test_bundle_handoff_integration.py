"""Bundle handoff integration tests (§6.4 evaluator → §6.5/§6.6 read → §6.7 sidecar + clear).

High-risk end-to-end simulation covering:
  1. Build clean draft spec.
  2. Write to temp draft path.
  3. evaluate(draft_path, bundle_persist_dir=tmp) → verify bundle persisted.
  4. Compute draft SHA-256.
  5. load_persisted_bundle(bundle_path, draft_sha256) → verify equivalence.
  6. Simulate /vision §6.7: write_sidecar via result.sidecar_payload.
  7. Verify sidecar at <spec>.eval.json.
  8. clear_bundle(bundle_path) → verify file gone.

Each test single-assertion per Pragma policy.
"""
import json
import pathlib
import tempfile
import hashlib
import pytest

from bin import spec_evaluator
from bin import eval_metadata


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture
def clean_minimal_spec_text():
    """Minimal valid spec with no findings."""
    return """# Minimal Spec (integration test)

## 1. Hard Problem
Test problem description.

## 2. First Principles
- Decision: test-decision

## 3. Algorithm Audit
No deletions needed.

## 4. Speed-of-Light Limit
Completes in 1 second.

## 5. Physics Guardrails
- No guardrails needed for test.

## 6. Steps

```yaml
- step: 1
  why: "Test step."
  action: "echo test"
  verification: "test -n \"test\""
```

## 7. Success Criteria
- [ ] Test passes.

## 8. Receiver Calibration

### 8.1 Hard contract (machine-enforced)
- `mutates:` /tmp
- `never-touches:` /etc/passwd
- `decision-budget:` none
- `reboot-survival:` not-required

### 8.2 Human-facing notes
- `assumes:` basic-shell
- `runtime-flavor:` test
- `expected-author-skill:` any
"""


@pytest.fixture
def temp_draft_path(clean_minimal_spec_text, tmp_path):
    """Write minimal spec to temp file and return path."""
    draft_file = tmp_path / "test.spec.md"
    draft_file.write_text(clean_minimal_spec_text, encoding="utf-8")
    return draft_file


@pytest.fixture
def temp_bundle_dir(tmp_path):
    """Temp directory for bundle persistence."""
    bundle_dir = tmp_path / "state"
    return bundle_dir


# ── Test Suite ────────────────────────────────────────────────────────────────

class TestBundlePersistence:
    """Tests for bundle persistence at expected path."""

    def test_evaluate_persists_bundle_at_expected_path(
        self, temp_draft_path, temp_bundle_dir
    ):
        """Assert bundle_persist_dir/.eval-bundle.json exists after evaluate."""
        spec_evaluator.evaluate(
            temp_draft_path,
            bundle_persist_dir=temp_bundle_dir,
        )
        bundle_path = temp_bundle_dir / ".eval-bundle.json"
        assert bundle_path.exists()


class TestBundleEquivalence:
    """Tests for loaded bundle equivalence to persisted bundle."""

    def test_persisted_bundle_draft_sha256_matches_input_draft_hash(
        self, clean_minimal_spec_text, temp_draft_path, temp_bundle_dir
    ):
        """Assert persisted bundle has correct draft_sha256."""
        expected_sha256 = hashlib.sha256(
            clean_minimal_spec_text.encode()
        ).hexdigest()

        result = spec_evaluator.evaluate(
            temp_draft_path,
            bundle_persist_dir=temp_bundle_dir,
        )
        assert result.bundle.draft_sha256 == expected_sha256

    def test_load_persisted_bundle_returns_equivalent_preview_resources(
        self, temp_draft_path, temp_bundle_dir
    ):
        """Bundle from load() has same preview_resources as bundle from evaluate()."""
        result1 = spec_evaluator.evaluate(
            temp_draft_path,
            bundle_persist_dir=temp_bundle_dir,
        )
        draft_sha256 = result1.bundle.draft_sha256

        bundle_path = temp_bundle_dir / ".eval-bundle.json"
        result2 = spec_evaluator.load_persisted_bundle(
            bundle_path,
            draft_sha256,
            draft_path=temp_draft_path,
        )
        assert result2 is not None
        assert result2.preview_resources == result1.bundle.preview_resources

    def test_load_persisted_bundle_returns_equivalent_preview_adrs(
        self, temp_draft_path, temp_bundle_dir
    ):
        """Bundle from load() has same preview_adrs as bundle from evaluate()."""
        result1 = spec_evaluator.evaluate(
            temp_draft_path,
            bundle_persist_dir=temp_bundle_dir,
        )
        draft_sha256 = result1.bundle.draft_sha256

        bundle_path = temp_bundle_dir / ".eval-bundle.json"
        result2 = spec_evaluator.load_persisted_bundle(
            bundle_path,
            draft_sha256,
            draft_path=temp_draft_path,
        )
        assert result2 is not None
        assert result2.preview_adrs == result1.bundle.preview_adrs

    def test_load_persisted_bundle_returns_equivalent_tier_classifications(
        self, temp_draft_path, temp_bundle_dir
    ):
        """Bundle from load() has same tier classifications as bundle from evaluate()."""
        result1 = spec_evaluator.evaluate(
            temp_draft_path,
            bundle_persist_dir=temp_bundle_dir,
        )
        draft_sha256 = result1.bundle.draft_sha256

        bundle_path = temp_bundle_dir / ".eval-bundle.json"
        result2 = spec_evaluator.load_persisted_bundle(
            bundle_path,
            draft_sha256,
            draft_path=temp_draft_path,
        )
        assert result2 is not None
        assert (
            result2.preview_tier_classifications
            == result1.bundle.preview_tier_classifications
        )


class TestBundleInvalidation:
    """Tests for bundle invalidation on draft changes."""

    def test_refine_changes_draft_invalidates_bundle(
        self, temp_draft_path, temp_bundle_dir, clean_minimal_spec_text
    ):
        """Modified draft with new SHA causes load() to return None."""
        # Evaluate with original draft
        result1 = spec_evaluator.evaluate(
            temp_draft_path,
            bundle_persist_dir=temp_bundle_dir,
        )
        original_sha = result1.bundle.draft_sha256

        # Modify draft
        modified_text = clean_minimal_spec_text + "\n# Extra comment"
        temp_draft_path.write_text(modified_text, encoding="utf-8")
        new_sha = hashlib.sha256(modified_text.encode()).hexdigest()

        # Attempt load with new SHA (old bundle persisted, but SHA mismatch)
        bundle_path = temp_bundle_dir / ".eval-bundle.json"
        result2 = spec_evaluator.load_persisted_bundle(
            bundle_path,
            new_sha,
            draft_path=temp_draft_path,
        )
        assert result2 is None

    def test_load_persisted_bundle_returns_none_when_bundle_file_missing(
        self, temp_draft_path
    ):
        """load() returns None when bundle file does not exist."""
        nonexistent_bundle = temp_draft_path.parent / "state" / ".eval-bundle.json"
        result = spec_evaluator.load_persisted_bundle(
            nonexistent_bundle,
            "anysha256",
            draft_path=temp_draft_path,
        )
        assert result is None


class TestSidecarWriting:
    """Tests for sidecar writing after bundle evaluation."""

    def test_sidecar_landed_at_spec_eval_json_path(
        self, temp_draft_path, temp_bundle_dir
    ):
        """Sidecar file exists at <spec>.eval.json after write_sidecar()."""
        result = spec_evaluator.evaluate(
            temp_draft_path,
            bundle_persist_dir=temp_bundle_dir,
        )

        # Simulate /vision §6.7: write sidecar
        sidecar_path = eval_metadata.write_sidecar(
            temp_draft_path,
            evaluator_version=result.sidecar_payload["evaluator_version"],
            tiers_run=result.sidecar_payload["tiers_run"],
            findings=result.findings,
            dismissals=result.sidecar_payload["dismissals"],
            config_path=None,
            config_hash=None,
            deepseek_model_version=None,
            policy_hash="test_hash",
        )
        expected_path = temp_draft_path.parent / (temp_draft_path.name + ".eval.json")
        assert sidecar_path.exists()
        assert sidecar_path == expected_path

    def test_sidecar_payload_round_trips_evaluator_version(
        self, temp_draft_path, temp_bundle_dir
    ):
        """Evaluator version in payload matches EVALUATOR_VERSION constant."""
        result = spec_evaluator.evaluate(
            temp_draft_path,
            bundle_persist_dir=temp_bundle_dir,
        )
        assert (
            result.sidecar_payload["evaluator_version"]
            == spec_evaluator.EVALUATOR_VERSION
        )

    def test_sidecar_payload_round_trips_tiers_run(
        self, temp_draft_path, temp_bundle_dir
    ):
        """Tiers_run in payload contains [1, 2] (no config means no Tier 3)."""
        result = spec_evaluator.evaluate(
            temp_draft_path,
            bundle_persist_dir=temp_bundle_dir,
        )
        assert result.sidecar_payload["tiers_run"] == [1, 2]

    def test_sidecar_payload_round_trips_policy_hash(
        self, temp_draft_path, temp_bundle_dir
    ):
        """Sidecar payload includes dismissals list from bundle evaluation."""
        result = spec_evaluator.evaluate(
            temp_draft_path,
            bundle_persist_dir=temp_bundle_dir,
        )
        # Write sidecar with computed policy hash
        policy_hash = eval_metadata.compute_policy_hash({}, {})
        sidecar_path = eval_metadata.write_sidecar(
            temp_draft_path,
            evaluator_version=result.sidecar_payload["evaluator_version"],
            tiers_run=result.sidecar_payload["tiers_run"],
            findings=result.findings,
            dismissals=result.sidecar_payload["dismissals"],
            config_path=None,
            config_hash=None,
            deepseek_model_version=None,
            policy_hash=policy_hash,
        )
        # Verify sidecar contains policy_hash
        sidecar_data = json.loads(sidecar_path.read_text(encoding="utf-8"))
        assert sidecar_data["policy_hash"] == policy_hash


class TestBundleClearing:
    """Tests for bundle file clearing."""

    def test_clear_bundle_removes_persisted_file(
        self, temp_draft_path, temp_bundle_dir
    ):
        """clear_bundle() removes the persisted bundle file."""
        spec_evaluator.evaluate(
            temp_draft_path,
            bundle_persist_dir=temp_bundle_dir,
        )
        bundle_path = temp_bundle_dir / ".eval-bundle.json"
        assert bundle_path.exists()

        spec_evaluator.clear_bundle(bundle_path)
        assert not bundle_path.exists()

    def test_clear_bundle_idempotent_on_missing_file(
        self, temp_draft_path, temp_bundle_dir
    ):
        """clear_bundle() is idempotent (no-op on missing file)."""
        bundle_path = temp_bundle_dir / ".eval-bundle.json"
        # Call clear on non-existent bundle (should not raise)
        spec_evaluator.clear_bundle(bundle_path)
        assert not bundle_path.exists()


class TestFullHandoffPipeline:
    """End-to-end test of the complete handoff flow."""

    def test_full_handoff_pipeline_end_to_end(
        self, clean_minimal_spec_text, temp_draft_path, temp_bundle_dir
    ):
        """Full §6.4→§6.5→§6.6→§6.7→clear pipeline."""
        # Step 3: evaluate() → bundle persisted
        result = spec_evaluator.evaluate(
            temp_draft_path,
            bundle_persist_dir=temp_bundle_dir,
        )
        bundle_path = temp_bundle_dir / ".eval-bundle.json"
        assert bundle_path.exists(), "Bundle not persisted after evaluate()"

        # Step 5: compute draft SHA-256
        draft_sha256 = hashlib.sha256(
            clean_minimal_spec_text.encode()
        ).hexdigest()

        # Step 6: load_persisted_bundle() → should succeed
        loaded_bundle = spec_evaluator.load_persisted_bundle(
            bundle_path,
            draft_sha256,
            draft_path=temp_draft_path,
        )
        assert loaded_bundle is not None, "load_persisted_bundle() returned None"
        assert (
            loaded_bundle.preview_adrs == result.bundle.preview_adrs
        ), "Loaded bundle ADRs do not match"

        # Step 8: write_sidecar() with result.sidecar_payload
        policy_hash = eval_metadata.compute_policy_hash({}, {})
        sidecar_path = eval_metadata.write_sidecar(
            temp_draft_path,
            evaluator_version=result.sidecar_payload["evaluator_version"],
            tiers_run=result.sidecar_payload["tiers_run"],
            findings=result.findings,
            dismissals=result.sidecar_payload["dismissals"],
            config_path=None,
            config_hash=None,
            deepseek_model_version=None,
            policy_hash=policy_hash,
        )
        assert sidecar_path.exists(), "Sidecar not written"

        # Step 10: clear_bundle()
        spec_evaluator.clear_bundle(bundle_path)
        assert not bundle_path.exists(), "Bundle not cleared"

        # Verify final state: sidecar present, bundle gone
        assert sidecar_path.exists(), "Sidecar should still exist after clear"
        assert not bundle_path.exists(), "Bundle should be gone after clear"
