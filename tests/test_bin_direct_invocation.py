"""v1.1.1 Fix G: direct `python3 path/to/bin/<module>.py` invocation must
not raise `ModuleNotFoundError: No module named 'bin'`.

Pre-v1.1.1 the bin/spectre wrapper was the only blessed entry point;
direct invocation from a cwd outside CLAUDE_PLUGIN_ROOT failed because
sibling `from bin import …` imports could not resolve. Each module
covered here now carries a small sys.path shim that puts the plugin
root on sys.path before the sibling imports run.

This test uses a real subprocess (not importlib) so it observes what
shell users actually see when they run `python3 bin/walker.py` from
some other working directory.
"""

from __future__ import annotations

import pathlib
import subprocess
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent

# Each entry: (module file, args that produce a fast no-op exit).
# We pick args that exercise import-time wiring but don't do real work.
# `--help` is used wherever argparse exposes it; for modules without a
# CLI we use a tiny inline probe via -c importing the module.
_DIRECT_INVOKE_CASES = [
    ("walker.py", ["--help"]),
    ("spec_evaluator.py", ["--help"]),
    ("exemplars.py", ["list"]),
    ("adr.py", ["--help"]),
    ("compact.py", []),  # PostToolUse hook; no-op when no stdin payload
    ("track.py", ["--help"]),
    ("personal_rules.py", ["--help"]),
    ("hydrate.py", []),
    # migrate script DOES write — but tmp_path cwd contains it, so no leak.
    ("migrate_scratchpad_v1_to_v2.py", ["state/scratchpad.json"]),
]


@pytest.mark.parametrize("module_file,args", _DIRECT_INVOKE_CASES)
def test_bin_module_direct_invocation_imports_cleanly(module_file, args, tmp_path):
    """Each affected bin/*.py module must import successfully when invoked
    as `python3 path/to/bin/<module>.py [args]` from a cwd outside the
    plugin root.
    """
    module_path = ROOT / "bin" / module_file
    result = subprocess.run(
        [sys.executable, str(module_path), *args],
        cwd=str(tmp_path),
        capture_output=True,
        text=True,
        timeout=10,
    )
    combined = (result.stdout + "\n" + result.stderr).lower()
    assert "modulenotfounderror" not in combined, (
        f"{module_file} raised ModuleNotFoundError on direct invocation:\n"
        f"stdout: {result.stdout}\nstderr: {result.stderr}"
    )
    assert "no module named 'bin'" not in combined, (
        f"{module_file} cannot resolve 'bin' package on direct invocation:\n"
        f"stdout: {result.stdout}\nstderr: {result.stderr}"
    )
