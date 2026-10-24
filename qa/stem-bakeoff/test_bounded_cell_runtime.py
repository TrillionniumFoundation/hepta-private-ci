"""Serving regressions using explicit synthetic arrays and fixture receipts.

No research checkpoint, research label, Encoder or optimizer is used here.
"""

import copy
import unittest
from unittest.mock import patch

import numpy as np

from bounded_cell_runtime import BoundedCalibratedCellRuntime
from cell_batch_runtime import BatchRuntimeError, BatchedCellRuntime
from cell_calibration_bounded import apply_bounded_calibrator, fit_bounded_calibrator
from cell_learning_models import NumpyCellHead, canonical


IDENTITY, CONTEXT = "a" * 64, "b" * 64
SOURCES = ("c" * 64, "d" * 64, "e" * 64)


class BoundedRuntimeTests(unittest.TestCase):
    def head(self, mode="linear", offset=0.):
        head = NumpyCellHead(4, 2, mode, rank=2, seed=7)
        head.params["W"][:] = 0
        head.params["W"][:, 1] = np.array([1., .5, -.25, .1]) + offset
        if mode == "residual":
            head.params["U"][:] = .01
        head.feature_identity = IDENTITY
        self.receipt(head)
        return head

    def receipt(self, head):
        head.report = {"optimizer_steps": 1, "trained_tensor_sha256": head.digest(),
                       "unit_test_fixture_not_training_evidence": True}

    def bindings(self, head, context=CONTEXT):
        return {"feature_identity": IDENTITY, "predictor_sha256": head.digest(),
                "calibration_context_sha256": context}

    def fit(self, head, context=CONTEXT, *, mode="pointwise", prior_only=False):
        margins = np.zeros(32) if prior_only else np.tile([-3., -1., 1., 3.], 8)
        labels = np.array([0] * 24 + [1] * 8) if prior_only else np.tile([0, 0, 1, 1], 8)
        return fit_bounded_calibrator(margins, labels,
            [{"source_id": f"s{i}", "group_id": f"g{i}"} for i in range(32)],
            effective_training_prior=[.5, .5], bindings=self.bindings(head, context), mode=mode)

    def runtime(self, heads, fits, *, tasks=None, contexts=None, **options):
        return BoundedCalibratedCellRuntime(heads, fits, [f"c{i}" for i in range(len(heads))],
            ["task"] * len(heads) if tasks is None else tasks, IDENTITY,
            expected_calibration_context_digests=[CONTEXT] * len(heads) if contexts is None else contexts,
            **options)

    def predict(self, runtime, x=None, **options):
        x = np.array([[1., 0, 0, 0], [-1., 0, 0, 0], [0., 0, 0, 0]]) if x is None else x
        return runtime.predict(x, source_digests=SOURCES[:len(x)], feature_identity=IDENTITY,
                               generation=1, **options)

    def test_all_modes_match_physical_calibration_bitwise_and_scalar_with_tolerance(self):
        x = np.random.default_rng(23).normal(size=(3, 4))
        for mode in ("linear", "gated", "residual"):
            with self.subTest(mode=mode):
                first, second = self.head(mode), self.head(mode, .2)
                heads = [first, second, first]
                fits = [self.fit(first), self.fit(second)]
                fits.append(fits[0])
                runtime = self.runtime(heads, fits)
                result = self.predict(runtime, x)
                physical = BatchedCellRuntime(heads, ["a", "b", "c"], ["task"] * 3, IDENTITY)
                raw = self.predict(physical, x)["logits"]
                expected = np.stack([apply_bounded_calibrator(raw[:, i, 1] - raw[:, i, 0], fit,
                    expected_bindings=self.bindings(head)) for i, (head, fit) in enumerate(zip(heads, fits))], axis=1)
                scalar = np.stack([head.predict_logits(x) for head in heads], axis=1)
                scalar_p = np.stack([apply_bounded_calibrator(scalar[:, i, 1] - scalar[:, i, 0], fit,
                    expected_bindings=self.bindings(head)) for i, (head, fit) in enumerate(zip(heads, fits))], axis=1)
                np.testing.assert_array_equal(result["logits"], raw)
                np.testing.assert_array_equal(result["probabilities"], expected)
                np.testing.assert_allclose(result["logits"], scalar, atol=1e-9, rtol=0)
                np.testing.assert_allclose(result["probabilities"], scalar_p, atol=1e-12, rtol=0)
                np.testing.assert_array_equal(result["positive_action_mask"], scalar_p[:, :, 1] >= .7)
                self.assertEqual((result["head_evaluations"], result["calibration_row_evaluations"],
                    result["encoder_invocations_by_runtime"], result["private_parameter_updates"],
                    result["calibration_parameter_updates"], result["authority"]), (6, 6, 0, 0, 0, "DENY_ALL"))

    def test_full_record_context_and_task_identity_prevent_incorrect_deduplication(self):
        head = self.head()
        fit = self.fit(head)
        annotated = {**fit, "diagnostic_note": "a distinct full frozen record"}
        other_context = self.fit(head, "f" * 64)
        runtime = self.runtime([head] * 5, [fit, fit, annotated, other_context, fit],
            tasks=["task"] * 4 + ["other"], contexts=[CONTEXT] * 3 + ["f" * 64, CONTEXT])
        result, accounting = self.predict(runtime), runtime.accounting()
        self.assertEqual(runtime.router.physical_to_logical.tolist(), [0, 0, 1, 2, 3])
        for index in range(1, 5):
            np.testing.assert_array_equal(result["probabilities"][:, 0], result["probabilities"][:, index])
        self.assertEqual((accounting["logical_state_count"], accounting["physical_calibration_references"],
            accounting["retained_calibration_record_count"], accounting["declared_task_count"]), (4, 5, 3, 2))
        self.assertEqual(accounting["serialized_calibration_bytes"], sum(len(canonical(f)) for f in (fit, annotated, other_context)))
        self.assertEqual(accounting["total_owned_tensor_bytes"], 4 * head.tensor_bytes + 5 * 8)

    def test_caller_mutations_and_returned_arrays_cannot_change_frozen_cached_state(self):
        head, tasks = self.head(), ["original"]
        fit = self.fit(head)
        runtime = self.runtime([head], [fit], tasks=tasks, cache_bytes=96)
        x = np.ones((3, 4))
        before = self.predict(runtime, x)["probabilities"].copy()
        x[:] = 99
        head.params["W"][:] = 99
        fit["alpha"] = 0
        fit["bindings"]["predictor_sha256"] = "0" * 64
        fit["calibration_source_ids"].clear()
        tasks[0] = "changed"
        after = runtime.predict_cached(SOURCES, feature_identity=IDENTITY, generation=1)
        np.testing.assert_array_equal(before, after["probabilities"])
        after["probabilities"][:] = 42
        again = runtime.predict_cached(SOURCES, feature_identity=IDENTITY, generation=1)
        np.testing.assert_array_equal(before, again["probabilities"])
        self.assertEqual(again["task_ids"], ("original",))
        with self.assertRaises(ValueError):
            runtime.router.runtime._params["W"].setflags(write=True)
        self.assertTrue(all(type(blob) is bytes for blob in runtime._records))

    def test_wrong_context_predictor_feature_and_nonbinary_or_unbound_head_reject(self):
        head = self.head()
        fit = self.fit(head)
        with self.assertRaisesRegex(BatchRuntimeError, "binding"):
            self.runtime([head], [fit], contexts=["f" * 64])
        head.params["W"][0, 1] += 1
        self.receipt(head)
        with self.assertRaisesRegex(BatchRuntimeError, "binding"):
            self.runtime([head], [fit])
        for identity in (None, "f" * 64):
            head.feature_identity = identity
            with self.assertRaisesRegex(BatchRuntimeError, "feature identity"):
                self.runtime([head], [fit])
        three_classes = NumpyCellHead(4, 3)
        three_classes.feature_identity = IDENTITY
        with self.assertRaisesRegex(BatchRuntimeError, "binary"):
            self.runtime([three_classes], [fit])

    def test_invalid_requests_reject_before_dispatch(self):
        head = self.head()
        runtime = self.runtime([head], [self.fit(head)])
        for changed in ({"generation": True}, {"generation": 2}, {"feature_identity": "f" * 64},
                        {"threshold": True}, {"threshold": float("nan")}, {"threshold": .49},
                        {"source_digests": [False]}, {"top_k": True}):
            options = {"source_digests": SOURCES[:1], "feature_identity": IDENTITY, "generation": 1, **changed}
            with self.subTest(changed=changed), self.assertRaises(BatchRuntimeError):
                runtime.predict(np.ones((1, 4)), **options)
        self.assertEqual(runtime.router.runtime.dispatch_calls, 0)

    def test_feature_and_router_bounds_reject_before_frozen_copy(self):
        head = self.head()
        runtime = self.runtime([head], [self.fit(head)])
        invalid = (np.empty((65, 4)), np.empty((0, 4)), np.empty((1, 5)), np.empty(4),
                   np.ones((1, 4), dtype=bool), np.ones((1, 4), dtype=complex),
                   np.full((1, 4), "1"), np.ones((1, 4), dtype=object))
        with patch("cell_logical_routing._frozen", side_effect=AssertionError("copied before shape guard")):
            for features in invalid:
                with self.subTest(shape=features.shape, dtype=features.dtype), self.assertRaises(BatchRuntimeError):
                    runtime.predict(features, source_digests=SOURCES[:1], feature_identity=IDENTITY, generation=1)
            for scores in (np.ones((1, 10000)), np.ones((1, 1), dtype=bool), np.array([[1j]])):
                with self.subTest(scores_shape=scores.shape), self.assertRaises(BatchRuntimeError):
                    self.predict(runtime, np.ones((1, 4)), router_scores=scores)
        self.assertEqual(runtime.router.runtime.dispatch_calls, 0)

    def test_selective_routing_keeps_unserved_slots_distinct_and_cache_repeats_exactly(self):
        first, second = self.head(), self.head(offset=.2)
        runtime = self.runtime([first, first, second], [self.fit(first)] * 2 + [self.fit(second)], cache_bytes=96)
        scores = np.array([[2., 1.], [1., 2.], [2., 1.]])
        result = self.predict(runtime, top_k=1, router_scores=scores)
        valid = result["served_mask"]
        np.testing.assert_array_equal(valid, [[True, True, False], [False, False, True], [True, True, False]])
        self.assertTrue((result["probabilities"][~valid] == 0).all())
        self.assertTrue((result["predictions"][~valid] == -1).all())
        self.assertFalse(result["classification_accepted_mask"][~valid].any())
        self.assertFalse(result["positive_action_mask"][~valid].any())
        cached = runtime.predict_cached(SOURCES, feature_identity=IDENTITY, generation=1, top_k=1, router_scores=scores)
        np.testing.assert_array_equal(result["probabilities"], cached["probabilities"])
        self.assertTrue(result["classification_accepted_mask"][1, 2])
        self.assertFalse(result["positive_action_mask"][1, 2])

    def test_cache_misses_and_same_source_with_changed_values_fail_explicitly(self):
        head = self.head()
        runtime = self.runtime([head], [self.fit(head)], cache_bytes=32)
        self.predict(runtime)
        with self.assertRaisesRegex(BatchRuntimeError, "cache miss"):
            runtime.predict_cached(SOURCES[:1], feature_identity=IDENTITY, generation=1)
        with self.assertRaisesRegex(BatchRuntimeError, "different features"):
            runtime.predict(np.ones((1, 4)), source_digests=SOURCES[2:], feature_identity=IDENTITY, generation=1)
        self.assertEqual(runtime.router.runtime.dispatch_calls, 1)

    def test_prior_zero_evidence_symmetric_extremes_and_masks_preserve_calibrator_contract(self):
        head = self.head()
        head.params["W"][:, 1] *= 1e150
        self.receipt(head)
        fit = self.fit(head, mode="complement_symmetric")
        result = self.predict(self.runtime([head], [fit]))
        p = result["probabilities"][:, 0]
        np.testing.assert_array_equal(p[0], p[1, ::-1])
        np.testing.assert_array_equal(p[2], fit["prior"])
        self.assertGreaterEqual(float(p[:, 1].min()), fit["positive_probability_bounds"][0] - 1e-15)
        self.assertLessEqual(float(p[:, 1].max()), fit["positive_probability_bounds"][1] + 1e-15)
        prior = self.fit(head, prior_only=True)
        result = self.predict(self.runtime([head], [prior]))
        np.testing.assert_array_equal(result["probabilities"][:, 0], np.tile(prior["prior"], (3, 1)))

    def test_nonshadow_or_boolean_calibration_and_metadata_budgets_reject(self):
        head = self.head()
        original = self.fit(head)
        for key, value in (("fit_role", "holdout"), ("holdout_supplied_to_fit", True),
                           ("quality_qualified", True), ("authority", "ALLOW"),
                           ("alpha", True), ("training_log_odds", False), ("alpha", float("nan"))):
            fitted = copy.deepcopy(original)
            fitted[key] = value
            with self.subTest(key=key, value=value), self.assertRaises(BatchRuntimeError):
                self.runtime([head], [fitted])
        for limit in ("MAX_CALIBRATION_RECORD_BYTES", "MAX_UNIQUE_CALIBRATION_BYTES"):
            with patch(f"bounded_cell_runtime.{limit}", 1), self.assertRaisesRegex(BatchRuntimeError, "budget"):
                self.runtime([head], [original])


if __name__ == "__main__":
    unittest.main()
