"""Namespace, information-boundary and completion-order tests using development data."""

import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import numpy as np

from ..round4.runtime_learning import fit_dynamics, public_row
from .data import ARMS, SEEDS, SMOKE_SEED, dataset
from .learning import law, noise_scale, prepare_seed
from .study import configuration, confirm_seed, score, select_action, verify_scope


class StudyContract(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.training = dataset(SMOKE_SEED, 24, "train", smoke=True)
        cls.model, cls.fit = fit_dynamics(cls.training)

    def test_namespace_refuses_formal_seed_as_smoke(self):
        with self.assertRaises(ValueError):
            dataset(SEEDS[0], 8, "confirmation", smoke=True)
        with self.assertRaises(ValueError):
            dataset(SMOKE_SEED, 8, "confirmation")
        with self.assertRaises(ValueError):
            configuration(SMOKE_SEED, "drift", 8, True)
        with self.assertRaises(ValueError):
            configuration(SMOKE_SEED, "nominal", 9, True)

    def test_training_and_development_are_disjoint(self):
        development = dataset(SMOKE_SEED, 12, "development", smoke=True)
        self.assertFalse(set(self.training["ids"]) & set(development["ids"]))
        self.assertFalse(np.array_equal(self.training["target"][:12], development["target"]))
        with self.assertRaises(ValueError):
            dataset(SMOKE_SEED, 24, "train", "drift", smoke=True)

    def test_unacquired_and_private_fields_do_not_change_public_inference(self):
        altered = {k: v.copy() if isinstance(v, np.ndarray) else v for k, v in self.training.items()}
        altered["target"][:] = 1e6
        altered["wait_evaluation"][:] = -1e6
        altered["domain"] = "hidden_changed"
        public = public_row(self.training, 0)
        self.assertEqual(public, public_row(altered, 0))
        for arm in ARMS:
            self.assertEqual(law(self.model, public, arm), law(self.model, public_row(altered, 0), arm))
        with self.assertRaises(ValueError):
            law(self.model, {**public, "target": 1.0}, "event")

    def test_uncalibrated_ablation_preserves_prior_but_changes_conditioning(self):
        public = public_row(self.training, 0)
        self.assertEqual(noise_scale(self.model, "uncalibrated"), 1.0)
        self.assertEqual(noise_scale(self.model, "float"), self.model["calibration"]["noise_scale"])
        self.assertNotEqual(law(self.model, public, "float"), law(self.model, public, "uncalibrated"))
        self.assertTrue(self.fit["prior_parameters_changed"])
        self.assertEqual(len(self.fit["training_nll_by_iteration"]), 80)

    def test_gaussian_dense_probit_matches_precision_conditioning(self):
        for row in range(12):
            for second in (False, True):
                public = public_row(self.training, row, second)
                left, right = law(self.model, public, "gaussian"), law(self.model, public, "probit")
                for key in ("weights", "means", "variances"):
                    np.testing.assert_allclose(left[key], right[key], atol=1e-12, rtol=1e-12)

    def test_formal_confirmation_requires_expected_freeze_before_data_creation(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch("experiments.analytic_event_neuron.round6.study.dataset") as generator:
                with self.assertRaises(ValueError):
                    confirm_seed(directory, SEEDS[0], "nominal")
                generator.assert_not_called()
            self.assertFalse((Path(directory) / "confirmation").exists())

    def test_smoke_cannot_enter_a_frozen_or_registered_run(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "FREEZE.json").write_text("{}")
            with self.assertRaises(ValueError):
                verify_scope(root, SMOKE_SEED, "nominal", 8, None, True)
            (root / "FREEZE.json").unlink()
            (root / "PREPARING.json").write_text("{}")
            with self.assertRaises(ValueError):
                verify_scope(root, SMOKE_SEED, "nominal", 8, None, True)
            with self.assertRaises(ValueError):
                prepare_seed(root, SMOKE_SEED, 24, 12, smoke=True)

    def test_scorer_requires_successful_policy_exit_before_private_load(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "confirmation" / f"seed_{SMOKE_SEED}" / "nominal"
            root.mkdir(parents=True)
            (root / "WORKER_COMPLETED.json").write_text(json.dumps({"returncode": 2}))
            with patch("experiments.analytic_event_neuron.round6.study.load_data") as loader:
                with self.assertRaises(ValueError):
                    score(directory, SMOKE_SEED, "nominal", n=8, smoke=True)
                loader.assert_not_called()

    def test_second_acquired_stage_cannot_request_another_wait(self):
        public = public_row(self.training, 0, True)
        received = {"conditional_law": law(self.model, public, "float")}
        choice, values, scores, vector, actual = select_action(
            self.model, "float", public, received, None, "unit", 1)
        self.assertNotIn("wait", scores)
        self.assertIsNone(values["wait_gain"])
        self.assertIn(choice, ("stop", "repair"))
        self.assertIsNone(vector)
        self.assertEqual(actual, [])


if __name__ == "__main__":
    unittest.main()
