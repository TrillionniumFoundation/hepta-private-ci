"""Behavioral/gradient checks, not formal heldout performance evidence."""

from dataclasses import FrozenInstanceError
import unittest

import numpy as np
import torch

from metrics import score_outputs
from model import MODALITIES, OutputModel, _weight_hashes
from v3.feedback_model import (FeedbackOutputModel, external_loss_from_outputs,
                               innovation_bank, train_feedback_denoiser)


class FeedbackModelTests(unittest.TestCase):
    def setUp(self):
        with torch.random.fork_rng(devices=[]):
            torch.manual_seed(781)
            self.base = OutputModel(dict(zip(MODALITIES, (16, 20, 24, 28)))).eval()
        rng = np.random.default_rng(921)
        self.targets = {name: rng.normal(size=(8, width)).astype(np.float32)
                        for name, width in self.base.dimensions.items()}
        self.model = FeedbackOutputModel(self.base, seed=13)
        self.q = torch.eye(8)
        self.bank, self.probabilities = innovation_bank(19)

    def test_actual_outputs_causal_noise_and_noiseless_contraction(self):
        random_before = torch.random.get_rng_state().clone()
        anchor = self.model.anchor_tensor(self.q)
        latent = self.model.initialize_tensor(self.q, self.bank[0], anchor=anchor)
        refined = self.model.refine_tensor(self.q, latent, self.bank[1], anchor=anchor)
        perturbed = self.model.refine_tensor(self.q, latent, self.bank[2], anchor=anchor)
        torch.testing.assert_close(perturbed - refined,
                                   torch.as_tensor(self.bank[2]).expand_as(refined))
        self.assertTrue(torch.all((refined - anchor).square().sum(1)
                                  < (latent - anchor).square().sum(1)))
        before, after = self.model.decode_tensor(latent), self.model.decode_tensor(refined)
        for name in MODALITIES:
            self.assertEqual(after[name].shape, (8, self.base.dimensions[name]))
            self.assertFalse(torch.equal(before[name], after[name]))
        self.assertTrue(torch.equal(random_before, torch.random.get_rng_state()))
        # Neither transition accepts truth, targets, a future path, or a new q
        # through the live-stream API; innovations must be explicitly supplied.
        with self.assertRaises(TypeError):
            self.model.refine_tensor(self.q, latent, self.bank[0], truth=0)

    def test_stream_feedback_budget_previews_and_sealing(self):
        q = self.q[:1].clone()
        costs = self.model.cost_profile()
        budget = costs["anchor"] + costs["refinement"] + costs["emit_all"] + costs["decoder"]["text"]
        state = self.model.initialize(q, self.bank[0], budget_macs=budget)
        original = state.latent.detach().clone()
        q.zero_()
        state.latent.zero_()
        self.assertTrue(torch.equal(state.latent, original))
        with self.assertRaises(FrozenInstanceError):
            state.depth = 2
        with self.assertRaisesRegex(ValueError, "feedback"):
            self.model.refine_step(state, self.bank[1])
        self.model.feedback(state)
        self.model.preview(state, ("text",))
        current = self.model.refine_step(state, self.bank[1])
        with self.assertRaisesRegex(ValueError, "stale"):
            self.model.feedback(state)
        with self.assertRaisesRegex(ValueError, "feedback"):
            self.model.emit(current)
        feedback = self.model.feedback(current)
        self.assertEqual(feedback["depth"], 1)
        with self.assertRaisesRegex(ValueError, "budget"):
            self.model.preview(current, ("audio",))
        outputs = self.model.emit(current)
        self.assertEqual(set(outputs), set(MODALITIES))
        self.assertEqual(current.receipt, {"depth": 1, "sealed": True,
                         "linear_macs": budget, "budget_macs": budget,
                         "feedback_events": 2, "preview_events": 1})
        for previous in (state, current):
            self.assertTrue(previous.sealed)
            for operation in (self.model.emit, self.model.feedback, self.model.preview):
                with self.assertRaisesRegex(ValueError, "sealed"):
                    operation(previous)
            with self.assertRaisesRegex(ValueError, "sealed"):
                self.model.refine_step(previous, self.bank[1])

    def test_depth_zero_is_legal_and_rejected_work_does_not_spend_budget(self):
        cost = self.model.cost_profile()
        budget = cost["anchor"] + cost["emit_all"]
        state = self.model.initialize(self.q[:1], self.bank[1], budget_macs=budget)
        self.model.feedback(state)
        receipt = state.receipt
        work = self.model.work_receipt()
        with self.assertRaisesRegex(ValueError, "budget"):
            self.model.refine_step(state, self.bank[0])
        self.assertEqual(receipt, state.receipt)
        self.assertEqual(work, self.model.work_receipt())
        self.model.emit(state)
        self.assertEqual(state.receipt["depth"], 0)

    def test_linear_forward_accounting_matches_actual_executed_layers(self):
        observed = []
        def count(module, inputs, _output):
            observed.append(inputs[0].numel() // module.in_features
                            * module.in_features * module.out_features)
        hooks = [module.register_forward_hook(count) for module in self.model.modules()
                 if isinstance(module, torch.nn.Linear)]
        anchor = self.model.anchor_tensor(self.q)
        latent = self.model.initialize_tensor(self.q, self.bank[0], anchor=anchor)
        child = self.model.refine_tensor(self.q, latent, self.bank[1], anchor=anchor)
        self.model.decode_tensor(child)
        offline = sum(observed)
        state = self.model.initialize(self.q[:1], self.bank[2], budget_macs=10**8)
        self.model.feedback(state)
        self.model.preview(state, ("image", "video"))
        child_state = self.model.refine_step(state, self.bank[1])
        self.model.feedback(child_state)
        self.model.emit(child_state)
        for hook in hooks:
            hook.remove()
        self.assertEqual(sum(observed), self.model.work_receipt()["linear_macs"])
        self.assertEqual(sum(observed) - offline, child_state.receipt["linear_macs"])
        self.assertEqual(self.model.work_receipt()["feedback_examples"], 2)

    def test_exact_external_metric_and_direct_gradient_finite_difference(self):
        self.model.double()
        self.model.base.decoders.requires_grad_(True)
        q = self.q.double()
        def loss():
            anchor = self.model.anchor_tensor(q)
            latent = self.model.initialize_tensor(q, self.bank[0], anchor=anchor)
            child = self.model.refine_tensor(q, latent, self.bank[1], anchor=anchor)
            outputs = self.model.decode_tensor(child)
            return external_loss_from_outputs(self.model, outputs, self.targets), outputs
        table, outputs = loss()
        raw = {name: value.detach().numpy() for name, value in outputs.items()}
        expected = np.column_stack([score_outputs(raw, np.full(8, truth), self.targets)["loss"]
                                    for truth in range(8)])
        np.testing.assert_allclose(table.detach().numpy(), expected, rtol=0, atol=2e-12)
        scalar = table[:, 0].mean()
        scalar.backward()
        for module in (self.model.refinement, *self.model.base.decoders.values()):
            gradients = [p.grad for p in module.parameters()]
            self.assertTrue(all(g is not None and torch.isfinite(g).all() for g in gradients))
            self.assertGreater(sum(float(g.abs().sum()) for g in gradients), 0)
        self.assertTrue(all(p.grad is None for p in self.model.base.encoders.parameters()))
        parameter = self.model.refinement[2].bias
        analytic, original, epsilon = float(parameter.grad[0]), float(parameter[0]), 1e-5
        values = []
        with torch.no_grad():
            for delta in (epsilon, -epsilon):
                parameter[0] = original + delta
                values.append(float(loss()[0][:, 0].mean()))
            parameter[0] = original
        self.assertGreater(abs(analytic), 1e-10)
        self.assertAlmostEqual(analytic, (values[0] - values[1]) / (2 * epsilon), delta=1e-9)

    def test_supervised_training_only_changes_refiner_and_reports_real_work(self):
        parent_hash = _weight_hashes(self.base)
        trained, receipt = train_feedback_denoiser(self.base, self.targets, 17,
                                                   steps=3, batch_size=16)
        self.assertEqual(parent_hash, _weight_hashes(self.base))
        changed = {name for name, value in receipt["groups_changed"].items() if value}
        self.assertEqual(changed, {"all", "refinement"})
        self.assertTrue(all(not p.requires_grad for p in trained.parameters()))
        profile = trained.cost_profile()
        self.assertEqual(receipt["training_forward_work"]["linear_macs"],
                         3 * 16 * (profile["anchor"] + profile["refinement"] + profile["emit_all"]))
        self.assertEqual(receipt["diagnostic_forward_linear_macs"],
                         2 * 32 * (profile["anchor"] + profile["refinement"] + 3 * profile["emit_all"]))
        self.assertTrue(all(entry["supervised_refinement_gradient_l2"] > 0
                            for entry in receipt["gradient_evidence"]))
        self.assertFalse(receipt["ndu_training"])

    def test_invalid_inputs_foreign_stream_and_horizon(self):
        for invalid in (np.zeros((1, 8)), np.full((1, 8), np.nan), torch.ones((1, 8), dtype=torch.bool)):
            with self.assertRaises(ValueError):
                self.model.initialize(invalid, self.bank[0], budget_macs=10**8)
        for invalid in (np.ones(65), np.full(64, np.inf), np.ones(64, dtype=complex)):
            with self.assertRaises(ValueError):
                self.model.initialize(self.q[:1], invalid, budget_macs=10**8)
        other = FeedbackOutputModel(self.base)
        foreign = other.initialize(self.q[:1], self.bank[0], budget_macs=10**8)
        with self.assertRaisesRegex(ValueError, "another"):
            self.model.feedback(foreign)
        state = self.model.initialize(self.q[:1], self.bank[0], budget_macs=10**8)
        for _ in range(self.model.max_refinements):
            self.model.feedback(state)
            state = self.model.refine_step(state, self.bank[1])
        self.model.feedback(state)
        with self.assertRaisesRegex(ValueError, "horizon"):
            self.model.refine_step(state, self.bank[1])


if __name__ == "__main__":
    unittest.main()
