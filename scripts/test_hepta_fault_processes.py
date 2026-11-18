"""Actual child admission, partial launch failure and independent start audit."""

import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from audit_cell_effect_faults import audit
from hepta_cells.fault_processes import run_fault_workers
from hepta_cells.lifecycle import CellOwner
from hepta_cells.receiver_handoff import ReceiverLedger
from qualify_cell_effect_faults import objects, exercise_cold_recovery, run


SCRIPT = Path(__file__).with_name("qualify_cell_effect_faults.py")


class FaultProcessTests(unittest.TestCase):
    def setUp(self):
        if os.environ.get("HEPTA_FAULT_TEST_ARTIFACT_ROOT"):
            self.root = (
                Path(os.environ["HEPTA_FAULT_TEST_ARTIFACT_ROOT"])
                / self._testMethodName
            )
            self.root.mkdir(parents=True, exist_ok=False)
        else:
            self.directory = tempfile.TemporaryDirectory()
            self.addCleanup(self.directory.cleanup)
            self.root = Path(self.directory.name)
        ReceiverLedger.create(self.root / "receiver.sqlite", "7" * 64).close()
        partition, ledger, tool = objects(self.root)
        ledger.provision(tool.port.lease, tool.identity.digest, tool.tool_digest)
        owner = CellOwner(self.root / "owner.sqlite")
        owner.create(partition, tool)
        owner.close()
        ledger.close()

    def test_all_admitted_owners_contend_after_common_release(self):
        result = run_fault_workers(
            self.root, SCRIPT, "concurrent_writers", expected_workers=4
        )
        processes, admission = result["processes"], result["admission"]
        self.assertEqual((len(processes), admission["launched_workers"]), (4, 4))
        self.assertIsNone(admission["startup_error"])
        self.assertTrue(admission["released"])
        self.assertTrue(
            all(p["exit"] in (0, 20) and not p["timed_out"] for p in processes)
        )
        self.assertTrue(any(p["exit"] == 0 for p in processes))
        pids = [p["pid"] for p in processes]
        start = json.loads((self.root / "START.json").read_text())
        self.assertEqual(start["pids"], pids)
        for pid, ready in zip(pids, admission["ready"]):
            self.assertEqual(
                ready, json.loads((self.root / f"READY-{pid}.json").read_text())
            )
            self.assertLessEqual(ready["ready_ns"], start["released_ns"])
        self.assertTrue(
            exercise_cold_recovery(self.root, "concurrent_writers")["passed"]
        )

    def test_partial_launch_failure_reaps_every_started_child_without_dispatch(self):
        children, actual = [], subprocess.Popen

        def fail_second(*args, **kwargs):
            if children:
                raise OSError("injected launch refusal after first actual child")
            child = actual(*args, **kwargs)
            children.append(child)
            return child

        with patch(
            "hepta_cells.fault_processes.subprocess.Popen", side_effect=fail_second
        ):
            result = run_fault_workers(
                self.root, SCRIPT, "concurrent_writers", expected_workers=4
            )
        self.assertEqual(result["admission"]["launched_workers"], 1)
        self.assertIn("injected launch refusal", result["admission"]["startup_error"])
        self.assertFalse(result["admission"]["released"])
        self.assertFalse((self.root / "START.json").exists())
        self.assertTrue(all(child.poll() is not None for child in children))
        ledger = ReceiverLedger(self.root / "receiver.sqlite", "7" * 64)
        try:
            self.assertEqual(
                ledger.db.execute("SELECT count(*) FROM effects").fetchone()[0], 0
            )
        finally:
            ledger.close()

    def test_failed_store_admission_never_releases_other_writers(self):
        # An actual child failure before READY must not look like successful contention.
        broken = self.root / "bad-worker.py"
        broken.write_text("raise SystemExit(29)\n")
        result = run_fault_workers(
            self.root, broken, "concurrent_writers", expected_workers=4
        )
        self.assertEqual(result["admission"]["launched_workers"], 1)
        self.assertIsNotNone(result["admission"]["startup_error"])
        self.assertFalse(result["admission"]["released"])
        self.assertFalse((self.root / "START.json").exists())
        self.assertTrue(all(p["exit"] is not None for p in result["processes"]))

    def test_incomplete_start_is_archived_and_cannot_pass_independent_audit(self):
        actual, children = subprocess.Popen, []

        def fail_eighth(*args, **kwargs):
            if "--worker" not in args[0]:
                return actual(*args, **kwargs)
            if len(children) == 7:
                raise OSError("injected second concurrent launch failure")
            child = actual(*args, **kwargs)
            children.append(child)
            return child

        output = self.root / "incomplete-campaign"
        with patch(
            "hepta_cells.fault_processes.subprocess.Popen", side_effect=fail_eighth
        ):
            self.assertEqual(run(output), 1)
        result = json.loads((output / "RESULT.json").read_text())
        self.assertEqual(result["case_count"], 7)
        self.assertFalse(result["passed"])
        self.assertTrue(all(row["passed"] for row in result["results"][:-1]))
        self.assertFalse(result["results"][-1]["startup_complete"])
        self.assertTrue((output / "concurrent_writers/ORIGINALS.json").exists())
        self.assertTrue(all(child.poll() is not None for child in children))
        plan = json.loads((output / "PLAN.json").read_text())
        with self.assertRaisesRegex(ValueError, "incomplete worker admission"):
            audit(output, plan["source_git_head"], allow_working_tree=True)

    def test_independent_audit_rejects_dispatch_before_last_ready(self):
        output = self.root / "audited-campaign"
        self.assertEqual(run(output), 0)
        head = json.loads((output / "PLAN.json").read_text())["source_git_head"]
        self.assertTrue(audit(output, head, allow_working_tree=True)["passed"])
        process_path = output / "concurrent_writers/PROCESSES.json"
        process_raw = process_path.read_text()
        process_record = json.loads(process_raw)
        process_record["processes"][0]["timed_out"] = None
        process_path.write_text(json.dumps(process_record))
        with self.assertRaisesRegex(
            ValueError, "worker timeout or missing observation"
        ):
            audit(output, head, allow_working_tree=True)
        process_path.write_text(process_raw)
        start_path = output / "concurrent_writers/START.json"
        start = json.loads(start_path.read_text())
        start["released_ns"] = 0
        start_path.write_text(json.dumps(start))
        with self.assertRaisesRegex(ValueError, "dispatch preceded worker admission"):
            audit(output, head, allow_working_tree=True)


if __name__ == "__main__":
    unittest.main()
