"""Actual CPU/Torch mechanism tests against the original frozen TokenReader interface."""
import unittest
from unittest.mock import patch

import torch

from binding_v6_bridge import ARMS, FactBridgeReader, equal_parameter_arms
from binding_v6_training import fit_bridge_fixed_budget
from token_protocol import build_binding_cases
from token_reader_training import TokenBatch, parameter_digest


def features(n=2, dim=8):
    torch.manual_seed(17)
    facts = torch.randn(n, 4, 3, dim)
    question, candidate = torch.randn(n, 3, dim), torch.randn(n, 3, dim)
    fact_mask = torch.ones(n, 4, 3, dtype=torch.bool)
    fact_mask[:, 3, :] = False
    fact_mask[:, 0, 2] = False
    question_mask = torch.ones(n, 3, dtype=torch.bool)
    candidate_mask = torch.ones(n, 3, dtype=torch.bool)
    return facts, question, candidate, fact_mask, question_mask, candidate_mask


class FactBridgeTests(unittest.TestCase):
    def setUp(self):
        torch.set_num_threads(1)

    def test_identical_initial_tensors_and_exact_budget(self):
        rng = torch.random.get_rng_state().clone()
        models = equal_parameter_arms(8, 8, seed=41)
        self.assertEqual(set(models), set(ARMS))
        self.assertEqual(set(parameter_digest(m) for m in models.values()).__len__(), 1)
        self.assertTrue(torch.equal(rng, torch.random.get_rng_state()),
                        "constructing matched arms must not contaminate global RNG")
        for arm, model in models.items():
            self.assertEqual(sum(p.numel() for p in model.parameters()) -  
                             sum(p.numel() for p in __import__('token_reader').TokenReader(8, 8).parameters()), 256)
            self.assertFalse(model.training)
            self.assertTrue(all(not p.requires_grad for p in model.parameters()))

    def test_masked_padding_has_no_effect_and_fact_order_is_invariant(self):
        inputs = features()
        for arm, model in equal_parameter_arms(8, 8, seed=47).items():
            with self.subTest(arm=arm), torch.no_grad():
                first = model(*inputs, steps=3)
                perturbed = list(inputs)
                perturbed[0] = inputs[0].clone()
                perturbed[0][:, 3, :] = 1000000.
                perturbed[0][:, 0, 2] = -1000000.
                torch.testing.assert_close(first, model(*perturbed, steps=3), atol=1e-6, rtol=1e-6)
                order = [2, 0, 3, 1]
                moved = list(inputs)
                moved[0], moved[3] = inputs[0][:, order], inputs[3][:, order]
                torch.testing.assert_close(first, model(*moved, steps=3), atol=1e-5, rtol=1e-5)

    def test_cross_fact_uses_distant_evidence_and_real_gradients(self):
        models = equal_parameter_arms(8, 8, seed=53)
        for model in models.values():
            model.train().requires_grad_(True)
        inputs = features()
        losses = {}
        for arm, model in models.items():
            output = model(*inputs, steps=2)
            self.assertEqual(tuple(output.shape), (2, 2))
            self.assertTrue(torch.isfinite(output).all())
            (output[:, 1] - output[:, 0]).mean().backward()
            self.assertTrue(model.bridge_o.weight.grad is not None)
            self.assertGreater(model.bridge_o.weight.grad.abs().sum().item(), 0)
            if arm == "cross_fact":
                self.assertGreater(model.bridge_q.weight.grad.abs().sum().item(), 0)
                self.assertGreater(model.bridge_k.weight.grad.abs().sum().item(), 0)
            losses[arm] = output.detach()
        self.assertFalse(torch.allclose(losses["cross_fact"], losses["local"], atol=1e-8, rtol=0))

    def test_fixed_budget_never_early_stops_on_train_only_success(self):
        cases = build_binding_cases("train", groups=4, seed=41)
        x = features(n=16)
        # Training labels deliberately never enter the model's six-argument feature tuple.
        data = TokenBatch(*x, targets=torch.tensor([c.label for c in cases]),
                          source_groups=tuple(c.source_hash for c in cases))
        model = FactBridgeReader(8, 8).eval().requires_grad_(False)
        before = parameter_digest(model)
        trained, receipt = fit_bridge_fixed_budget(model, data, cases, seed=41, steps=2,
                                                   diagnostic_interval=1,
                                                   wall_time_ns=30_000_000_000)
        self.assertEqual(receipt["status"], "fixed_budget_completed")
        self.assertEqual(receipt["completed_steps"], 2)
        self.assertEqual(receipt["actual_training_exposures"], 32)
        self.assertEqual(receipt["selection_rule"], "none_fixed_budget")
        self.assertEqual(len(receipt["updates"]), 2)
        self.assertEqual(receipt["diagnostics"][-1]["optimizer_step"], 2)
        self.assertEqual(parameter_digest(model), before)
        self.assertFalse(trained.training)
        self.assertFalse(receipt["official_validation_evaluated"])
        self.assertFalse(receipt["full_lifecycle_cost_claimed"])


if __name__ == "__main__":
    unittest.main()
