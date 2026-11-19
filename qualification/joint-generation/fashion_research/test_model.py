"""Synthetic-array model checks; fixed finite-difference tolerances declared first."""

import copy
from decimal import Decimal, localcontext
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import numpy as np

from fashion_research.autodiff import Tensor, posterior
from fashion_research.model import Actor, ContentModel, categorical_ce, construct, joint_risk


MODULES = ("C", "T_initial", "I_initial", "text_head", "image_head", "qT", "qI",
           "feedback", "T_update", "I_update")
FD_EPS, FD_ATOL, FD_RTOL = 1e-6, 2e-6, 2e-4


def fixture(rows=1):
    rng = np.random.default_rng(3151)
    z = rng.uniform(.2, .8, (rows, 784))
    clean = rng.uniform(.2, .8, (rows, 784))
    labels = np.arange(rows, dtype=np.int64) % 10
    noise = np.linspace(-.4, .4, rows * 4 * 784).reshape(rows, 4, 784)
    return z, clean, labels, noise


def content_loss(model, inputs, sequence="JJ", *, backward=True):
    z, clean, labels, noise = inputs
    method = model.loss_grad if backward else model.loss_value
    return method(z, clean, labels, sequence, np.random.default_rng(184), terminal_noise=noise)


class FashionModelTests(unittest.TestCase):
    def assert_prediction(self, actual, expected):
        for key in ("p", "mu", "image", "classes"):
            np.testing.assert_array_equal(getattr(actual, key), getattr(expected, key))

    def assert_fd(self, value, derivative):
        np.testing.assert_allclose(value, derivative, atol=FD_ATOL, rtol=FD_RTOL)

    def test_posterior_feedback_preserves_dominant_class_tail_gradient(self):
        logits = np.array([[50.] + [0.] * 9])
        x = Tensor(logits, True)
        p, _, _ = posterior(x)
        reference = np.exp(logits - logits.max(axis=-1, keepdims=True))
        reference /= reference.sum(axis=-1, keepdims=True)
        np.testing.assert_array_equal(p.data, reference)
        p[:, 0].sum().backward()
        tail = np.exp(-50.)
        expected = np.full((1, 10), -tail / (1 + 9 * tail)**2)
        expected[0, 0] *= -9
        self.assertEqual(p.data[0, 0], 1.)
        self.assertGreater(x.grad[0, 0], 0.)
        self.assertTrue(np.all(x.grad[0, 1:] < 0.))
        np.testing.assert_allclose(x.grad, expected, rtol=2e-13, atol=0)

    def test_joint_risk_value_and_vjp_match_explicit_marginal_finite_difference(self):
        logits = np.array([[.2, -.3, .7], [-.5, .4, .8]])
        quality = np.array([[.15, .25, .45, .65], [.2, .3, .5, .8]])
        labels = np.array([1, 2])
        z, q = Tensor(logits.copy(), True), Tensor(quality.copy(), True)
        p, shifted, _ = posterior(z)
        risk = joint_risk(shifted, p, q, labels)
        # Enumerate class and terminal outcomes, including zero utility for
        # incorrect classes. This oracle does not use the implementation VJP.
        utilities = np.zeros((2, 3, 4))
        utilities[np.arange(2), labels] = quality
        mixture = (p.data[:, :, None] * np.exp(-2 * utilities)).sum(axis=1).mean(axis=1)
        np.testing.assert_allclose(risk.data, -.5 * np.log(mixture), rtol=2e-13, atol=1e-15)
        risk.sum().backward()
        for array, gradient, is_logits in ((logits, z.grad, True), (quality, q.grad, False)):
            for index in np.ndindex(array.shape):
                def value(delta):
                    changed = array.copy()
                    changed[index] += delta
                    zz = Tensor(changed if is_logits else logits)
                    pp, ss, _ = posterior(zz)
                    qq = Tensor(quality if is_logits else changed)
                    return joint_risk(ss, pp, qq, labels).data.sum()
                self.assert_fd((value(FD_EPS) - value(-FD_EPS)) / (2 * FD_EPS), gradient[index])

    def test_extreme_risk_and_ce_preserve_tiny_values_and_tail_gradients(self):
        labels = np.array([1])
        quality = np.array([[1e-20, 2e-20, 3e-20, 4e-20]])
        for true_logit in (-50., 50.):
            with self.subTest(true_logit=true_logit):
                logits = np.array([[0., true_logit, 0.]])
                z, q = Tensor(logits, True), Tensor(quality, True)
                p, shifted, _ = posterior(z)
                risk = joint_risk(shifted, p, q, labels)
                risk.sum().backward()
                # Decimal80 enumerates the original expectation rather than
                # using log1p/expm1 or the source's factorized logits VJP.
                with localcontext() as ctx:
                    ctx.prec = 80
                    weights = [Decimal(str(v)).exp() for v in logits[0]]
                    probabilities = [w / sum(weights) for w in weights]
                    exponentials = [(-2 * Decimal(str(v))).exp() for v in quality[0]]
                    class_values = [Decimal(1), sum(exponentials) / 4, Decimal(1)]
                    normalization = sum(a * b for a, b in zip(probabilities, class_values))
                    expected_value = float(-normalization.ln() / 2)
                    expected_logits = [float(-prob * (value - normalization) / (2 * normalization))
                                       for prob, value in zip(probabilities, class_values)]
                    expected_q = [float(probabilities[1] * exp / (4 * normalization))
                                  for exp in exponentials]
                    expected_ce = float(-probabilities[1].ln())
                    ce_gradient = [probabilities[0], -(weights[0] + weights[2]) / sum(weights),
                                   probabilities[2]]
                self.assertGreater(risk.data.item(), 0)
                self.assertGreater(z.grad[0, 1], 0)
                self.assertTrue(np.all(z.grad[0, [0, 2]] < 0))
                self.assertTrue(np.all(q.grad > 0))
                np.testing.assert_allclose(risk.data, expected_value, rtol=2e-13, atol=0)
                np.testing.assert_allclose(z.grad[0], expected_logits, rtol=2e-13, atol=0)
                np.testing.assert_allclose(q.grad[0], expected_q, rtol=2e-13, atol=0)
                z = Tensor(logits, True)
                p, shifted, denominator = posterior(z)
                ce = categorical_ce(shifted, p, denominator, labels)
                ce.sum().backward()
                self.assertGreater(ce.data.item(), 0)
                self.assertLess(z.grad[0, 1], 0)
                self.assertTrue(np.all(z.grad[0, [0, 2]] > 0))
                np.testing.assert_allclose(ce.data, expected_ce, rtol=2e-13, atol=0)
                np.testing.assert_allclose(z.grad[0], [float(v) for v in ce_gradient], rtol=2e-13, atol=0)

    def test_clip_subgradient_is_zero_on_bounds_and_outside(self):
        x = Tensor(np.array([-1e-12, 0., 1e-12, .4, 1 - 1e-12, 1., 1 + 1e-12]), True)
        y = x.clip(0., 1.)
        y.sum().backward()
        np.testing.assert_array_equal(y.data, np.clip(x.data, 0, 1))
        np.testing.assert_array_equal(x.grad, [0., 0., 1., 1., 1., 0., 0.])

    def test_all_actions_shared_branches_and_prediction_contract(self):
        z, _, _, _ = fixture(2)
        model = ContentModel(27)
        self.assertEqual(sum(value.size for value in model.params.values()), 65562)
        self.assertEqual(set(model.params), {name + suffix for name in MODULES for suffix in (".W", ".b")})
        self.assertEqual(model.digest(), construct(27).digest())
        expected_keys = {"", "T", "I", "J"} | {a + b for a in "TIJ" for b in "TIJ"}
        before = (model.digest(), model.optimizer_digest())
        shared = model.all_sequences(z)
        self.assertEqual(set(shared), expected_keys)
        self.assert_prediction(model.infer(z, "JJ"), model.infer(z.reshape(2, 28, 28), "JJ"))
        for seq in sorted(expected_keys):
            with self.subTest(sequence=seq):
                out = shared[seq]
                self.assert_prediction(out, model.infer(z, seq))
                self.assertEqual((out.p.shape, out.mu.shape, out.image.shape, out.classes.shape),
                                 ((2, 10), (2, 784), (2, 28, 28), (2,)))
                self.assertEqual((out.p.dtype, out.mu.dtype, out.image.dtype),
                                 (np.float64, np.float64, np.float32))
                np.testing.assert_allclose(out.p.sum(1), 1, atol=1e-12, rtol=0)
                self.assertTrue(np.isfinite(out.mu).all())
                self.assertTrue(np.all((out.mu >= 0) & (out.mu <= 1)))
                np.testing.assert_array_equal(out.image, out.mu.reshape(2, 28, 28).astype(np.float32))
                np.testing.assert_array_equal(out.classes, out.p.argmax(1))
        self.assertFalse(np.array_equal(shared["T"].p, shared[""].p))
        self.assertFalse(np.array_equal(shared["I"].mu, shared[""].mu))
        self.assertFalse(np.array_equal(shared["J"].p, shared[""].p))
        self.assertFalse(np.array_equal(shared["J"].mu, shared[""].mu))
        features, candidates = model.j_candidates(z)
        self.assertEqual(features.shape, (2, 32))
        self.assertTrue(np.isfinite(features).all())
        self.assertEqual(set(candidates), {"JT", "JI", "JJ"})
        for seq in candidates:
            self.assert_prediction(candidates[seq], shared[seq])
        with (patch.object(model, "_context", wraps=model._context) as contexts,
              patch.object(model, "_updates", wraps=model._updates) as updates,
              patch.object(model, "j_candidates", side_effect=AssertionError("redundant J forward")),
              patch.object(model, "infer", side_effect=AssertionError("independent branch recomputation"))):
            cached, cached_features = model.all_sequences(z, return_features=True)
        self.assertEqual((contexts.call_count, updates.call_count), (1, 4))
        np.testing.assert_array_equal(cached_features, features)
        for seq in expected_keys:
            self.assert_prediction(cached[seq], shared[seq])
        self.assertEqual((model.digest(), model.optimizer_digest()), before)

    def test_joint_feedback_finite_difference_each_module_weight_and_bias(self):
        inputs, model = fixture(), ContentModel(27)
        weights = model.params["image_head.W"]
        # Each image latent is initially in [-1,1], then receives two bounded
        # tanh residuals. This analytical scale bounds pixel residuals by .02.
        weights *= .02 / (3 * np.max(np.abs(weights).sum(axis=0)))
        prediction = model.infer(inputs[0], "JJ")
        terminals = prediction.mu[:, None, :] + .05 * inputs[3]
        self.assertTrue(np.all((terminals > .05) & (terminals < .95)))
        before = (model.digest(), model.optimizer_digest())
        loss, grads, metrics = content_loss(model, inputs)
        self.assertTrue(np.isfinite(loss))
        self.assertIsInstance(metrics, dict)
        self.assertEqual(set(grads), set(model.params))
        self.assertEqual(loss, model.loss_value(*inputs[:3], "JJ", np.random.default_rng(184),
                         terminal_noise=inputs[3], objective="N"))
        q = np.exp(-np.mean((terminals - inputs[1][:, None, :])**2, axis=-1) / .04)
        py = prediction.p[np.arange(len(inputs[0])), inputs[2]]
        ndu = -.5 * np.log(1 - py + py * np.exp(-2 * q).mean(axis=1))
        expected = (-np.log(py) + np.mean((prediction.mu - inputs[1])**2, axis=1) / .04 - .1 * ndu).mean()
        self.assertAlmostEqual(loss, float(expected), places=12)
        for name in MODULES:
            for suffix in (".W", ".b"):
                key = name + suffix
                with self.subTest(parameter=key):
                    array, gradient = model.params[key], grads[key]
                    self.assertEqual(array.shape, gradient.shape)
                    self.assertTrue(np.isfinite(gradient).all())
                    index = np.unravel_index(np.abs(gradient).argmax(), gradient.shape)
                    self.assertGreater(abs(gradient[index]), 1e-10)
                    original = array[index]
                    try:
                        array[index] = original + FD_EPS
                        plus = content_loss(model, inputs, backward=False)
                        array[index] = original - FD_EPS
                        minus = content_loss(model, inputs, backward=False)
                    finally:
                        array[index] = original
                    self.assert_fd((plus - minus) / (2 * FD_EPS), gradient[index])
        self.assertEqual((model.digest(), model.optimizer_digest()), before)
        _, initial_grads, _ = content_loss(model, inputs, "")
        self.assertFalse(any(key.startswith(("qT.", "qI.", "feedback.", "T_update.", "I_update."))
                             for key in initial_grads))

    def test_actor_mse_all_parameters_and_adam_clocks(self):
        actor = Actor(71)
        self.assertEqual(sum(value.size for value in actor.params.values()), 291)
        rng = np.random.default_rng(113)
        features, targets = rng.uniform(-.4, .4, (2, 32)), rng.uniform(.1, .9, (2, 3))
        prediction = actor.predict(features)
        self.assertEqual(prediction.shape, (2, 3))
        loss, grads, metrics = actor.loss_grad(features, targets)
        self.assertIsInstance(metrics, dict)
        self.assertEqual(set(grads), set(actor.params))
        self.assertAlmostEqual(loss, float(np.mean((prediction - targets)**2)), places=13)
        for key, array in actor.params.items():
            for index in np.ndindex(array.shape):
                original = array[index]
                try:
                    array[index] = original + FD_EPS
                    plus = actor.loss_grad(features, targets)[0]
                    array[index] = original - FD_EPS
                    minus = actor.loss_grad(features, targets)[0]
                finally:
                    array[index] = original
                self.assert_fd((plus - minus) / (2 * FD_EPS), grads[key][index])
        old_digest = actor.digest()
        for clock in (1, 2):
            actor.adam_step(grads)
            self.assertEqual(set(actor._moments), set(actor.params))
            self.assertTrue(all(row[2] == clock for row in actor._moments.values()))
        self.assertNotEqual(actor.digest(), old_digest)

    def test_content_optimizer_export_resume_and_float32_outputs(self):
        inputs, model = fixture(2), ContentModel(27)
        _, grads, _ = content_loss(model, inputs)
        model.adam_step(grads)
        self.assertEqual(set(model._moments), set(model.params))
        self.assertTrue(all(row[2] == 1 for row in model._moments.values()))
        actor = Actor(71)
        features = model.j_candidates(inputs[0])[0]
        _, actor_grads, _ = actor.loss_grad(features, np.full((2, 3), .3))
        actor.adam_step(actor_grads)
        with tempfile.TemporaryDirectory() as directory:
            for current, cls in ((model, ContentModel), (actor, Actor)):
                path = Path(directory) / (cls.__name__ + ".npz")
                current.export(path, include_optimizer=True)
                restored = cls.load(path)
                self.assertEqual(restored.digest(), current.digest())
                self.assertEqual(restored.optimizer_digest(), current.optimizer_digest())
                if cls is ContentModel:
                    self.assert_prediction(current.infer(inputs[0], "JJ"), restored.infer(inputs[0], "JJ"))
                    current.adam_step(grads)
                    restored.adam_step(grads)
                else:
                    np.testing.assert_array_equal(current.predict(features), restored.predict(features))
                    current.adam_step(actor_grads)
                    restored.adam_step(actor_grads)
                self.assertEqual(restored.digest(), current.digest())
                self.assertEqual(restored.optimizer_digest(), current.optimizer_digest())

    def test_bad_inputs_and_gradients_do_not_mutate_model_or_optimizer(self):
        z, clean, labels, noise = fixture(2)
        model, actor = ContentModel(27), Actor(71)
        _, grads, _ = content_loss(model, (z, clean, labels, noise))
        model.adam_step(grads)
        before = (model.digest(), model.optimizer_digest())
        invalid = ((z[:, :-1], clean, labels, "JJ", noise),
                   (np.full_like(z, np.nan), clean, labels, "JJ", noise),
                   (z, np.full_like(clean, 1.1), labels, "JJ", noise),
                   (z, clean, labels.astype(float), "JJ", noise),
                   (z, clean, np.full(2, 10), "JJ", noise),
                   (z, clean, labels, "JJJ", noise), (z, clean, labels, "X", noise),
                   (z, clean, labels, "JJ", noise[:, :3]))
        for x, target, y, seq, terminal in invalid:
            with self.assertRaises((ValueError, TypeError)):
                model.loss_grad(x, target, y, seq, np.random.default_rng(1), terminal_noise=terminal)
            self.assertEqual((model.digest(), model.optimizer_digest()), before)
        for current in (model, actor):
            snapshot = (current.digest(), current.optimizer_digest())
            good = {key: np.ones_like(value) for key, value in current.params.items()}
            bad = copy.deepcopy(good)
            bad[next(reversed(bad))].flat[0] = np.nan
            with self.assertRaises((ValueError, TypeError)):
                current.adam_step(bad)
            self.assertEqual((current.digest(), current.optimizer_digest()), snapshot)
        for inputs in (np.zeros((2, 31)), np.full((2, 32), np.inf)):
            with self.assertRaises((ValueError, TypeError)):
                actor.predict(inputs)


if __name__ == "__main__":
    unittest.main()
