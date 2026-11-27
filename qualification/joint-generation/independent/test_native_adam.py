"""Hand-array bitwise proofs for adaptation Adam; no experiment data."""

import copy
import ctypes
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

import numpy as np

from independent.learning import CONTENT_PARAMETERS
from independent.native_adam import NativeAdam, setup_work
from model import JointModel


def gradients(model, step):
    rng = np.random.default_rng(17000 + step)
    factor = (0.0, 1e-12, 0.05, 20.0)[step % 4]
    result = {}
    order = CONTENT_PARAMETERS if step % 2 else CONTENT_PARAMETERS[::-1]
    for key in order:
        shape = model.params[key].shape
        value = rng.normal(size=shape) * factor
        if step % 3 == 0:
            storage = np.empty((2 * shape[0],) + shape[1:])
            storage[::2] = value
            value = storage[::2]
        elif step % 3 == 1:
            value = value.astype(np.float32)
        result[key] = value
    return result


class NativeAdamTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory(prefix="hepta-native-adam-unit-")
        cls.library = Path(cls.temporary.name) / "adam.so"
        source = Path(__file__).with_name("native.c")
        compiler = shutil.which("cc")
        if compiler is None:
            raise RuntimeError("native Adam unit proof requires configured cc")
        command = [compiler, "-O3", "-std=c11", "-ffp-contract=off", "-shared", "-fPIC",
                   str(source), "-o", str(cls.library), "-lm"]
        result = subprocess.run(command, capture_output=True, text=True)
        if result.returncode:
            raise RuntimeError("unit library compile failed: " + result.stdout + result.stderr)

    @classmethod
    def tearDownClass(cls):
        cls.temporary.cleanup()

    def assert_state(self, actual, expected):
        self.assertEqual(actual.updates, expected.updates)
        self.assertEqual(set(actual.params), set(expected.params))
        self.assertEqual(set(actual._moments), set(expected._moments))
        for key in actual.params:
            np.testing.assert_array_equal(actual.params[key], expected.params[key])
            self.assertEqual(actual.params[key].tobytes(order="C"),
                             expected.params[key].tobytes(order="C"), key)
        for key, (m, v, clock) in actual._moments.items():
            em, ev, ec = expected._moments[key]
            np.testing.assert_array_equal(m, em)
            np.testing.assert_array_equal(v, ev)
            self.assertEqual(m.tobytes(order="C"), em.tobytes(order="C"), key + " first moment")
            self.assertEqual(v.tobytes(order="C"), ev.tobytes(order="C"), key + " second moment")
            self.assertEqual(clock, ec)

    def model(self, mixed):
        model = JointModel(202, 12, 192, hidden=32, seed=1701)
        if mixed:
            for index, key in enumerate(CONTENT_PARAMETERS):
                for _ in range(index % 3 + 1):
                    model.apply_gradients({key: np.full_like(model.params[key], .001)}, .002)
            model.apply_gradients({"decoder": np.full_like(model.params["decoder"], .003)}, .001)
        return model

    def test_one_eight_and_sixty_four_updates_are_bitwise_with_mixed_clocks(self):
        for updates in (1, 8, 64):
            for mixed in (False, True):
                with self.subTest(updates=updates, mixed_clocks=mixed):
                    actual = self.model(mixed)
                    expected = copy.deepcopy(actual)
                    before_keys = set(actual._moments)
                    adapter = NativeAdam(actual, self.library)
                    self.assertEqual(set(actual._moments), before_keys)
                    for step in range(updates):
                        grads = gradients(actual, step)
                        untouched = {key: value.copy() for key, value in grads.items()}
                        expected.apply_gradients(grads, .003)
                        adapter.apply_gradients(actual, grads, .003)
                        self.assert_state(actual, expected)
                        for key, value in grads.items():
                            np.testing.assert_array_equal(value, untouched[key])

    def test_bad_late_gradient_or_bound_state_rejects_atomically(self):
        model = self.model(False)
        adapter = NativeAdam(model, self.library)
        valid = gradients(model, 2)
        for error in ("nan", "shape", "missing", "unknown", "alias", "lr"):
            with self.subTest(error=error):
                grads = {key: value.copy() for key, value in valid.items()}
                if error == "nan": grads["image_bias"][-1] = np.nan
                if error == "shape": grads["image_bias"] = np.zeros(11)
                if error == "missing": del grads["image_bias"]
                if error == "unknown": grads["unknown"] = np.zeros(12)
                if error == "alias": grads["image_bias"] = model.params["image_bias"]
                before = copy.deepcopy(model)
                with self.assertRaises(ValueError):
                    adapter.apply_gradients(model, grads, 0.0 if error == "lr" else .003)
                self.assert_state(model, before)
        adapter.apply_gradients(model, valid, .003)
        for change in ("rebind", "readonly", "shape", "clock", "other_model"):
            with self.subTest(change=change):
                param = model.params["image_bias"]
                moment = model._moments["image_bias"]
                if change == "rebind": model.params["image_bias"] = param.copy()
                if change == "readonly": param.flags.writeable = False
                if change == "shape": param.shape = (3, 4)
                if change == "clock": model._moments["image_bias"] = (moment[0], moment[1], moment[2] + 1)
                before = copy.deepcopy(model)
                with self.assertRaises(ValueError):
                    adapter.apply_gradients(copy.deepcopy(model) if change == "other_model" else model, valid, .003)
                self.assert_state(model, before)
                model.params["image_bias"] = param
                param.flags.writeable = True
                param.shape = (12,)
                model._moments["image_bias"] = moment

    def test_constructor_work_and_c_abi_late_rejection(self):
        model = self.model(False)
        elements = sum(model.params[key].size for key in CONTENT_PARAMETERS)
        self.assertEqual(elements, 7288)
        self.assertEqual(setup_work(model), {"compare_ops": elements})
        adapter = NativeAdam(model, self.library)
        grads = gradients(model, 2)
        adapter.apply_gradients(model, grads, .003)
        self.assertEqual(setup_work(model), {"compare_ops": 3 * elements})
        self.assertEqual(setup_work(model, empty_moments=True), {"compare_ops": elements})
        double = ctypes.POINTER(ctypes.c_double)
        pointers = (double * 6)(*(np.ascontiguousarray(grads[key]).ctypes.data_as(double)
                                 for key in CONTENT_PARAMETERS))
        corrections = (ctypes.c_double * 6)(*[.1] * 5, 0.0)
        before = copy.deepcopy(model)
        status = adapter._function(6, adapter._parameter_pointers, adapter._first_pointers,
            adapter._second_pointers, pointers, adapter._sizes, corrections,
            (ctypes.c_double * 6)(*[.001] * 6), 1.0, .003)
        self.assertEqual(status, 1)
        self.assert_state(model, before)
        invalid = self.model(False)
        invalid.params["image_bias"][-1] = np.nan
        with self.assertRaises(ValueError):
            NativeAdam(invalid, self.library)
        invalid = self.model(False)
        invalid.params["image"] = invalid.params["text"]
        with self.assertRaises(ValueError):
            NativeAdam(invalid, self.library)


if __name__ == "__main__":
    unittest.main()
