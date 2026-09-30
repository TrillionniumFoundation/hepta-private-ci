#!/usr/bin/env python3
"""Fresh-interpreter regressions for the CLI/import attestation identity.

These tests exercise initialization, not product execution, and cannot issue a
successful qualification receipt. In particular, --help does not run Rust.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import os
import pathlib
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

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

    def test_failed_matrix_handoff_retains_a_verified_diagnostic_receipt(self):
        # Exercise the same always-run handoff used after a qualification
        # command fails. The retained transcript must verify against the frozen
        # inputs, but changing only the receipt label to success must fail.
        scripts = ROOT / "scripts"
        sys.path.insert(0, str(scripts))
        try:
            import memory_federation_execution_guard as guard
            import memory_federation_execution_receipt as execution
            import memory_federation_full_attestation as full

            candidate = guard._candidate()
            command = "exit 23"
            with tempfile.TemporaryDirectory(
                prefix="memory-federation-failure-attestation-"
            ) as directory:
                root = pathlib.Path(directory)
                execution_directory = root / execution.DIRECTORY
                execution_directory.mkdir()
                with (
                    mock.patch.object(full.base, "COMMANDS", (command,)),
                    mock.patch.object(
                        full.base,
                        "_toolchain",
                        return_value={
                            "rustc": "rustc-test",
                            "cargo": "cargo-test",
                            "python": "python-test",
                            "runnerOs": "",
                            "runnerArch": "",
                            "runnerName": "",
                        },
                    ),
                    mock.patch.dict(
                        os.environ,
                        {"RUNNER_TEMP": str(root), "GITHUB_ACTIONS": "false"},
                    ),
                ):
                    inputs = guard._snapshot(candidate["sha"], candidate["tree"])
                    entry = execution.command_record(
                        0, command, command, ROOT, execution_directory
                    )
                    self.assertEqual(entry["exitCode"], 23)
                    transcript = {
                        "schema": execution.SCHEMA,
                        "candidate": candidate,
                        "inputs": inputs,
                        "finalInputs": copy.deepcopy(inputs),
                        "commandManifestSha256": hashlib.sha256(
                            execution.canonical([command])
                        ).hexdigest(),
                        "commands": [entry],
                        "conclusion": "failure",
                        "github": {},
                    }
                    (execution_directory / "execution.json").write_bytes(
                        execution.canonical(transcript)
                    )

                    output = root / "diagnostic-attestation"
                    full.emit(
                        argparse.Namespace(
                            output=str(output),
                            lane="source-head",
                            conclusion="failure",
                            source_sha=candidate["sha"],
                            tested_sha=candidate["sha"],
                            tested_tree=candidate["tree"],
                            base_sha=None,
                            merge_sha=None,
                            merge_tree=None,
                        )
                    )
                    receipt = output / "attestation.json"
                    document = full.read_json(receipt)
                    verified = full.verify(receipt, document)
                    retained = output / verified["evidence"]["commandExecution"]
                    self.assertEqual(
                        execution.strict_json(retained)["conclusion"], "failure"
                    )

                    promoted = copy.deepcopy(document)
                    promoted["conclusion"] = "success"
                    with self.assertRaises(full.base.AttestationError):
                        full.verify(receipt, promoted)
        finally:
            if sys.path and sys.path[0] == str(scripts):
                sys.path.pop(0)


if __name__ == "__main__":
    unittest.main()
