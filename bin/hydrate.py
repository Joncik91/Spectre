#!/usr/bin/env python3
"""SessionStart hook: print the active spec body or a fallback signal."""
import sys
from pathlib import Path

# Allow running both as `python3 bin/hydrate.py` and via shebang.
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from bin import _scratchpad as sp  # noqa: E402
from bin import migrate_scratchpad_v1_to_v2 as _mig  # noqa: E402
from bin import _status  # noqa: E402

SPECS = Path("specs")
ACTIVE = SPECS / ".active"
SCRATCH = Path("state") / "scratchpad.json"


def list_specs() -> str:
    if not SPECS.exists():
        return "(no specs/ directory)"
    files = sorted(p.name for p in SPECS.glob("*.spec.md"))
    return "\n".join(f"  - specs/{f}" for f in files) or "  (no spec files)"


def _state_fields() -> dict:
    data = sp.load(SCRATCH)
    # Handle both v1 (top-level fields) and v2 (tracks.default) formats.
    if data.get("version") == 2:
        track = data.get("tracks", {}).get("default", {})
    else:
        track = data
    return {
        "step": track.get("step"),
        "exit_code": track.get("exit_code"),
        "last_command": track.get("last_command"),
    }


def main() -> int:
    # Auto-migrate v1 scratchpad on SessionStart, regardless of .active state.
    _result = _mig.migrate(SCRATCH)
    if _result == "migrated":
        _status.emit("ok", "hydrate.migrated",
                     migration="scratchpad-v1-to-v2")

    if not ACTIVE.exists():
        _status.emit("info", "hydrate.signal", reason="no-active-spec",
                     hint="run /vision to begin")
        detect_and_propose_patches()
        surface_pending_template_patches()
        return 0

    target = ACTIVE.read_text(encoding="utf-8").strip()
    target_path = Path(target)
    if not target_path.exists():
        _status.emit("warn", "hydrate.stale_active", path=target)
        detect_and_propose_patches()
        surface_pending_template_patches()
        return 0

    body = target_path.read_text(encoding="utf-8")
    fields = _state_fields()
    _status.emit("result", "hydrate.spec_summary",
                 slug=target,
                 step=fields.get("step"),
                 exit_code=fields.get("exit_code"),
                 expand=body)
    detect_and_propose_patches()
    surface_pending_template_patches()
    return 0


def surface_pending_template_patches() -> None:
    """Emit a single-line signal at SessionStart if proposed patches exist."""
    from bin import template_patcher
    proposals = template_patcher.list_proposed_patches()
    _status.emit("info", "hydrate.template_patches_pending", count=len(proposals))


def detect_and_propose_patches() -> None:
    """At SessionStart, scan observations for recurrence patterns and
    write template-patch proposals for any new candidates.

    Idempotent — if a candidate's patch file already exists in proposed/,
    it's not rewritten.
    """
    import re as _re
    from bin import template_patcher
    candidates = template_patcher.detect_patch_candidates()
    existing = {p.stem for p in template_patcher.list_proposed_patches()}
    for c in candidates:
        # Reuse the same filename heuristic as propose_patch.
        fp_short = c["fingerprint"][:8]
        label = (c.get("classifier_label") or "unknown").lower()
        safe = _re.sub(r"[^a-z0-9-]+", "-", label).strip("-")[:40]
        candidate_stem = f"{safe}-{fp_short}"
        if candidate_stem in existing:
            continue
        try:
            template_patcher.propose_patch(c)
        except Exception:
            # Patch proposal must never block hydration.
            pass


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:
        _status.emit("error", "hydrate.error", reason=f"{type(exc).__name__}: {exc}")
        sys.exit(0)
