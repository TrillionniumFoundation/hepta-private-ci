"""Whole-model checks separate from independent operator acceptance."""

import unittest

import torch

from experiments.hcsn_distributional_v2 import model as sealed
from .model import DistributionalClassifier, DISTRIBUTION_ARMS


def compare_tree(left, right, atol=0, rtol=0):
    if isinstance(left, torch.Tensor):
        torch.testing.assert_close(left, right, atol=atol, rtol=rtol)
    elif isinstance(left, dict):
        if left.keys() != right.keys():
            raise AssertionError("State dictionary fields changed")
        for key in left:
            compare_tree(left[key], right[key], atol, rtol)
    elif isinstance(left, list):
        if len(left) != len(right):
            raise AssertionError("State depth changed")
        for a, b in zip(left, right, strict=True):
            compare_tree(a, b, atol, rtol)
    elif left != right:
        raise AssertionError("Non-tensor state changed")


class ModelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        torch.set_num_threads(1)

    def inputs(self, dtype=torch.float32):
        rng = torch.Generator().manual_seed(41)
        x = torch.randn(2, 5, 4, generator=rng, dtype=dtype)
        dt = torch.tensor([[0., .5, 4.2, .4, .8], [.1, 2.3, 0., 5.1, .7]], dtype=dtype)
        return x, dt

    def test_raw_reference_preserves_sealed_outputs_and_all_gradients(self):
        x, dt = self.inputs()
        for arm in DISTRIBUTION_ARMS:
            with self.subTest(arm=arm):
                old = sealed.DistributionalClassifier(4, 3, width=8, depth=2, seed=11, arm=arm)
                new = DistributionalClassifier(4, 3, width=8, depth=2, seed=11,
                                               arm=arm, backend="reference", profile="raw")
                compare_tree(old.state_dict(), new.state_dict())
                self.assertEqual(old.counts(), new.counts())
                a, ar = old(x, dt, return_sequence=True)
                b, br = new(x, dt, return_sequence=True)
                torch.testing.assert_close(a, b, atol=0, rtol=0)
                compare_tree(ar["state"], br["state"])
                (a.square().mean() + .01*ar["total_activity"]).backward()
                (b.square().mean() + .01*br["total_activity"]).backward()
                compare_tree({k: p.grad for k, p in old.named_parameters()},
                             {k: p.grad for k, p in new.named_parameters()})

    def test_backend_forward_gradient_and_state_agree_in_both_profiles(self):
        for dtype in (torch.float32, torch.float64):
            x, dt = self.inputs(dtype)
            tolerance = dict(atol=5e-5, rtol=5e-5) if dtype==torch.float32 else dict(atol=1e-10, rtol=1e-10)
            for profile in ("raw", "stable"):
                for arm in DISTRIBUTION_ARMS:
                    with self.subTest(dtype=dtype, profile=profile, arm=arm):
                        models = [DistributionalClassifier(4, 3, width=8, seed=17, arm=arm,
                                  backend=key, profile=profile).to(dtype)
                                  for key in ("reference", "accelerated")]
                        results = [model(x, dt, return_sequence=True) for model in models]
                        torch.testing.assert_close(results[0][0], results[1][0], **tolerance)
                        compare_tree(results[0][1]["state"], results[1][1]["state"], **tolerance)
                        for (logits, aux), model in zip(results, models, strict=True):
                            (logits.square().mean()+.01*aux["total_activity"]).backward()
                            self.assertTrue(all(p.grad is not None and torch.isfinite(p.grad).all()
                                                for p in model.parameters()))
                        compare_tree({k: p.grad for k, p in models[0].named_parameters()},
                                     {k: p.grad for k, p in models[1].named_parameters()}, **tolerance)

    def test_precompute_and_local_preparation_agree(self):
        x, dt = self.inputs(torch.float64)
        for backend in ("reference", "accelerated"):
            a = DistributionalClassifier(4, 3, width=8, seed=19, backend=backend).double()
            b = DistributionalClassifier(4, 3, width=8, seed=19, backend=backend).double()
            for layer in b.layers:
                layer.precompute = False
            av, ax = a(x, dt, return_sequence=True)
            bv, bx = b(x, dt, return_sequence=True)
            torch.testing.assert_close(av, bv, atol=1e-11, rtol=1e-11)
            compare_tree(ax["state"], bx["state"], atol=1e-11, rtol=1e-11)

    def test_stable_rejects_corrupt_state_without_clipping(self):
        x, dt = self.inputs()
        model = DistributionalClassifier(4, 3, width=8, backend="accelerated")
        with torch.inference_mode():
            _, state, _ = model.step(x[:, 0], dt[:, 0])
            state["layers"][0]["probability"][0, 0, 0] = -.01
            with self.assertRaisesRegex(ValueError, "Negative input probability"):
                model.step(x[:, 1], dt[:, 1], state)


if __name__ == "__main__":
    unittest.main()
