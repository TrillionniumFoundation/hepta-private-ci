"""Measured dispatch, real queued optimization, and artifact CLI regression."""

import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest

import numpy as np

from cell_learning_models import NumpyCellHead
from cell_scale_probe import measure_queue, measure_scale

IDENTITY = "c" * 64
SOURCES = ("a" * 64, "b" * 64)


class ScaleProbeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.x = np.array([[2., 0., 1., 0.], [0., 2., 0., 1.]])
        self.y = np.array([0, 1])
        self.heads = [NumpyCellHead(4, 2, "gated", seed=i) for i in range(2)]
        for index, head in enumerate(self.heads):
            head.train(self.x, self.y, steps=8)
            head.save(Path(self.temp.name) / str(index), IDENTITY)

    def test_real_scale_samples_preserve_task_count_and_report_route_coverage(self):
        receipt = {"feature_identity": IDENTITY, "observation_kind": "measured",
                   "physical_forward_calls": 1, "encoder_instances": 1}
        result = measure_scale(self.heads, ["task-a", "task-b"], self.x, SOURCES, IDENTITY,
            scales=(64, 256, 1024), repeats=5, top_k=4, router_keys=self.x,
            relevant_task_ids=[{"task-a"}, {"task-b"}], encoder_receipt=receipt)
        self.assertEqual(result["declared_task_count"], 2)
        self.assertFalse(result["copies_are_independent_learning"])
        for row in result["results"]:
            count = row["resident_cells"]
            self.assertEqual(row["accounting"]["unique_parameter_states"], 2)
            self.assertEqual(row["accounting"]["private_parameter_tensor_bytes"], count * self.heads[0].tensor_bytes)
            all_heads, selected = row["measurements"]["all"], row["measurements"]["selective"]
            self.assertEqual(all_heads["measured_head_evaluations"], 5 * 2 * count)
            self.assertEqual(selected["measured_head_evaluations"], 5 * 2 * 4)
            self.assertEqual(selected["mean_relevant_task_recall"], 1)
            self.assertEqual(selected["activated_cell_fraction"], 4 / count)
            self.assertEqual(selected["encoder_calls_inside_dispatch"], 0)
            for sample in selected["timing"].values():
                self.assertEqual(sample["sample_count"], 5)
                self.assertLessEqual(sample["p50_ns"], sample["p95_ns"])
                self.assertLessEqual(sample["p95_ns"], max(sample["samples_ns"]))
            self.assertIsNone(row["cost_ledger"]["energy_joules"])
            self.assertIsNone(row["cost_ledger"]["shared_encoder"]["upstream_measured_receipt"].get("cpu_ns"))

    def test_fake_boolean_forward_counter_and_untrained_head_reject(self):
        for calls in (True, 1.0, -1):
            with self.subTest(calls=calls), self.assertRaises(ValueError):
                measure_scale(self.heads, ["a", "b"], self.x, SOURCES, IDENTITY,
                    scales=(64,), repeats=5, encoder_receipt={"feature_identity": IDENTITY,
                    "observation_kind": "measured", "physical_forward_calls": calls, "encoder_instances": 1})
        with self.assertRaises(ValueError):
            measure_scale([NumpyCellHead(4, 2)], ["a"], self.x, SOURCES, IDENTITY, scales=(64,), repeats=5)

    def test_queue_measures_actual_training_and_durable_publication(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "queue.sqlite"
            submissions = [{"cell_id": "cell", "generation": 1, "source_digest": SOURCES[0],
                "feature_identity": IDENTITY, "payload": {"steps": 10},
                "deadline_ns": time.time_ns() + 10**10}]
            trained = NumpyCellHead(4, 2, "gated")
            before = trained.digest()
            def train(job):
                report = trained.train(self.x, self.y, steps=job["payload"]["steps"])
                return {"tensor_sha256": trained.digest(), "source_digest": job["source_digest"],
                        "generation": job["generation"], "training_report": report}
            result = measure_queue(path, submissions, train)
            self.assertNotEqual(trained.digest(), before)
            self.assertEqual(result["queue_costs_open"]["jobs_by_status"], {"done": 1})
            self.assertEqual(result["recovery"]["verified_publications"], 1)
            self.assertGreater(result["training_receipts"][0]["wall_ns"], 0)

    def test_cli_loads_trained_artifacts_and_hash_bound_features(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.heads[0].save(root / "head", IDENTITY)
            archive = root / "features.npz"
            np.savez(archive, features=self.x)
            plan = {"arrays_npz": str(archive), "arrays_sha256": hashlib.sha256(archive.read_bytes()).hexdigest(),
                    "feature_identity": IDENTITY, "head_feature_identity": IDENTITY,
                    "heads": [{"path": str(root / "head"), "task_id": "real-fixture-task"}],
                    "source_digests": SOURCES, "scales": [64], "repeats": 5}
            (root / "plan.json").write_text(json.dumps(plan))
            subprocess.run([sys.executable, str(Path(__file__).with_name("cell_scale_probe.py")),
                            "--plan", str(root / "plan.json"), "--output", str(root / "report.json")],
                           check=True, capture_output=True, text=True)
            result = json.loads((root / "report.json").read_text())
            self.assertEqual(result["results"][0]["resident_cells"], 64)
            self.assertEqual(result["declared_task_count"], 1)
            self.assertFalse(result["selective_routing_measured"])


if __name__ == "__main__":
    unittest.main()
