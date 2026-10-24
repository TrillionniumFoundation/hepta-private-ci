import hashlib
import json
import tempfile
import unittest
from pathlib import Path

import numpy as np

from cell_calibrated_curve import sha_file, write_json
from run_calibrated_cells import load_inputs, run_study, task_cohort


class CalibratedDriverTests(unittest.TestCase):
    def fixture(self, root):
        rows, values = [], []
        rng = np.random.default_rng(91)
        for split in ("train", "calibration", "holdout"):
            for task in ("first", "second"):
                for i in range(16):
                    name = f"{split}-{task}-{i}"
                    rows.append(dict(source_id=name, group_id=name, text=f"independent input {name}",
                        split=split, labels={task: i % 2}))
                    x = rng.normal(size=4); x[0] += 2*(2*(i % 2)-1)
                    values.append(x)
        data = dict(rows=rows, selected_tasks=["first", "second"], task_definitions={
            "first": {"family_id": "outcome"}, "second": {"family": "diagnosis"}})
        dataset, features = root/"dataset.json", root/"features"
        features.mkdir()
        write_json(dataset, data)
        array = np.array(values, dtype=np.float32)
        np.savez_compressed(features/"features.npz", features=array)
        write_json(features/"report.json", {"plan": {"dataset_sha256": sha_file(dataset),
            "source_ids": [r["source_id"] for r in rows]}, "feature_identity": "fixture",
            "feature_archive_sha256": sha_file(features/"features.npz"),
            "feature_shape": list(array.shape), "feature_tensor_sha256": hashlib.sha256(array.tobytes()).hexdigest()})
        return dataset, features

    def test_partial_labels_and_prepare_all_before_evaluate(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            dataset, features = self.fixture(root)
            plan = dict(budgets=[8], seeds=[7], checkpoints=[2, 4], l2_grid=[.1])
            data, array, _, _, _ = load_inputs(dataset, features)
            cohort, counts = task_cohort(data["rows"], array, "first", "train")
            self.assertEqual(counts["applicable_rows"], 16)
            self.assertEqual(counts["not_applicable_rows"], 16)
            self.assertEqual(set(cohort.labels), {0, 1})
            out = root/"study"
            prepared = run_study(dataset, features, out, holdout_use="fixture", protocol=plan)
            self.assertEqual(prepared["status"], "prepared")
            self.assertTrue((out/"selection-seal.json").exists())
            self.assertFalse((out/"first/evaluation").exists())
            self.assertFalse((out/"second/evaluation").exists())
            report = run_study(dataset, features, out, phase="evaluate", holdout_use="fixture", protocol=plan)
            self.assertEqual(report["tasks_evaluated"], ["first", "second"])
            self.assertEqual(report["plan"]["families"], {"first": "outcome", "second": "diagnosis"})
            again = run_study(dataset, features, out, phase="evaluate", holdout_use="fixture", protocol=plan)
            self.assertEqual(again, report)
            (out/"first/prepared/unsealed.txt").write_text("unexpected")
            with self.assertRaises(ValueError):
                run_study(dataset, features, out, phase="evaluate", holdout_use="fixture", protocol=plan)

    def test_feature_binding_and_evaluation_requires_preparation(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            dataset, features = self.fixture(root)
            with self.assertRaises(ValueError):
                run_study(dataset, features, root/"unprepared", phase="evaluate", holdout_use="fixture")
            receipt = json.loads((features/"report.json").read_bytes())
            receipt["plan"]["source_ids"].reverse()
            (features/"report.json").write_text(json.dumps(receipt))
            with self.assertRaises(ValueError):
                load_inputs(dataset, features)

    def test_empty_applicable_split_is_explicit_unavailable(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            dataset, features = self.fixture(root)
            data = json.loads(dataset.read_bytes())
            data["selected_tasks"] = ["missing"]
            dataset.write_text(json.dumps(data))
            receipt = json.loads((features/"report.json").read_bytes())
            receipt["plan"]["dataset_sha256"] = sha_file(dataset)
            (features/"report.json").write_text(json.dumps(receipt))
            result = run_study(dataset, features, root/"study", phase="all", holdout_use="fixture")
            self.assertEqual(result["tasks_evaluated"], [])
            self.assertEqual(result["unavailable_tasks"][0]["task"], "missing")
            self.assertEqual(result["unavailable_tasks"][0]["all_budgets_unavailable"], [8, 32, 128])

    def test_global_cross_task_group_leakage_is_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            dataset, features = self.fixture(root)
            data = json.loads(dataset.read_bytes())
            target = next(r for r in data["rows"] if r["split"] == "calibration" and "second" in r["labels"])
            target["group_id"] = data["rows"][0]["group_id"]
            dataset.write_text(json.dumps(data))
            receipt = json.loads((features/"report.json").read_bytes())
            receipt["plan"]["dataset_sha256"] = sha_file(dataset)
            (features/"report.json").write_text(json.dumps(receipt))
            with self.assertRaises(ValueError):
                load_inputs(dataset, features)


if __name__ == "__main__":
    unittest.main()
