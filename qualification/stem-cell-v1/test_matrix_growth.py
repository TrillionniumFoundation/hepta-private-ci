import copy
import unittest
from unittest.mock import patch

import torch

from growth_test_support import growth_setup, run_growth
from matrix_bank import state_digest
from matrix_growth import GrowthNotAdmitted, initial_bank, split_population, validate_growth_policy
from matrix_materials import freeze_config, validate_config
from matrix_test_support import FixtureEncoder, setup


class GrowthTests(unittest.TestCase):
    def initial(self, parts):
        p, c, cfg, _ = parts
        profile = validate_config(p, c, cfg)
        with torch.random.fork_rng():
            torch.manual_seed(p["seed"])
            bank = initial_bank(4, 2, profile, cfg, parameter_cap=c["max_peak_trainable_params"])
        return bank, profile

    def test_initial_population_is_preflighted_against_lifecycle_cap(self):
        parts = growth_setup(cap=447)
        p,c,cfg,_ = parts
        profile = validate_config(p,c,cfg)
        with patch("matrix_growth.CellBank", side_effect=AssertionError("must not allocate")):
            with self.assertRaisesRegex(ValueError, "initial population"):
                initial_bank(4,2,profile,cfg,parameter_cap=447)

    def test_clone_creates_independent_tensors_and_preserves_parent(self):
        parts = growth_setup(); bank, profile = self.initial(parts)
        before = state_digest(bank)
        after, report = split_population(bank, profile, parts[2], seed=12, parameter_cap=1344)
        self.assertEqual(state_digest(bank), before)
        self.assertEqual((len(bank.heads), len(after.heads)), (16, 32))
        self.assertEqual((report["parent_parameters"], report["final_parameters"], report["peak_live_trainable_params"]), (448, 896, 1344))
        self.assertEqual(report["transition_model_weight_bytes"], 1344 * 4)
        self.assertFalse(report["function_preserving"])
        pointers = []
        for i, child in enumerate(after.heads):
            for old, new in zip(bank.heads[i % 16].parameters(), child.parameters(), strict=True):
                torch.testing.assert_close(old, new, rtol=0, atol=0)
                self.assertNotEqual(old.data_ptr(), new.data_ptr())
                pointers.append(new.data_ptr())
        self.assertEqual(len(pointers), len(set(pointers)))

    def test_transition_ceiling_checked_before_successor_allocation(self):
        parts = growth_setup(); bank, profile = self.initial(parts)
        before = state_digest(bank)
        with patch("matrix_growth.CellBank", side_effect=AssertionError("should not allocate")):
            with self.assertRaisesRegex(ValueError, "live-parameter"):
                split_population(bank, profile, parts[2], seed=12, parameter_cap=1343)
        self.assertEqual(state_digest(bank), before)

    def test_split_runtime_trains_32_cells_and_meters_actual_migration(self):
        parts = growth_setup(); bank, manifest, predictions = run_growth(parts)
        self.assertEqual(manifest["schema"], "hepta.stem.bound-execution.v2")
        g = manifest["growth_receipt"]
        self.assertTrue(g["split_performed"])
        self.assertEqual(g["optimizer_reset_count"], 1)
        self.assertEqual(g["decision_step"], 2)
        self.assertGreater(manifest["phase_flops"]["migration"], 0)
        self.assertGreater(manifest["phase_flops"]["train"], 0)
        self.assertEqual(manifest["work_observation"]["unknown_operators"], {})
        self.assertEqual(manifest["training"]["steps"], 6)
        self.assertEqual(manifest["training"]["examples_seen"], 12)
        self.assertNotEqual(g["initialized_child_sha256"], manifest["trained_bank_sha256"])
        self.assertEqual(manifest["inventory"]["parameters"], 896)
        self.assertEqual(manifest["peak_trainable_params"], 1344)
        self.assertEqual([r["status"] for r in predictions], ["completed", "completed"])
        self.assertFalse(manifest["independent_success_established"])
        self.assertEqual(manifest["execution_kind"], "mechanism_fixture")
        self.assertTrue(any(not torch.equal(bank.heads[i][0].weight, bank.heads[i+16][0].weight) for i in range(16)))

    def test_direct_control_has_same_final_parameters_and_reset_not_dummy_migration(self):
        a = run_growth(growth_setup())[1]
        b = run_growth(growth_setup("shared_421m_sparse_direct32_no_ndu"))[1]
        self.assertEqual(a["inventory"]["parameters"], b["inventory"]["parameters"])
        self.assertEqual(a["training"]["steps"], b["training"]["steps"])
        self.assertEqual(a["growth_receipt"]["policy_id"], b["growth_receipt"]["policy_id"])
        self.assertEqual(b["growth_receipt"]["optimizer_reset_count"], 1)
        self.assertFalse(b["growth_receipt"]["split_performed"])
        self.assertEqual(b["phase_flops"]["migration"], 0)
        self.assertEqual(b["peak_trainable_params"], 896)
        self.assertNotEqual(a["phase_flops"]["train"], b["phase_flops"]["train"])

    def test_64m_control_grows_real_double_capacity(self):
        a = run_growth(growth_setup())[1]
        b = run_growth(growth_setup("shared_421m_sparse_split_64m_no_ndu"))[1]
        self.assertEqual(b["inventory"]["parameters"], 2 * a["inventory"]["parameters"])
        self.assertEqual(b["peak_trainable_params"], 2 * a["peak_trainable_params"])

    def test_residual_or_data_shortfall_refuses_evaluation_calls(self):
        for options in ({"threshold": 100.}, {"groups": 3}):
            backend = FixtureEncoder()
            with self.subTest(options=options), self.assertRaises(GrowthNotAdmitted) as caught:
                run_growth(growth_setup(**options), backend)
            self.assertEqual(caught.exception.report["disposition"], "growth_not_triggered")
            self.assertFalse(caught.exception.report["split_performed"])
            self.assertEqual(backend.calls, 2)
            self.assertTrue(all(r["sample_id"].startswith("t") for r in backend.seen))

    def test_migration_cap_is_enforced_during_actual_growth(self):
        from execution_meter import BudgetStop
        from paired_execution import freeze_contract
        p,c,cfg,w = growth_setup()
        names = ("source_sha", "workload_sha256", "task_ids", "device_id", "observer_id", "train_cutoff_ns", "eval_start_ns", "eval_end_ns", "max_peak_trainable_params")
        contract = freeze_contract(p, **{k:c[k] for k in names}, flops_caps={**c["flops_caps"], "migration": 0})
        values = {k:v for k,v in cfg.items() if k not in ("schema", "config_id", "contract_id")}
        cfg = freeze_config(p, contract, **values)
        backend = FixtureEncoder()
        with self.assertRaisesRegex(BudgetStop, "formula_flop_budget:migration"):
            run_growth((p,contract,cfg,w), backend)
        self.assertEqual(backend.calls, 2)

    def test_fixed_seed_repeats_parameters_routing_and_formula_work(self):
        first, second = run_growth(growth_setup())[1:], run_growth(growth_setup())[1:]
        self.assertEqual(first[0]["trained_bank_sha256"], second[0]["trained_bank_sha256"])
        self.assertEqual(first[0]["phase_flops"], second[0]["phase_flops"])
        self.assertEqual([r["logits"] for r in first[1]], [r["logits"] for r in second[1]])

    def test_fresh_generation_no_evaluation_labels_enter_growth(self):
        p,c,cfg,w = growth_setup(); w["eval"][0]["label"] = 1
        backend = FixtureEncoder()
        with self.assertRaises(ValueError): run_growth((p,c,cfg,w), backend)
        self.assertEqual(backend.calls, 0)

    def test_v4_requires_meter_lifecycle_cap_and_explicit_growth_policy(self):
        p,c,cfg,w = growth_setup()
        self.assertEqual(cfg["schema"], "hepta.stem.bound-hf-config.v4")
        validate_config(p,c,cfg)
        for key in ("growth_policy", "measurement_policy"):
            bad = copy.deepcopy(cfg); del bad[key]
            with self.subTest(key=key), self.assertRaises(ValueError): validate_config(p,c,bad)
        _, legacy, _, _ = setup()
        values = {k:v for k,v in cfg.items() if k not in ("schema", "config_id", "contract_id")}
        with self.assertRaisesRegex(ValueError, "lifecycle cap"):
            freeze_config(p,legacy,**values)

    def test_invalid_policy_and_ndu_relabeling_rejected(self):
        p,c,cfg,w = growth_setup()
        for key, value in (("decision_step",True),("decision_step",6),("loss_threshold",float("nan")),
                           ("minimum_source_groups",0),("gate_noise_scale",0),("extra",True)):
            policy = {**cfg["growth_policy"],key:value}
            with self.subTest(key=key), self.assertRaises(ValueError):
                validate_growth_policy(policy,train_steps=6,width_units=4,arm_id=cfg["arm_id"])
        for arm in ("shared_421m_sparse_split_ndu", "replicated_421m_no_ndu"):
            with self.subTest(arm=arm), self.assertRaises(ValueError): growth_setup(arm)

    def test_v1_v2_v3_still_reject_split_without_new_growth_policy(self):
        p,c,cfg,w = growth_setup()
        vals = {k:v for k,v in cfg.items() if k not in ("schema", "config_id", "contract_id", "growth_policy")}
        with self.assertRaisesRegex(ValueError, "no relabeling"):
            freeze_config(p,c,**vals)


if __name__ == "__main__":
    unittest.main()
