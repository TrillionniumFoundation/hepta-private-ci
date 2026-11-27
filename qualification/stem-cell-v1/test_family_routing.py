import copy
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import torch
from safetensors.torch import load_file, save_file

from family_routing import FamilyCellBank, POLICY_SCHEMA, ROUTING_PROFILE, transition_parity
from growth_test_support import growth_setup, run_growth
from matrix_bank import CellBank, state_digest, train_bank
from matrix_growth import GrowthNotAdmitted, initial_bank, split_population
from matrix_materials import freeze_config, validate_config


def family_setup(arm="shared_421m_sparse_split_no_ndu", **kwargs):
    p, c, cfg, w = growth_setup(arm, **kwargs)
    fields = {k: v for k, v in cfg.items() if k not in ("schema", "contract_id", "config_id")}
    fields["growth_policy"] = {**fields["growth_policy"], "schema": POLICY_SCHEMA,
                               "sibling_loss_weight": .1, "transition_atol": 1e-6, "transition_rtol": 1e-5}
    return p, c, freeze_config(p, c, **fields), w


def make_pair(dimension=4, classes=2, seed=123):
    p, c, cfg, _ = family_setup(cap=10_000_000)
    profile = validate_config(p, c, cfg)
    with torch.random.fork_rng():
        torch.manual_seed(seed)
        parent = initial_bank(dimension, classes, profile, cfg, parameter_cap=c["max_peak_trainable_params"])
    child, report = split_population(parent, profile, cfg, seed=seed + 1, parameter_cap=c["max_peak_trainable_params"])
    return parent, child, report, profile, cfg


