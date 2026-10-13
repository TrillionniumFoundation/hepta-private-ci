import copy
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import torch
from safetensors.torch import save_file

from hf_encoder_kernel import snapshot_digest, validate_encoder_loading_info, verify_loaded_safetensors
from matrix_bank import CellBank, state_digest
from matrix_materials import PUBLIC_FIELDS, validate_config
from matrix_runtime import execute, publish_prediction_bundle
from matrix_test_support import FixtureEncoder, setup


class MatrixRuntimeTests(unittest.TestCase):
    def test_same_total_actual_parameters_for_16_and_32_cells(self):
        counts = []
        for arm in ("shared_421m_head_no_ndu", "shared_421m_sparse_fixed16_no_ndu",
                    "shared_421m_sparse_direct32_no_ndu"):
            plan, contract, config, _ = setup(arm)
            bank = CellBank(4, 2, validate_config(plan, contract, config), 3)
            inv = bank.inventory()
            counts.append(inv["parameters"])
            self.assertEqual(inv["gate_params"] + inv["head_params"], inv["parameters"])
            self.assertEqual(inv["unique_weight_bytes"], inv["parameters"] * 4)
        self.assertEqual(counts, [672, 672, 672])

    def test_capacity_control_really_doubles_total_trainable_parameters(self):
        counts = []
        for arm in ("shared_421m_sparse_direct32_no_ndu", "shared_421m_sparse_direct32_64m_no_ndu"):
            plan, contract, config, _ = setup(arm)
            bank = CellBank(4, 2, validate_config(plan, contract, config), 3)
            counts.append(bank.inventory()["parameters"])
        self.assertEqual(counts, [672, 1344])

    def test_dense_and_sparse_execute_different_subsets_same_weight_shapes(self):
        counts, states = [], []
        for arm in ("shared_421m_head_no_ndu", "shared_421m_sparse_fixed16_no_ndu"):
            plan, contract, config, _ = setup(arm)
            with torch.random.fork_rng():
                torch.manual_seed(8)
                bank = CellBank(4, 2, validate_config(plan, contract, config), 3)
            states.append(state_digest(bank))
            bank(torch.ones(3, 4))
            counts.append(sum(bank.executed_rows))
        self.assertEqual(states[0], states[1])
        self.assertEqual(counts, [48, 6])

    def test_actual_tensor_training_and_forward_seal_without_outcomes(self):
        plan, contract, config, work = setup()
        backend = FixtureEncoder()
        _, manifest, predictions = execute(plan, contract, config, work, backend, clock=lambda: 25)
        self.assertEqual(manifest["execution_kind"], "mechanism_fixture")
        self.assertNotEqual(manifest["initial_bank_sha256"], manifest["trained_bank_sha256"])
        self.assertEqual(manifest["inventory"]["cells"], 16)
        self.assertEqual(manifest["encoder_calls"], 5)  # Two train, one warmup, two eval.
        self.assertEqual(sum(manifest["inventory"]["executed_rows"]), 22)
        self.assertEqual([p["status"] for p in predictions], ["completed", "completed"])
        self.assertEqual([p["task_id"] for p in predictions], contract["task_ids"])
        self.assertTrue(all(set(r) == PUBLIC_FIELDS for r in backend.seen))
        self.assertTrue(backend.reverified)
        self.assertFalse(manifest["outcomes_loaded"])
        self.assertFalse(manifest["actual_compute_caps_verified"])
        self.assertIsNone(manifest["phase_flops"]["inference"])
        self.assertTrue(all(p["energy_joules"] is None and p["peak_memory_bytes"] is None for p in predictions))

    def test_failed_inference_is_retained_not_removed(self):
        p, c, cfg, w = setup()
        _, manifest, rows = execute(p, c, cfg, w, FixtureEncoder(fail_task="e1"), clock=lambda: 25)
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[1]["status"], "failed")
        self.assertIsNone(rows[1]["logits"])
        self.assertEqual(manifest["encoder_calls"], 5)

    def test_feature_budget_rejects_before_first_model_call(self):
        p, c, cfg, w = setup()
        from matrix_materials import freeze_config
        values = {k:v for k,v in cfg.items() if k not in ("schema", "contract_id", "config_id")}
        values["max_feature_bytes"] = 1
        cfg = freeze_config(p, c, **values)
        backend = FixtureEncoder()
        with self.assertRaises(ValueError):
            execute(p, c, cfg, w, backend, clock=lambda: 25)
        self.assertEqual(backend.calls, 0)

    def test_outside_window_rejects_and_timeouts_keep_denominator(self):
        p, c, cfg, w = setup()
        with self.assertRaises(ValueError):
            execute(p, c, cfg, w, FixtureEncoder(), clock=lambda: 101)
        times = iter([25, 101, 101, 101, 101])
        _, _, rows = execute(p, c, cfg, w, FixtureEncoder(), clock=lambda: next(times))
        self.assertEqual([r["status"] for r in rows], ["timed_out", "timed_out"])

    def test_reproducible_training_for_fixed_seed_and_materials(self):
        p, c, cfg, w = setup()
        a = execute(p, c, cfg, w, FixtureEncoder(), clock=lambda: 25)
        b = execute(p, c, cfg, w, FixtureEncoder(), clock=lambda: 25)
        self.assertEqual(a[1]["trained_bank_sha256"], b[1]["trained_bank_sha256"])
        self.assertEqual([r["logits"] for r in a[2]], [r["logits"] for r in b[2]])

    def test_real_safetensor_bytes_verify_and_mutation_rejects(self):
        # Real tensor serialization, NOT a pretrained-model experiment.
        layer = torch.nn.Linear(3, 2)
        with tempfile.TemporaryDirectory() as td:
            save_file(layer.state_dict(), str(Path(td) / "weights.safetensors"))
            first = snapshot_digest(td)
            self.assertEqual(verify_loaded_safetensors(torch, layer, td)["tensor_count"], 2)
            with torch.no_grad(): layer.bias.add_(1)
            with self.assertRaises(ValueError): verify_loaded_safetensors(torch, layer, td)
            (Path(td) / "metadata.json").write_text("{}")
            self.assertNotEqual(first, snapshot_digest(td))

    def test_loading_report_refuses_missing_or_ignored_weights(self):
        complete = dict(missing_keys=[], unexpected_keys=[], mismatched_keys=[], error_msgs=[])
        self.assertTrue(validate_encoder_loading_info(complete)["complete"])
        for key in complete:
            bad = copy.deepcopy(complete); bad[key] = ["weight"]
            with self.subTest(key=key), self.assertRaises(ValueError):
                validate_encoder_loading_info(bad)

    def test_publication_failure_cannot_produce_a_consumable_seal(self):
        from matrix_export import read_sealed
        p, c, cfg, w = setup()
        bank, manifest, rows = execute(p, c, cfg, w, FixtureEncoder(), clock=lambda: 25)
        manifest["sealed_at_ns"] = 27
        with tempfile.TemporaryDirectory() as td:
            with patch("matrix_runtime.write_json_exclusive", side_effect=OSError("disk full")):
                with self.assertRaises(OSError):
                    publish_prediction_bundle(Path(td), bank, manifest, rows)
            self.assertFalse((Path(td) / "COMMITTED.json").exists())
            with self.assertRaises(ValueError): read_sealed(td, "a"*64)


if __name__ == "__main__":
    unittest.main()
