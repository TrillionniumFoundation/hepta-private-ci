"""Reject ambiguous or changed native artifacts without guessing producers."""

import copy
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from scripts import hepta_ci_native_binaries as native


class NativeBindingTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.target = self.root / "target"
        self.target.mkdir()
        for name in ("worker-host", "test-elf"):
            path = self.target / name
            path.write_bytes(b"#!/bin/sh\nexit 0\n")
            path.chmod(0o755)
        self.document = {
            "rust-build-meta": {
                "target-directory": str(self.target),
                "non-test-binaries": {
                    "producer": [
                        {
                            "kind": "bin-exe",
                            "name": "worker-host",
                            "path": "worker-host",
                        }
                    ]
                },
            },
            "rust-binaries": {
                "consumer::test": {"binary-path": str(self.target / "test-elf")}
            },
        }

    def test_exact_aliases_survive_the_original_shell(self):
        bound = native.bind_inventory(self.document, {})
        expected = {
            "CARGO_BIN_EXE_worker-host": str(self.target / "worker-host"),
            "CARGO_BIN_EXE_worker_host": str(self.target / "worker-host"),
        }
        self.assertEqual(bound["environment"], expected)
        value = subprocess.check_output(
            ["sh", "-c", 'printf %s "$CARGO_BIN_EXE_worker_host"'],
            env=os.environ | expected,
            text=True,
        )
        self.assertEqual(value, expected["CARGO_BIN_EXE_worker_host"])
        self.assertEqual(native.bind_inventory(self.document, expected), bound)

    def test_duplicate_producers_and_aliases_reject_even_same_file(self):
        for name in ("worker-host", "worker_host"):
            document = copy.deepcopy(self.document)
            document["rust-build-meta"]["non-test-binaries"]["another-producer"] = [
                {"kind": "bin-exe", "name": name, "path": "worker-host"}
            ]
            with (
                self.subTest(name=name),
                self.assertRaisesRegex(ValueError, "multiple native producers"),
            ):
                native.bind_inventory(document, {})

    def test_external_bindings_missing_paths_and_symlinks_reject(self):
        for key in (
            "CARGO_BIN_EXE_worker-host",
            "CARGO_BIN_EXE_worker_host",
            "NEXTEST_BIN_EXE_worker-host",
            "CARGO_BIN_EXE_unbuilt",
        ):
            with self.subTest(key=key), self.assertRaises(ValueError):
                native.bind_inventory(self.document, {key: "/unrelated"})
        binary = self.document["rust-build-meta"]["non-test-binaries"]["producer"][0]
        (self.target / "alias").symlink_to(self.target / "worker-host")
        for path in (
            "alias",
            "absent",
            "../target/worker-host",
            str(self.target / "worker-host"),
        ):
            binary["path"] = path
            with self.subTest(path=path), self.assertRaises((OSError, ValueError)):
                native.bind_inventory(self.document, {})

    def test_library_only_inventory_and_both_binary_mutations(self):
        document = copy.deepcopy(self.document)
        document["rust-build-meta"]["non-test-binaries"] = {}
        self.assertEqual(native.bind_inventory(document, {})["environment"], {})
        for name in ("worker-host", "test-elf"):
            bound = native.bind_inventory(self.document, {})
            (self.target / name).write_bytes(b"#!/bin/sh\nexit 1\n")
            with (
                self.subTest(name=name),
                self.assertRaisesRegex(ValueError, "changed after inventory"),
            ):
                native.verify_files(bound)

    def test_run_preserves_argv_empty_mapping_failure_and_post_run_mutation(self):
        command = ["just", "test", "--locked", "-p", "consumer"]
        for outcome in (0, 100, "changed", "inventory"):
            calls = []
            output = self.root / f"{outcome}.json"
            document = copy.deepcopy(self.document)
            document["rust-build-meta"]["non-test-binaries"] = {}

            def execute(root, tested, argv, record, environment):
                calls.append(argv)
                if len(calls) == 1:
                    Path(argv[2]).write_text(json.dumps(document))
                    return 0
                if outcome == "changed":
                    (self.target / "test-elf").write_bytes(b"replaced")
                    return 0
                if outcome == "inventory":
                    Path(str(output) + ".native.json").write_text("{}")
                    return 0
                return outcome

            with (
                patch.object(native, "stage", side_effect=execute),
                patch.dict(os.environ, {}, clear=True),
            ):
                code = native.run_planned_tests(
                    self.root / "checkout", command, "a" * 40, output
                )
            self.assertEqual(
                calls,
                [
                    [
                        "just",
                        "test-planned-binaries",
                        str(output) + ".native.json",
                        *command[2:],
                    ],
                    command,
                ],
            )
            self.assertEqual(code, 2 if isinstance(outcome, str) else outcome)
            state = json.loads(Path(str(output) + ".bindings.json").read_text())
            self.assertEqual(state["status"], "passed" if outcome == 0 else "failed")


if __name__ == "__main__":
    unittest.main()
