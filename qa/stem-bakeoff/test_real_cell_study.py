"""Real optimization and strict completed-task resume on mechanism fixtures."""

import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import numpy as np

from cell_learning_models import NumpyCellHead, canonical
from real_cell_study import cohorts_for_task, run_study, sha_file, source_files


class RealStudyTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.dataset = self.root / "dataset.json"
        self.feature_dir = self.root / "features"
        self.feature_dir.mkdir()
        self.output = self.root / "study"
        self.identity = "c" * 64
        rows = []
        for split, count in (("train", 16), ("calibration", 4), ("holdout", 4)):
            for i in range(count):
                rows.append({"source_id": f"{split}:{i}", "group_id": f"group:{split}:{i}",
                    "text": f"{split} diagnostic event {i}", "split": split,
                    "labels": {"added_return": i % 2}, "patch": "FORBIDDEN_GOLD"})
        self.rows = rows
        self.features = np.array([[2 * r["labels"]["added_return"] - 1, 1, i / 100]
                                  for i, r in enumerate(rows)], dtype=np.float32)
        self.dataset.write_bytes(canonical({"selected_tasks": ["added_return"], "rows": rows,
            "protocol": {"definition_sha256": "d" * 64, "task_family_count": 1}}))
        np.savez(self.feature_dir / "features.npz", features=self.features)
        self.report = {"plan": {"dataset_sha256": sha_file(self.dataset),
                               "source_ids": [r["source_id"] for r in rows]},
            "feature_identity": self.identity, "feature_shape": list(self.features.shape),
            "feature_archive_sha256": sha_file(self.feature_dir / "features.npz"),
            "feature_tensor_sha256": hashlib.sha256(self.features.tobytes()).hexdigest(),
            "source_record_digests": [hashlib.sha256(r["source_id"].encode()).hexdigest() for r in rows],
            "load": {"fixture": True}, "encoding": {"fixture": True}}
        self.write_report()

    def write_report(self):
        (self.feature_dir / "report.json").write_bytes(canonical(self.report))

    def execute(self, **options):
        return run_study(self.dataset, self.feature_dir, self.output,
                         phase="curves", budgets=(8,), seeds=(7,), steps=3, **options)

    def test_projection_excludes_outcomes_and_actual_curve_resume_preserves_artifacts(self):
        cohorts = cohorts_for_task(self.rows, self.features, "added_return")
        self.assertEqual(set(cohorts[0].rows[0]), {"source_id", "group_id", "text"})
        result = self.execute()
        self.assertEqual(result["task_count"], 1)
        self.assertEqual(len(result["aggregate"]), 13)
        model = self.output / "curves/added_return/seed-7_n-8_gated"
        head = NumpyCellHead.load(model, self.identity)
        self.assertEqual(head.report["optimizer_steps"], 3)
        digest = sha_file(model / "weights.npz")
        with patch("real_cell_study.run_curve", side_effect=AssertionError("completed task retrained")):
            resumed = self.execute(resume=True)
        self.assertEqual(resumed["aggregate"], result["aggregate"])
        self.assertEqual(sha_file(model / "weights.npz"), digest)
        (model / "weights.npz").write_bytes(b"changed artifact")
        with self.assertRaisesRegex(ValueError, "artifacts changed"):
            self.execute(resume=True)

    def test_resume_rejects_changed_plan_and_unfinished_task(self):
        self.execute()
        with self.assertRaisesRegex(ValueError, "identical"):
            run_study(self.dataset, self.feature_dir, self.output, resume=True,
                      phase="curves", budgets=(8,), seeds=(7,), steps=4)
        (self.output / "completed/added_return.json").unlink()
        with self.assertRaisesRegex(ValueError, "incomplete task"):
            self.execute(resume=True)

    def test_source_order_mismatch_rejects_before_creating_output(self):
        self.report["plan"]["source_ids"].reverse()
        self.write_report()
        with self.assertRaisesRegex(ValueError, "source order"):
            self.execute()
        self.assertFalse(self.output.exists())

    def test_source_preservation_binds_bytes_not_only_path(self):
        source = self.root / "source.bin"
        source.write_bytes(b"original")
        first = source_files([source, source])
        self.assertEqual(len(first), 1)
        source.write_bytes(b"modified")
        second = source_files([source])
        self.assertEqual(first[0]["bytes"], second[0]["bytes"])
        self.assertNotEqual(first[0]["sha256"], second[0]["sha256"])

    def test_complete_curve_queue_scale_flow_and_source_changed_resume_rejection(self):
        rows = [{"source_id": f"train:{i}", "group_id": f"group:train:{i}", "split": "train",
                 "text": f"train diagnostic event {i}", "labels": {"added_return": i % 2}}
                for i in range(128)] + [r for r in self.rows if r["split"] != "train"]
        features = np.array([[2 * r["labels"]["added_return"] - 1, 1, i / 100]
                             for i, r in enumerate(rows)], dtype=np.float32)
        data = json.loads(self.dataset.read_bytes())
        data["rows"] = rows
        self.dataset.write_bytes(canonical(data))
        np.savez(self.feature_dir / "features.npz", features=features)
        self.report.update(feature_shape=list(features.shape),
            feature_archive_sha256=sha_file(self.feature_dir / "features.npz"),
            feature_tensor_sha256=hashlib.sha256(features.tobytes()).hexdigest(),
            source_record_digests=[hashlib.sha256(r["source_id"].encode()).hexdigest() for r in rows],
            load={"loaded_model": {"resident_tensor_storage_bytes": 0}, "fixture": True},
            encoding={"physical_forward_calls": 1, "encoder_instances": 1, "fixture": True})
        self.report["plan"].update(dataset_sha256=sha_file(self.dataset), source_ids=[r["source_id"] for r in rows])
        self.write_report()
        source = self.root / "preserved.txt"
        source.write_text("first")
        options = dict(budgets=(32, 128), seeds=(7,), steps=3, source_paths=[source])
        result = run_study(self.dataset, self.feature_dir, self.output, **options)
        self.assertIsNotNone(result["finalization"])
        scale = json.loads((self.output / "scale-report.json").read_bytes())
        self.assertEqual([r["resident_cells"] for r in scale["results"]], [64, 256, 1024])
        queue = json.loads((self.output / "queue-report.json").read_bytes())
        self.assertEqual(queue["training_rows_per_task"], 32)
        self.assertTrue(queue["recovery"]["fresh_process"])
        run_study(self.dataset, self.feature_dir, self.output, resume=True, phase="finalize", **options)
        source.write_text("other")
        with self.assertRaisesRegex(ValueError, "evidence or its implementation changed"):
            run_study(self.dataset, self.feature_dir, self.output, resume=True, phase="finalize", **options)


if __name__ == "__main__":
    unittest.main()
