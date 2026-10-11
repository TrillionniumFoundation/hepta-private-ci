"""Explicit CPU tensor suite; dependency absence FAILS, it does not silently skip.

Kept outside test_*.py so the inherited model-free workflow stays model-free.
Run: PYTHONPATH=qualification/neuron-stem python -m unittest four_gate_tensor_tests -v
"""
import copy
import unittest

import numpy as np
import torch
from torch.nn import functional as F

from four_gate_core import (COMPUTE_ARMS, TASKS, causal_depth, default_plan, digest,
                            generic_nested_risk, recursive_value)
from four_gate_compute_probe import Encoder, Heads, measure_one, weights_digest
from four_gate_learning_probe import (GatedHead, NODES, RecurrentReasoner, FlatReasoner,
                                      activation_trace, configure, decision_tree, fit,
                                      graph_case, tensor_graphs)


class RealTensorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        configure()

    def setUp(self):
        torch.manual_seed(121)

    def test_encoder_batch_matches_serial_joint_input(self):
        model = Encoder().eval()
        tokens = torch.randint(0, 257, (12, 9))
        with torch.no_grad():
            batch = model(tokens)
            serial = torch.cat([model(row.unsqueeze(0)) for row in tokens])
        torch.testing.assert_close(batch, serial, rtol=1e-5, atol=1e-7)
        self.assertEqual(model.calls, 13)
        self.assertEqual(model.samples, 24)
        self.assertEqual(model.tokens, 216)

    def test_encoder_weights_not_changed_by_execution(self):
        model = Encoder().eval()
        before = weights_digest(model)
        model(torch.randint(0, 257, (8, 8)))
        self.assertEqual(before, weights_digest(model))

    def test_physical_cache_reuses_fewer_encoder_items(self):
        base = {"logical_cells": 64, "active_fraction": 1., "input_repeat_fraction": .9,
                "task_similarity": "high", "repetition": 0, "seed": 20261011,
                "plan_digest": digest(default_plan()), "host_session_digest": digest("unit-cpu-host")}
        rows = []
        for arm in COMPUTE_ARMS:
            rows.append(measure_one(dict(base, arm=arm, execution_id="unit/" + arm)))
        self.assertEqual(rows[0]["encoded_samples"], 64)
        self.assertEqual(rows[1]["encoded_samples"], 64)
        self.assertEqual(rows[2]["encoded_samples"], 6)
        self.assertEqual(rows[2]["cache_hits"] + rows[2]["inflight_coalesced"], 58)
        self.assertEqual(len(rows[2]["ticked_cell_ids"]), 64)
        self.assertEqual(len(rows[2]["request_latencies_ms"]), 64)
        self.assertEqual(rows[0]["weights_digest"], rows[2]["weights_digest"])

    def test_head_inventory_has_isolated_trainable_rows(self):
        heads = Heads(3)
        before = heads.gate.detach().clone()
        optimizer = torch.optim.SGD(heads.parameters(), lr=.1)
        loss = heads(torch.randn(4, 16), torch.zeros(4, dtype=torch.long),
                     torch.zeros(4, dtype=torch.long)).square().mean()
        loss.backward()
        optimizer.step()
        self.assertFalse(torch.equal(before[0], heads.gate[0]))
        self.assertTrue(torch.equal(before[1:], heads.gate[1:]))

    def test_learned_head_changes_frozen_clone_does_not(self):
        head = GatedHead()
        frozen = copy.deepcopy(head)
        before = weights_digest(head)
        x = torch.randn(32, 24)
        y = (x[:, 0] > 0).long()
        fit(head, x, y, 5)
        self.assertNotEqual(before, weights_digest(head))
        self.assertEqual(before, weights_digest(frozen))

    def test_frozen_stem_no_gradient_from_head_training(self):
        stem = torch.nn.Linear(8, 24)
        before = weights_digest(stem)
        with torch.no_grad():
            x = stem(torch.randn(16, 8))
        fit(GatedHead(), x, (x[:, 0] > 0).long(), 3)
        self.assertEqual(before, weights_digest(stem))
        self.assertTrue(all(p.grad is None for p in stem.parameters()))

    def test_each_graph_family_contains_both_outcomes(self):
        rng = np.random.default_rng(13)
        for family in TASKS:
            a = graph_case(rng, 8, family, blocked=False)
            b = graph_case(rng, 8, family, blocked=True)
            expected = {1, 2} if family == "missing_evidence" else {0, 1}
            self.assertEqual({a["label"], b["label"]}, expected)

    def test_graph_bounds_and_unknown_family_rejected(self):
        rng = np.random.default_rng(13)
        for length in (0, NODES, True, 2.5):
            with self.assertRaises(ValueError):
                graph_case(rng, length)
        with self.assertRaises(ValueError):
            graph_case(rng, 4, "unregistered")

    def test_tensor_ingress_excludes_oracle_label(self):
        case = graph_case(np.random.default_rng(5), 7)
        before = tensor_graphs([case])
        changed = dict(case, label=999, oracle_trajectory=np.full((16, 16), np.nan))
        after = tensor_graphs([changed])
        for a, b in zip(before, after):
            torch.testing.assert_close(a, b)

    def test_recurrent_cell_receives_real_gradients(self):
        model = RecurrentReasoner()
        case = graph_case(np.random.default_rng(8), 3)
        a, s, h = tensor_graphs([case])
        state = s
        for _ in range(4):
            state = model.step(a, state, s, h)
        target = torch.from_numpy(case["oracle_trajectory"][3]).unsqueeze(0)
        F.binary_cross_entropy(state.clamp(1e-6, 1-1e-6), target).backward()
        self.assertTrue(any(p.grad is not None and p.grad.abs().sum() > 0 for p in model.parameters()))
        self.assertTrue(torch.isfinite(state).all())

    def test_flat_control_one_forward_shape(self):
        cases = [graph_case(np.random.default_rng(i), 4) for i in range(3)]
        output = FlatReasoner()(*tensor_graphs(cases))
        self.assertEqual(tuple(output.shape), (3, 4, 16))

    def test_recorded_recurrence_depth_is_not_parallel_count(self):
        self.assertEqual(causal_depth(activation_trace(16))["sequential_cell_depth"], 16)
        parallel = [{"event_id": str(i), "activation_id": str(i), "kind": "cell", "parents": []}
                    for i in range(16)]
        self.assertEqual(causal_depth(parallel)["sequential_cell_depth"], 1)

    def test_immutable_stopping_table_matches_direct_values(self):
        for depth in (1, 4, 8, 12, 16):
            for p0, p1 in ((.1, .9), (.8, .9), (.95, .96)):
                for risk in (0., 1. + .5 * depth / 16):
                    tree = decision_tree(p0, p1, .008 * (16 - depth))
                    direct, actions = recursive_value(tree, "root", risk=risk)
                    independent = generic_nested_risk(tree, "root", risk=risk)
                    self.assertAlmostEqual(direct, independent, places=12)
                    cache = {(depth, p0, p1, risk): (direct, actions["root"])}
                    self.assertEqual(cache[(depth, p0, p1, risk)][1], actions["root"])


if __name__ == "__main__":
    unittest.main()
