"""State, pure-task training, and actual-event checks for the research model."""

import json
import unittest

import torch
from torch.nn import functional as F

from .model import HCSNClassifier, simulate_event_interval


class ModelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        torch.set_num_threads(1)

    def test_pure_task_gradient_and_parameter_updates(self):
        generator = torch.Generator().manual_seed(216)
        x = torch.randn(20, 7, 4, generator=generator)
        # A real delayed classification label, not a supplied oracle target.
        targets = (x[:, :4, 0].sum(1) > 0).long()
        dt = 0.4 + torch.rand(20, 7, generator=generator)
        model = HCSNClassifier(4, 2, width=10, depth=2, seed=91)
        initial = {name: parameter.detach().clone() for name, parameter in model.named_parameters()}
        optimizer = torch.optim.Adam(model.parameters(), lr=0.012)
        gradients = {}
        losses = []
        for iteration in range(32):
            optimizer.zero_grad(set_to_none=True)
            logits, _ = model(x, dt)
            loss = F.cross_entropy(logits, targets)
            loss.backward()
            if iteration == 0:
                for group, entries in model.parameter_groups().items():
                    gradients[group] = sum(
                        parameter.grad.detach().square().sum().item()
                        for _, parameter in entries if parameter.grad is not None) ** 0.5
                for name, parameter in model.named_parameters():
                    if any(part in name for part in (
                        "mu_bias", "raw_sigma", "raw_rho", "raw_K",
                        "raw_reset_gap", "raw_refractory")):
                        self.assertIsNotNone(parameter.grad, name)
                        self.assertTrue(torch.isfinite(parameter.grad).all(), name)
                        self.assertGreater(parameter.grad.abs().max().item(), 1e-12, name)
            torch.nn.utils.clip_grad_norm_(model.parameters(), 2)
            optimizer.step()
            losses.append(loss.item())
        changes = {
            group: sum((parameter.detach() - initial[name]).square().sum().item()
                       for name, parameter in entries) ** 0.5
            for group, entries in model.parameter_groups().items()}
        self.assertLess(losses[-1], losses[0] - 0.08)
        for group in gradients:
            self.assertGreater(gradients[group], 1e-10, group)
            self.assertGreater(changes[group], 1e-6, group)
        print(json.dumps(dict(test="pure_task_training", loss_start=losses[0],
                              loss_end=losses[-1], initial_gradient_norms=gradients,
                              actual_parameter_change_norms=changes), sort_keys=True))

    def test_streaming_matches_batch_on_unseen_inputs(self):
        generator = torch.Generator().manual_seed(17)
        x = torch.randn(5, 9, 3, generator=generator)
        dt = torch.rand(5, 9, generator=generator)
        dt[1, 3] = 0
        for boundary in ("fixed", "direct", "free"):
            model = HCSNClassifier(3, 4, width=8, depth=2,
                                   boundary_mode=boundary, seed=21).eval()
            with torch.no_grad():
                expected, batch_aux = model(x, dt, return_sequence=True)
                state, outputs = None, []
                for index in range(x.shape[1]):
                    output, state, _ = model.step(x[:, index], dt[:, index], state)
                    outputs.append(output)
            torch.testing.assert_close(torch.stack(outputs, 1), expected, atol=2e-6, rtol=2e-5)
            for expected_layer, actual_layer in zip(batch_aux["state"]["layers"], state["layers"], strict=True):
                for key in expected_layer:
                    torch.testing.assert_close(actual_layer[key], expected_layer[key], atol=2e-6, rtol=2e-5)

    def test_zero_time_leaves_state_unchanged(self):
        model = HCSNClassifier(3, 2, width=8, depth=2, seed=3)
        x = torch.randn(4, 3)
        _, state, _ = model.step(x, torch.full((4,), 0.8))
        _, next_state, aux = model.step(x * 3, torch.zeros(4), state)
        torch.testing.assert_close(next_state["elapsed"], state["elapsed"], atol=0, rtol=0)
        for old_layer, new_layer in zip(state["layers"], next_state["layers"], strict=True):
            for key in old_layer:
                torch.testing.assert_close(new_layer[key], old_layer[key], atol=0, rtol=0)
        self.assertEqual(aux["total_activity"].item(), 0)

    def test_dynamics_intervention_changes_content_and_predictions(self):
        generator = torch.Generator().manual_seed(45)
        x = torch.randn(6, 10, 3, generator=generator)
        dt = torch.full((6, 10), 0.75)
        model = HCSNClassifier(3, 3, width=8, depth=2, seed=21)
        with torch.no_grad():
            before, before_aux = model(x, dt)
            model.layers[0].mu_bias.add_(0.8)
            after, after_aux = model(x, dt)
        self.assertGreater((before - after).abs().max().item(), 1e-5)
        self.assertGreater((before_aux["content"] - after_aux["content"]).abs().max().item(), 1e-5)

    def test_boundary_variants_receive_identical_frontend_and_readout(self):
        models = [HCSNClassifier(3, 2, width=8, boundary_mode=boundary, seed=19)
                  for boundary in ("fixed", "direct", "free")]
        for model in models[1:]:
            for module_name in ("frontend", "readout"):
                actual = getattr(model, module_name).state_dict()
                expected = getattr(models[0], module_name).state_dict()
                for key in expected:
                    torch.testing.assert_close(actual[key], expected[key], atol=0, rtol=0)

    def test_all_counted_parameters_connect_to_task_loss_in_every_ablation(self):
        generator = torch.Generator().manual_seed(731)
        x = torch.randn(5, 8, 3, generator=generator)
        dt = torch.full((5, 8), 0.8)
        targets = torch.tensor([0, 1, 0, 1, 1])
        for boundary in ("fixed", "direct", "free"):
            for channels in ("margin", "continuation", "dual", "ordinary"):
                model = HCSNClassifier(3, 2, width=8, boundary_mode=boundary,
                                       channels=channels, seed=11)
                logits, _ = model(x, dt)
                F.cross_entropy(logits, targets).backward()
                for name, parameter in model.named_parameters():
                    label = (boundary, channels, name)
                    self.assertIsNotNone(parameter.grad, label)
                    self.assertTrue(torch.isfinite(parameter.grad).all(), label)
                    self.assertGreater(parameter.grad.abs().max().item(), 0, label)

    def test_dual_values_match_and_smooth_fit_at_free_boundary(self):
        model = HCSNClassifier(3, 2, width=8, seed=72).double()
        cell = model.layers[0]
        generator = torch.Generator().manual_seed(335)
        x = torch.randn(2, 1, 8, dtype=torch.float64, generator=generator)
        signal, prepared = cell.prepare(x)
        local = {key: value[:, 0] if value.ndim == 3 else value
                 for key, value in prepared.items()}
        duration = x.new_full((2, 1), 0.5)
        for epsilon in (0.0, 1e-7):
            state = cell.initial_state(2, x)
            voltage = (local["boundary"].detach() - epsilon).requires_grad_()
            state["voltage"] = voltage
            _, _, aux = cell.advance(x[:, 0], signal[:, 0], duration, state, local)
            value, obstacle = aux["continuation"], aux["intervention"]
            torch.testing.assert_close(value, obstacle, rtol=1e-10, atol=1e-10)
            torch.testing.assert_close(aux["continuation_gap"], value - obstacle,
                                       rtol=0, atol=0)
            value_slope = torch.autograd.grad(value.sum(), voltage, retain_graph=True)[0]
            obstacle_slope = torch.autograd.grad(obstacle.sum(), voltage, retain_graph=True)[0]
            torch.testing.assert_close(value_slope, obstacle_slope, rtol=1e-6, atol=1e-6)
            transformed_value = value / (1 + value.abs())
            transformed_obstacle = obstacle / (1 + obstacle.abs())
            transformed_slope = torch.autograd.grad(transformed_value.sum(), voltage,
                                                     retain_graph=True)[0]
            obstacle_transformed_slope = torch.autograd.grad(transformed_obstacle.sum(), voltage)[0]
            torch.testing.assert_close(transformed_slope, obstacle_transformed_slope,
                                       rtol=1e-6, atol=1e-6)

    def test_actual_events_reset_and_respect_refractory_clock(self):
        zeros, ones = torch.zeros(2), torch.ones(2)
        result = simulate_event_interval(
            voltage=zeros, refractory=zeros, mu=ones, sigma=zeros,
            boundary=ones, reset=zeros, tau=ones / 2,
            dt=ones * 4, noise=torch.zeros(8, 2))
        # Exact deterministic event times on this grid are 1, 2.5, and 4.
        torch.testing.assert_close(result["events"], ones * 3, atol=0, rtol=0)
        torch.testing.assert_close(result["voltage"], zeros, atol=0, rtol=0)
        torch.testing.assert_close(result["refractory"], ones / 2, atol=0, rtol=0)

    def test_initial_hit_precedes_negative_drift_after_boundary_moves(self):
        # A newly lowered barrier is already crossed. Negative drift must not
        # erase the initial firing; refractory time precedes remaining motion.
        result = simulate_event_interval(
            voltage=torch.full((3,), 1.01), refractory=torch.tensor([0.0, 0.2, 0.0]),
            mu=-torch.ones(3), sigma=torch.zeros(3), boundary=torch.ones(3),
            reset=torch.zeros(3), tau=torch.full((3,), 0.02),
            dt=torch.tensor([0.1, 0.1, 0.0]), noise=torch.zeros(1, 3))
        torch.testing.assert_close(result["events"], torch.tensor([1.0, 0.0, 0.0]), rtol=0, atol=0)
        torch.testing.assert_close(result["voltage"], torch.tensor([-0.08, 1.01, 1.01]))
        torch.testing.assert_close(result["refractory"], torch.tensor([0.0, 0.1, 0.0]))

    def test_public_context_and_invalid_time_contract(self):
        model = HCSNClassifier(3, 2, width=8, context_dim=2)
        x, dt = torch.ones(2, 4, 3), torch.ones(2, 4)
        with self.assertRaises(ValueError):
            model(x, dt)
        output, _ = model(x, dt, context=torch.ones(2, 4, 2))
        self.assertEqual(output.shape, (2, 2))
        with self.assertRaises(ValueError):
            model(x, -dt, context=torch.ones(2, 4, 2))


if __name__ == "__main__":
    unittest.main(verbosity=2)
