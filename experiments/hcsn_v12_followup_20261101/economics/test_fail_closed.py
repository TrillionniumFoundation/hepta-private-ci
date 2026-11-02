"""Resource qualification refusals; no synthetic hardware-success receipt."""

import copy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from .campaign import cases
from .profile import singleton_verified


ROOT = Path(__file__).resolve().parents[3]
BUNDLE = ROOT / "experiments/hcsn_v12_followup_20261101/model_runtime/export002"


class FailClosedControls(unittest.TestCase):
    def test_duplicate_frozen_model_refuses(self):
        models = json.loads((BUNDLE / "CI_MANIFEST.json").read_text())["models"]
        models[-1] = copy.deepcopy(models[0])
        with self.assertRaises(RuntimeError):
            cases(models)

    def test_extra_kernel_task_cannot_qualify_rss(self):
        before = {"inode": 3, "pids_current": 0, "pids_max": 1, "pids_peak": 0}
        after = {**before, "pids_peak": 2}
        self.assertFalse(singleton_verified(before, after, {}))

    def test_denied_fork_event_cannot_qualify_rss(self):
        before = {"inode": 3, "pids_current": 0, "pids_max": 1, "pids_peak": 0, "pids_events": {"max": 0}}
        after = {**before, "pids_peak": 1, "pids_events": {"max": 1}}
        self.assertFalse(singleton_verified(before, after, {}))

    def test_wrong_head_fails_before_creating_group(self):
        with tempfile.TemporaryDirectory(prefix="hcsn-v12-wrong-head-") as temporary:
            out = Path(temporary) / "run"
            result = subprocess.run([sys.executable, "-m", "experiments.hcsn_v12_followup_20261101.economics.campaign",
                                     "--bundle", str(BUNDLE), "--out", str(out), "--expected-head", "0" * 40],
                                    cwd=ROOT, capture_output=True, text=True, timeout=10)
            report = json.loads((out / "CAMPAIGN.json").read_text())
            profile = json.loads((out / "PARENT_PROFILE.json").read_text())
            self.assertEqual((result.returncode, report["status"], profile["created"]), (1, "FAIL", False))
            self.assertIsNone(report["device_energy_joules"])
            self.assertFalse(report["scientific_adoption_passed"])

    def test_missing_hardware_records_fail_audit(self):
        with tempfile.TemporaryDirectory(prefix="hcsn-v12-empty-audit-") as temporary:
            out = Path(temporary)
            result = subprocess.run([sys.executable, "-m", "experiments.hcsn_v12_followup_20261101.economics.audit",
                                     "--run", str(out)], cwd=ROOT, capture_output=True, text=True, timeout=10)
            report = json.loads((out / "INDEPENDENT_AUDIT.json").read_text())
            self.assertEqual((result.returncode, report["passed"]), (1, False))


if __name__ == "__main__":
    unittest.main(verbosity=2)
