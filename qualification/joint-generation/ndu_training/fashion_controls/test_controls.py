"""Hand-only integration checks. No dataset, downloaded inputs or timing claims."""

from dataclasses import replace
import hashlib
import inspect
import unittest

import numpy as np

from .bound.model import ContentModel
from .fairness import BudgetBook, Opportunity, holm_gate, require_matched
from .objectives import ARMS, Batch, Control, offline_service_utility, verify_binding


def fixture():
    i = np.arange(2 * 784).reshape(2, 784)
    z = .3 + .3 * (i % 31) / 30
    x = .15 + .65 * ((i * 7 + 3) % 43) / 42
    draws = np.array([((i * (2 * k + 3) + 7 * k) % 23 - 11) / 5 for k in range(4)])
    return Batch(z, x, np.array([3, 7]), draws.transpose(1, 0, 2), np.ones(2))


def plans():
    plan = Opportunity("99001f4/model+autodiff", 11, "hand-only", "pinned-C",
                       "pinned-Adam", "shared-fixed-draws", ("stable-A-and-N",),
                       ("greedy-mean",), 1000, 100, "dot-hand-test")
    return {a: plan for a in ARMS}


class ControlsTest(unittest.TestCase):
    def test_bound_source_is_explicit_and_reversible(self):
        from pathlib import Path
        root = Path(__file__).resolve().parent
        binding = verify_binding()
        for path, entry in binding["dependencies"].items():
            raw = (root / path).read_bytes()
            if path.endswith("model.py"):
                raw = raw.replace(b"from .autodiff import", b"from fashion_research.autodiff import")
            self.assertEqual(hashlib.sha256(raw).hexdigest(), entry["source_sha256"])

    def test_three_real_chains_match_pinned_objective_and_update(self):
        batch = fixture()
        controls = {a: Control(a, 11) for a in ARMS}
        initial = controls["H"].model.digest()
        observed, gradients = {}, {}
        for arm, control in controls.items():
            self.assertEqual(control.model.digest(), initial)
            value, grad, metrics = control.loss_grad(batch, "JJ")
            original = ContentModel(11)
            expected, source_grad, _ = original.loss_grad(
                batch.noisy, batch.clean, batch.labels, "JJ", None,
                terminal_noise=batch.draws, objective="anchor" if arm == "H" else arm)
            self.assertAlmostEqual(value, expected, places=13)
            self.assertEqual(grad.keys(), source_grad.keys())
            for name in grad:
                np.testing.assert_allclose(grad[name], source_grad[name], rtol=2e-13, atol=2e-14)
            self.assertEqual(metrics["batch_digest"], batch.digest())
            original.adam_step(source_grad, lr=.001)
            control.step(batch, "JJ", learning_rate=.001)
            for name in original.params:
                np.testing.assert_allclose(control.model.params[name], original.params[name], atol=2e-14)
            self.assertNotEqual(control.model.digest(), initial)
            observed[arm] = control.model.optimizer_digest()
            gradients[arm] = grad
        self.assertEqual(len(set(observed.values())), 3)
        for left, right in (("H", "A"), ("A", "N")):
            self.assertTrue(any(not np.array_equal(gradients[left][k], gradients[right][k])
                                for k in gradients[left]))

    def test_hand_enumeration_matches_declared_objectives(self):
        batch = fixture()
        prediction = Control("H", 11).serve(batch.noisy, "J")
        py = prediction.p[np.arange(2), batch.labels]
        v = np.clip(prediction.mu[:, None, :] + .05 * batch.draws, 0, 1)
        q = np.exp(-np.mean((v - batch.clean[:, None, :]) ** 2, axis=-1) / .04)
        h = -np.log(py) + np.mean((prediction.mu - batch.clean) ** 2, axis=-1) / .04
        a = py * q.mean(axis=-1)
        # Enumerate the forty class/image outcomes, independently of joint_risk.
        utility = (np.arange(10)[None, :, None] == batch.labels[:, None, None]) * q[:, None, :]
        z = (prediction.p[:, :, None] * np.exp(-2 * utility) / 4).sum(axis=(1, 2))
        n = -np.log(z) / 2
        for arm, expected in (("H", h), ("A", h - .1 * a), ("N", h - .1 * n)):
            value, _, metrics = Control(arm, 11).loss_grad(batch, "J")
            np.testing.assert_allclose(metrics["row_loss"], expected, atol=2e-14, rtol=2e-14)
            self.assertAlmostEqual(value, expected.mean(), places=13)
        self.assertTrue(np.all((0 <= n) & (n <= a) & (a <= 1)))

    def test_weight_entire_loss_and_explicit_normalization(self):
        batch = replace(fixture(), weights=np.array([.25, 1.75]))
        for arm in ARMS:
            control = Control(arm, 11)
            value, grad, _ = control.loss_grad(batch, "J")
            values, grads = [], []
            for row in range(2):
                one = Batch(batch.noisy[row:row+1], batch.clean[row:row+1], batch.labels[row:row+1],
                            batch.draws[row:row+1], np.ones(1))
                v, g, _ = control.loss_grad(one, "J")
                values.append(v); grads.append(g)
            self.assertAlmostEqual(value, np.dot(values, batch.weights) / 2, places=12)
            for name in grad:
                np.testing.assert_allclose(grad[name], sum(batch.weights[i] * grads[i][name]
                                           for i in range(2)) / 2, atol=2e-13, rtol=2e-12)
            scaled = replace(batch, weights=3 * batch.weights)
            self.assertAlmostEqual(control.loss_value(scaled, "J"), 3 * value, places=12)
            normalized = replace(scaled, normalizer=6)
            self.assertAlmostEqual(control.loss_value(normalized, "J"), value, places=12)

    def test_feedback_and_both_heads_reach_all_three_losses(self):
        batch = fixture()
        for arm in ARMS:
            control = Control(arm, 11)
            _, gradients, _ = control.loss_grad(batch, "JJ")
            for name in ("C.W", "qT.W", "qI.W", "feedback.W", "text_head.W", "image_head.W"):
                index = np.unravel_index(np.argmax(np.abs(gradients[name])), gradients[name].shape)
                analytic = gradients[name][index]
                self.assertGreater(abs(analytic), 1e-8)
                param = control.model.params[name]
                saved = param[index]
                try:
                    param[index] = saved + 1e-6
                    plus = control.loss_value(batch, "JJ")
                    param[index] = saved - 1e-6
                    minus = control.loss_value(batch, "JJ")
                finally:
                    param[index] = saved
                self.assertAlmostEqual((plus - minus) / 2e-6, analytic,
                                       delta=2e-6 * max(1, abs(analytic)))

    def test_saturated_true_class_keeps_complement_gradient(self):
        for arm in ARMS:
            control = Control(arm, 11)
            control.model.params["text_head.W"].fill(0)
            control.model.params["text_head.b"].fill(0)
            control.model.params["text_head.b"][3] = 45
            batch = replace(fixture(), labels=np.array([3, 3]))
            _, gradient, _ = control.loss_grad(batch, "")
            self.assertLess(gradient["text_head.b"][3], 0)
            self.assertGreater(gradient["text_head.b"][3], -1e-15)
            self.assertTrue(np.all(gradient["text_head.b"][[0, 1, 2, 4, 5, 6, 7, 8, 9]] > 0))

    def test_serving_has_no_label_reference_draw_or_weight_channel(self):
        self.assertEqual(tuple(inspect.signature(Control.serve).parameters), ("self", "noisy", "sequence"))
        batch, control = fixture(), Control("N", 11)
        first = control.serve(batch.noisy, "J")
        alternate = replace(batch, labels=(batch.labels + 1) % 10, clean=1 - batch.clean,
                            draws=-batch.draws, weights=np.array([.5, 1.5]))
        second = control.serve(alternate.noisy, "J")
        np.testing.assert_array_equal(first.p, second.p)
        np.testing.assert_array_equal(first.image, second.image)
        self.assertEqual(first.image.dtype, np.float32)
        with self.assertRaises(TypeError):
            control.serve(batch.noisy, "J", labels=batch.labels)

    def test_actual_greedy_mean_output_is_not_auxiliary_law(self):
        batch, control = fixture(), Control("A", 11)
        prediction = control.serve(batch.noisy, "J")
        wrong = replace(batch, labels=(prediction.classes + 1) % 10, clean=prediction.mu)
        _, _, a = control.loss_grad(wrong, "J")
        _, _, n = Control("N", 11).loss_grad(wrong, "J")
        np.testing.assert_array_equal(offline_service_utility(prediction, wrong), np.zeros(2))
        self.assertTrue(np.all(a["auxiliary"] > n["auxiliary"]))
        self.assertTrue(np.all(n["auxiliary"] > 0))
        correct = replace(wrong, labels=prediction.classes)
        _, _, a = control.loss_grad(correct, "J")
        service = offline_service_utility(prediction, correct)
        self.assertTrue(np.all(service > a["auxiliary"]))
        self.assertTrue(np.all(service > .999999))

    def test_public_dtype_shape_and_base_metadata_cannot_change_batch(self):
        batch = fixture()
        digest = batch.digest()
        expected = {name: getattr(batch, name).copy()
                    for name in ("noisy", "clean", "labels", "draws", "weights")}
        for name, original in expected.items():
            exposed = getattr(batch, name)
            exposed.dtype = np.int64 if original.dtype.kind == "f" else np.float64
            exposed.shape = (exposed.size,)
            exposed.base.dtype = np.uint8
            exposed.base.shape = (exposed.base.size,)
            current = getattr(batch, name)
            self.assertEqual(current.dtype, original.dtype)
            self.assertEqual(current.shape, original.shape)
            np.testing.assert_array_equal(current, original)
            self.assertEqual(batch.digest(), digest)
        # A legitimate content change still changes the canonical identity.
        changed = replace(batch, clean=1 - batch.clean)
        self.assertNotEqual(changed.digest(), digest)

    def test_shared_metadata_mutation_preserves_all_three_gradient_chains(self):
        batch = fixture()
        controls = {arm: Control(arm, 11) for arm in ARMS}
        before = {arm: c.loss_grad(batch, "") for arm, c in controls.items()}
        digest = batch.digest()
        # Reproduce the review's ordinary attribute assignment exactly.
        batch.clean.dtype = np.int64
        batch.noisy.shape = (batch.noisy.size,)
        batch.draws.dtype = np.uint8
        batch.weights.shape = (1, len(batch.weights))
        batch.labels.dtype = np.float64
        for arm, control in controls.items():
            value, gradients, metrics = control.loss_grad(batch, "")
            self.assertEqual(value, before[arm][0])
            self.assertEqual(metrics["batch_digest"], digest)
            for name, gradient in gradients.items():
                np.testing.assert_array_equal(gradient, before[arm][1][name])

    def test_paired_inputs_are_owned_immutable_and_reject_invalid(self):
        batch = fixture()
        for name in ("noisy", "clean", "labels", "draws", "weights"):
            with self.assertRaises(ValueError):
                getattr(batch, name).setflags(write=True)
        for fields in ({"draws": batch.draws[:, :3]}, {"weights": np.array([0., 0.])},
                       {"weights": np.array([1., np.nan])}, {"normalizer": 0},
                       {"labels": np.array([3., 7.])}):
            with self.assertRaises(ValueError):
                replace(batch, **fields)


