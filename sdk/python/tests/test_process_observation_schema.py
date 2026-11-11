"""Boundary tests for selecting the overlay; synthetic inputs are not protocol evidence."""

import copy
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts._process_observation.schema import (  # noqa: E402
    METHODS,
    select_process_schema,
    validate_generated_module,
)
from scripts._process_observation.source import (  # noqa: E402
    ARCHIVE_PATH,
    COMMANDS,
    load_evidence,
    sha256,
)


def synthetic_notifications():
    definitions = {
        "ProcessExitedNotification": {
            "type": "object",
            "properties": {"exitCode": {"type": "integer"}},
        },
        "ProcessIndeterminateNotification": {
            "type": "object",
            "properties": {"reason": {"$ref": "#/definitions/ProcessIndeterminateReason"}},
        },
        "ProcessIndeterminateReason": {"type": "string", "enum": ["exitObservationLost"]},
        "ProcessOutputDeltaNotification": {
            "type": "object",
            "properties": {"stream": {"$ref": "#/definitions/ProcessOutputStream"}},
        },
        "ProcessOutputStream": {"type": "string", "enum": ["stdout", "stderr"]},
        "Unrelated": {"$ref": "https://invalid.example/unselected.json"},
    }
    return {
        "oneOf": [
            {
                "properties": {
                    "method": {"enum": [method]},
                    "params": {"$ref": f"#/definitions/{name}"},
                }
            }
            for method, name in METHODS.items()
        ],
        "definitions": definitions,
    }


class OverlayClosureTests(unittest.TestCase):
    def test_transitive_closure_keeps_payload_fields_and_omits_unselected_types(self):
        server = synthetic_notifications()
        overlay = select_process_schema(server)
        expected = copy.deepcopy(server["definitions"])
        del expected["Unrelated"]
        self.assertEqual(overlay["definitions"], expected)
        self.assertEqual(
            overlay["anyOf"],
            [{"$ref": f"#/definitions/{name}"} for name in METHODS.values()],
        )

    def test_missing_method_is_rejected_instead_of_using_stable_exports(self):
        server = synthetic_notifications()
        server["oneOf"].pop(1)
        with self.assertRaisesRegex(ValueError, "all process notifications"):
            select_process_schema(server)

    def test_duplicate_method_is_rejected(self):
        server = synthetic_notifications()
        server["oneOf"].append(copy.deepcopy(server["oneOf"][0]))
        with self.assertRaisesRegex(ValueError, "duplicate"):
            select_process_schema(server)

    def test_unresolved_transitive_reference_is_rejected(self):
        server = synthetic_notifications()
        del server["definitions"]["ProcessIndeterminateReason"]
        with self.assertRaisesRegex(ValueError, "unresolved"):
            select_process_schema(server)

    def test_external_reference_is_rejected(self):
        server = synthetic_notifications()
        server["definitions"]["ProcessOutputStream"] = {"$ref": "elsewhere.json#/Stream"}
        with self.assertRaisesRegex(ValueError, "non-local"):
            select_process_schema(server)

    def test_untyped_definition_is_rejected(self):
        server = synthetic_notifications()
        server["definitions"]["ProcessOutputStream"] = {}
        with self.assertRaisesRegex(ValueError, "untyped"):
            select_process_schema(server)

    def test_generated_any_fallback_is_rejected(self):
        code = "\n".join(f"class {name}:\n    pass" for name in METHODS.values())
        with self.assertRaisesRegex(ValueError, "Any fallback"):
            validate_generated_module(code + "\nvalue: Any\n")

    def test_missing_generated_payload_class_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "all process payload classes"):
            validate_generated_module("class ProcessExitedNotification:\n    pass\n")


class EvidenceTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="synthetic-schema-evidence-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.commit = "1" * 40
        self.tree = "2" * 40
        self.server = synthetic_notifications()
        exports = json.dumps(
            {
                "typescript": {},
                "json_schema": {"ServerNotification.json": json.dumps(self.server)},
                "internal_json_schema": {},
            }
        ).encode()
        archive = subprocess.run(
            ["zstd", "--compress", "--stdout"], input=exports, capture_output=True, check=True
        ).stdout
        path = self.root / "generated" / ARCHIVE_PATH
        path.parent.mkdir(parents=True)
        path.write_bytes(archive)
        self.archive_sha = sha256(archive)
        self.write(
            "source.json",
            {
                "source_sha": self.commit,
                "source_tree": self.tree,
                "run_id": "synthetic-test",
                "run_attempt": "1",
            },
        )
        self.write(
            "commands.json",
            [
                {"name": name, "argv": argv, "cwd": "codex-rs", "exit_code": 0}
                for name, argv in COMMANDS
            ],
        )
        self.write(
            "generated-manifest.json",
            {
                "source_sha": self.commit,
                "unexpected_paths": [],
                "diff_check_exit_code": 0,
                "generated_files": [
                    {"path": ARCHIVE_PATH, "sha256": self.archive_sha, "size": len(archive)}
                ],
            },
        )
        (self.root / "tool-versions.txt").write_text("synthetic tool receipts\n")

    def write(self, name, value):
        (self.root / name).write_text(json.dumps(value))

    def read(self, name):
        return json.loads((self.root / name).read_text())

    def load(self):
        return load_evidence(self.root, self.commit, self.tree, self.archive_sha)

    def test_real_zstd_roundtrip_preserves_schema_and_binds_provenance(self):
        server, provenance = self.load()
        self.assertEqual(server, self.server)
        self.assertEqual(provenance["experimental_archive_sha256"], self.archive_sha)
        self.assertEqual(provenance["source_commit"], self.commit)
        self.assertEqual(
            provenance["commands_receipt_sha256"],
            sha256((self.root / "commands.json").read_bytes()),
        )

    def test_source_tree_mismatch_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "different source"):
            load_evidence(self.root, self.commit, "3" * 40, self.archive_sha)

    def test_failed_owning_tests_are_not_generation_qualification(self):
        commands = self.read("commands.json")
        commands[-1]["exit_code"] = 1
        self.write("commands.json", commands)
        with self.assertRaisesRegex(ValueError, "owning-tests"):
            self.load()

    def test_missing_experimental_run_is_rejected(self):
        self.write("commands.json", self.read("commands.json")[:1])
        with self.assertRaisesRegex(ValueError, "incomplete"):
            self.load()

    def test_archive_changed_after_manifest_is_rejected_before_decompression(self):
        path = self.root / "generated" / ARCHIVE_PATH
        path.write_bytes(path.read_bytes() + b"changed")
        with self.assertRaisesRegex(ValueError, "manifest"):
            self.load()

    def test_modified_original_command_is_rejected(self):
        commands = self.read("commands.json")
        commands[-1]["argv"] += ["--filter", "one_test"]
        self.write("commands.json", commands)
        with self.assertRaisesRegex(ValueError, "owning-tests"):
            self.load()


if __name__ == "__main__":
    unittest.main()
