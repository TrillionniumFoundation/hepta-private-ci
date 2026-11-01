"""Integration checks for actual process accounting and metadata boundaries."""

import json
from pathlib import Path
import sys
import tempfile
import unittest

from .worker_cost import amortized_cpu, run


PROBE = "experiments.hcsn_v8_execution_20261101.economics.process_tree_probe"


class WorkerCostTests(unittest.TestCase):
    def check_tree(self, orphan):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            command = [sys.executable, "-m", PROBE, "--out", str(base / "nodes")]
            if orphan:
                command.append("--orphan")
            receipt = run(command, base / "cost", timeout=10)
            details = json.loads((base / "cost/SUPERVISION.json").read_text())
            nodes = {role: json.loads((base / "nodes" / (role + ".json")).read_text())
                     for role in ("root", "child", "grandchild")}
            self.assertTrue(receipt["task_success"])
            self.assertTrue(receipt["complete_task_cpu_coverage"])
            self.assertEqual(len(details["disjoint_wait4_subtrees"]), 2 if orphan else 1)
            # Each process's own rusage is disjoint. The complete wrapper must
            # include all three, whereas nested child wait4 is not added again.
            own_sum = sum(row["self_cpu_seconds"] for row in nodes.values())
            self.assertGreaterEqual(details["observed_task_subtree_cpu_seconds"] + 1e-5, own_sum)
            self.assertGreaterEqual(receipt["complete_supervisor_wait4"]["cpu_seconds"],
                                    details["observed_task_subtree_cpu_seconds"])
            self.assertEqual(len(details["episode_outputs"]), 1)
            marker = details["episode_outputs"][0]
            self.assertTrue(marker["bounds_valid"])
            self.assertLessEqual(marker["source_to_flush_seconds"], marker["source_to_receive_upper_seconds"])
            self.assertLess(marker["source_to_flush_seconds"], receipt["cold_supervisor_to_exit_seconds"])
            self.assertFalse(details["memory"]["continuous_peak_proved"])
            self.assertIsNone(details["energy"]["joules"])
            with self.assertRaises(FileExistsError):
                run(command, base / "cost")

    def test_normal_waited_grandchild_cpu_is_counted_once(self):
        self.check_tree(False)

    def test_orphan_is_adopted_and_counted(self):
        self.check_tree(True)

    def test_timeout_preserves_nonzero_cost_and_failure(self):
        with tempfile.TemporaryDirectory() as temporary:
            receipt = run([sys.executable, "-c", "import time;time.sleep(20)"],
                          Path(temporary) / "cost", timeout=0.3)
            details = json.loads((Path(temporary) / "cost/SUPERVISION.json").read_text())
            self.assertFalse(receipt["task_success"])
            self.assertTrue(details["timed_out"])
            self.assertEqual(details["root_exit_code"], -9)
            self.assertGreater(receipt["complete_supervisor_wait4"]["cpu_seconds"], 0)

    def test_invalid_flush_clock_is_not_latency(self):
        source = 'import json;print(json.dumps({"kind":"episode_output","episode_id":"bad","source_monotonic_ns":1,"output_flush_monotonic_ns":2}))'
        with tempfile.TemporaryDirectory() as temporary:
            run([sys.executable, "-c", source], Path(temporary) / "cost")
            details = json.loads((Path(temporary) / "cost/SUPERVISION.json").read_text())
            self.assertFalse(details["episode_outputs"][0]["bounds_valid"])
            self.assertIsNone(details["episode_outputs"][0]["source_to_flush_seconds"])

    def test_missing_setup_prevents_full_amortized_cost(self):
        observed = amortized_cpu({"training": 10.0, "feature_preparation": None}, 2.0, 20)
        expected = [{"horizon_episodes": h, "cpu_seconds_per_episode": None,
                     "known_setup_cpu_seconds": 10.0, "measured_execution_cpu_seconds_per_episode": 0.1,
                     "unavailable_components": ["feature_preparation"], "complete_scope": False}
                    for h in (20, 10000)]
        self.assertEqual(observed, expected)
        complete = amortized_cpu({"training": 10.0}, 2.0, 20)
        self.assertEqual([x["cpu_seconds_per_episode"] for x in complete], [0.6, 0.101])
        for bad in (-1, float("nan"), True):
            with self.assertRaises(ValueError):
                amortized_cpu({"training": bad}, 2.0, 20)


if __name__ == "__main__":
    unittest.main()