class FairnessTest(unittest.TestCase):
    def test_mismatched_comparison_opportunities_fail_closed(self):
        for key, value in (("seed", 23), ("encoder", "different"), ("cpu_cap_ns", 999),
                           ("static_decoder_opportunities", ()), ("optimization_opportunities", ()),
                           ("executor", "codex-cloud")):
            panel = plans(); panel["A"] = replace(panel["A"], **{key: value})
            with self.assertRaises(ValueError):
                require_matched(panel)
        with self.assertRaises(ValueError):
            require_matched({"H": plans()["H"], "N": plans()["N"]})

    def test_shared_cost_full_each_and_cheap_arm_can_use_remaining_budget(self):
        book = BudgetBook(plans())
        book.charge(ARMS, "common-setup", 200, 10, executor="dot-hand-test")
        self.assertEqual(book.used, {a: [200, 10] for a in ARMS})
        book.charge(("N",), "N-only-update", 700, 60, executor="dot-hand-test")
        self.assertTrue(book.fits("A", 200, 30, tail_cpu_ns=100, tail_work=10))
        self.assertFalse(book.fits("N", 200, 30, tail_cpu_ns=100, tail_work=10))
        with self.assertRaises(ValueError):
            book.charge(ARMS, "mixed-CPU", 1, 1, executor="codex-cloud")
        with self.assertRaises(RuntimeError):
            book.charge(("N",), "actual-overrun", 101, 0, executor="dot-hand-test")
        self.assertEqual(book.used["N"], [1001, 70])
        self.assertEqual(book.rows[-1]["phase"], "actual-overrun")
        self.assertFalse(book.fits("A", 0, 0, tail_cpu_ns=0, tail_work=0))

    def test_false_positive_family_cannot_drop_failed_claims(self):
        family = ("N>A-service", "N>H-service")
        self.assertEqual(holm_gate(dict(zip(family, [.04, .9])), family=family, alpha=.05),
                         {k: False for k in family})
        self.assertEqual(holm_gate(dict(zip(family, [.01, .04])), family=family, alpha=.05),
                         {k: True for k in family})
        for values in ({family[0]: .01}, dict(zip(family, [float("nan"), .01]))):
            with self.assertRaises(ValueError):
                holm_gate(values, family=family, alpha=.05)


if __name__ == "__main__":
    unittest.main()