class FamilyRoutingTests(unittest.TestCase):
    def test_seeded_probe_preserves_copied_functions_across_batch_geometries(self):
        for dimension, classes in ((4, 2), (17, 5), (65, 3)):
            for seed in range(3):
                parent, child, _, _, cfg = make_pair(dimension, classes, seed)
                rng = torch.Generator().manual_seed(seed + 99)
                for size in (1, 17, 65):
                    with self.subTest(dimension=dimension, seed=seed, size=size):
                        x = torch.randn(size, dimension, generator=rng)
                        observation = transition_parity(parent, child, x, cfg["growth_policy"])
                        self.assertTrue(observation["passed"], observation)
                        self.assertEqual(observation["examples"], size)
                        self.assertLessEqual(observation["max_tolerance_ratio"], 1)
                        self.assertFalse(observation["global_float_parity_established"])

    def test_adversarial_sibling_scores_cannot_displace_another_parent(self):
        parent, child, _, profile, cfg = make_pair()
        with torch.no_grad():
            parent.gate.weight.zero_(); parent.gate.bias.fill_(-100)
            parent.gate.bias[:2].copy_(torch.tensor([10., 9.]))
            for i, head in enumerate(parent.heads):
                for parameter in head.parameters(): parameter.zero_()
                head[-1].bias.copy_(torch.tensor([float(i), -float(i)]))
        child, _ = split_population(parent, profile, cfg, seed=1, parameter_cap=10000)
        with torch.no_grad():
            child.gate.weight[16:].zero_()
            child.gate.bias[16:].fill_(1e6)
        x = torch.zeros(4, 4)
        torch.testing.assert_close(child(x), parent(x), rtol=0, atol=0)
        groups = child._routing(x)[0]
        self.assertEqual(groups.tolist(), [[0, 1]] * 4)
        # The retained V1 flat router picks both siblings of group zero.
        legacy_cfg = copy.deepcopy(cfg)
        for key in ("sibling_loss_weight", "transition_atol", "transition_rtol"):
            legacy_cfg["growth_policy"].pop(key)
        legacy_cfg["growth_policy"]["schema"] = "hepta.cell-growth-policy.v1"
        flat, _ = split_population(parent, profile, legacy_cfg, seed=1, parameter_cap=10000)
        self.assertGreater((flat(x) - parent(x)).abs().max().item(), .1)

    def test_ties_follow_parent_index_and_inference_executes_two_heads_only(self):
        _, child, _, _, _ = make_pair()
        with torch.no_grad():
            child.gate.weight.zero_(); child.gate.bias.zero_()
            child.gate.weight[16, 0] = 1
            child.gate.weight[17, 0] = -1
        before = child.inventory()
        x = torch.tensor([[1., 0, 0, 0], [-1., 0, 0, 0]])
        counts = [0] * 32
        handles = []
        for index, head in enumerate(child.heads):
            def observe(module, args, index=index): counts[index] += len(args[0])
            handles.append(head.register_forward_pre_hook(observe))
        try:
            child(x)
        finally:
            for handle in handles: handle.remove()
        self.assertEqual(sum(counts), 4)
        self.assertEqual([i for i, n in enumerate(counts) if n], [0, 1, 16, 17])
        self.assertEqual(child._routing(x)[0].tolist(), [[0, 1], [0, 1]])
        self.assertEqual(child.inventory()["sibling_probe_rows"], before["sibling_probe_rows"])

    def test_independent_clones_and_unmodified_parent_state(self):
        parent, child, report, _, _ = make_pair()
        self.assertEqual(report["parent_sha256"], state_digest(parent))
        for i in range(16):
            for a, b, original in zip(child.heads[i].parameters(), child.heads[i+16].parameters(),
                                      parent.heads[i].parameters(), strict=True):
                torch.testing.assert_close(a, original, rtol=0, atol=0)
                torch.testing.assert_close(b, original, rtol=0, atol=0)
                self.assertEqual(len({a.data_ptr(), b.data_ptr(), original.data_ptr()}), 3)
        before = state_digest(parent)
        with torch.no_grad(): child.heads[0][-1].bias.add_(2)
        self.assertEqual(state_digest(parent), before)

    def test_selected_child_and_auxiliary_selector_gradients_are_real(self):
        _, child, _, _, _ = make_pair()
        with torch.no_grad():
            child.gate.weight.zero_(); child.gate.bias.zero_()
            child.gate.bias[:2].fill_(10)
            child.gate.bias[16:].fill_(.1)
            for i, head in enumerate(child.heads):
                for parameter in head.parameters(): parameter.zero_()
                head[-1].bias.copy_(torch.tensor([3., -3.]) if i < 16 else torch.tensor([-3., 3.]))
        child.training_loss(torch.ones(4, 4), torch.zeros(4, dtype=torch.long)).backward()
        self.assertGreater(child.gate.weight.grad[16:].abs().sum().item(), 0.)
        self.assertEqual(child.sibling_supervised_rows, 8)
        self.assertEqual(sum(child.sibling_probe_rows), 16)
        # Counterfactual better Heads were probed under no_grad, not backpropagated.
        self.assertIsNone(child.heads[0][-1].bias.grad)
        self.assertGreater(child.heads[16][-1].bias.grad.abs().sum().item(), 0.)

    def test_nonselected_sibling_nonfinite_probe_cannot_be_ignored(self):
        _, child, _, _, _ = make_pair()
        with torch.no_grad():
            child.gate.weight.zero_(); child.gate.bias.zero_()
            child.gate.bias[:2].fill_(10)
            # Tie chooses child zero. Only the unselected counterfactual is bad.
            child.heads[16][-1].bias.fill_(float("inf"))
        with self.assertRaisesRegex(ValueError, "counterfactual sibling loss"):
            child.training_loss(torch.ones(2, 4), torch.zeros(2, dtype=torch.long))

    def test_equal_siblings_do_not_invent_a_preference_label(self):
        parent, child, _, _, _ = make_pair()
        child.training_loss(torch.ones(4, 4), torch.zeros(4, dtype=torch.long)).backward()
        self.assertEqual(child.sibling_supervised_rows, 0)
        self.assertEqual(sum(child.sibling_probe_rows), 16)
        self.assertEqual(child.gate.weight.grad[16:].abs().sum().item(), 0.)

    def test_training_updates_selector_and_children_not_predecessor(self):
        parent, child, _, _, cfg = make_pair()
        old_parent, old_child = state_digest(parent), state_digest(child)
        x = torch.tensor([[-2., 1., 4., 2.], [2., 1., 4., -2.]])
        before_selector = child.gate.weight[16:].detach().clone()
        train_bank(child, x, torch.tensor([0, 1]), {**cfg, "train_steps": 12}, seed=99)
        self.assertEqual(state_digest(parent), old_parent)
        self.assertNotEqual(state_digest(child), old_child)
        self.assertFalse(torch.equal(child.gate.weight[16:], before_selector))
        self.assertGreater(child.sibling_supervised_rows, 0)
        self.assertTrue(any(not torch.equal(a, b) for i in range(16) for a, b in
                            zip(child.heads[i].parameters(), child.heads[i+16].parameters(), strict=True)))

    def test_matching_final_parameter_counts_and_actual_capacity_doubling(self):
        counts = []
        for suffix in ("", "_64m"):
            for kind in ("split", "direct32"):
                p, c, cfg, _ = family_setup(f"shared_421m_sparse_{kind}{suffix}_no_ndu")
                profile = validate_config(p, c, cfg)
                bank = initial_bank(4, 2, profile, cfg, parameter_cap=10000)
                if kind == "split": bank, _ = split_population(bank, profile, cfg, seed=5, parameter_cap=10000)
                counts.append(bank.inventory()["parameters"])
                self.assertEqual(bank.inventory()["unique_weight_bytes"], counts[-1] * 4)
                self.assertIsInstance(bank, FamilyCellBank)
        self.assertEqual(counts, [896, 896, 1792, 1792])

    def test_live_peak_limit_preflights_allocation(self):
        parent, _, _, profile, cfg = make_pair()
        with patch("matrix_growth.FamilyCellBank", side_effect=AssertionError("must not allocate")):
            with self.assertRaisesRegex(ValueError, "live-parameter cap"):
                split_population(parent, profile, cfg, seed=1, parameter_cap=1343)

    def test_numerical_gate_detects_real_transition_damage(self):
        parent, child, _, _, cfg = make_pair()
        with torch.no_grad():
            for head in child.heads: head[-1].bias.add_(1)
        probe = transition_parity(parent, child, torch.ones(70, 4), cfg["growth_policy"])
        self.assertFalse(probe["passed"])
        self.assertGreater(probe["max_tolerance_ratio"], 1)
        with self.assertRaises(ValueError): transition_parity(parent, child, torch.empty(0, 4), cfg["growth_policy"])

    def test_nonfinite_values_and_bad_policy_rejected(self):
        _, child, _, _, _ = make_pair()
        with self.assertRaises(ValueError): child(torch.full((1, 4), float("nan")))
        for key, value in (("sibling_loss_weight", 0), ("transition_atol", 1),
                           ("transition_rtol", float("nan")), ("transition_atol", True)):
            p, c, cfg, _ = family_setup()
            fields = {k: v for k, v in cfg.items() if k not in ("schema", "contract_id", "config_id")}
            fields["growth_policy"][key] = value
            with self.subTest(key=key, value=value), self.assertRaises(ValueError): freeze_config(p, c, **fields)
        with self.assertRaises(ValueError): family_setup("shared_421m_sparse_fixed16_no_ndu")

    def test_existing_flat_profile_is_not_reinterpreted(self):
        legacy = run_growth(growth_setup())
        self.assertIs(type(legacy[0]), CellBank)
        self.assertFalse(legacy[1]["growth_receipt"]["function_preserving"])
        self.assertNotIn("routing_profile", legacy[1]["inventory"])
        new = run_growth(family_setup())
        self.assertIs(type(new[0]), FamilyCellBank)
        self.assertTrue(new[1]["growth_receipt"]["transition_probe"]["passed"])
        self.assertEqual(new[1]["work_observation"]["unknown_operators"], {})

    def test_trained_checkpoint_roundtrip_under_bound_family_geometry(self):
        bank, _, rows = run_growth(family_setup())
        p, c, cfg, _ = family_setup("shared_421m_sparse_direct32_no_ndu")
        restored = initial_bank(4, 2, validate_config(p, c, cfg), cfg, parameter_cap=10000)
        with tempfile.TemporaryDirectory() as td:
            target = Path(td) / "bank.safetensors"
            save_file(bank.state_dict(), str(target))
            restored.load_state_dict(load_file(str(target)), strict=True)
        self.assertEqual(state_digest(bank), state_digest(restored))
        x = torch.randn(10, 4)
        torch.testing.assert_close(bank(x), restored(x), rtol=0, atol=0)
        self.assertEqual(restored.inventory()["routing_profile"], ROUTING_PROFILE)

    def test_corrupted_transition_stops_before_post_split_training(self):
        actual_split = split_population
        def damaged(*args, **kwargs):
            child, report = actual_split(*args, **kwargs)
            with torch.no_grad():
                for head in child.heads: head[-1].bias.add_(1.)
            return child, report
        with patch("matrix_growth.split_population", side_effect=damaged):
            with self.assertRaises(GrowthNotAdmitted) as failure: run_growth(family_setup())
        self.assertEqual(failure.exception.report["disposition"], "transition_parity_failed")
        self.assertFalse(failure.exception.report["transition_probe"]["passed"])


if __name__ == "__main__":
    unittest.main()
