"""Tests for build_step_table action_segments injection logic."""
import json

import pytest

from bin.llm_judge import build_step_table, _STEP_FIELD_TRUNCATE


# Minimal spec template — steps section only (no §8.1).
def _make_spec(action: str) -> str:
    return f"""\
## 6. Steps

```yaml
- step: 1
  why: do the thing
  action: {action}
  verification: exit 0
```
"""


class TestBuildStepTableSegments:
    def test_chained_action_gets_segments(self):
        spec = _make_spec("pnpm install && pnpm exec tsc")
        entry = build_step_table(spec)["steps"][0]
        assert "action_segments" in entry
        segs = entry["action_segments"]
        assert isinstance(segs, list)
        assert len(segs) == 2
        assert "pnpm install" in segs[0]
        assert "pnpm exec tsc" in segs[1]

    def test_non_chained_action_omits_segments(self):
        spec = _make_spec("pnpm test")
        entry = build_step_table(spec)["steps"][0]
        assert "action_segments" not in entry

    def test_malformed_quoting_omits_segments(self):
        # Unterminated single quote → _segment_action returns None.
        spec = _make_spec("echo 'unterminated")
        entry = build_step_table(spec)["steps"][0]
        assert "action_segments" not in entry

    def test_segments_truncated_individually(self):
        # Build a segment that exceeds _STEP_FIELD_TRUNCATE chars.
        long_cmd = "x" * (_STEP_FIELD_TRUNCATE + 50)
        spec = _make_spec(f"{long_cmd} && short")
        entry = build_step_table(spec)["steps"][0]
        assert "action_segments" in entry
        segs = entry["action_segments"]
        # First segment should be truncated.
        assert "[truncated," in segs[0]
        # Second segment is short — no truncation marker.
        assert "[truncated," not in segs[1]
        assert segs[1].strip() == "short"
