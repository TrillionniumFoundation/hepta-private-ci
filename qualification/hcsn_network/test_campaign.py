"""Actual zero-model process failures must not strand surviving owned children."""

import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

from .benchmark_campaign import run_stage


class CampaignTests(unittest.TestCase):
    def test_exec_failure_collects_survivor_and_marks_unstarted_tail(self):
        cpus = sorted(os.sched_getaffinity(0))[:2]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            tasks = [("survivor", [sys.executable, "-c", "import time; time.sleep(.2); print('done')"]),
                     ("missing", ["/hcsn-nonexistent-executable-for-failure-control"]),
                     ("unstarted", [sys.executable, "-c", "raise RuntimeError('must not run')"])]
            result = run_stage(tasks, root, {"child_deadline_seconds": 5}, cpus)
            by_name = {r["directory"]: r for r in result}
            self.assertEqual(len(result), 3)
            self.assertEqual(by_name["survivor"]["exit_code"], 0)
            self.assertGreater(by_name["survivor"]["wall_seconds"], .15)
            self.assertEqual(by_name["missing"]["status"], "NOT_STARTED")
            self.assertEqual(by_name["unstarted"]["model_calls"], 0)
            self.assertTrue((root/"survivor"/"COST.json").exists())

    def test_resource_rejection_drains_already_running_child(self):
        cpus = sorted(os.sched_getaffinity(0))[:2]
        observations = [{"MemAvailable": 4*1024**3}, {"MemAvailable": 1}]
        with tempfile.TemporaryDirectory() as directory, patch(
                "qualification.hcsn_network.benchmark_campaign.resources", side_effect=observations):
            tasks = [("live", [sys.executable, "-c", "import time; time.sleep(.1)"]),
                     ("resource_rejected", [sys.executable, "-c", "raise RuntimeError('must not run')"])]
            result = run_stage(tasks, Path(directory), {"child_deadline_seconds": 5}, cpus)
            self.assertEqual(sum(r["exit_code"] == 0 for r in result), 1)
            cost = json.loads((Path(directory)/"live"/"COST.json").read_text())
            self.assertEqual(cost["exit_code"], 0)
            self.assertGreater(cost["cpu_seconds"], 0)


if __name__ == "__main__":
    unittest.main()
