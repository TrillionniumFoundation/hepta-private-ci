"""Literal invariants only; no generator split or saved model is read."""
import pathlib
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parent
sys.path[:0] = [str(ROOT), str(ROOT.parent)]
import numpy as np
from mechanism import SplitPolicy
from model import JointModel


class MechanismTests(unittest.TestCase):
    def fixture(self):
        base = JointModel(3, 2, 4, hidden=4, seed=17)
        x = np.array([[.2, .4, .6], [.7, .1, .3]])
        y = np.array([0, 1])
        rewards = np.array([[[1., -.3], [-.3, .1]], [[.1, -.3], [-.3, 1.]]])
        return base, x, y, rewards

    def test_zero_adaptation_identity(self):
        base, x, _, _ = self.fixture()
        expected = base.forward(x)
        for mode in ("joint", "protected"):
            for got, want in zip(SplitPolicy(base, mode).forward(x), expected):
                np.testing.assert_array_equal(got, want)

    def test_protected_marginal_and_base_unchanged(self):
        base, x, y, rewards = self.fixture()
        original = base.digest()
        for objective in ("additive", "ndu"):
            model = SplitPolicy(base, "protected")
            before = model.forward(x)
            for _ in range(3):
                model.step(x, y, rewards, objective, 1.5, .2, .003)
            after = model.forward(x)
            np.testing.assert_array_equal(before[0], after[0])
            self.assertFalse(np.array_equal(before[1], after[1]))
            self.assertEqual(original, base.digest())
            model.verify_frozen()
            np.testing.assert_array_equal(model.adapted.params['text'], base.params['text'])

    def test_joint_is_original_objective_pullback(self):
        from utility import joint_value_and_grad
        base, x, y, rewards = self.fixture()
        for objective in ("additive", "ndu"):
            model = SplitPolicy(base, "joint")
            reference = base.clone()
            p, q = reference.forward(x)
            dp, dq = p.copy(), q.copy()
            dp[np.arange(2), y] -= 1
            dq[np.arange(2), y] -= 1
            _, gp, gq = joint_value_and_grad(p, q, rewards, 0 if objective == "additive" else 1.5)
            reference.train_step(x, .2 * dp / 4 + gp, .2 * dq / 4 + gq, .003)
            model.step(x, y, rewards, objective, 1.5, .2, .003)
            self.assertEqual(reference.digest(), model.adapted.digest())

    def test_protected_image_gradient_finite_difference(self):
        from utility import joint_value_and_grad
        base, x, y, rewards = self.fixture()
        model = SplitPolicy(base, "protected")
        p, q = model.forward(x)
        _, _, gq = joint_value_and_grad(p, q, rewards, 1.5)
        dq = q.copy(); dq[np.arange(2), y] -= 1
        gradients = model.adapted.gradients(x, np.zeros_like(p), gq + .2 * dq / 4)
        def loss():
            p1, q1 = model.forward(x)
            values = joint_value_and_grad(p1, q1, rewards, 1.5)[0]
            ce = -np.mean(np.log(p1[np.arange(2), y]) + np.log(q1[np.arange(2), y])) / 2
            return -values.mean() + .2 * ce
        for key, index in (("encoder", (0, 1)), ("image", (1, 0)), ("image_bias", (1,))):
            value = model.adapted.params[key][index]; eps = 1e-6
            model.adapted.params[key][index] = value + eps; plus = loss()
            model.adapted.params[key][index] = value - eps; minus = loss()
            model.adapted.params[key][index] = value
            self.assertAlmostEqual((plus-minus)/(2*eps), gradients[key][index], places=8)

    def test_invalid_profile_and_frozen_readonly(self):
        base, x, y, rewards = self.fixture()
        with self.assertRaises(ValueError): SplitPolicy(base, "unknown")
        model = SplitPolicy(base, "protected")
        with self.assertRaises(ValueError): model.frozen.params['bias'][0] = 1
        with self.assertRaises(ValueError): model.step(x,y,rewards,"other",1.5,.2,.003)
        with self.assertRaises(ValueError): model.step(x,np.array([0.,1.]),rewards,"ndu",1.5,.2,.003)


if __name__ == "__main__":
    unittest.main()
