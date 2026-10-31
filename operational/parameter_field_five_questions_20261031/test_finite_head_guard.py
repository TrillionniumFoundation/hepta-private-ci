"""Synthetic-only tests; imports one exact frozen heads.py, no torch or data."""

import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import pickle
import random
from types import FunctionType, SimpleNamespace
import unittest

import numpy as np

from finite_head_guard import (
    FROZEN_HEADS_SHA256, HeadIntegrityError, guarded_choose, make_guarded_choose,
    installed_choose_guard,
)


FROZEN = None


def fixed_head(scores=(0., 0., 0., 0.), threshold=0., baseline=2):
    return {"mean": np.zeros(1), "scale": np.ones(1),
            "coefficients": np.zeros((1, 4)), "intercept": np.asarray(scores, dtype=float),
            "threshold": float(threshold), "baseline": baseline,
            "fit_max_standardized_norm": 1.}


class FiniteHeadGuardTests(unittest.TestCase):
    def test_exact_frozen_source_reproduces_finite_multiplication_overflow(self):
        head = fixed_head()
        head["coefficients"][0, 0] = 1e308
        feature = np.array([2.])
        self.assertTrue(np.isfinite(head["coefficients"]).all())
        self.assertTrue(np.isfinite(feature).all())
        with np.errstate(over="ignore", invalid="ignore"):
            action, receipt = FROZEN.choose(head, feature)
        self.assertEqual(action, 0)
        self.assertTrue(receipt["override"])
        self.assertTrue(np.isposinf(receipt["predicted_margin"]))

    def test_overflow_stops_before_transition_in_explicit_binding(self):
        head = fixed_head()
        head["coefficients"][0, 0] = 1e308
        choose = make_guarded_choose(FROZEN.choose)
        transitions = []
        with self.assertRaises(HeadIntegrityError):
            action, receipt = choose(head, [2.])
            transitions.append(action)
        self.assertEqual(transitions, [])

    def test_standardization_and_norm_overflow_stop(self):
        head = fixed_head()
        head["mean"][0] = -1e308
        with self.assertRaises(HeadIntegrityError):
            guarded_choose(FROZEN.choose, head, [1e308])
        with self.assertRaises(HeadIntegrityError):
            guarded_choose(FROZEN.choose, fixed_head(), [1e200])

    def test_invalid_head_stops_before_original_is_called(self):
        changes = ({"scale": np.array([0.])}, {"scale": np.array([-1.])},
                   {"scale": np.array([np.inf])}, {"mean": np.array([np.nan])},
                   {"coefficients": np.array([[np.nan, 0., 0., 0.]])},
                   {"coefficients": np.zeros((2, 4))},
                   {"threshold": np.nan}, {"threshold": -1.},
                   {"fit_max_standardized_norm": np.inf}, {"baseline": True})
        calls = []
        def should_not_run(*args):
            calls.append(args)
            raise AssertionError("Invalid head reached original chooser")
        for change in changes:
            with self.subTest(change=str(change)):
                with self.assertRaises(HeadIntegrityError):
                    guarded_choose(should_not_run, {**fixed_head(), **change}, [0.])
        self.assertEqual(calls, [])

    def test_postcheck_rejects_nonfinite_receipt_without_arithmetic_warning(self):
        def malformed(*args):
            action, receipt = FROZEN.choose(*args)
            receipt["predicted_advantages"][0] = np.inf
            return action, receipt
        with self.assertRaises(HeadIntegrityError):
            guarded_choose(malformed, fixed_head(), [0.])

    def test_valid_boundary_results_and_inputs_are_exactly_preserved(self):
        cases = (([.5, .4, 0., -.1], .5),
                 ([.5, .4, 0., -.1], np.nextafter(.5, 0.)),
                 ([.5, .5, 0., -.1], .1),
                 ([0., 0., 0., 0.], 0.),
                 ([-1., -2., 0., -3.], 0.))
        for scores, threshold in cases:
            head, feature = fixed_head(scores, threshold), np.array([0.])
            before = pickle.dumps((head, feature, np.random.get_state(), random.getstate()))
            expected = FROZEN.choose(head, feature)
            actual = guarded_choose(FROZEN.choose, head, feature)
            self.assertEqual(json.dumps(actual, sort_keys=True, allow_nan=False),
                             json.dumps(expected, sort_keys=True, allow_nan=False))
            self.assertEqual(before, pickle.dumps((head, feature, np.random.get_state(), random.getstate())))
        head = fixed_head([.7, .2, .1, 0.], .5, baseline=3)
        self.assertEqual(guarded_choose(FROZEN.choose, head, [0.], 3), FROZEN.choose(head, [0.], 3))

    def test_original_called_once_and_result_returned_without_replacement(self):
        result = FROZEN.choose(fixed_head(), [0.])
        calls = []
        def original(*args):
            calls.append(args)
            return result
        self.assertIs(guarded_choose(original, fixed_head(), [0.]), result)
        self.assertEqual(len(calls), 1)

    def test_numpy_error_policy_is_restored(self):
        before = np.geterr().copy()
        guarded_choose(FROZEN.choose, fixed_head(), [0.])
        self.assertEqual(before, np.geterr())
        head = fixed_head()
        head["coefficients"][0, 0] = 1e308
        with self.assertRaises(HeadIntegrityError):
            guarded_choose(FROZEN.choose, head, [2.])
        self.assertEqual(before, np.geterr())

    def test_context_installation_restores_binding_on_success_and_failure(self):
        run = SimpleNamespace(choose=FROZEN.choose)
        with installed_choose_guard(run, FROZEN) as receipt:
            self.assertIsNot(run.choose, FROZEN.choose)
            self.assertEqual(run.choose(fixed_head(), [0.]), FROZEN.choose(fixed_head(), [0.]))
        self.assertIs(run.choose, FROZEN.choose)
        self.assertEqual((receipt["attempted_calls"], receipt["admitted_calls"], receipt["failed_calls"]), (1, 1, 0))
        with self.assertRaises(HeadIntegrityError):
            with installed_choose_guard(run, FROZEN) as failure:
                head = fixed_head()
                head["coefficients"][0, 0] = 1e308
                run.choose(head, [2.])
        self.assertIs(run.choose, FROZEN.choose)
        self.assertEqual((failure["attempted_calls"], failure["admitted_calls"], failure["failed_calls"]), (1, 0, 1))

    def test_context_rejects_in_memory_choose_and_predict_replacement(self):
        for name in ("choose", "predict"):
            previous = getattr(FROZEN, name)
            try:
                setattr(FROZEN, name, lambda *args: None)
                run = SimpleNamespace(choose=FROZEN.choose)
                with self.subTest(name=name), self.assertRaises(HeadIntegrityError):
                    with installed_choose_guard(run, FROZEN):
                        self.fail("Mismatched loaded code was admitted")
            finally:
                setattr(FROZEN, name, previous)

    def test_context_rejects_identical_code_with_different_globals(self):
        previous = FROZEN.choose
        try:
            FROZEN.choose = FunctionType(previous.__code__, dict(previous.__globals__),
                                         previous.__name__, previous.__defaults__)
            run = SimpleNamespace(choose=FROZEN.choose)
            with self.assertRaises(HeadIntegrityError):
                with installed_choose_guard(run, FROZEN):
                    self.fail("Foreign globals were admitted")
        finally:
            FROZEN.choose = previous

    def test_context_rejects_aliased_target_module(self):
        original = FROZEN.choose
        with self.assertRaises(HeadIntegrityError):
            with installed_choose_guard(FROZEN, FROZEN):
                self.fail("Aliased target was admitted")
        self.assertIs(FROZEN.choose, original)

    def test_context_binding_tamper_restores_then_fails(self):
        run = SimpleNamespace(choose=FROZEN.choose)
        with self.assertRaises(HeadIntegrityError):
            with installed_choose_guard(run, FROZEN) as receipt:
                run.choose = lambda *args: None
        self.assertIs(run.choose, FROZEN.choose)
        self.assertTrue(receipt["binding_tampered"])


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--frozen-heads", type=Path, required=True)
    args, remaining = parser.parse_known_args()
    source = args.frozen_heads.read_bytes()
    if hashlib.sha256(source).hexdigest() != FROZEN_HEADS_SHA256:
        raise SystemExit("Refusing nonidentical frozen heads.py")
    spec = importlib.util.spec_from_file_location("exact_frozen_heads", args.frozen_heads)
    FROZEN = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(FROZEN)
    unittest.main(argv=[__file__, *remaining])
