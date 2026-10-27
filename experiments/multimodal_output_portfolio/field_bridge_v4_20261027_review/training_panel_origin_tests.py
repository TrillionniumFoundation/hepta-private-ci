"""Synthetic contracts for the fixed panel-origin transformation."""
import argparse
import hashlib
import json
from pathlib import Path
import time
import unittest

import numpy as np

from training_panel_origin import PANEL_INDICES, fit_origin, translate


class OriginContracts(unittest.TestCase):
    def setUp(self):
        self.rng = np.random.default_rng(271040)
        self.raw = self.rng.normal(size=(7, 30))
        self.initial = self.rng.normal(size=30)
        self.reference = self.rng.normal(size=30)

    def test_same_origin_is_exact_identity_and_does_not_alias(self):
        source = self.raw.copy()
        result = translate(self.raw, self.initial, self.initial)
        np.testing.assert_array_equal(result, source)
        result[0, 0] += 1
        np.testing.assert_array_equal(self.raw, source)

    def test_additive_panel_context_shift_is_cancelled(self):
        shift = np.zeros(30)
        shift[list(PANEL_INDICES)] = self.rng.normal(size=len(PANEL_INDICES)) * 20
        left = translate(self.raw, self.initial, self.reference)
        right = translate(self.raw + shift, self.initial + shift, self.reference)
        np.testing.assert_allclose(left, right, atol=1e-13, rtol=0)
        weights = self.rng.normal(size=(30, 4))
        np.testing.assert_allclose(left @ weights, right @ weights, atol=1e-12, rtol=0)
        np.testing.assert_array_equal(np.argmax(left @ weights, axis=1),
                                      np.argmax(right @ weights, axis=1))

    def test_physical_state_and_direction_coordinates_are_unchanged(self):
        untouched = [i for i in range(30) if i not in PANEL_INDICES]
        result = translate(self.raw, self.initial, self.reference)
        np.testing.assert_array_equal(result[:, untouched], self.raw[:, untouched])
        np.testing.assert_array_equal(
            translate(self.raw[2], self.initial, self.reference), result[2])

    def test_all_inputs_can_be_readonly_and_are_preserved(self):
        baseline, reference, values = self.initial.copy(), self.reference.copy(), self.raw.copy()
        for value in (self.initial, self.reference, self.raw):
            value.flags.writeable = False
        translate(self.raw, self.initial, self.reference)
        np.testing.assert_array_equal(self.initial, baseline)
        np.testing.assert_array_equal(self.reference, reference)
        np.testing.assert_array_equal(self.raw, values)

    def test_fit_origin_requires_exact_common_panel_context(self):
        records = []
        for trajectory in range(4):
            state = self.initial.copy()
            state[7] += trajectory
            records.append({"trajectory": trajectory, "step": 0, "state": state.tolist()})
        bank = {"schema": "hepta.field-bridge.v3.terminal-reference-bank.1", "records": records}
        np.testing.assert_array_equal(fit_origin(bank)[list(PANEL_INDICES)],
                                      self.initial[list(PANEL_INDICES)])
        records[2]["state"][3] += 1e-12
        with self.assertRaises(ValueError):
            fit_origin(bank)
        bank["records"] = bank["records"][:3]
        with self.assertRaises(ValueError):
            fit_origin(bank)

    def test_invalid_shapes_or_nonfinite_inputs_are_rejected(self):
        for value in (np.ones(29), np.ones((2, 3, 30)), np.full(30, np.nan), np.full(30, np.inf)):
            with self.assertRaises(ValueError):
                translate(value, self.initial, self.reference)
        for value in (np.ones((1, 30)), np.full(30, np.nan)):
            with self.assertRaises(ValueError):
                translate(self.raw, value, self.reference)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise ValueError("Refusing to overwrite a contract result")
    start = time.perf_counter_ns()
    result = unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(OriginContracts))
    root = Path(__file__).parent
    record = {"schema": "hepta.field-bridge.v4.panel-origin-contract.1",
              "passed": result.wasSuccessful(), "tests_run": result.testsRun,
              "failures": len(result.failures), "errors": len(result.errors),
              "synthetic_only": True, "scientific_model_observer_native_network_calls": 0,
              "source_files": {name: hashlib.sha256((root / name).read_bytes()).hexdigest()
                               for name in ("training_panel_origin.py", "training_panel_origin_tests.py")},
              "wall_ns": time.perf_counter_ns() - start}
    with args.output.open("x") as stream:
        json.dump(record, stream, indent=2, sort_keys=True)
        stream.write("\n")
    if not result.wasSuccessful():
        raise SystemExit(1)
