"""Exact review-range and invariant-receipt tests for channel.matrix."""
from __future__ import annotations

import hashlib
import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts/channel_matrix_review_slices.py"
spec = importlib.util.spec_from_file_location("channel_matrix_review_slices_test", SCRIPT)
assert spec and spec.loader
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)


class ReviewSliceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / "checkout"
        self.evidence = Path(self.temp.name) / "evidence"
        self.root.mkdir()
        self.evidence.mkdir()
        self.git("init", "-q")
        self.git("config", "user.name", "fixture")
        self.git("config", "user.email", "fixture@example.test")
        for index in range(1, 8):
            path = self.root / f"slice-{index}.txt"
            path.write_text("base\n", encoding="utf-8")
        self.git("add", ".")
        self.git("commit", "-qm", "base")
        self.base = self.git("rev-parse", "HEAD").strip()
        for index in range(1, 8):
            path = self.root / f"slice-{index}.txt"
            path.write_text(f"candidate-{index}\n", encoding="utf-8")
            self.git("add", str(path.relative_to(self.root)))
            self.git("commit", "-qm", f"slice {index}")
        self.head = self.git("rev-parse", "HEAD").strip()
        self.tree = self.git("rev-parse", "HEAD^{tree}").strip()
        self.registry = Path(self.temp.name) / "review-slices.json"
        self.registry.write_text(
            json.dumps(
                {
                    "schema": module.REGISTRY_SCHEMA,
                    "schemaVersion": 1,
                    "module": "channel.matrix",
                    "historyPolicy": "append_only_review_slices_no_history_rewrite",
                    "rangePolicy": "derive_first_last_touch_from_exact_base_and_head",
                    "slices": [
                        {
                            "id": slice_id,
                            "owner": "owner",
                            "deputy": "deputy",
                            "paths": [f"slice-{index}.txt"],
                            "invariants": [f"invariant_{index}"],
                            "commands": [f"verify slice {index}"],
                        }
                        for index, slice_id in enumerate(
                            module.EXPECTED_SLICE_IDS,
                            start=1,
                        )
                    ],
                },
                indent=2,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
        source = {
            "lane": "source-head",
            "sourceSha": self.head,
            "baseSha": self.base,
            "testedSha": self.head,
            "testedTree": self.tree,
        }
        self.write_json(self.evidence / "source.json", source)
        self.write_json(
            self.evidence / "source-provenance.json",
            {
                "schema": "hepta.channel-matrix-source-provenance.v1",
                "valid": True,
                "checkoutSha": self.head,
                "checkoutTree": self.tree,
                "execution": {"workflowRunId": "run-1", "attemptId": "1"},
            },
        )
        self.command_map = {
            "compile": ["cargo", "check", "--locked"],
            "focused-tests": ["just", "test", "--locked"],
        }
        for label, arguments in self.command_map.items():
            log = self.evidence / f"{label}.log"
            log.write_text("passed\n", encoding="utf-8")
            junit = None
            if label == "focused-tests":
                junit_path = self.evidence / "focused-tests.junit.xml"
                junit_path.write_text("<testsuites/>\n", encoding="utf-8")
                junit = {
                    "path": junit_path.name,
                    "bytes": junit_path.stat().st_size,
                    "sha256": self.digest(junit_path),
                }
            self.write_json(
                self.evidence / f"{label}.command.json",
                {
                    "schema": "hepta.channel-matrix-command.v1",
                    "label": label,
                    "arguments": arguments,
                    "workingDirectory": "codex-rs",
                    "testedSha": self.head,
                    "sourceSnapshotSha256": self.digest(self.evidence / "source.json"),
                    "exitCode": 0,
                    "completed": True,
                    "launchError": None,
                    "junit": junit,
                    "sourceUnchanged": True,
                    "log": {
                        "path": log.name,
                        "bytes": log.stat().st_size,
                        "sha256": self.digest(log),
                        "withinBudget": True,
                    },
                },
            )

    def git(self, *arguments: str) -> str:
        return subprocess.run(
            ["git", *arguments],
            cwd=self.root,
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        ).stdout

    @staticmethod
    def write_json(path: Path, value: object) -> None:
        path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    @staticmethod
    def digest(path: Path) -> str:
        return hashlib.sha256(path.read_bytes()).hexdigest()

    def build(self):
        with mock.patch.object(module, "command_policy", return_value=self.command_map):
            return module.build(self.root, self.evidence, self.registry)

    def test_all_seven_slices_bind_range_invariants_and_one_command_set(self) -> None:
        row = self.build()
        self.assertEqual(row["lane"], "source-head")
        self.assertEqual(len(row["slices"]), 7)
        self.assertTrue(row["allSlicesSourceBound"])
        self.assertTrue(row["allSlicesInvariantPolicyBound"])
        self.assertTrue(row["allSlicesCommandEvidenceBound"])
        self.assertFalse(row["authorityGranted"])
        for item in row["slices"]:
            self.assertEqual(item["commitCount"], 1)
            self.assertEqual(item["changedPathCount"], 1)
            self.assertEqual(item["commandEvidenceSha256"], row["commandSetSha256"])

    def test_untouched_slice_fails_closed(self) -> None:
        registry = json.loads(self.registry.read_text())
        registry["slices"][-1]["paths"] = ["never-touched.txt"]
        self.write_json(self.registry, registry)
        with self.assertRaisesRegex(ValueError, "no exact source delta"):
            self.build()

    def test_failed_command_cannot_back_an_invariant_receipt(self) -> None:
        path = self.evidence / "compile.command.json"
        row = json.loads(path.read_text())
        row["exitCode"] = 1
        self.write_json(path, row)
        with self.assertRaisesRegex(ValueError, "failed command"):
            self.build()

    def test_wrong_checkout_or_execution_provenance_fails_closed(self) -> None:
        source = json.loads((self.evidence / "source.json").read_text())
        source["testedSha"] = self.base
        self.write_json(self.evidence / "source.json", source)
        with self.assertRaisesRegex(ValueError, "checkout differs"):
            self.build()


if __name__ == "__main__":
    unittest.main()
