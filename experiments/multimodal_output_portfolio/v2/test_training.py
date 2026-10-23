"""Finite, no-heldout tests of matched training work and actual utility credit."""

import unittest
from unittest.mock import patch

import numpy as np
import torch

from control import CalibrationModel
from controlled_model import ControlledOutputModel, loss_table
from generation_control import GenerationPlanner
from model import MODALITIES, OutputModel, _weight_hashes
from v2.training import (train_matched_supervised, train_ndu,
                         _selected_policy_distribution)


def fixture():
    """One supported calibration truth; refinements demonstrably reduce its error."""
    model = OutputModel({name: 6 for name in MODALITIES})
    with torch.no_grad():
        for parameter in model.parameters():
            parameter.zero_()
        model.initial_latent.bias[0] = 3
        model.refinement[0].weight[0, 0] = 1
        model.refinement[2].weight[0, 0] = -2
        for decoder in model.decoders.values():
            decoder[0].weight[0, 0] = 1
            decoder[2].weight[:, 0] = 1
    targets = {name: np.repeat(np.arange(8, dtype=np.float32)[:, None], 6, axis=1)
               for name in MODALITIES}
    calibration = CalibrationModel(np.zeros(16, dtype=np.int64),
                                    np.zeros((16, 4), dtype=np.int64), smoothing=0)
    grid = np.concatenate((np.eye(8), np.full((1, 8), 1 / 8)))
    protocol = {'gamma': 2, 'penalty': 0.025, 'joint_training': {
        'optimizer': 'AdamW', 'learning_rate': 0.0003, 'weight_decay': 0.0001,
        'gradient_norm_cap': 1, 'anchor_weight': 0.1}}
    return model.eval().requires_grad_(False), calibration, targets, grid, protocol


