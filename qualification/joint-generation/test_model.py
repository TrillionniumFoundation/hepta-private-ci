"""Gradient, learning and artifact checks for the real NumPy model."""

import tempfile
import unittest
from pathlib import Path
import io
import zipfile

import numpy as np

from model import JointModel


class ModelTests(unittest.TestCase):
    def test_shared_gradient_matches_finite_difference(self):
        model = JointModel(4, 3, 8, hidden=5, seed=9)
        x = np.random.default_rng(7).normal(size=(2, 4))
        dt = np.array([[0.2, -0.1, -0.1], [-0.3, 0.1, 0.2]])
        di = -dt
        grads = model.gradients(x, dt, di)

        def objective():
            _, h, _, _ = model._forward(x)
            lt = h @ model.params["text"] + model.params["text_bias"]
            li = h @ model.params["image"] + model.params["image_bias"]
            return float(np.sum(lt * dt + li * di))

        for key, index in [("encoder", (1, 2)), ("bias", (3,)),
                           ("text", (2, 1)), ("image_bias", (0,))]:
            old = model.params[key][index]
            model.params[key][index] = old + 1e-6
            plus = objective()
            model.params[key][index] = old - 1e-6
            minus = objective()
            model.params[key][index] = old
            self.assertAlmostEqual((plus - minus) / 2e-6, grads[key][index], places=7)

    def test_learning_changes_content_and_decoder(self):
        x = np.eye(3)
        model = JointModel(3, 3, 4, hidden=8, seed=11)
        before = model.digest()
        for _ in range(100):
            model.supervised_step(x, np.arange(3), lr=0.03)
        pt, pi = model.forward(x)
        np.testing.assert_array_equal(pt.argmax(axis=1), np.arange(3))
        np.testing.assert_array_equal(pi.argmax(axis=1), np.arange(3))
        self.assertNotEqual(before, model.digest())
        target = np.eye(3, 4)
        loss = model.fit_decoder(target, steps=150)
        self.assertLess(loss, 0.004)
        frozen = model.digest()
        model.forward(x)
        model.decode_images(np.arange(3))
        self.assertEqual(frozen, model.digest())

    def test_entropic_and_additive_updates_improve_known_utility(self):
        rewards = np.array([[[0.0, -1.0], [-1.0, 2.0]]])
        for rho in (0.0, 1.5):
            model = JointModel(2, 2, 3, hidden=4, seed=3)
            old = model.params["encoder"].copy()
            first = model.utility_step(np.ones((1, 2)), rewards, rho=rho, lr=0.01)
            last = first
            for _ in range(40):
                last = model.utility_step(np.ones((1, 2)), rewards, rho=rho, lr=0.01)
            self.assertGreater(last, first)
            self.assertFalse(np.array_equal(old, model.params["encoder"]))

    def test_joint_utility_parameter_gradient_matches_finite_difference(self):
        x = np.array([[0.7, -0.2], [0.1, 0.9]])
        reward = np.array([[[0.2, -0.8], [0.5, 1.7]], [[1.1, 0.3], [-0.2, 0.4]]])
        for rho in (0.0, 1.5):
            model = JointModel(2, 2, 3, hidden=4, seed=13)
            captured = {}
            model.train_step = lambda x, dt, di, lr: captured.update(model.gradients(x, dt, di))
            model.utility_step(x, reward, rho=rho)

            def loss():
                pt, pi = model.forward(x)
                law = pt[:, :, None] * pi[:, None, :]
                if rho == 0:
                    return -float(np.mean(np.sum(law * reward, axis=(1, 2))))
                return float(np.mean(np.log(np.sum(law * np.exp(-rho * reward), axis=(1, 2))) / rho))

            for key, index in [("encoder", (0, 1)), ("text", (2, 0)), ("image_bias", (1,))]:
                old = model.params[key][index]
                model.params[key][index] = old + 1e-6
                plus = loss()
                model.params[key][index] = old - 1e-6
                minus = loss()
                model.params[key][index] = old
                self.assertAlmostEqual((plus - minus) / 2e-6, captured[key][index], places=7)

    def test_bundle_reload_and_rejection(self):
        model = JointModel(3, 2, 4)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "model.npz"
            model.save(path)
            restored = JointModel.load(path)
            self.assertEqual(model.digest(), restored.digest())
            for a, b in zip(model.forward(np.eye(3)), restored.forward(np.eye(3))):
                np.testing.assert_array_equal(a, b)
            with self.assertRaises(ValueError):
                restored.forward([[float("nan"), 0, 0]])
            np.savez(path, dimensions=np.array([3, 2, 4, 32]), injected=np.zeros(1))
            with self.assertRaises(ValueError):
                JointModel.load(path)

    def test_bundle_advertised_size_rejects_before_array_allocation(self):
        model = JointModel(3, 2, 4)
        with tempfile.TemporaryDirectory() as directory:
            source, bad = Path(directory) / "model.npz", Path(directory) / "bad.npz"
            model.save(source)
            header = io.BytesIO()
            np.lib.format.write_array_header_1_0(header, {
                "descr": "<f8", "fortran_order": False, "shape": (2, 2 ** 40),
            })
            with zipfile.ZipFile(source) as original, zipfile.ZipFile(bad, "w") as modified:
                for name in original.namelist():
                    modified.writestr(name, header.getvalue() if name == "decoder.npy" else original.read(name))
            with self.assertRaisesRegex(ValueError, "advertised tensor shape"):
                JointModel.load(bad)


if __name__ == "__main__":
    unittest.main()
