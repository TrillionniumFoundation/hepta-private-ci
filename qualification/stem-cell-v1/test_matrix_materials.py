import copy
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from matrix_materials import (PUBLIC_FIELDS, freeze_config, public_row, strict_json,
                              validate_config, validate_workload)
from matrix_test_support import setup


class MatrixMaterialTests(unittest.TestCase):
    def setUp(self):
        self.plan, self.contract, self.config, self.work = setup()

    def test_config_and_blind_dataset_admit_expected_input(self):
        self.assertEqual(validate_config(self.plan, self.contract, self.config)["logical_cells"], 16)
        self.assertEqual(validate_workload(self.work, self.contract), 2)
        self.assertEqual(set(public_row(self.work["train"][0])), PUBLIC_FIELDS)

    def test_all_unsupported_arms_reject_before_loading(self):
        for arm in ("replicated_421m_no_ndu", "shared_421m_sparse_split_no_ndu",
                    "shared_421m_sparse_split_ndu", "shared_421m_sparse_split_64m_no_ndu"):
            with self.subTest(arm=arm), self.assertRaisesRegex(ValueError, "no relabeling"):
                freeze_config(self.plan, self.contract, arm_id=arm, snapshot_sha256="a"*64,
                              upstream_revision="b"*40, material_approval_sha256="c"*64)

    def test_unknown_and_rehashed_config_changes_reject(self):
        for key, value in (("train_steps", True), ("device", "cuda"), ("width_units", 2048),
                           ("config_id", "1"*64), ("override", True)):
            cfg = dict(self.config); cfg[key] = value
            with self.subTest(key=key), self.assertRaises(ValueError):
                validate_config(self.plan, self.contract, cfg)

    def test_evaluation_labels_never_admitted(self):
        for key in ("label", "answer", "ground_truth", "critic_reward"):
            work = copy.deepcopy(self.work); work["eval"][0][key] = 1
            with self.subTest(key=key), self.assertRaises(ValueError):
                validate_workload(work, self.contract)

    def test_future_training_labels_and_inputs_reject(self):
        for key in ("available_at_ns", "label_observed_at_ns"):
            work = copy.deepcopy(self.work); work["train"][0][key] = 11
            with self.subTest(key=key), self.assertRaises(ValueError):
                validate_workload(work, self.contract)

    def test_source_overlap_and_principal_mix_reject(self):
        for key, value in (("source_group", "t0"), ("state", "-1"), ("scope", "other")):
            work = copy.deepcopy(self.work); work["eval"][0][key] = value
            with self.subTest(key=key), self.assertRaises(ValueError):
                validate_workload(work, self.contract)

    def test_denominator_duplicates_and_order_reject(self):
        for how in ("delete", "reorder", "duplicate"):
            work = copy.deepcopy(self.work)
            if how == "delete": work["eval"].pop()
            if how == "reorder": work["eval"].reverse()
            if how == "duplicate": work["train"][0]["sample_id"] = "e0"
            with self.subTest(how=how), self.assertRaises(ValueError):
                validate_workload(work, self.contract)

    def test_strict_json_duplicate_nan_and_size(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "input.json"
            for text in ('{"x":1,"x":2}', '{"x":NaN}', '{"x":Infinity}', '{"x":"large"}'):
                p.write_text(text)
                with self.subTest(text=text), self.assertRaises(ValueError):
                    strict_json(p, max_bytes=10 if "large" in text else 1024)
            p.write_text(json.dumps(self.config))
            self.assertEqual(strict_json(p), self.config)

    def test_run_and_export_help_have_no_missing_study_dependency(self):
        root = Path(__file__).parent
        for script in ("matrix_runtime.py", "matrix_export.py"):
            result = subprocess.run([sys.executable, str(root / script), "--help"],
                                    capture_output=True, text=True, timeout=10)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("--contract", result.stdout)


if __name__ == "__main__":
    unittest.main()
