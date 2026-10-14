"""Mechanism/contract tests; never independent task-quality evidence."""
from copy import deepcopy
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

import torch
from torch.nn import functional as F
from safetensors.torch import load_file, save_file

import five_causal_experiments as c
import shared_gate_cosine_residual as r
import shared_question_gate as gate
from experiments.shared_stem_cell.execution import parameters, tensor_digest
from test_shared_question_gate import inputs


def plans():
    train, select = inputs()
    train["units"][0]["donor_question_id"] = c.digest("train-donor-question")
    return train, select


def own_inputs():
    def request(question, text):
        return {"question": question, "options": [], "evidence": [
            {"id": "O1", "modality": "text", "text": text,
             "asset_sha256": None, "position": 0}]}
    return [
        {"question_id": "trainq", "family": "train:r", "split": "train",
         "condition": "own_sources",
         "request": request("train different question?", "train original own source and date 2019-01-01")},
        {"question_id": "trainmissing", "family": "train:r", "split": "train",
         "condition": "own_sources",
         "request": request("train missing original?", "train missing original source")},
    ]


def material():
    train, select = plans()
    public = gate.public_plan(train, select)
    rectangle = r.build_train_rectangles(public, train, own_inputs())
    specs = list(public["features"]) + list(rectangle["additional_features"])
    features = {}
    for spec in specs:
        raw = torch.tensor([int(spec["key"][2*i:2*i+2], 16) - 127.5 for i in range(8)],
                           dtype=torch.float32)
        if not bool(raw.norm()):
            raw[0] = 1
        features[spec["key"]] = F.normalize(raw, dim=0).contiguous()
    return train, select, public, rectangle, features


def metadata(role, *, status="completed", conclusion="success"):
    expected = r.ORIGINS[role]
    run = {"id": expected["run"], "head_sha": expected["source"],
           "path": expected["path"], "run_attempt": 1,
           "status": status, "conclusion": conclusion,
           "repository": {"full_name": "TrillionniumFoundation/hepta-private-ci"},
           "head_repository": {"full_name": "TrillionniumFoundation/hepta-private-ci"}}
    artifacts = {"total_count": 1, "artifacts": [{"name": expected["artifact"],
        "id": 101 + list(r.ORIGINS).index(role), "expired": False,
        "size_in_bytes": 123, "digest": "sha256:" + str(list(r.ORIGINS).index(role)+1) * 64,
        "workflow_run": {"id": expected["run"], "head_sha": expected["source"]}}]}
    return run, artifacts


class RectanglePlanTests(unittest.TestCase):
    def test_four_corners_close_original_train_pair(self):
        _, _, _, plan, _ = material()
        available = next(x for x in plan["units"] if x["status"] == "available")
        aa, ab, ba, bb = available["variants"]
        self.assertEqual([x["role"] for x in available["variants"]], list(r.ORDER))
        self.assertEqual(aa["question_key"], ab["question_key"])
        self.assertEqual(ba["question_key"], bb["question_key"])
        self.assertEqual(aa["evidence_key"], ba["evidence_key"])
        self.assertEqual(ab["evidence_key"], bb["evidence_key"])
        self.assertNotEqual(aa["evidence_key"], ab["evidence_key"])

    def test_only_original_train_evidence_is_added(self):
        _, _, public, plan, _ = material()
        old = {x["key"] for x in public["features"]}
        self.assertTrue(plan["additional_features"])
        for row in plan["additional_features"]:
            self.assertNotIn(row["key"], old)
            self.assertEqual(row["scope"], ["train", "train:r", "evidence"])
            value = json.loads(row["text"])
            self.assertEqual(set(value), {"evidence"})
            self.assertIn("original own source", value["evidence"][0]["text"])

    def test_missing_pair_remains_missing(self):
        _, _, _, plan, _ = material()
        missing = [x for x in plan["units"] if x["status"] != "available"]
        self.assertEqual(len(missing), 1)
        self.assertEqual(missing[0]["variants"], [])

    def test_no_target_answer_or_arm_enters_features(self):
        _, _, public, plan, _ = material()
        for row in list(public["features"]) + list(plan["additional_features"]):
            self.assertNotIn("answer", row["text"].casefold())
            self.assertNotIn("arm", row["text"].casefold())
            self.assertIn(set(json.loads(row["text"])), ({"question", "options"}, {"evidence"}))

    def test_inputs_not_mutated(self):
        train, select = plans(); public = gate.public_plan(train, select); own = own_inputs()
        before = c.digest([public, train, own])
        result = r.build_train_rectangles(public, train, own)
        self.assertEqual(before, c.digest([public, train, own]))
        result["units"][0]["variants"].clear()
        self.assertEqual(before, c.digest([public, train, own]))

    def reject(self, change):
        train, select = plans(); public = gate.public_plan(train, select); own = own_inputs()
        change(public, train, own)
        with self.assertRaises((c.Invalid, KeyError)):
            r.build_train_rectangles(public, train, own)

    def test_missing_original_source_rejected(self):
        self.reject(lambda public, train, own: own.pop())

    def test_duplicate_original_source_rejected(self):
        self.reject(lambda public, train, own: own.append(deepcopy(own[0])))

    def test_changed_question_rejected(self):
        self.reject(lambda public, train, own: own[0]["request"].update(question="replacement"))

    def test_changed_source_cardinality_rejected(self):
        self.reject(lambda public, train, own: own[0]["request"]["evidence"].append(
            {"id": "O2", "modality": "text", "text": "extra", "asset_sha256": None, "position": 1}))

    def test_wrong_family_rejected(self):
        self.reject(lambda public, train, own: own[0].update(family="train:wrong"))

    def test_changed_saved_pair_order_rejected(self):
        self.reject(lambda public, train, own: train["units"][0]["matched_request"].update(question="changed"))


