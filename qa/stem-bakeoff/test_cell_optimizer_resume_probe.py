"""Synthetic orchestration failures must stop before any real input or update."""

import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

import numpy as np

from cell_optimizer_checkpoint import file_sha
from cell_optimizer_resume_worker import (BUNDLE_SHA256, CONTRACT, FEATURE_SHA256,
    MODES, code_pins, job_boundary, run_worker, write_json)
from probe_cell_optimizer_resume import committed_code, compare_mode, execute, reverify_inputs


class ResumeProbeTests(unittest.TestCase):
    def plan(self, path, *, stale=False):
        pins = code_pins()
        if stale: pins["cell_resumable_training.py"] = "0"*64
        write_json(path, {"schema": "hepta.optimizer-continuation-run.v1", "contract": CONTRACT,
            "bundle_manifest_sha256": BUNDLE_SHA256, "feature_identity": FEATURE_SHA256,
            "source_code_sha256": pins, "owners": {mode: {} for mode in MODES},
            "bundle": "/synthetic-plan-never-open-original-inputs"})
        return file_sha(path)

    def test_missing_predecessor_or_unplanned_cursor_fail_before_input(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            digest = self.plan(root/"plan.json")
            for target in (4, 20):
                output = root/str(target)
                with mock.patch("cell_optimizer_resume_worker.make_owner") as prepare:
                    with self.assertRaises(ValueError):
                        run_worker(root/"plan.json", digest, output, "linear", "segment", target)
                    prepare.assert_not_called()
                failed = json.loads((output/"failed.json").read_bytes())
                self.assertEqual(failed["actual_optimizer_updates"], 0)
                self.assertFalse(failed["partial_optimizer_work_unknown"])

    def test_stale_execution_code_fails_before_input(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            digest = self.plan(root/"plan.json", stale=True)
            with mock.patch("cell_optimizer_resume_worker.make_owner") as prepare:
                with self.assertRaisesRegex(ValueError, "implementation differs"):
                    run_worker(root/"plan.json", digest, root/"attempt", "linear", "segment", 3)
                prepare.assert_not_called()

    def test_failed_subprocess_keeps_complete_outer_receipt(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root/"worker-receipts").mkdir()
            with self.assertRaises(RuntimeError):
                execute(root, "synthetic-failure", [sys.executable, "-c", "raise SystemExit(9)"])
            receipt = json.loads((root/"worker-receipts/synthetic-failure.json").read_bytes())
            self.assertEqual(receipt["exit_code"], 9)
            self.assertTrue(receipt["fresh_process"])
            self.assertGreater(receipt["wall_ns"], 0)
            self.assertGreaterEqual(receipt["child_cpu_ns"], 0)

    def test_source_commit_mismatch_is_rejected(self):
        with mock.patch("probe_cell_optimizer_resume.subprocess.check_output", return_value=b"different frozen file"):
            with self.assertRaisesRegex(ValueError, "differs from frozen commit"):
                committed_code("0"*40, code_pins())
        with self.assertRaises(ValueError): job_boundary("uninterrupted", 60, "checkpoint", "a"*64)
        with self.assertRaises(ValueError): job_boundary("verify", 59, "checkpoint", "a"*64)

    def test_signed_zero_is_not_bitwise_equality(self):
        left, right = {"p_W": np.array([0.0])}, {"p_W": np.array([-0.0])}
        self.assertTrue(np.array_equal(left["p_W"], right["p_W"]))
        owners = [mock.Mock(snapshot=mock.Mock(return_value=({}, arrays))) for arrays in (left, right)]
        binding = {"plan_sha256": "a"*64, "input_sha256": "b"*64}
        reports = {name: {"checkpoint": {"manifest_sha256": "c"*64}}
                   for name in ("linear-uninterrupted", "linear-segment-60")}
        with mock.patch("probe_cell_optimizer_resume.load_optimizer_checkpoint", side_effect=owners):
            with self.assertRaisesRegex(ValueError, "differ bitwise"):
                compare_mode(Path("/synthetic-unused"), "linear", {"owners": {"linear": binding}}, reports)

    def test_final_plan_and_bundle_reverification(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/"plan.json"
            path.write_bytes(b"frozen synthetic execution plan")
            digest = file_sha(path)
            with mock.patch("probe_cell_optimizer_resume.verify_bundle") as verify:
                reverify_inputs("synthetic-bundle", path, digest)
                verify.assert_called_once_with("synthetic-bundle", expected_manifest_sha256=BUNDLE_SHA256)
                path.write_bytes(b"altered execution plan")
                with self.assertRaisesRegex(ValueError, "execution plan changed"):
                    reverify_inputs("synthetic-bundle", path, digest)
                self.assertEqual(verify.call_count, 1)


if __name__ == "__main__":
    unittest.main()
