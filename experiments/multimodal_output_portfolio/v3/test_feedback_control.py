"""Independent finite-strategy, neural-path and work-accounting fixtures.

These tests do not use registered heldout worlds or establish benchmark gains.
The oracle enumerates complete stopping strategies and terminal distributions;
it does not reuse the implementation's Bellman backup or certainty equivalent.
"""

from itertools import product
import math
import unittest
from unittest.mock import patch

import numpy as np
import torch

import feedback_control as control
from feedback_model import FeedbackOutputModel, weight_hashes
from feedback_training import train_pair
from metrics import score_outputs
from model import MODALITIES, OutputModel


def scalar_ce(outcomes, gamma):
    if gamma == 0:
        return math.fsum(probability * value for probability, value in outcomes)
    floor = min(value for probability, value in outcomes if probability > 0)
    mass = math.fsum(probability * math.exp(-gamma * (value - floor))
                     for probability, value in outcomes if probability > 0)
    return floor - math.log(mass) / gamma


def strategy_oracle(losses, condition, depth, node, probabilities, gamma, penalty, rows=None):
    """Enumerate every stopping tree, then every rectangular nature strategy."""
    horizon = len(losses) - 1
    laws = [probabilities] if rows is None else rows

    def plans(time):
        result = [None]
        if time < horizon:
            result.extend(product(plans(time + 1), repeat=3))
        return result

    def distributions(plan, time, index):
        if plan is None:
            return [[(1., -float(losses[time][condition, index]))]]
        children = [distributions(child, time + 1, 3 * index + j)
                    for j, child in enumerate(plan)]
        result = []
        for law in laws:
            for future in product(*children):
                result.append([(float(law[j]) * p, value - penalty)
                               for j, outcomes in enumerate(future) for p, value in outcomes])
        return result

    candidates = [(min(scalar_ce(outcomes, gamma)
                       for outcomes in distributions(plan, depth, node)), plan)
                  for plan in plans(depth)]
    # Strict > preserves the initial STOP option at exact ties.
    best = candidates[0]
    for candidate in candidates[1:]:
        if candidate[0] > best[0] + 1e-12:
            best = candidate
    return best[0], "emit" if best[1] is None else "refine"


