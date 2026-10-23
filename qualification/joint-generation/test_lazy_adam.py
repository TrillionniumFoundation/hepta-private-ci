import unittest
from unittest.mock import patch
import numpy as np
from model import JointModel


def eager_adam_reference(model, grads, lr):
    if not np.isfinite(lr) or not 0 < lr <= 1 or not grads:
        raise ValueError("invalid optimizer step")
    clean = {}
    for key, grad in grads.items():
        g = np.asarray(grad, dtype=np.float64)
        if key not in model.params or g.shape != model.params[key].shape or not np.isfinite(g).all():
            raise ValueError("invalid parameter gradient")
        clean[key] = g
    norm = np.sqrt(sum(float(np.sum(g * g)) for g in clean.values()))
    scale = min(1.0, 5.0 / max(norm, 1e-300))
    for key, g in clean.items():
        m, v, step = model._moments.get(key, (np.zeros_like(g), np.zeros_like(g), 0))
        g = g * scale
        m, v, step = 0.9 * m + 0.1 * g, 0.999 * v + 0.001 * g * g, step + 1
        model.params[key] -= lr * (m / (1 - 0.9 ** step)) / (np.sqrt(v / (1 - 0.999 ** step)) + 1e-8)
        model._moments[key] = (m, v, step)
    model.updates += 1


class LazyAdamTests(unittest.TestCase):
    def test_all_parameter_groups_clipping_and_parameter_clocks_match_eager_reference_bitwise(self):
        actual, expected = JointModel(4, 3, 6, hidden=5, seed=19), JointModel(4, 3, 6, hidden=5, seed=19)
        rng = np.random.default_rng(27)
        content = ("encoder", "bias", "text", "text_bias", "image", "image_bias")
        decoder = ("decoder", "decoder_bias")
        def gradients(keys, scale):
            return {key: rng.normal(size=actual.params[key].shape) * scale for key in keys}
        sequence = [gradients(decoder, .001), gradients(content, .002), gradients(decoder, 50),
                    gradients(("encoder", "text_bias", "decoder"), 40),
                    {key: np.zeros_like(value) for key, value in actual.params.items()},
                    gradients(tuple(actual.params), 1e-12), gradients(("image_bias",), .01)]
        parameter_steps = {key: 0 for key in actual.params}
        self.assertGreater(np.sqrt(sum(float(np.sum(g * g)) for g in sequence[2].values())), 5)
        for index, grads in enumerate(sequence, 1):
            before = {key: value.copy() for key, value in grads.items()}
            actual.apply_gradients(grads, .003)
            eager_adam_reference(expected, grads, .003)
            self.assertEqual(actual.updates, index)
            self.assertEqual(actual._moments.keys(), expected._moments.keys())
            for key in grads:
                parameter_steps[key] += 1
                np.testing.assert_array_equal(grads[key], before[key])
            for key in actual.params:
                np.testing.assert_array_equal(actual.params[key], expected.params[key])
            for key, (m, v, step) in actual._moments.items():
                em, ev, es = expected._moments[key]
                np.testing.assert_array_equal(m, em)
                np.testing.assert_array_equal(v, ev)
                self.assertEqual(step, es)
                self.assertEqual(step, parameter_steps[key])

    def test_zero_moment_arrays_are_allocated_once_for_each_first_updated_parameter(self):
        model = JointModel(4, 3, 6, hidden=5, seed=19)
        content = {key: np.full_like(value, .01) for key, value in model.params.items()
                   if key not in ("decoder", "decoder_bias")}
        decoder = {key: np.full_like(model.params[key], .01) for key in ("decoder", "decoder_bias")}
        zeros = np.zeros_like
        with patch("model.np.zeros_like", wraps=zeros) as allocations:
            model.apply_gradients(content, .003)
            self.assertEqual(allocations.call_count, 12)
            model.apply_gradients(content, .003)
            self.assertEqual(allocations.call_count, 12)
            model.apply_gradients(decoder, .003)
            self.assertEqual(allocations.call_count, 16)
            model.apply_gradients({**content, **decoder}, .003)
            self.assertEqual(allocations.call_count, 16)
        self.assertEqual(model.updates, 4)
        self.assertTrue(all(model._moments[key][2] == 3 for key in content))
        self.assertTrue(all(model._moments[key][2] == 2 for key in decoder))

    def test_invalid_gradient_batch_remains_atomic_before_any_moment_allocation(self):
        model = JointModel(4, 3, 6, hidden=5, seed=19)
        before = model.digest()
        first = np.ones_like(model.params["encoder"])
        with patch("model.np.zeros_like", side_effect=AssertionError("unadmitted allocation")):
            for grads, lr in (({"encoder": first, "image_bias": np.zeros(1)}, .003),
                              ({"encoder": first, "decoder_bias": np.full(6, np.nan)}, .003),
                              ({"unknown": np.zeros(1)}, .003), ({"encoder": first}, 0.0), ({}, .003)):
                with self.assertRaises(ValueError):
                    model.apply_gradients(grads, lr)
                self.assertEqual(model.digest(), before)
                self.assertEqual(model.updates, 0)
                self.assertEqual(model._moments, {})
