import hashlib
import json
from pathlib import Path
import tempfile
import unittest

import numpy as np

from cell_calibrated_curve import bounded_protocol, code_hashes, prepare_curve, sha_file, write_json
from operational_head_view import bind_features, build_view
from run_calibrated_supplement import run_supplement, validate_preparation
from run_calibrated_cells import load_inputs, task_cohort


class CalibratedSupplementTests(unittest.TestCase):
    def fixture(self, root, long_text=False):
        rows, values = [], []
        rng = np.random.default_rng(91)
        for split, count in (("train", 131), ("calibration", 8), ("holdout", 12)):
            for i in range(count):
                source = f"{split}-{i}"
                label = int(i >= 70) if split == "train" else i % 2
                text = f"independent source {source}" + (" code"*9000 if long_text and i == 0 else "")
                rows.append(dict(source_id=source, group_id=source, text=text, split=split,
                    labels={"diagnostic_test_selection": label, "regression_outcome": 1-label}))
                values.append(rng.normal(size=4)+np.array([2*label-1, 0, 0, 0]))
        path = root/"original.json"
        write_json(path, dict(rows=rows, selected_tasks=["diagnostic_test_selection", "regression_outcome"],
            task_definitions={"diagnostic_test_selection": {"family_id": "diagnostic"}}))
        features = root/"features"
        features.mkdir()
        array = np.asarray(values, dtype=np.float32)
        np.savez_compressed(features/"features.npz", features=array)
        write_json(features/"report.json", {"plan": {"dataset_sha256": sha_file(path),
            "source_ids": [r["source_id"] for r in rows]}, "feature_identity": "fixture",
            "feature_shape": list(array.shape), "feature_archive_sha256": sha_file(features/"features.npz"),
            "feature_tensor_sha256": hashlib.sha256(array.tobytes()).hexdigest()})
        registration, reconciliation = root/"registration.json", root/"reconciliation.json"
        write_json(registration, {"schema": "hepta.availability-derived-balanced-ceiling-supplement.v1",
            "task_id": "diagnostic_test_selection", "protocol": bounded_protocol({"budgets": [122]}),
            "balanced_budget": 122, "main_code_sha256": code_hashes(),
            "before_any_operational_heldout_score": True,
            "no_upsampling_relabelling_or_action_order_changes": True,
            "holdout_use": "new_operational_holdout", "dataset_sha256": sha_file(path),
            "conditions": ["fixture"], "available_training_groups": 131, "training_class_counts": [70, 61]})
        write_json(reconciliation, {"schema": "hepta.operational122-input-reconciliation.v1",
            "original_preregistration_sha256": sha_file(registration),
            "definitive_dataset_sha256": sha_file(path), "balanced_budget": 122,
            "superseded_unexecuted_dataset_sha256": sha_file(path),
            "training_source_group_predictor_labels_identical": True,
            "no_operational_heldout_scores_observed": True,
            "primary128_remains_unavailable_for_diagnostic": True,
            "main_numerical_protocol_changed": False})
        return path, features, dict(registration=registration, reconciliation=reconciliation, condition="fixture")

    def test_frozen_n122_uses_only_declared_task_then_scores_without_refit(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            dataset, features, options = self.fixture(root, long_text=True)
            build_view(dataset, root/"view")
            bind_features(dataset, root/"view", features, root/"alias")
            view, out = root/"view/dataset.json", root/"study"
            kwargs = dict(**options, source_dataset=dataset)
            result = run_supplement(view, root/"alias", out, **kwargs)
            self.assertEqual(result["status"], "prepared")
            self.assertFalse((out/"diagnostic_test_selection/evaluation").exists())
            self.assertFalse((out/"regression_outcome").exists())
            prepared = out/"diagnostic_test_selection/prepared"
            before = sha_file(prepared/"seal.json")
            frozen = json.loads((prepared/"frozen.json").read_bytes())
            for run in frozen["runs"]:
                self.assertEqual(run["training_class_counts"], [61, 61])
                self.assertEqual(len(set(run["training_group_ids"])), 122)
            report = run_supplement(view, root/"alias", out, phase="evaluate", **kwargs)
            self.assertEqual(report["plan"]["protocol"]["budgets"], [122])
            self.assertEqual(report["tasks_evaluated"], ["diagnostic_test_selection"])
            self.assertEqual(before, sha_file(prepared/"seal.json"))
            self.assertEqual(report, run_supplement(view, root/"alias", out, phase="evaluate", **kwargs))
            (prepared/"unexpected.txt").write_text("changed")
            with self.assertRaisesRegex(ValueError, "inventory changed"):
                run_supplement(view, root/"alias", out, phase="evaluate", **kwargs)

    def test_invalid_registration_and_unprepared_evaluation_are_blocked(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            dataset, features, options = self.fixture(root)
            with self.assertRaisesRegex(ValueError, "already frozen preparation"):
                run_supplement(dataset, features, root/"study", phase="evaluate", **options)
            linked = json.loads(options["reconciliation"].read_bytes())
            linked["definitive_dataset_sha256"] = "0"*64
            options["reconciliation"].write_text(json.dumps(linked))
            with self.assertRaisesRegex(ValueError, "input reconciliation"):
                run_supplement(dataset, features, root/"study", **options)
            self.assertFalse((root/"study").exists())

    def test_valid_sealed_n32_artifact_cannot_resume_as_n122(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            dataset, features, _ = self.fixture(root)
            data, matrix, _, _, _ = load_inputs(dataset, features)
            task = "diagnostic_test_selection"
            train, _ = task_cohort(data["rows"], matrix, task, "train")
            calibration, _ = task_cohort(data["rows"], matrix, task, "calibration")
            frozen = prepare_curve(train, calibration, feature_identity="fixture",
                output_dir=root/"n32", task_id=task, family_id="diagnostic", protocol={"budgets": [32]})
            with self.assertRaisesRegex(ValueError, "registered inputs or n122 protocol"):
                validate_preparation(frozen, train, calibration, task, "diagnostic", "fixture",
                                     bounded_protocol({"budgets": [122]}))


if __name__ == "__main__":
    unittest.main()
