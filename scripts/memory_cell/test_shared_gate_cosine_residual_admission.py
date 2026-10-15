"""Admission-census regressions; no model or task-quality evidence."""
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
import os
import subprocess
import sys
import tempfile
import unittest

import five_causal_experiments as c
import shared_gate_cosine_residual_trial as legacy
import shared_gate_cosine_residual_trial_v2 as v2
import shared_gate_cosine_residual_trial_v3 as v3


def request(question):
    return {"question": question, "options": [], "evidence": [
        {"id": "E1", "modality": "text", "text": "fixed source",
         "asset_sha256": None, "position": 0}]}


def fixture(selected=3, admitted=2):
    questions = [SimpleNamespace(identity=f"selected-{i}") for i in range(selected)]
    qids = [c.digest(q.identity) for q in questions]
    units = [{"question_id": qids[i], "status": "available" if i == 0 else "unavailable_donor"}
             for i in range(admitted)]
    train = []
    for i in range(admitted):
        train.extend([
            {"question_id": qids[i], "kind": "annotated_answer", "split": "train",
             "family": f"train:{i}", "request": request(f"question {i}")},
            {"question_id": qids[i], "kind": "empty_refusal", "split": "train",
             "family": f"train:{i}", "request": {"question": f"question {i}",
                 "options": [], "evidence": []}},
        ])
    return train, {"units": units}, questions


class AdmissionTests(unittest.TestCase):
    def test_selected_superset_of_admitted_is_preserved_not_fabricated(self):
        train, rebuilt, selected = fixture(3, 2)
        own, receipt = v3.admitted_own_inputs(train, rebuilt, selected)
        self.assertEqual(len(own), 2)
        self.assertEqual(receipt["selected_train_questions"], 3)
        self.assertEqual(receipt["admitted_train_questions"], 2)
        self.assertEqual(receipt["selected_but_not_admitted_questions"], 1)
        self.assertFalse(receipt["replacement_selected"])
        self.assertEqual({row["question_id"] for row in own},
                         {selected[0].identity, selected[1].identity})

    def test_all_selected_may_be_admitted(self):
        train, rebuilt, selected = fixture(2, 2)
        own, receipt = v3.admitted_own_inputs(train, rebuilt, selected)
        self.assertEqual(len(own), 2)
        self.assertEqual(receipt["selected_but_not_admitted_questions"], 0)

    def test_unavailable_donor_unit_still_requires_own_source(self):
        train, rebuilt, selected = fixture(2, 2)
        self.assertEqual(rebuilt["units"][1]["status"], "unavailable_donor")
        own, _ = v3.admitted_own_inputs(train, rebuilt, selected)
        self.assertEqual(len(own), 2)

    def test_missing_admitted_annotation_rejected(self):
        train, rebuilt, selected = fixture(3, 2)
        train = [row for row in train
                 if not (row["question_id"] == rebuilt["units"][1]["question_id"]
                         and row["kind"] == "annotated_answer")]
        with self.assertRaises(c.Invalid):
            v3.admitted_own_inputs(train, rebuilt, selected)

    def test_extra_selected_but_nonadmitted_annotation_rejected(self):
        train, rebuilt, selected = fixture(3, 2)
        train.append({"question_id": c.digest(selected[2].identity),
                      "kind": "annotated_answer", "split": "train",
                      "family": "train:extra", "request": request("extra")})
        with self.assertRaises(c.Invalid):
            v3.admitted_own_inputs(train, rebuilt, selected)

    def test_admitted_unit_outside_selected_cohort_rejected(self):
        train, rebuilt, selected = fixture(2, 2)
        rebuilt["units"][1]["question_id"] = c.digest("not-selected")
        with self.assertRaises(c.Invalid):
            v3.admitted_own_inputs(train, rebuilt, selected)

    def test_duplicate_selected_or_admitted_identity_rejected(self):
        train, rebuilt, selected = fixture(2, 2)
        selected.append(SimpleNamespace(identity=selected[0].identity))
        with self.assertRaises(c.Invalid):
            v3.admitted_own_inputs(train, rebuilt, selected)
        train, rebuilt, selected = fixture(2, 2)
        rebuilt["units"].append(deepcopy(rebuilt["units"][0]))
        with self.assertRaises(c.Invalid):
            v3.admitted_own_inputs(train, rebuilt, selected)

    def test_duplicate_annotated_answer_rejected(self):
        train, rebuilt, selected = fixture(2, 2)
        train.append(deepcopy(train[0]))
        with self.assertRaises(c.Invalid):
            v3.admitted_own_inputs(train, rebuilt, selected)

    def test_input_not_mutated_and_public_request_preserved(self):
        train, rebuilt, selected = fixture(3, 2)
        before = c.digest([train, rebuilt, [q.identity for q in selected]])
        own, _ = v3.admitted_own_inputs(train, rebuilt, selected)
        self.assertEqual(before, c.digest([train, rebuilt, [q.identity for q in selected]]))
        self.assertEqual(own[0]["request"], train[0]["request"])
        own[0]["request"]["question"] = "changed"
        self.assertNotEqual(own[0]["request"], train[0]["request"])

    def test_wrapper_preserves_receipt_fix_and_installs_admission_fix(self):
        self.assertIs(legacy.validate_similarity, v2.validate_similarity)
        self.assertIs(legacy.rebuild_train_material, v3.rebuild_train_material)


class EntrypointTests(unittest.TestCase):
    def test_help_from_foreign_directory_without_pythonpath(self):
        script = Path(v3.__file__)
        env = dict(os.environ); env.pop("PYTHONPATH", None)
        with tempfile.TemporaryDirectory() as directory:
            run = subprocess.run([sys.executable, str(script), "--help"], cwd=directory,
                                 env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                 text=True, timeout=30)
        self.assertEqual(run.returncode, 0, run.stderr)
        self.assertIn("dependency", run.stdout)
        self.assertIn("run", run.stdout)
        self.assertNotIn("ModuleNotFoundError", run.stderr)


if __name__ == "__main__":
    unittest.main()