class ResidualModelTests(unittest.TestCase):
    def test_actual_parameter_count_and_no_additive_biases(self):
        model = r.ResidualGate(384)
        self.assertEqual(parameters(model)["parameters"], 6152)
        self.assertEqual(set(model.state_dict()), {"q_down.weight", "e_down.weight", "read"})
        self.assertEqual(parameters(model)["parameter_bytes"], 24608)

    def test_zero_residual_exactly_preserves_cosine_baseline(self):
        _, _, _, plan, features = material()
        q, e, _, _ = r.training_batch(plan["units"], features, "rectangle_residual")
        fixed = r.base_scores(q, e, .2)
        model = r.ResidualGate(8)
        with torch.no_grad():
            got = fixed + model(q, e).double()
        self.assertTrue(torch.equal(got, fixed))

    def test_training_profiles_have_equal_rows_and_expected_labels(self):
        _, _, _, plan, features = material()
        expected = {
            "one_way_residual": ([1., 0., 1., 0.], ["bb", "ab", "bb", "ab"]),
            "rectangle_residual": ([1., 0., 0., 1.], list(r.ORDER)),
            "rectangle_reversed": ([0., 1., 1., 0.], list(r.ORDER)),
        }
        for arm, (labels, roles) in expected.items():
            q, e, y, ids = r.training_batch(plan["units"], features, arm)
            self.assertEqual(q.shape, e.shape)
            self.assertEqual(y.tolist(), labels)
            self.assertEqual([x[1] for x in ids], roles)

    def test_optimizer_changes_residual_not_shared_features(self):
        _, _, _, plan, features = material()
        before = {k: tensor_digest(v) for k, v in features.items()}
        model, receipt = r.fit(plan["units"], features, .2,
                               arm="rectangle_residual", seed=7, steps=16)
        self.assertEqual(receipt["optimizer_steps"], 16)
        self.assertTrue(receipt["initial_scores_equal_fixed_cosine"])
        self.assertNotEqual(receipt["initial"]["sha256"], receipt["saved_model"]["sha256"])
        self.assertEqual(before, {k: tensor_digest(v) for k, v in features.items()})
        self.assertFalse(any(p.requires_grad for p in model.parameters()))

    def test_save_reload_preserves_predictions(self):
        _, _, _, plan, features = material()
        model, _ = r.fit(plan["units"], features, .2,
                         arm="rectangle_residual", seed=3, steps=4)
        before = r.predict(plan["units"], features, .2, model)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "head.safetensors"
            save_file(model.state_dict(), str(path))
            reloaded = r.ResidualGate(8)
            reloaded.load_state_dict(load_file(str(path)), strict=True)
            reloaded.eval().requires_grad_(False)
            self.assertEqual(before, r.predict(plan["units"], features, .2, reloaded))

    def test_select_units_cannot_enter_optimizer(self):
        _, _, _, plan, features = material()
        plan["units"][0]["split"] = "select"
        with self.assertRaises(c.Invalid):
            r.fit(plan["units"], features, .2, arm="rectangle_residual", seed=1, steps=1)

    def test_bad_arm_nonfinite_and_wrong_geometry_rejected(self):
        _, _, _, plan, features = material()
        with self.assertRaises(c.Invalid):
            r.training_batch(plan["units"], features, "unknown")
        model = r.ResidualGate(8)
        for q, e in ((torch.ones(2, 7), torch.ones(2, 7)),
                     (torch.full((2, 8), float("nan")), torch.ones(2, 8))):
            with self.assertRaises(c.Invalid):
                model(q, e)

    def test_prediction_retains_unavailable_pair(self):
        _, _, _, plan, features = material()
        rows = r.predict(plan["units"], features, .2)
        self.assertEqual(len(rows), 2)
        self.assertEqual(sum(x["status"] == "unavailable" for x in rows), 1)
        self.assertIsNone(next(x for x in rows if x["status"] == "unavailable")["logits"])