class TrainingTests(unittest.TestCase):
    def test_actual_forward_and_optimizer_work_match_with_frozen_parent(self):
        base, calibration, targets, grid, protocol = fixture()
        initial, joint = _weight_hashes(base), calibration.joint.copy()
        events, optimizer_steps = [], []

        def record(module, arguments, _output):
            rows = arguments[0].numel() // module.in_features
            events.append((rows, module.in_features, module.out_features))

        handles = [module.register_forward_hook(record) for module in base.modules()
                   if isinstance(module, torch.nn.Linear)]
        original_step = torch.optim.AdamW.step

        def record_step(optimizer, *args, **kwargs):
            optimizer_steps.append(1)
            return original_step(optimizer, *args, **kwargs)

        with patch.object(torch.optim.AdamW, 'step', record_step):
            ndu, left = train_ndu(base, calibration, targets, grid, 17, protocol, 2)
            first_events = list(events)
            first_steps = len(optimizer_steps)
            events.clear()
            optimizer_steps.clear()
            supervised, right = train_matched_supervised(
                base, calibration, targets, grid, 17, protocol, 2)
        for handle in handles:
            handle.remove()
        self.assertEqual(first_events, events)
        self.assertEqual(first_steps, 2)
        self.assertEqual(len(optimizer_steps), 2)
        observed_macs = sum(rows * incoming * outgoing for rows, incoming, outgoing in events)
        self.assertEqual(observed_macs, left['forward_linear_macs'])
        self.assertEqual(observed_macs, right['forward_linear_macs'])
        self.assertEqual(left['forward_portfolio_examples'], right['forward_portfolio_examples'])
        self.assertEqual(left['initial_hashes'], right['initial_hashes'])
        self.assertEqual(initial, _weight_hashes(base))
        np.testing.assert_array_equal(calibration.joint, joint)
        for model, receipt in ((ndu, left), (supervised, right)):
            self.assertEqual(receipt['optimizer_steps'], 2)
            self.assertFalse(receipt['groups_changed']['encoders'])
            self.assertFalse(receipt['lifetime_compute_matched'])
            self.assertTrue(all(not p.requires_grad for p in model.parameters()))
            self.assertTrue(all(torch.isfinite(p).all() for p in model.parameters()))
            self.assertEqual([entry['step'] for entry in receipt['gradient_evidence']], [1, 2])
            self.assertTrue(all(np.isfinite(value) for entry in receipt['gradient_evidence']
                                for value in entry['primary_gradient_l2'].values()))
        evidence = left['gradient_evidence'][0]
        self.assertGreater(evidence['negative_utility_gradient_l2']['refinement'], 0)
        for name in MODALITIES:
            self.assertGreater(evidence['negative_utility_gradient_l2']['decoders.' + name], 0)
        for entry in left['selected_policy_evidence']:
            self.assertAlmostEqual(sum(entry['root_action_probabilities'].values()), 1)
            self.assertAlmostEqual(sum(entry['reached_commitment_depth_probabilities']), 1)
            self.assertGreater(sum(entry['reached_commitment_depth_probabilities'][1:]), 0)
        self.assertGreater(left['separate_control_and_diagnostic_cost'][
            'policy_compilation_process_cpu_seconds'], 0)
        self.assertEqual(right['separate_control_and_diagnostic_cost'][
            'policy_compilation_process_cpu_seconds'], 0)

    def test_zero_utility_refinement_credit_is_not_conflated_with_anchor(self):
        base, calibration, targets, grid, protocol = fixture()
        protocol['penalty'] = 2.0
        _, receipt = train_ndu(base, calibration, targets, grid, 17, protocol, 1)
        gradient = receipt['gradient_evidence'][0]
        self.assertEqual(gradient['negative_utility_gradient_l2']['refinement'], 0)
        self.assertGreater(gradient['unweighted_anchor_gradient_l2']['refinement'], 0)
        self.assertEqual(receipt['selected_policy_evidence'][0][
            'reached_commitment_depth_probabilities'], [1.0, 0.0, 0.0, 0.0])
        self.assertEqual(receipt['gradient_diagnostic_autograd_calls'], 2)

    def test_supervised_objective_has_convex_target_gradient(self):
        base, _, targets, grid, _ = fixture()
        base.double().requires_grad_(True)
        wrapper = ControlledOutputModel(base, copy_model=False)
        q = torch.as_tensor(grid)
        expected = (loss_table(wrapper, q, targets) * q[None]).sum(-1).mean()
        depth_losses, variances = [], []
        for outputs in wrapper.outputs_by_depth(q):
            losses = []
            for name in MODALITIES:
                canonical = torch.as_tensor(targets[name], dtype=torch.float64)
                distances = (canonical[:, None] - canonical[None]).square().mean(-1)
                normalizer = distances[~torch.eye(8, dtype=torch.bool)].mean()
                mixture = q @ canonical
                losses.append((outputs[name] - mixture).square().mean() / normalizer)
            depth_losses.append(torch.stack(losses).mean())
        for name in MODALITIES:
            canonical = torch.as_tensor(targets[name], dtype=torch.float64)
            distances = (canonical[:, None] - canonical[None]).square().mean(-1)
            normalizer = distances[~torch.eye(8, dtype=torch.bool)].mean()
            variances.append(((q @ canonical.square().mean(1))
                              - (q @ canonical).square().mean(1)).mean() / normalizer)
        convex = torch.stack(depth_losses).mean()
        self.assertAlmostEqual(float((expected - convex).detach()),
                               float(torch.stack(variances).mean()), delta=1e-10)
        parameters = [p for name, p in base.named_parameters() if not name.startswith('encoders.')]
        left = torch.autograd.grad(expected, parameters, retain_graph=True)
        right = torch.autograd.grad(convex, parameters)
        for first, second in zip(left, right):
            torch.testing.assert_close(first, second, rtol=1e-9, atol=1e-10)

    def test_policy_distribution_records_reached_acquisition_branches(self):
        _, _, _, grid, _ = fixture()
        truth = np.array([0] * 9 + [1])
        reports = np.full((10, 4), 8)
        reports[:, 1] = truth
        calibration = CalibrationModel(truth, reports, smoothing=0)
        loss = np.ones((4, 9, 8))
        for index in range(8):
            loss[:, index, index] = 0
        loss[:, -1] = 0.5
        planner = GenerationPlanner(calibration, loss, grid)
        roots = [(report, -1, -1, -1) for report in range(9)]
        marginal = calibration.joint.sum(axis=(0, 2, 3, 4))
        summary = _selected_policy_distribution(planner, roots, marginal, 12)
        self.assertEqual(summary['root_action_probabilities'],
                         {'generate': 0, 'audio': 1, 'image': 0, 'video': 0})
        self.assertEqual(summary['reached_commitment_depth_probabilities'], [1, 0, 0, 0])
        self.assertEqual(summary['expected_evidence_acquisitions'], 1)
        self.assertEqual(summary['reached_committed_plan_probabilities'], [
            {'depth': 0, 'portfolio': 0, 'probability': 0.9},
            {'depth': 0, 'portfolio': 1, 'probability': 0.1}])


if __name__ == '__main__':
    unittest.main()
