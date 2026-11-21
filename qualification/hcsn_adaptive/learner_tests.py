import tempfile
from pathlib import Path
import unittest

import torch

from .budget import Budget
from .checkpoint import claim_final_holdout
from .learner import (LearnerConfig, _objective, _programmatic_edit, _ridge,
                      _zero_order, fit_readout)


class LearnerTests(unittest.TestCase):
    def data(self):
        generator = torch.Generator().manual_seed(111)
        x = torch.randn(80, 3, generator=generator, dtype=torch.float64)
        y = x @ torch.tensor([[0.3], [-0.7], [0.2]], dtype=torch.float64) + 0.15
        return x[:64], y[:64], x[64:], y[64:]

    def test_ridge_learns_known_linear_map(self):
        with tempfile.TemporaryDirectory() as directory:
            model, report = fit_readout(*self.data(), method="ridge", seed=4,
                                       budget=Budget(), directory=directory, identity="ridge-test")
            x, y = self.data()[2:]
            self.assertLess(float((model(x) - y).square().mean().detach()), 1e-8)
            self.assertEqual(report["outcome"], "Candidate")
            self.assertEqual(report["cost"]["backward_examples"], 0)

    def test_all_updates_share_the_regularized_stationary_point(self):
        x, y, _, _ = self.data()
        y = torch.cat((y, 0.5 * y - 0.2), dim=1)
        model = torch.nn.Linear(3, 2).double()
        config = LearnerConfig(ridge=0.4)
        coefficient = config.ridge / y.numel()
        with torch.no_grad():
            _ridge(model, x, y, config.ridge)
        _objective(model, x, y, coefficient).backward()
        for parameter in model.parameters():
            self.assertLess(float(parameter.grad.abs().max()), 1e-10)
        before = {key: value.detach().clone() for key, value in model.state_dict().items()}
        with torch.no_grad():
            _programmatic_edit(model, x, y, config.trust_radius, config.ridge)
            _zero_order(model, x, y, torch.Generator().manual_seed(9), config, coefficient)
        for name, value in before.items():
            torch.testing.assert_close(value, model.state_dict()[name], rtol=0, atol=1e-10)

    def test_adam_resume_restores_rng_optimizer_and_controller(self):
        config = LearnerConfig(steps=6, batch_size=13, evaluate_every=2)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            arguments = dict(method="bp", seed=9, budget=Budget(wall_seconds=60),
                             identity="resume-test", config=config)
            full, a = fit_readout(*self.data(), directory=root / "full", **arguments)
            _, paused = fit_readout(*self.data(), directory=root / "resumed", stop_after=2,
                                    **arguments)
            self.assertEqual(paused["status"], "paused")
            resumed, b = fit_readout(*self.data(), directory=root / "resumed", resume=True,
                                    **arguments)
            for name, value in full.state_dict().items():
                torch.testing.assert_close(value, resumed.state_dict()[name], rtol=0, atol=0)
            self.assertEqual(a["history"], b["history"])
            for key in ("training_examples", "forward_examples", "backward_examples", "proposals"):
                self.assertEqual(a["cost"][key], b["cost"][key])

    def test_no_update_retains_better_untrained_checkpoint(self):
        train_x, _, dev_x, _ = self.data()
        torch.manual_seed(7)
        initial = torch.nn.Linear(3, 1).double()
        with torch.no_grad():
            dev_y = initial(dev_x)
        with tempfile.TemporaryDirectory() as directory:
            model, report = fit_readout(train_x, torch.full((64, 1), 100.0, dtype=torch.float64),
                                       dev_x, dev_y, method="ridge", seed=7,
                                       budget=Budget(), directory=directory, identity="no-update")
            self.assertEqual(report["outcome"], "NoUpdate")
            for name, value in initial.state_dict().items():
                torch.testing.assert_close(value, model.state_dict()[name], rtol=0, atol=0)

    def test_final_holdout_claim_cannot_be_repeated(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "test.started"
            claim_final_holdout(path, "one")
            with self.assertRaises(FileExistsError):
                claim_final_holdout(path, "one")

    def test_features_with_encoder_gradients_are_rejected(self):
        data = list(self.data())
        data[0].requires_grad_(True)
        with tempfile.TemporaryDirectory() as directory, self.assertRaises(ValueError):
            fit_readout(*data, method="bp", seed=3, budget=Budget(),
                        directory=directory, identity="frozen-feature-contract")

    def test_initial_budget_failure_is_unavailable_and_costed(self):
        with tempfile.TemporaryDirectory() as directory:
            _, report = fit_readout(*self.data(), method="bp", seed=3,
                                    budget=Budget(forward_examples=1), directory=directory,
                                    identity="initial-budget")
            self.assertEqual(report["outcome"], "Unavailable")
            self.assertEqual(report["cost"]["forward_examples"], 0)
            self.assertGreater(report["cost"]["wall_seconds"], 0)

    def test_resume_rejects_changed_seed_or_data(self):
        config = LearnerConfig(steps=4, evaluate_every=2)
        with tempfile.TemporaryDirectory() as directory:
            arguments = dict(method="bp", seed=11, budget=Budget(), directory=directory,
                             identity="bound-resume", config=config)
            fit_readout(*self.data(), stop_after=2, **arguments)
            with self.assertRaises(ValueError):
                fit_readout(*self.data(), resume=True, **{**arguments, "seed": 12})
            changed = list(self.data())
            changed[1] = changed[1] + 0.001
            with self.assertRaises(ValueError):
                fit_readout(*changed, resume=True, **arguments)


if __name__ == "__main__":
    unittest.main()
