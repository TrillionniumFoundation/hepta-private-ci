"""Synthetic shrinkage mechanism tests; never task-quality evidence."""
from pathlib import Path
import os
import subprocess
import sys
import tempfile
import unittest

import torch

import five_causal_experiments as c
import shared_gate_cosine_residual as residual
import shared_gate_residual_shrinkage as shrink
from test_shared_gate_cosine_residual import material
from experiments.shared_stem_cell.execution import parameters, tensor_digest


class ScaleTests(unittest.TestCase):
    def fitted(self):
        _, _, _, plan, features = material()
        model, _ = residual.fit(plan["units"], features, .2,
                                arm="rectangle_residual", seed=7, steps=16)
        return plan, features, model

    def test_zero_is_exact_baseline_and_one_is_exact_saved_model(self):
        plan, features, model = self.fitted()
        zero = shrink.scaled_predict(plan["units"], features, .2, model, 0.0)
        one = shrink.scaled_predict(plan["units"], features, .2, model, 1.0)
        self.assertEqual(zero, residual.predict(plan["units"], features, .2))
        self.assertEqual(one, residual.predict(plan["units"], features, .2, model))

    def test_fixed_scale_is_linear_about_cosine(self):
        plan, features, model = self.fitted()
        base = shrink.scaled_predict(plan["units"], features, .2, model, 0.0)
        full = shrink.scaled_predict(plan["units"], features, .2, model, 1.0)
        half = shrink.scaled_predict(plan["units"], features, .2, model, .5)
        for b, f, h in zip(base, full, half):
            if b["logits"] is None:
                self.assertIsNone(h["logits"])
            else:
                self.assertEqual(h["logits"], [(x + y) / 2 for x, y in zip(b["logits"], f["logits"])])

    def test_checkpoint_features_and_units_are_not_mutated(self):
        plan, features, model = self.fitted()
        before_model = parameters(model)
        before_features = {k: tensor_digest(v) for k, v in features.items()}
        before_plan = c.digest(plan)
        shrink.scaled_predict(plan["units"], features, .2, model, 1/32)
        self.assertEqual(before_model, parameters(model))
        self.assertEqual(before_features, {k: tensor_digest(v) for k, v in features.items()})
        self.assertEqual(before_plan, c.digest(plan))

    def test_unavailable_pair_is_retained(self):
        plan, features, model = self.fitted()
        rows = shrink.scaled_predict(plan["units"], features, .2, model, 1/16)
        self.assertEqual(len(rows), len(plan["units"]))
        self.assertEqual(sum(row["status"] == "unavailable" for row in rows), 1)
        self.assertIsNone(next(row for row in rows if row["status"] == "unavailable")["logits"])

    def test_unknown_bool_and_integer_scales_rejected(self):
        plan, features, model = self.fitted()
        for alpha in (True, 1, .03, -1.0, 2.0):
            with self.assertRaises(c.Invalid):
                shrink.scaled_predict(plan["units"], features, .2, model, alpha)

    def test_registered_scale_names_are_bijective(self):
        self.assertEqual(len(shrink.ALPHAS), len(shrink.ALPHA_NAMES))
        self.assertEqual(len(set(shrink.ALPHA_NAMES)), len(shrink.ALPHA_NAMES))
        self.assertEqual([shrink.name_alpha(x) for x in shrink.ALPHAS], list(shrink.ALPHA_NAMES))


class TrainOnlySelectionTests(unittest.TestCase):
    def row(self, *, scored=3, q=3, e=3, signs=3, sep=3, common=True):
        return {"train": {
                    "crossed": {"scored_pairs": scored, "both_question_rankings": q,
                                "both_evidence_rankings": e,
                                "all_four_threshold_directions": signs},
                    "threshold_geometry": {"scored_pairs": scored,
                                           "per_pair_separable": sep,
                                           "common_threshold_exists": common}},
                "select": {"sentinel": "readout-only"}}

    def test_smallest_strict_train_alpha_selected_without_seed_choice(self):
        names = {"a", "b"}; summaries = {}
        for name in names:
            for alpha in shrink.ALPHAS[1:]:
                summaries[name + "@" + shrink.name_alpha(alpha)] = self.row(
                    signs=3 if alpha >= 1/16 else 2,
                    common=alpha >= 1/16)
        result = shrink.select_train_alpha(summaries, names)
        self.assertFalse(result["reads_select"])
        self.assertFalse(result["seed_selection"])
        self.assertEqual({row["alpha"] for row in result["selected"].values()}, {1/16})

    def test_no_qualifying_checkpoint_is_explicit(self):
        names = {"a"}; summaries = {
            "a@" + shrink.name_alpha(alpha): self.row(q=2)
            for alpha in shrink.ALPHAS[1:]}
        result = shrink.select_train_alpha(summaries, names)
        self.assertIsNone(result["selected"]["a"])

    def test_missing_summary_and_denominator_drift_rejected(self):
        with self.assertRaises(c.Invalid):
            shrink.select_train_alpha({}, {"a"})
        summaries = {"a@" + shrink.name_alpha(alpha): self.row()
                     for alpha in shrink.ALPHAS[1:]}
        summaries["a@1_64"]["train"]["threshold_geometry"]["scored_pairs"] = 2
        with self.assertRaises(c.Invalid):
            shrink.select_train_alpha(summaries, {"a"})


class EntrypointTests(unittest.TestCase):
    def test_help_from_foreign_directory_without_pythonpath(self):
        script = Path(shrink.__file__).with_name("shared_gate_residual_shrinkage_trial.py")
        env = dict(os.environ); env.pop("PYTHONPATH", None)
        with tempfile.TemporaryDirectory() as directory:
            run = subprocess.run([sys.executable, str(script), "--help"], cwd=directory,
                                 env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                 text=True, timeout=30)
        self.assertEqual(run.returncode, 0, run.stderr)
        self.assertIn("--v3-archive", run.stdout)
        self.assertIn("--crossed-archive", run.stdout)
        self.assertNotIn("ModuleNotFoundError", run.stderr)


if __name__ == "__main__":
    unittest.main()
