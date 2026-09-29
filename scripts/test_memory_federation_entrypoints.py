#!/usr/bin/env python3
"""Fresh-interpreter regressions for the CLI/import attestation identity.

These tests exercise initialization, not product execution, and cannot issue a
successful qualification receipt. In particular, --help does not run Rust.
"""
from __future__ import annotations

import pathlib
import subprocess
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
FULL = ROOT / "scripts/memory_federation_full_attestation.py"


class EntrypointTests(unittest.TestCase):
    def child(self, program):
        result = subprocess.run(
            [sys.executable, "-c", program, str(FULL)], cwd=ROOT,
            text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            timeout=30, check=False,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_cli_and_guard_use_one_module_instance(self):
        self.child(r'''
import importlib, pathlib, runpy, sys
path = pathlib.Path(sys.argv[1])
sys.path.insert(0, str(path.parent))
sys.argv = [str(path), "--help"]
try:
    runpy.run_path(str(path), run_name="__main__")
except SystemExit as exc:
    assert exc.code == 0
full = sys.modules.get("memory_federation_full_attestation")
assert full is not None, "CLI did not register its canonical module identity"
assert full.__name__ == "__main__", "CLI was imported twice"
before = (tuple(full.base.QUALIFIED_PATHS), tuple(full.base.COMMANDS), full.base._verify_payload)
guard = importlib.import_module("memory_federation_execution_guard")
assert guard.full is full
assert before == (tuple(full.base.QUALIFIED_PATHS), tuple(full.base.COMMANDS), full.base._verify_payload)
assert full.ORIGINAL_VERIFY is not full.verify
''')

    def test_module_then_guard_preserve_the_same_contract(self):
        self.child(r'''
import importlib, pathlib, sys
sys.path.insert(0, str(pathlib.Path(sys.argv[1]).parent))
full = importlib.import_module("memory_federation_full_attestation")
before = (tuple(full.base.QUALIFIED_PATHS), tuple(full.base.COMMANDS), full.base._verify_payload)
guard = importlib.import_module("memory_federation_execution_guard")
assert guard.full is full
assert before == (tuple(full.base.QUALIFIED_PATHS), tuple(full.base.COMMANDS), full.base._verify_payload)
''')


if __name__ == "__main__":
    unittest.main()
