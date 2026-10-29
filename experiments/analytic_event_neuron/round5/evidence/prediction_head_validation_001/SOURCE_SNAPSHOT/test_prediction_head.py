"""Conformance with frozen learned heads; no new fit or confirmation sample."""

from copy import deepcopy
import hashlib
import json
from pathlib import Path
import unittest
from unittest.mock import patch

import numpy as np
from scipy.special import log_ndtr, logsumexp

from .. import task
from ..round4 import calibration as cal, calibration_study as saved, runtime_law
from . import interop, selection_study as study
from .prediction_head import PredictionHead, PublicHistory, PUBLIC_FIELDS, release_q24


class PredictionHeadTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.run = Path(__file__).resolve().parent / "evidence/selection_registered_001"
        cls.freeze = "1e5676bd481ef5a3d13e63a5de8eb90223e9abf55bb918721b28ab32e1f5ba16"
        root = cls.run / "prepared/seed_2131"
        cls.models = json.loads((root / "window_11_CHECKPOINT.json").read_text())["models"]
        cls.heads = {arm: PredictionHead(cls.run, seed=2131, window=11, arm=arm,
                                        expected_freeze_sha256=cls.freeze) for arm in study.ARMS}
        seed = int.from_bytes(hashlib.sha256(b"hepta.aen.r5.prediction-head.unit.v1|public").digest()[:6], "big")
        cls.data = task.build_dataset(seed, 6, "prediction_head_unit")
        cls.history = task.history(cls.data)
        cls.development = task.history(saved.subset(saved.load(root / "window_11_NEW_DEV.npz"), 4))

    @staticmethod
    def public(history):
        return PublicHistory(**{key: history[key] for key in PUBLIC_FIELDS})

    def test_all_selected_heads_match_learned_moments_and_independent_call_put_logs(self):
        for history in (self.history, self.development):
            public = self.public(history)
            for arm, head in self.heads.items():
                distribution = cal.predict_distribution(self.models[arm], history)
                for j, horizon in enumerate(task.HORIZONS):
                    row = 2
                    forecast = head.forecast(public, row=row, horizon=float(horizon))
                    self.assertIs(type(forecast), interop.TerminalForecast)
                    actual = release_q24(forecast)
                    weights = distribution["weights"][row]
                    means, variances = distribution["means"][row, j], distribution["variances"][row, j]
                    mean = float(weights @ means)
                    variance = float(weights @ (variances + (means - mean) ** 2))
                    np.testing.assert_allclose([actual["mean"], actual["variance"]], [mean, variance], rtol=0, atol=3e-13)
                    logw = distribution["log_weights"][row]
                    reference = [logsumexp(logw + log_ndtr((task.LOWER - means) / np.sqrt(variances))),
                                 logsumexp(logw + log_ndtr((means - task.UPPER) / np.sqrt(variances)))]
                    np.testing.assert_allclose(np.asarray(actual["physical_log_probabilities"])[[0, 2]], reference, rtol=0, atol=3e-13)
                    np.testing.assert_allclose(actual["physical_log_probabilities"],
                                               cal.mixture_event_log_probs(distribution)[row, j], rtol=0, atol=3e-13)
                    self.assertEqual(forecast.condition_time, float(task.latest_time(history)[row]))
                    self.assertEqual(forecast.horizon, float(horizon))

    def test_private_fields_are_rejected_and_prediction_never_reads_datasets_or_targets(self):
        head, public = self.heads["mixture_full_range"], self.public(self.history)
        expected = head.forecast(public, row=0, horizon=1.)
        changed = deepcopy(self.data)
        for key in ("future", "repair_observation", "wait_observation", "wait_repair_observation"):
            changed[key][...] = -1e30
        changed["ids"][...] = "private"
        changed["law"], changed["drift"] = "hidden", 999.
        with patch.object(task, "targets", side_effect=AssertionError("target access")), \
                patch.object(np, "load", side_effect=AssertionError("dataset access")):
            self.assertEqual(head.forecast(self.public(task.history(changed)), row=0, horizon=1.), expected)
        for private in ("future", "targets", "ids", "law", "context", "wait_observation"):
            with self.assertRaises(TypeError):
                PublicHistory(**{**{key: self.history[key] for key in PUBLIC_FIELDS}, private: [123]})
        with self.assertRaises(TypeError):
            head.forecast(self.data, row=0, horizon=1.)

    def test_missing_last_slot_sets_physical_clock_without_observation_evidence(self):
        history = deepcopy(self.history)
        history["mask"][:, 5] = False
        head = self.heads["mixture_full_range"]
        expected = head.forecast(self.public(history), row=0, horizon=.5)
        self.assertEqual(expected.condition_time, float(history["times"][0, 5]))
        history["obs"][:, 5] = np.nan
        history["obs_var"][:, 5] = -999.
        self.assertEqual(head.forecast(self.public(history), row=0, horizon=.5), expected)
        public = self.public(history)
        history["obs"][:, 0] += 1000.
        self.assertEqual(head.forecast(public, row=0, horizon=.5), expected)

    def test_structural_zero_is_pruned_but_actual_positive_log_underflow_is_rejected(self):
        public = self.public(self.history)
        law = self.heads["frozen"].forecast(public, row=0, horizon=1.).law
        self.assertEqual(law["weights"], [1.])
        extreme = deepcopy(self.history)
        extreme["obs"][extreme["mask"] & extreme["occupied"]] = 1e5
        distribution = cal.predict_distribution(self.models["mixture_full_range"], extreme)
        self.assertTrue(np.any((distribution["weights"][0] == 0) & np.isfinite(distribution["log_weights"][0])))
        with self.assertRaisesRegex(ValueError, "not representable"):
            self.heads["mixture_full_range"].forecast(self.public(extreme), row=0, horizon=1.)

    def test_actual_release_is_explicit_and_its_positive_counts_obey_the_error_bound(self):
        terminal = self.heads["mixture_full_range"].forecast(self.public(self.history), row=1, horizon=2., lower=-9., upper=12.)
        actual = release_q24(terminal)
        self.assertEqual(actual, runtime_law.release_law(terminal.law, terminal.lower, terminal.upper))
        self.assertEqual(sum(actual["probabilities_q24"]), 1 << 24)
        self.assertTrue(all(type(value) is int and value > 0 for value in actual["probabilities_q24"]))
        self.assertLess(np.max(np.abs(np.asarray(actual["probabilities"]) - actual["physical_probabilities"])), 3 / (1 << 24))
        with self.assertRaises(TypeError):
            release_q24(actual)

    def test_identity_checkpoint_reopens_and_rejects_model_source_or_freeze_changes(self):
        head = self.heads["mixture_full_range"]
        checkpoint = json.loads(json.dumps(head.checkpoint()))
        restored = PredictionHead.restore(checkpoint, self.run)
        self.assertEqual(restored.checkpoint(), checkpoint)
        self.assertEqual(restored.forecast(self.public(self.history), row=0, horizon=1.),
                         head.forecast(self.public(self.history), row=0, horizon=1.))
        for key in ("model_sha256", "adapter_sha256", "interop_sha256", "checkpoint_sha256", "freeze_sha256"):
            changed = deepcopy(checkpoint)
            changed["binding"][key] = "0" * 64
            with self.assertRaises(ValueError):
                PredictionHead.restore(changed, self.run)
        checkpoint["binding"]["model_sha256"] = "mutated caller copy"
        self.assertNotEqual(head.checkpoint(), checkpoint)

    def test_strict_horizon_boundary_and_public_history_effective_domain(self):
        head, public = self.heads["mixture_full_range"], self.public(self.history)
        for horizon in (-1., .50000000001, float("nan"), float("inf"), True):
            with self.assertRaises(ValueError):
                head.forecast(public, row=0, horizon=horizon)
        for lower, upper in ((0., 0.), (1., -1.), (-np.inf, 1.)):
            with self.assertRaises(ValueError):
                head.forecast(public, row=0, horizon=1., lower=lower, upper=upper)
        with self.assertRaises(ValueError):
            head.forecast(public, row=-1, horizon=1.)
        wrong = deepcopy(self.history)
        wrong["mask"] = wrong["mask"].astype(int)
        with self.assertRaises(ValueError):
            self.public(wrong)
        with self.assertRaises(ValueError):
            release_q24(interop.TerminalForecast(runtime_law.make_law([1.], [0.], [1.]), 0., 1., 0., 0.))
        study.verify_prepared(self.run, self.run / "FREEZE.json")


if __name__ == "__main__":
    unittest.main()
