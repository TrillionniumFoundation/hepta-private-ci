"""Focused qualification of the provenance gate. Fixtures are not model evidence."""
from __future__ import annotations

import importlib.util
import json
import os
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
                                             "arms": {k: self.files[k] for k in m.ARMS["E1"]},
                                             "commands": {k: [sys.executable, "-c", "pass"] for k in m.ARMS["E1"]}}))
        self.plan = self.root / "plan.json"
        m.freeze(self.repo, self.manifest, "E1", self.plan)

    def plan_with_commands(self, filename: str, overrides: dict[str, list[str]], repetitions: int = 1) -> Path:
        manifest = self.root / f"{filename}.manifest.json"
        spec = json.loads(self.manifest.read_text())
        spec["commands"].update(overrides)
        manifest.write_text(json.dumps(spec))
        plan = self.root / f"{filename}.plan.json"
        m.freeze(self.repo, manifest, "E1", plan, repetitions=repetitions)
        return plan

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
        m.run(self.repo, self.plan, "multi_head", rec, 5.0, [sys.executable, "-c", "pass"])
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
        fail_cmd = [sys.executable, "-c", "raise SystemExit(3)"]
        fail_plan = self.plan_with_commands("failure", {"fixed_moe": fail_cmd})
        with self.assertRaisesRegex(m.EvidenceError, "run failed"):
            m.run(self.repo, fail_plan, "fixed_moe", rec, 5, fail_cmd)
        with self.assertRaisesRegex(m.EvidenceError, "failed model execution"):
            m.audit(fail_plan, self.repo, [rec])
        receipt = json.loads(rec.read_text())
        receipt["status"] = "completed"
        receipt["exit_code"] = 0
        receipt["qualification"] = "accepted"
        rec.write_text(json.dumps(receipt))
        with self.assertRaisesRegex(m.EvidenceError, "receipt digest mismatch"):
            m.audit(fail_plan, self.repo, [rec])
        receipt.pop("receipt_digest")
        receipt["receipt_digest"] = m.digest(receipt)
        rec.write_text(json.dumps(receipt))
        with self.assertRaisesRegex(m.EvidenceError, "invents qualification"):
            m.audit(fail_plan, self.repo, [rec])

    def test_raw_log_drift_rejected(self) -> None:
        rec = self.root / "raw.json"
        m.run(self.repo, self.plan, "multi_head", rec, 5, [sys.executable, "-c", "pass"])
        rec.with_suffix(".json.stdout").write_text("tampered")
        with self.assertRaisesRegex(m.EvidenceError, "raw log .* drift"):
            m.audit(self.plan, self.repo, [rec])

    def test_output_limit_kills_process_group_and_stays_failed(self) -> None:
        before = m.MAX_LOG_BYTES
        try:
            m.MAX_LOG_BYTES = 4096
            rec = self.root / "large.json"
            cmd = [sys.executable, "-c", "import sys,time; sys.stdout.write('X'*100000); sys.stdout.flush(); time.sleep(1)"]
            plan = self.plan_with_commands("huge", {"multi_head": cmd})
            with self.assertRaisesRegex(m.EvidenceError, "output_limit"):
                m.run(self.repo, plan, "multi_head", rec, 5, cmd)
            self.assertEqual(json.loads(rec.read_text())["status"], "output_limit")
        finally:
            m.MAX_LOG_BYTES = before

    def test_frozen_repetitions_require_all_unique_arm_trials(self) -> None:
        plan = self.root / "repeated-plan.json"
        m.freeze(self.repo, self.manifest, "E1", plan, repetitions=2)
        self.assertEqual(m.verify_plan(plan, self.repo)["repetitions"], 2)
        receipts = []
        for arm in m.ARMS["E1"]:
            for trial in range(2):
                path = self.root / f"{arm}-{trial}.json"
                m.run(self.repo, plan, arm, path, 5, [sys.executable, "-c", "pass"], trial=trial)
                receipts.append(path)
        report = m.audit(plan, self.repo, receipts[:-1])
        self.assertFalse(report["execution_matrix_complete"])
        self.assertEqual(report["missing_slots"], [{"arm": "cell_graph", "trial": 1}])
        self.assertTrue(m.audit(plan, self.repo, receipts)["execution_matrix_complete"])
        self.assertIsNone(m.audit(plan, self.repo, receipts)["whole_process_wall_time_only"]["fixed_moe"]["p99"])
        with self.assertRaisesRegex(m.EvidenceError, "duplicate arm/trial receipt"):
            m.audit(plan, self.repo, [receipts[0], receipts[0]])
        with self.assertRaisesRegex(m.EvidenceError, "unregistered trial"):
            m.run(self.repo, plan, "fixed_moe", self.root / "bad-trial.json", 5,
                  [sys.executable, "-c", "pass"], trial=2)
        with self.assertRaisesRegex(m.EvidenceError, "invalid frozen repetitions"):
            m.freeze(self.repo, self.manifest, "E1", self.root / "bad-plan.json", repetitions=0)

    def test_per_arm_command_drift_rejected_at_audit(self) -> None:
        plan = self.root / "commands-plan.json"
        m.freeze(self.repo, self.manifest, "E1", plan, repetitions=2)
        first = self.root / "cmd-0.json"
        second = self.root / "cmd-1.json"
        m.run(self.repo, plan, "fixed_moe", first, 5, [sys.executable, "-c", "pass"], trial=0)
        with self.assertRaisesRegex(m.EvidenceError, "attempted unfrozen command"):
            m.run(self.repo, plan, "fixed_moe", second, 5, [sys.executable, "-c", "print(1)"], trial=1)

    def test_modified_executable_rejected_even_after_successful_exit(self) -> None:
        executable = self.root / "model-runner.sh"
        executable.write_text("#!/bin/sh\nexit 0\n")
        executable.chmod(0o700)
        rec = self.root / "local-bin.json"
        plan = self.plan_with_commands("executable", {"multi_head": [str(executable)]})
        m.run(self.repo, plan, "multi_head", rec, 5, [str(executable)])
        executable.write_text("#!/bin/sh\nexit 1\n")
        with self.assertRaisesRegex(m.EvidenceError, "artifact byte drift"):
            m.audit(plan, self.repo, [rec])

    @unittest.skipUnless(sys.platform.startswith("linux") and Path("/proc").is_dir(), "Linux procfs")
    def test_sampled_process_group_rss_is_lower_bound_only(self) -> None:
        rec = self.root / "sampled.json"
        command = [sys.executable, "-c", "import time; a=bytearray(1000000); time.sleep(.3)"]
        plan = self.plan_with_commands("sampled", {"multi_head": command})
        m.run(self.repo, plan, "multi_head", rec, 5, command, sample_group_rss=True)
        value = json.loads(rec.read_text())
        self.assertGreaterEqual(value["sampled_process_group_observations"], 1)
        self.assertGreater(value["sampled_process_group_peak_rss_kib"], 0)
        self.assertEqual(value["process_group_rss_scope"], "linux_procfs_sampled_lower_bound")
        self.assertEqual(value["gpu_status"], "not_measured")

    def test_e0_requires_real_files_and_does_not_certify_model_execution(self) -> None:
        no_change = self.artifacts / "no_change"
        no_change.write_bytes(b"fixture candidate bytes (not a real trained model)")
        files = {}
        for key in m.E0_MODEL:
            path = self.artifacts / key
            path.write_bytes(f"not-real-{key}".encode())
            files[key] = str(path)
        spec = json.loads(self.manifest.read_text())
        spec["arms"] = {"no_change": str(no_change)}
        spec["commands"] = {"no_change": [sys.executable, "-c", "pass"]}
        manifest = self.root / "e0-manifest.json"
        manifest.write_text(json.dumps(spec))
        with self.assertRaisesRegex(m.EvidenceError, "missing E0 model"):
            m.freeze(self.repo, manifest, "E0", self.root / "e0-no-manifest.json")
        spec["e0_model"] = files
        manifest.write_text(json.dumps(spec))
        plan = self.root / "e0-complete-plan.json"
        m.freeze(self.repo, manifest, "E0", plan)
        self.assertEqual(set(m.verify_plan(plan, self.repo)["e0_model"]), set(m.E0_MODEL))
        run = self.root / "e0-run.json"
        m.run(self.repo, plan, "no_change", run, 5, [sys.executable, "-c", "pass"])
        result = m.audit(plan, self.repo, [run])
        self.assertTrue(result["execution_matrix_complete"])
        self.assertTrue(result["e0_model_manifest_and_auxiliary_files_frozen"])
        self.assertEqual(result["model_and_dataset_consumption"], "not_independently_verified")
        self.assertFalse(result["cell_split_approval"])
        (self.artifacts / "calibration").write_text("changed")
        with self.assertRaisesRegex(m.EvidenceError, "artifact byte drift"):
            m.verify_plan(plan, self.repo)

    def test_frozen_environment_and_file_argument_drift_rejected(self) -> None:
        script = self.root / "runner.py"
        script.write_text("print('runner')\n")
        plan = self.plan_with_commands("script", {"multi_head": [sys.executable, str(script)]})
        info = m.verify_plan(plan, self.repo)
        self.assertEqual(info["commands"]["multi_head"]["argument_files"]["1"]["sha256"], m.sha256_file(script))
        script.write_text("print('mutated runner')\n")
        with self.assertRaisesRegex(m.EvidenceError, "frozen command drift"):
            m.verify_plan(plan, self.repo)
        script.write_text("print('runner')\n")
        before = os.environ.get("RAYON_NUM_THREADS")
        try:
            os.environ["RAYON_NUM_THREADS"] = "3" if before != "3" else "5"
            with self.assertRaisesRegex(m.EvidenceError, "performance environment drift"):
                m.verify_plan(plan, self.repo)
        finally:
            if before is None:
                os.environ.pop("RAYON_NUM_THREADS", None)
            else:
                os.environ["RAYON_NUM_THREADS"] = before

    def test_timeout_receipt_and_no_success_laundering(self) -> None:
        rec = self.root / "timeout.json"
        command = [sys.executable, "-c", "import time; time.sleep(1)"]
        plan = self.plan_with_commands("timeout", {"cell_graph": command})
        with self.assertRaisesRegex(m.EvidenceError, "timed_out"):
            m.run(self.repo, plan, "cell_graph", rec, .05, command)
        self.assertEqual(json.loads(rec.read_text())["status"], "timed_out")
        with self.assertRaisesRegex(m.EvidenceError, "failed model execution"):
            m.audit(plan, self.repo, [rec])


if __name__ == "__main__":
    unittest.main()
