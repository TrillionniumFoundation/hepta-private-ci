import hashlib
import json
import tempfile
import unittest
from pathlib import Path

import numpy as np

from cell_calibrated_curve import sha_file
from cell_modality_controls import run_modality_off
from run_calibrated_cells import run_study
import test_run_calibrated_cells as driver_fixtures


class ModalityControlTests(unittest.TestCase):
    def fixture(self, root):
        dataset, features = driver_fixtures.CalibratedDriverTests().fixture(root)
        data = json.loads(dataset.read_bytes()); data["selected_tasks"] = ["first"]
        for row in data["rows"]:
            row.update(modality="image", text="neutral image input",
                input_content_sha256=hashlib.sha256(row["source_id"].encode()).hexdigest())
        dataset.write_text(json.dumps(data))
        report = json.loads((features/"report.json").read_bytes())
        report["plan"]["dataset_sha256"] = sha_file(dataset)
        report["encoder_identity"] = {"owner": "fixed-fixture"}
        (features/"report.json").write_text(json.dumps(report))
        main = root/"main"
        run_study(dataset, features, main, phase="all", holdout_use="new_multimodal_holdout",
                  protocol=dict(budgets=[8], seeds=[7], checkpoints=[2, 4], l2_grid=[.1]))
        control = np.zeros(report["feature_shape"], dtype=np.float32)
        array, receipt_path = root/"text_only.npy", root/"text_only.json"
        np.save(array, control, allow_pickle=False)
        receipt = {"dataset_sha256": sha_file(dataset), "source_ids": report["plan"]["source_ids"],
            "parent_feature_identity": report["feature_identity"], "encoder_identity": report["encoder_identity"],
            "feature_archive_sha256": sha_file(array), "feature_tensor_sha256": hashlib.sha256(control.tobytes()).hexdigest(),
            "feature_shape": list(control.shape), "input_fields": ["text"], "media_inputs_present": False}
        receipt_path.write_text(json.dumps(receipt))
        return dataset, features, main, array, receipt_path

    def test_intervention_preserves_fitted_state_and_removes_discrimination(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            args = self.fixture(root)
            before = sha_file(args[2]/"first/prepared/seal.json")
            summary = run_modality_off(*args, root/"off")
            self.assertTrue(summary["no_new_model_selection"])
            self.assertEqual(before, sha_file(args[2]/"first/prepared/seal.json"))
            arms = json.loads((root/"off/first/evaluation/report.json").read_bytes())["runs"][0]["arms"]
            for mode in ("linear", "gated", "residual"):
                self.assertEqual(arms[mode]["semantic"]["balanced_accuracy"], .5)
                self.assertTrue(arms[mode]["parameters_unchanged"])
                self.assertFalse(arms[mode]["calibration_refitted"])

    def test_wrong_owner_and_modified_control_bytes_are_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            args = self.fixture(root)
            receipt = json.loads(args[4].read_bytes())
            receipt["encoder_identity"] = {"owner": "other"}
            args[4].write_text(json.dumps(receipt))
            with self.assertRaises(ValueError):
                run_modality_off(*args, root/"wrong-owner")
            receipt["encoder_identity"] = {"owner": "fixed-fixture"}
            args[4].write_text(json.dumps(receipt))
            np.save(args[3], np.ones(receipt["feature_shape"], dtype=np.float32), allow_pickle=False)
            with self.assertRaises(ValueError):
                run_modality_off(*args, root/"changed-bytes")
            self.assertFalse((root/"wrong-owner").exists())
            self.assertFalse((root/"changed-bytes").exists())


if __name__ == "__main__":
    unittest.main()
