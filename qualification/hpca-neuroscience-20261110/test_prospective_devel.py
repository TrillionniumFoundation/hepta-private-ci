import copy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

import prospective_devel as study

ROOT = Path(__file__).resolve().parent


class ProspectivePreflight(unittest.TestCase):
    def setUp(self):
        self.data = json.loads((ROOT/"PROSPECTIVE_DEVEL_DATA.json").read_bytes())
        self.exposed = json.loads((ROOT/"PROSPECTIVE_EXPOSURE_REGISTRY.json").read_bytes())["questions"]

    def test_complete_frozen_disjoint_operator_roster(self):
        self.assertEqual(len(study.validate_data(self.data, self.exposed)), 96)

    def test_exposed_question_cannot_be_relabelled_or_renamed(self):
        self.data["tasks"][0].update(question=" Answer YES or NO. IS 12 GREATER THAN 9? ")
        with self.assertRaisesRegex(ValueError, "exposed"):
            study.validate_data(self.data, self.exposed)

    def test_duplicated_question_with_new_id_is_rejected(self):
        self.data["tasks"][1]["question"] = self.data["tasks"][0]["question"].upper()
        with self.assertRaisesRegex(ValueError, "duplicate"):
            study.validate_data(self.data, self.exposed)

    def test_world_cluster_cannot_cross_calibration_boundary(self):
        self.data["tasks"][16]["source_cluster"] = self.data["tasks"][0]["source_cluster"]
        with self.assertRaisesRegex(ValueError, "cluster crosses"):
            study.validate_data(self.data, self.exposed)

    def test_missing_task_and_changed_truth_balance_are_rejected(self):
        altered = copy.deepcopy(self.data)
        altered["tasks"].pop()
        with self.assertRaisesRegex(ValueError, "roster"):
            study.validate_data(altered, self.exposed)
        self.data["tasks"][0]["truth"] = "no"
        with self.assertRaisesRegex(ValueError, "balance"):
            study.validate_data(self.data, self.exposed)

    def test_calibration_selection_uses_only_base_calibration_and_fixed_tie_order(self):
        rows = [{"id": str(i), "wrapper": wrapper, "split": "calibration",
                 "condition": "base", "valid": True, "correct": i%2 == 0}
                for wrapper in study.WRAPPERS for i in range(16)]
        self.assertEqual(study.select_wrapper(rows), study.WRAPPERS[0])
        rows[16]["correct"] = True
        rows[16]["valid"] = False
        self.assertEqual(study.select_wrapper(rows), study.WRAPPERS[0])
        rows[16]["valid"] = True
        rows[17]["correct"] = True
        self.assertEqual(study.select_wrapper(rows), study.WRAPPERS[1])
        rows[16]["split"] = "retention"
        with self.assertRaisesRegex(ValueError, "calibration-only"):
            study.select_wrapper(rows)

    def test_incomplete_or_nonbase_wrapper_selection_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "complete base-only"):
            study.select_wrapper([])
        rows = [{"id": str(i), "wrapper": wrapper, "split": "calibration",
                 "condition": "adapter", "valid": True, "correct": True}
                for wrapper in study.WRAPPERS for i in range(16)]
        with self.assertRaisesRegex(ValueError, "calibration-only"):
            study.select_wrapper(rows)

    def test_invalid_answers_stay_in_primary_denominator(self):
        rows = [{"valid": False, "correct": False, "first_eos": True},
                {"valid": True, "correct": True, "first_eos": False}]
        self.assertEqual(study.summary(rows), {"n": 2, "valid": 1, "correct": 1,
            "first_eos": 1, "accuracy_including_invalid": 0.5})

    def test_wrapper_preserves_question_and_standalone_parser(self):
        task = {"question": "Is the blue crate empty?"}
        for wrapper in study.WRAPPERS:
            self.assertIn(task["question"], study.message(task, wrapper)[0]["content"])
        for text in ("yes12", "NO_more", "maybe YES", ""):
            self.assertIsNone(study.parse_answer(text))
        self.assertEqual(study.parse_answer(" YES."), "yes")

    def test_source_publication_mismatch_rejects_before_model_import(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest = root/"PUBLICATION.json"
            manifest.write_text(json.dumps({"commit": "0"*40, "sources": {}}))
            child = subprocess.run([sys.executable, str(ROOT/"prospective_devel.py"),
                "--model", str(root/"missing-model"), "--adapter-root", str(root/"missing-adapter"),
                "--out", str(root/"run"), "--publication-manifest", str(manifest)],
                capture_output=True, text=True, check=False)
            self.assertNotEqual(child.returncode, 0)
            self.assertIn("published source-file manifest mismatch", child.stderr)
            self.assertEqual(list((root/"run").iterdir()), [])


if __name__ == "__main__":
    unittest.main()
