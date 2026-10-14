"""Focused qualification of the provenance gate. Fixtures are not model evidence."""
from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("hepta_neuron_measure", HERE / "measure.py")
assert spec and spec.loader
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)


class ExperimentEvidenceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.repo = self.root / "repo"
        self.repo.mkdir()
        subprocess.run(["git", "init", "-q", str(self.repo)], check=True)
        subprocess.run(["git", "-C", str(self.repo), "-c", "user.name=Test", "-c", "user.email=test@example.org", "commit", "--allow-empty", "-qm", "source"], check=True)
        self.artifacts = self.root / "artifacts"
        self.artifacts.mkdir()
        self.files = {}
        for field in (*m.SHARED, *m.ARMS["E1"]):
            target = self.artifacts / field
            target.write_bytes(f"independent test fixture for {field}".encode())
            self.files[field] = str(target)
        self.manifest = self.root / "manifest.json"
        self.manifest.write_text(json.dumps({"shared": {k: self.files[k] for k in m.SHARED},
                                             "arms": {k: self.files[k] for k in m.ARMS["E1"]}}))
        self.plan = self.root / "plan.json"
        m.freeze(self.repo, self.manifest, "E1", self.plan)

    def test_source_bytes_and_plan_are_frozen(self) -> None:
        plan = m.verify_plan(self.plan, self.repo)
        self.assertEqual(set(plan["arms"]), set(m.ARMS["E1"]))
        self.assertEqual(plan["qualification"], "not_established")
        self.assertEqual(len(plan["plan_digest"]), 64)
        with self.assertRaisesRegex(m.EvidenceError, "already exists"):
            m.freeze(self.repo, self.manifest, "E1", self.plan)
        blob = self.artifacts / "encoder"
        blob.write_text("mutated fixture")
        with self.assertRaisesRegex(m.EvidenceError, "byte drift"):
            m.verify_plan(self.plan, self.repo)

    def test_plan_edit_and_git_drift_fail_closed(self) -> None:
        original = self.plan.read_text()
        edited = json.loads(original)
        edited["stage"] = "E2"
        self.plan.write_text(json.dumps(edited))
        with self.assertRaisesRegex(m.EvidenceError, "digest mismatch"):
            m.verify_plan(self.plan, self.repo)
        self.plan.write_text(original)
        (self.repo / "tracked.txt").write_text("a")
        subprocess.run(["git", "-C", str(self.repo), "add", "tracked.txt"], check=True)
        with self.assertRaisesRegex(m.EvidenceError, "dirty"):
            m.verify_plan(self.plan, self.repo)

    def test_real_process_observation_and_no_approval(self) -> None:
        rec = self.root / "multi_head.json"
        m.run(self.repo, self.plan, "multi_head", rec, 5.0, [sys.executable, "-c", "print('hello')"])
        value = json.loads(rec.read_text())
        self.assertEqual(value["status"], "completed")
        self.assertGreater(value["elapsed_wall_ns"], 0)
        self.assertGreater(value["child_peak_rss_kib"], 0)
        self.assertEqual(value["outcomes"], "not_independently_observed")
        self.assertIsNone(value["gpu_peak_bytes"])
        result = m.audit(self.plan, self.repo, [rec])
        self.assertEqual(result["missing_arms"], ["cell_graph", "dynamic_moe", "fixed_moe"])
        self.assertFalse(result["cell_split_approval"])
        self.assertEqual(result["fair_budget_and_parameter_comparison"], "not_evaluated")
        all_receipts = [rec]
        for arm in m.ARMS["E1"][1:]:
            next_receipt = self.root / f"{arm}.json"
            m.run(self.repo, self.plan, arm, next_receipt, 5.0, [sys.executable, "-c", "pass"])
            all_receipts.append(next_receipt)
        self.assertTrue(m.audit(self.plan, self.repo, all_receipts)["execution_matrix_complete"])

    def test_unregistered_or_failed_runs_rejected(self) -> None:
        with self.assertRaisesRegex(m.EvidenceError, "unregistered arm"):
            m.run(self.repo, self.plan, "split", self.root / "bad.json", 5, [sys.executable, "-c", "pass"])
        rec = self.root / "failed.json"
        with self.assertRaisesRegex(m.EvidenceError, "run failed"):
            m.run(self.repo, self.plan, "fixed_moe", rec, 5, [sys.executable, "-c", "raise SystemExit(3)"])
        with self.assertRaisesRegex(m.EvidenceError, "failed model execution"):
            m.audit(self.plan, self.repo, [rec])
        receipt = json.loads(rec.read_text())
        receipt["status"] = "completed"
        receipt["exit_code"] = 0
        receipt["qualification"] = "accepted"
        rec.write_text(json.dumps(receipt))
        with self.assertRaisesRegex(m.EvidenceError, "receipt digest mismatch"):
            m.audit(self.plan, self.repo, [rec])
        receipt.pop("receipt_digest")
        receipt["receipt_digest"] = m.digest(receipt)
        rec.write_text(json.dumps(receipt))
        with self.assertRaisesRegex(m.EvidenceError, "invents qualification"):
            m.audit(self.plan, self.repo, [rec])

    def test_timeout_receipt_and_no_success_laundering(self) -> None:
        rec = self.root / "timeout.json"
        with self.assertRaisesRegex(m.EvidenceError, "timed_out"):
            m.run(self.repo, self.plan, "cell_graph", rec, .05, [sys.executable, "-c", "import time; time.sleep(1)"])
        self.assertEqual(json.loads(rec.read_text())["status"], "timed_out")
        with self.assertRaisesRegex(m.EvidenceError, "failed model execution"):
            m.audit(self.plan, self.repo, [rec])


if __name__ == "__main__":
    unittest.main()