class ThresholdGeometryTests(unittest.TestCase):
    def units(self):
        _, _, _, plan, _ = material()
        return plan["units"]

    def rows(self, scores):
        units = self.units(); result = []
        for unit in units:
            result.append({"pair_id": unit["pair_id"],
                           "status": "succeeded" if unit["status"] == "available" else "unavailable",
                           "logits": scores if unit["status"] == "available" else None})
        return result

    def test_positive_interaction_does_not_imply_separability(self):
        result = r.separability(self.units(), self.rows([3., 2., 1., 1.]))
        self.assertEqual(result["per_pair_separable"], 0)
        self.assertLess(result["details"][0]["separability_gap"], 0)

    def test_pair_and_common_threshold_interval(self):
        result = r.separability(self.units(), self.rows([2., -1., -2., 1.]))
        self.assertEqual(result["per_pair_separable"], 1)
        self.assertEqual(result["fixed_zero_threshold_passes"], 1)
        self.assertTrue(result["common_threshold_exists"])
        self.assertEqual(result["details"][0]["separability_gap"], 2.)

    def test_missing_pair_stays_in_planned_denominator(self):
        result = r.separability(self.units(), self.rows([2., -1., -2., 1.]))
        self.assertEqual(result["planned_pairs"], 2)
        self.assertEqual(result["scored_pairs"], 1)
        self.assertEqual(result["unavailable_pairs"], 1)

    def test_duplicate_or_nonfinite_predictions_rejected(self):
        units = self.units(); rows = self.rows([2., -1., -2., 1.])
        with self.assertRaises(c.Invalid):
            r.separability(units, rows + rows[:1])
        rows[0]["logits"][0] = float("nan")
        with self.assertRaises(c.Invalid):
            r.separability(units, rows)


class DependencyTests(unittest.TestCase):
    def args(self):
        result = []
        for role in r.ORIGINS:
            result.extend(metadata(role))
        return result

    def test_three_exact_successful_origins_required(self):
        value = r.dependency(*self.args())
        self.assertTrue(value["ready"])
        self.assertEqual(set(value["origins"]), set(r.ORIGINS))

    def test_queued_or_failed_origin_defers_without_fallback(self):
        args = self.args(); args[2] = metadata("crossed", status="queued", conclusion=None)[0]
        value = r.dependency(*args)
        self.assertFalse(value["ready"])
        self.assertFalse(value["origins"]["crossed"]["ready"])

    def test_wrong_source_expiry_and_duplicate_artifact_rejected(self):
        args = self.args(); args[4]["head_sha"] = "0" * 40
        with self.assertRaises(c.Invalid): r.dependency(*args)
        args = self.args(); args[5]["artifacts"][0]["expired"] = True
        with self.assertRaises(c.Invalid): r.dependency(*args)
        args = self.args(); args[1]["artifacts"].append(deepcopy(args[1]["artifacts"][0])); args[1]["total_count"] = 2
        with self.assertRaises(c.Invalid): r.dependency(*args)

    def test_metadata_not_mutated(self):
        args = self.args(); before = c.digest(args)
        r.dependency(*args)
        self.assertEqual(before, c.digest(args))


class EntrypointTests(unittest.TestCase):
    def test_help_from_foreign_directory_without_pythonpath(self):
        script = Path(r.__file__).with_name("shared_gate_cosine_residual_trial.py")
        env = dict(os.environ); env.pop("PYTHONPATH", None)
        with tempfile.TemporaryDirectory() as directory:
            run = subprocess.run([sys.executable, str(script), "--help"], cwd=directory,
                                 env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                 text=True, timeout=30)
        self.assertEqual(run.returncode, 0, run.stderr)
        self.assertIn("dependency", run.stdout)
        self.assertNotIn("ModuleNotFoundError", run.stderr)


if __name__ == "__main__":
    unittest.main()
