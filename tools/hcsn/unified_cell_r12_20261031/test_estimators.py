"""Independent whole-sequence derivative and causal-inference audit.

The finite differences here audit one fixed loss; optimizers never call them.
Fixtures contain real latent transitions, READ, WAIT, action RESET and the
recovery-only symbol. They therefore test propagation of derivatives through
history, rather than an isolated output head or one time step.
"""

import unittest

import numpy as np
from scipy.linalg import expm

from .cell import Cell, DEFAULT_EMISSIONS
from .estimators import HXFilter, loss_and_logit_gradient, posterior_ce, restore_model
from .recurrent import RecurrentEstimator


def causal_fixture():
    """Generate a small exact finite-model path and its independent Bayes target."""
    world = Cell()
    rng = np.random.default_rng(29117)
    batch, length = 3, 9
    inputs = np.zeros((batch, length, 10))
    teacher = np.zeros((batch, length, 20))
    labels = np.zeros((batch, length), dtype=np.int64)
    actions = ["READ", "WAIT", "RESET", "READ", "WAIT", "READ", "RESET", "READ", "READ"]
    durations = [.15, .45, .15, .15, 1.05, .45, .15, .15, .45]
    transitions = {dt: expm(dt * world.Q) for dt in set(durations)}
    for b in range(batch):
        p = world.prior.copy()
        state = int(rng.choice(20, p=world.prior))
        for t, (action, dt) in enumerate(zip(actions, durations)):
            inputs[b, t, 8] = dt
            if action == "RESET":
                inputs[b, t, 9] = 1
                state = int(np.argmax(world.R[state]))
                p = p @ world.R
            state = int(rng.choice(20, p=transitions[dt][state]))
            p = p @ transitions[dt]
            if action == "READ":
                token = int(rng.choice(7, p=world.E[state]))
                inputs[b, t, token] = 1
                inputs[b, t, 7] = 1
                p = p * world.E[:, token]
                p /= p.sum()
            teacher[b, t] = p
            labels[b, t] = state % 2
    if not np.any(inputs[..., 6] == 1):
        raise AssertionError("Fixture must include an actual recovery observation")
    return inputs, teacher, labels


def independent_loss(probabilities, teacher, labels):
    """CE evaluated only on positive target support, without a probability floor."""
    count = labels.size
    used = teacher > 0
    if np.any(probabilities[used] <= 0):
        raise FloatingPointError("Positive teacher mass has zero prediction support")
    joint = -np.sum(teacher[used] * np.log(probabilities[used])) / count
    label_probability = np.empty(labels.shape)
    for index in np.ndindex(labels.shape):
        label_probability[index] = probabilities[index][int(labels[index])::2].sum()
    if np.any(label_probability <= 0):
        raise FloatingPointError("Current label has zero prediction support")
    return float(joint - .25 * np.mean(np.log(label_probability)))


def finite_difference(model, inputs, teacher, labels, name, index, epsilon=2e-6):
    original = model.params[name][index]
    losses = []
    try:
        for sign in (1, -1):
            model.params[name][index] = original + sign * epsilon
            losses.append(independent_loss(model.forward(inputs), teacher, labels))
    finally:
        model.params[name][index] = original
    return (losses[0] - losses[1]) / (2 * epsilon)


class EstimatorGradientTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.inputs, cls.teacher, cls.labels = causal_fixture()

    def test_hx_all_fifteen_parameters_on_complete_causal_sequence(self):
        model = HXFilter(seed=512)
        loss, gradients = model.loss_grad(self.inputs, self.teacher, self.labels)
        self.assertAlmostEqual(loss, independent_loss(model.forward(self.inputs), self.teacher, self.labels), places=13)
        self.assertTrue(np.isfinite(loss))
        for name, parameter in model.params.items():
            for index in np.ndindex(parameter.shape):
                numeric = finite_difference(model, self.inputs, self.teacher, self.labels, name, index)
                with self.subTest(block=name, index=index):
                    np.testing.assert_allclose(gradients[name][index], numeric, rtol=4e-5, atol=3e-7)
        self.assertGreater(np.linalg.norm(gradients["physical_raw"]), 1e-5)
        self.assertGreater(np.linalg.norm(gradients["emission_logits"]), 1e-5)

    def test_all_recurrent_parameter_blocks_have_whole_sequence_gradients(self):
        for kind in ("gru", "continuous_diagonal_ssm"):
            model = RecurrentEstimator(kind, seed=513)
            loss, gradients = model.loss_grad(self.inputs, self.teacher, self.labels)
            self.assertAlmostEqual(loss, independent_loss(model.forward(self.inputs), self.teacher, self.labels), places=13)
            rng = np.random.default_rng(9301)
            for name, parameter in model.params.items():
                # Three independently selected entries in every parameter block.
                for flat in rng.choice(parameter.size, size=min(3, parameter.size), replace=False):
                    index = np.unravel_index(int(flat), parameter.shape)
                    numeric = finite_difference(model, self.inputs, self.teacher, self.labels, name, index)
                    with self.subTest(kind=kind, block=name, index=index):
                        np.testing.assert_allclose(gradients[name][index], numeric, rtol=5e-5, atol=3e-8)
            recurrent = ["Uz", "Ur", "Un"] if kind == "gru" else ["rate"]
            self.assertGreater(sum(np.linalg.norm(gradients[k]) for k in recurrent), 1e-6)

    def test_zero_teacher_entries_are_legitimate_structural_zeros(self):
        model = HXFilter(seed=514)
        output = model.forward(self.inputs)
        self.assertGreater(np.count_nonzero(output == 0), 0)
        self.assertGreater(np.count_nonzero(self.teacher == 0), 0)
        self.assertFalse(np.any((self.teacher > 0) & (output <= 0)))
        loss, gradient = model.loss_grad(self.inputs, self.teacher, self.labels)
        self.assertTrue(np.isfinite(loss))
        self.assertTrue(all(np.isfinite(g).all() for g in gradient.values()))
        expected = -np.sum(self.teacher[self.teacher > 0] * np.log(output[self.teacher > 0])) / self.labels.size
        self.assertAlmostEqual(posterior_ce(output, self.teacher), expected, places=13)

    def test_positive_teacher_mass_outside_prediction_support_rejects(self):
        p = np.zeros((1, 1, 20))
        p[0, 0, 0] = 1
        target = p.copy()
        target[0, 0, 0] = .5
        target[0, 0, 1] = .5
        with self.assertRaises((ValueError, FloatingPointError)):
            loss_and_logit_gradient(p, target, np.zeros((1, 1), dtype=int))
        with self.assertRaises((ValueError, FloatingPointError)):
            posterior_ce(p, target)

    def test_batch_stream_and_prefix_causality(self):
        models = [HXFilter(seed=515), RecurrentEstimator("gru", seed=515),
                  RecurrentEstimator("continuous_diagonal_ssm", seed=515)]
        for model in models:
            with self.subTest(kind=model.kind):
                batched = model.forward(self.inputs)
                for b in range(len(self.inputs)):
                    model.start()
                    streamed = np.array([model.step(row) for row in self.inputs[b]])
                    np.testing.assert_allclose(streamed, batched[b], rtol=4e-13, atol=3e-14)
                altered = self.inputs.copy()
                cut = 4
                altered[:, cut:, :7] = altered[:, cut:, :7][..., [1, 0, 3, 2, 5, 4, 6]]
                altered[:, cut:, 8] = .75
                altered[:, cut:, 9] = 1 - altered[:, cut:, 9]
                other = model.forward(altered)
                np.testing.assert_array_equal(other[:, :cut], batched[:, :cut])
                np.testing.assert_allclose(model.forward(self.inputs[:, :cut]), batched[:, :cut],
                                           rtol=3e-13, atol=3e-14)
                self.assertGreater(np.max(np.abs(other[:, cut:] - batched[:, cut:])), 1e-5)

    def test_initialization_and_export_preserve_real_parameters(self):
        for make in (lambda: HXFilter(seed=516), lambda: RecurrentEstimator("gru", seed=516),
                     lambda: RecurrentEstimator("continuous_diagonal_ssm", seed=516)):
            model, duplicate = make(), make()
            for key in model.params:
                np.testing.assert_array_equal(model.params[key], duplicate.params[key])
            payload = model.export()
            self.assertEqual(payload["parameter_count"], sum(v.size for v in model.params.values()))
            restored = restore_model(payload)
            np.testing.assert_array_equal(restored.forward(self.inputs), model.forward(self.inputs))
            initial = model.start()
            before = model.current.copy()
            initial[:] = 0
            np.testing.assert_array_equal(model.current, before)
        candidate = HXFilter(seed=516)
        candidate.build_cell()
        self.assertGreater(np.max(np.abs(candidate.cell.active_emissions - DEFAULT_EMISSIONS)), .05)
        jacobians = candidate.cell.parameter_jacobians()
        self.assertEqual(jacobians["prior"].shape, (15, 20))
        self.assertEqual(jacobians["E"].shape, (15, 20, 7))
        np.testing.assert_array_equal(jacobians["prior"][:3], candidate.cell.dprior)
        np.testing.assert_array_equal(jacobians["prior"][3:], np.zeros((12, 20)))
        np.testing.assert_array_equal(jacobians["E"][3:], candidate.cell.dE_logits)


if __name__ == "__main__":
    unittest.main()