class FeedbackControlTests(unittest.TestCase):
    def setUp(self):
        with torch.random.fork_rng(devices=[]):
            torch.manual_seed(718)
            base = OutputModel(dict(zip(MODALITIES, (12, 16, 20, 24)))).double().eval()
        self.model = FeedbackOutputModel(base, seed=37, max_refinements=2)
        with torch.no_grad():
            anchor = self.model.anchor_tensor(torch.eye(8, dtype=torch.float64))
            self.targets = {name: value.numpy().copy()
                            for name, value in self.model.decode_tensor(anchor).items()}
        self.model.reset_costs()
        self.probabilities = [.2, .5, .3]

    def test_batched_tree_matches_every_independently_executed_path_and_class(self):
        with torch.no_grad():
            latents, losses, banks = control.build_tree(self.model, self.targets, 5, scale=.12)
            for condition in range(8):
                q = torch.eye(8, dtype=torch.float64)[condition:condition + 1]
                anchor = self.model.base.initial_latent(q)
                for depth in range(3):
                    for node, digits in enumerate(product(range(3), repeat=depth + 1)):
                        value = anchor + torch.as_tensor(banks[0][digits[0]])
                        for time, branch in enumerate(digits[1:], 1):
                            residual = value - anchor
                            gain = self.model.refinement(torch.cat((q, residual), dim=1))
                            value = anchor + (1 - gain) * residual + torch.as_tensor(banks[time][branch])
                        torch.testing.assert_close(latents[depth][condition, node], value[0],
                                                   rtol=0, atol=1e-13)
                        generated = {name: decoder(value).numpy()
                                     for name, decoder in self.model.base.decoders.items()}
                        external = score_outputs(generated, np.array([condition]), self.targets)["loss"][0]
                        self.assertAlmostEqual(float(losses[depth][condition, node]), external, places=12)

    def test_nominal_and_robust_backups_equal_exhaustive_terminal_strategy_game(self):
        rng = np.random.default_rng(184)
        losses = [rng.uniform(.01, 1.8, (8, 3 ** (depth + 1))) for depth in range(3)]
        latent = [torch.zeros((8, 3 ** (depth + 1), 64)) for depth in range(3)]
        tensors = [torch.as_tensor(value) for value in losses]
        laws = [self.probabilities, [.45, .1, .45]]
        for gamma in (0., 2.):
            for mode in ("feedback", "robust"):
                with patch.object(control, "build_tree", return_value=(latent, tensors, [None] * 3)):
                    policy = control.compile_policy(self.model, self.targets, 5, gamma=gamma,
                                                    penalty=.03, probabilities=self.probabilities,
                                                    ambiguity_rows=laws, mode=mode)
                for depth in range(3):
                    for condition in range(8):
                        for node in range(3 ** (depth + 1)):
                            expected, action = strategy_oracle(
                                losses, condition, depth, node, self.probabilities, gamma, .03,
                                rows=laws if mode == "robust" else None)
                            self.assertAlmostEqual(policy.values[depth][condition, node], expected, places=12)
                            self.assertEqual(policy.actions[depth][condition, node], action)
                if mode == "feedback":
                    expected_root = math.fsum(scalar_ce(
                        [(self.probabilities[j], strategy_oracle(
                            losses, condition, 0, j, self.probabilities, gamma, .03)[0])
                         for j in range(3)], gamma) for condition in range(8)) / 8
                    utility, _ = control.selected_utility(tensors, self.probabilities, gamma, .03)
                    self.assertAlmostEqual(float(utility), expected_root, places=12)

    def test_continuation_option_is_distinct_from_one_step_myopia_and_static_cost(self):
        losses = [torch.full((8, 3), .5, dtype=torch.float64),
                  torch.full((8, 9), .8, dtype=torch.float64),
                  torch.zeros((8, 27), dtype=torch.float64)]
        latent = [torch.zeros((8, value.shape[1], 64)) for value in losses]
        policies = {}
        for mode in ("feedback", "myopic"):
            with patch.object(control, "build_tree", return_value=(latent, losses, [None] * 3)):
                policies[mode] = control.compile_policy(self.model, self.targets, 5, gamma=2,
                    penalty=.05, probabilities=self.probabilities, mode=mode)
        self.assertTrue(np.all(policies["feedback"].actions[0] == "refine"))
        self.assertTrue(np.all(policies["myopic"].actions[0] == "emit"))
        np.testing.assert_allclose(policies["feedback"].values[0], -.1, rtol=0, atol=1e-14)
        np.testing.assert_allclose(policies["myopic"].values[0], -.5, rtol=0, atol=1e-14)
        np.testing.assert_allclose(policies["myopic"].continuation[0], -.85, rtol=0, atol=1e-14)
        fixed = control.choose_static_depth(policies["feedback"])
        self.assertEqual(fixed["depth"], 2)
        np.testing.assert_allclose(fixed["nominal_utilities"], [-.5, -.85, -.1], atol=1e-14)

    def test_decisions_bind_the_actual_current_latent_without_future_draws(self):
        policy = control.compile_policy(self.model, self.targets, 5, scale=.12)
        condition, digits = 3, (2, 0, 1)
        state = self.model.initialize(torch.eye(8)[condition:condition + 1],
                                      policy.banks[0][digits[0]], budget_macs=10**8)
        node = 0
        for depth, digit in enumerate(digits):
            node = 3 * node + digit
            feedback = self.model.feedback(state)
            observed = policy.observe(condition, feedback)
            self.assertEqual((observed["depth"], observed["node"]), (depth, node))
            self.assertEqual(observed["action"], policy.actions[depth][condition, node])
            other = dict(feedback, latent=feedback["latent"] + .1)
            with self.assertRaisesRegex(ValueError, "outside"):
                policy.observe(condition, other)
            with self.assertRaisesRegex(ValueError, "outside"):
                policy.observe((condition + 1) % 8, feedback)
            if depth + 1 < len(digits):
                state = self.model.refine_step(state, policy.banks[depth + 1][digits[depth + 1]])
        self.model.emit(state)

    def test_offline_tree_and_compilation_cost_equal_real_linear_hooks(self):
        observed = []
        def record(module, args, _output):
            observed.append(args[0].numel() // module.in_features
                            * module.in_features * module.out_features)
        hooks = [layer.register_forward_hook(record) for layer in self.model.modules()
                 if isinstance(layer, torch.nn.Linear)]
        with torch.no_grad():
            control.build_tree(self.model, self.targets, 5, scale=.12)
        tree_work = self.model.work_receipt()
        self.assertEqual(sum(observed), tree_work["linear_macs"])
        profile = self.model.cost_profile()
        nodes, transitions = 8 * (3 + 9 + 27), 8 * (9 + 27)
        expected = 8 * profile["anchor"] + transitions * profile["refinement"] + nodes * profile["emit_all"]
        self.assertEqual(tree_work["linear_macs"], expected)
        self.assertEqual(tree_work["anchor_examples"], 8)
        self.assertEqual(tree_work["refinement_examples"], transitions)
        self.assertEqual(tree_work["decoder_examples"], {name: nodes for name in MODALITIES})
        policy = control.compile_policy(self.model, self.targets, 5, scale=.12)
        self.assertEqual(policy.receipt["offline_forward_linear_macs"], expected)
        self.assertEqual(sum(observed), 2 * expected)
        for hook in hooks:
            hook.remove()

    def test_selected_global_utility_gradient_matches_independent_strategy_difference(self):
        self.model.refinement.requires_grad_(True)
        _, tensors, _ = control.build_tree(self.model, self.targets, 5, scale=.12)
        utility, decisions = control.selected_utility(tensors, self.probabilities, 2., .001)
        utility.backward()
        parameter = self.model.refinement[2].bias
        index = int(parameter.grad.abs().argmax())
        analytic, original, epsilon = float(parameter.grad[index]), float(parameter[index]), 1e-5
        self.assertGreater(abs(analytic), 1e-8)
        results = []
        with torch.no_grad():
            for delta in (epsilon, -epsilon):
                parameter[index] = original + delta
                _, shifted, _ = control.build_tree(self.model, self.targets, 5, scale=.12)
                _, shifted_decisions = control.selected_utility(shifted, self.probabilities, 2., .001)
                self.assertTrue(all(torch.equal(a, b) for a, b in zip(decisions, shifted_decisions)))
                losses = [value.numpy() for value in shifted]
                results.append(math.fsum(scalar_ce(
                    [(self.probabilities[j], strategy_oracle(
                        losses, condition, 0, j, self.probabilities, 2., .001)[0])
                     for j in range(3)], 2.) for condition in range(8)) / 8)
            parameter[index] = original
        self.assertAlmostEqual(analytic, (results[0] - results[1]) / (2 * epsilon), delta=1e-8)

    def test_matched_training_hooks_frozen_parent_and_utility_credit(self):
        parent = weight_hashes(self.model)
        observed = []
        def record(module, args, _output):
            observed.append(args[0].numel() // module.in_features
                            * module.in_features * module.out_features)
        hooks = [layer.register_forward_hook(record) for layer in self.model.modules()
                 if isinstance(layer, torch.nn.Linear)]
        settings = {"ndu_learning_rate": .001, "weight_decay": .0001,
                    "matched_supervised_steps": 2, "ndu_steps": 2, "noise_scale": .12,
                    "nominal_branch_probabilities": self.probabilities,
                    "gamma": 2., "cost_penalty_per_refinement": .001}
        models, receipts = train_pair(self.model, self.targets, 5, settings)
        for hook in hooks:
            hook.remove()
        self.assertEqual(parent, weight_hashes(self.model))
        self.assertEqual(receipts["supervised"]["cost"], receipts["ndu"]["cost"])
        self.assertEqual(sum(observed), sum(receipt["cost"]["linear_macs"] for receipt in receipts.values()))
        for mode in ("supervised", "ndu"):
            self.assertTrue(all(not parameter.requires_grad for parameter in models[mode].parameters()))
            receipt = receipts[mode]
            changed = {name for name in parent if receipt["initial_hashes"][name] != receipt["final_hashes"][name]}
            self.assertEqual(changed, {"all", "refinement"})
            self.assertTrue(all(entry["refinement_objective_gradient_l2"] > 0 for entry in receipt["history"]))
        self.assertTrue(receipts["ndu"]["gradient_is_utility_only"])
        self.assertFalse(receipts["supervised"]["gradient_is_utility_only"])


if __name__ == "__main__":
    unittest.main()
