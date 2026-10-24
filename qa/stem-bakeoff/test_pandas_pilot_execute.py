"""Native artifact/overlay/unknown checks on synthetic files only."""

import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import pandas_pilot_execute as executor
from pandas_pilot_execute import copy_records, materialize, paired_label
from pandas_source_pilot import sha


class ExecutionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def file(self, root, name, content):
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
        return {"path": name, "bytes": len(content), "sha256": sha(path)}

    def test_artifact_tampering_and_links_reject_before_copy(self):
        origin, target = self.root / "source", self.root / "copy"
        record = self.file(origin, "native.so", b"original")
        (origin / "native.so").write_bytes(b"modified")
        with self.assertRaisesRegex(ValueError, "changed"):
            copy_records(origin, target, [record])
        (origin / "native.so").unlink()
        (origin / "native.so").symlink_to(self.root / "other")
        with self.assertRaisesRegex(ValueError, "symlink"):
            copy_records(origin, target, [record])
        with self.assertRaisesRegex(ValueError, "unsafe"):
            copy_records(origin, target, [dict(record, path="../outside")])

    def test_candidate_test_overlay_keeps_each_revisions_own_native_artifact(self):
        tests = None
        for role in ("base", "candidate"):
            checkout = self.root / "checkouts" / role
            source = [self.file(checkout, "pandas/code.py", role.encode()),
                      self.file(checkout, "pandas/tests/test_example.py", (role + " test").encode())]
            native = self.file(checkout, "pandas/native.so", (role + " native").encode())
            (self.root / ("source-files-" + role + ".json")).write_text(json.dumps(source))
            (self.root / ("build-complete-" + role + ".json")).write_text(json.dumps({"extension_files": [native]}))
            if role == "candidate":
                tests = [source[1]]
        plan = {"fixed_test_roots": ["pandas/tests"], "fixed_test_files": tests}
        for role in ("base", "candidate"):
            destination = self.root / ("action-" + role)
            materialize(self.root, role, destination, plan)
            self.assertEqual((destination / "pandas/tests/test_example.py").read_bytes(), b"candidate test")
            self.assertEqual((destination / "pandas/native.so").read_bytes(), (role + " native").encode())
            self.assertEqual((destination / "pandas/code.py").read_bytes(), role.encode())

    def test_only_matched_ordinary_calls_receive_a_label(self):
        def result(outcome, status, identifier="test[a]"):
            return {"outcome": outcome, "observation": {"observations": [
                {"id": identifier, "phase": "call", "status": status}]}}
        pair = {"base": result("test_failure", "failed"), "candidate": result("pass", "passed")}
        self.assertEqual(paired_label(pair), 1)
        pair["base"] = result("pass", "passed")
        self.assertEqual(paired_label(pair), 0)
        for value in (result("pass", "skipped"), result("pass", "passed", "different"),
                      result("infrastructure_error", "failed"), {"outcome": "pass", "observation": None}):
            self.assertIsNone(paired_label(dict(pair, candidate=value)))
        self.assertIsNone(paired_label({"base": pair["base"]}))

    def execution_fixture(self):
        plan = {"file_pins": {}, "plain_pytest": True, "actions": [{"key": "synthetic"}],
                "limits": {}, "group_id": "synthetic"}
        (self.root / "execution-plan.json").write_text(json.dumps(plan))
        (self.root / "runtime-complete.json").write_text(json.dumps({"root": str(self.root), "python": "unused"}))
        (self.root / "runtime-files.json").write_text("[]")
        for role in ("base", "candidate"):
            (self.root / ("source-files-" + role + ".json")).write_text("[]")
            (self.root / ("build-complete-" + role + ".json")).write_text('{"extension_files":[]}')

    def test_interruption_preserves_workspace_without_confirmed_cleanup(self):
        self.execution_fixture()
        snapshot = {"source_bytes": 0, "runtime_build_bytes": 0, "free_disk_bytes": 4_000_000_000}
        def prepare(root, role, destination, frozen):
            destination.mkdir(parents=True)
        with patch.object(executor, "resources", return_value=snapshot), patch.object(executor, "materialize", side_effect=prepare), \
                patch.object(executor, "observe", side_effect=KeyboardInterrupt):
            with self.assertRaises(KeyboardInterrupt):
                executor.run(self.root, sha(self.root / "execution-plan.json"))
        self.assertTrue((self.root / "checkouts/action-work/synthetic-base").is_dir())
        failure = json.loads((self.root / "execution-attempt-1-failure.json").read_bytes())
        self.assertEqual(len(failure["unconfirmed_workspaces_preserved"]), 1)
        self.assertTrue(failure["benchmark_outcomes_not_completed_are_unknown"])

    def test_disk_loss_during_copy_stays_unknown_without_a_benchmark(self):
        self.execution_fixture()
        good = {"source_bytes": 0, "runtime_build_bytes": 0, "free_disk_bytes": 4_000_000_000}
        bad = dict(good, free_disk_bytes=900_000_000)
        def prepare(root, role, destination, frozen):
            destination.mkdir(parents=True)
        with patch.object(executor, "resources", side_effect=[good, bad, bad, bad]), \
                patch.object(executor, "materialize", side_effect=prepare), patch.object(executor, "observe") as observe:
            result = executor.run(self.root, sha(self.root / "execution-plan.json"))
        observe.assert_not_called()
        self.assertEqual(result["physical_benchmark_launches"], 0)
        self.assertEqual(result["valid_action_labels"], 0)
        self.assertFalse((self.root / "checkouts/action-work/synthetic-base").exists())


if __name__ == "__main__":
    unittest.main()
