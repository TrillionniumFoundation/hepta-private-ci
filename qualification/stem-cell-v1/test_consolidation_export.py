import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import torch
from safetensors.torch import load_file

import test_retention_training as fixtures
from test_consolidation_training import consolidation_policy
from consolidation_training import ConsolidationRejected, OUTPUT_PROFILE, student_recipe
from growth_test_support import run_growth
from matrix_bank import CellBank, state_digest
from matrix_export import export_observed, read_sealed
from matrix_materials import file_sha256, freeze_config, validate_config
from matrix_runtime import publish_prediction_bundle, run_bound, write_json_exclusive
from matrix_test_support import FixtureEncoder
from next_round_matrix import _digest
from paired_execution import audit_pair, freeze_contract


def setup(arm="shared_421m_sparse_split_no_ndu"):
    p, c, cfg, work = fixtures.retained_setup(arm)
    values = {k: v for k, v in cfg.items() if k not in ("schema", "config_id", "contract_id")}
    return p, c, freeze_config(p, c, **values, consolidation_policy=consolidation_policy()), work


class ConsolidationExportTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def bundle(self, name, arm="shared_421m_sparse_split_no_ndu", *, compressed=True):
        parts = setup(arm) if compressed else fixtures.retained_setup(arm)
        bank, manifest, rows = run_growth(parts)
        manifest["predictions_complete_at_ns"] = 26
        directory = self.root / name; directory.mkdir()
        seal = publish_prediction_bundle(directory, bank, manifest, rows, clock=lambda: 27)
        labels = {"schema": "hepta.stem.independent-labels.v1", "seal_id": seal["seal_id"],
                  "contract_id": parts[1]["contract_id"], "observer_id": parts[1]["observer_id"],
                  "created_at_ns": 31, "rows": [dict(task_id=r["task_id"], input_digest=r["input_digest"],
                                                   label=i, observed_at_ns=30) for i, r in enumerate(rows)]}
        write_json_exclusive(directory / "labels.json", labels)
        return parts, manifest, rows, directory, seal

    def export(self, bundle):
        parts, manifest, rows, directory, seal = bundle
        return export_observed(parts[0], parts[1], directory, expected_seal_id=seal["seal_id"],
                               observer_path=directory / "labels.json", expected_observer_sha256=file_sha256(directory / "labels.json"))

    def reseal(self, bundle):
        # Recompute the outer test envelope; semantic validation must still reject bad records.
        parts, manifest, rows, directory, seal = bundle
        (directory / "execution.json").write_text(json.dumps(manifest))
        seal = {k: v for k, v in seal.items() if k != "seal_id"}
        seal["files"] = {n: file_sha256(directory / n) for n in seal["files"]}
        seal["seal_id"] = _digest(seal)
        (directory / "COMMITTED.json").write_text(json.dumps(seal))
        labels = json.loads((directory / "labels.json").read_text()); labels["seal_id"] = seal["seal_id"]
        (directory / "labels.json").write_text(json.dumps(labels))
        return parts, manifest, rows, directory, seal

    def test_config_explicit_v6_and_omission_preserves_v5_hash(self):
        p, c, cfg, _ = setup()
        self.assertEqual(cfg["schema"], "hepta.stem.bound-hf-config.v6")
        validate_config(p, c, cfg)
        original = fixtures.retained_setup()[2]
        values = {k: v for k, v in cfg.items() if k not in ("schema", "config_id", "contract_id", "consolidation_policy")}
        self.assertEqual(freeze_config(p, c, **values), original)
        values.pop("retention_policy")
        with self.assertRaises(ValueError):
            freeze_config(p, c, **values, consolidation_policy=consolidation_policy())

    def test_execute_seal_observe_uses_student_and_preserves_real_rejection(self):
        # The direct fixture really regresses under three steps: it must NOT be
        # turned into a completed comparison just to make this integration pass.
        with self.assertRaises(ConsolidationRejected) as rejected:
            self.bundle("direct", "shared_421m_sparse_direct32_no_ndu")
        self.assertFalse(rejected.exception.report["final_retention"]["passed"])
        split = self.bundle("split")
        right, summary = self.export(split)
        self.assertEqual(right["trainable_params"], 448)
        self.assertEqual(right["precursor_trainable_params"], 896)
        self.assertEqual(right["peak_trainable_params"], 1792)
        self.assertEqual(right["schema"], "hepta.stem.paired-run-export.v3")
        self.assertEqual(right["output_profile"], OUTPUT_PROFILE)
        self.assertEqual(split[1]["inventory"]["cells"], 16)
        self.assertEqual(split[1]["consolidation_receipt"]["teacher_inventory"]["cells"], 32)
        self.assertGreater(right["phase_flops"]["migration"], 0)
        self.assertIsNone(right["phase_flops"]["evaluation"])
        self.assertFalse(summary["retention_established"])

    def test_normalized_v3_pair_fixture_checks_counts_without_attesting_runs(self):
        # Validator-only synthetic comparator, NOT an export from the rejected
        # direct run above and never retained as experimental evidence.
        split = self.bundle("schema")
        right, _ = self.export(split)
        left = copy.deepcopy(right)
        left.update(arm_id="shared_421m_sparse_direct32_no_ndu", peak_trainable_params=1344)
        result = audit_pair(split[0][0], split[0][1], "adaptive_split", left, right)
        self.assertEqual(result["status"], "blocked")
        self.assertNotIn("unmatched_actual_trainable_params", result["blockers"])
        self.assertIn("candidate:not_pretrained_model_execution", result["blockers"])
        left["precursor_trainable_params"] += 1
        with self.assertRaises(ValueError):
            audit_pair(split[0][0], split[0][1], "adaptive_split", left, right)

    def test_uncompressed_stage_cannot_be_reported_as_controlled_compressed_pair(self):
        direct = self.bundle("direct", "shared_421m_sparse_direct32_no_ndu", compressed=False)
        split = self.bundle("split")
        left, _ = self.export(direct); right, _ = self.export(split)
        result = audit_pair(split[0][0], split[0][1], "adaptive_split", left, right)
        self.assertIn("unmatched_output_stage", result["blockers"])
        self.assertIn("unmatched_training_protocol", result["blockers"])

    def test_actual_smaller_safetensor_roundtrip_reconstructs_output_geometry(self):
        bundle = self.bundle("roundtrip")
        parts, m, rows, directory, seal = bundle
        profile = validate_config(parts[0], parts[1], parts[2])
        bank = CellBank(4, 2, student_recipe(profile), parts[2]["width_units"] // 2)
        bank.load_state_dict(load_file(str(directory / "bank.safetensors")), strict=True)
        self.assertEqual(state_digest(bank), m["trained_bank_sha256"])
        encoder = FixtureEncoder()
        with torch.inference_mode():
            for row, prediction in zip(parts[3]["eval"], rows, strict=True):
                logits = bank(encoder.encode(row)[0][None])[0].tolist()
                self.assertEqual(logits, prediction["logits"])
        self.assertEqual(sum(p.numel() for p in bank.parameters()), 448)

    def test_rehashed_false_capacity_peak_and_stage_reject(self):
        bundle = self.bundle("bad")
        original = copy.deepcopy(bundle[1])
        for field, value in (("student_parameters", 896), ("retained_parent_parameters", 0),
                             ("teacher_reference_rows", 1), ("output_profile", "flat32")):
            bundle[1].clear(); bundle[1].update(copy.deepcopy(original))
            bundle[1]["consolidation_receipt"][field] = value
            bundle[1]["training"]["consolidation"] = bundle[1]["consolidation_receipt"]
            with self.subTest(field=field), self.assertRaises(ValueError):
                self.export(self.reseal(bundle))

    def test_rehashed_original_reference_or_training_denominator_change_rejects(self):
        bundle = self.bundle("bad-reference")
        original = copy.deepcopy(bundle[1])
        for how in ("baseline", "steps", "denominator", "group"):
            bundle[1].clear(); bundle[1].update(copy.deepcopy(original))
            report = bundle[1]["consolidation_receipt"]
            if how == "baseline": report["final_retention"]["reference_parameter_sha256"] = "a"*64
            if how == "steps": report["training"]["steps"] += 1
            if how == "denominator": report["training"]["examples_seen_by_role"]["old_train_groups"] += 1
            if how == "group": report["groups"][0]["candidate_nll"] = float("nan")
            bundle[1]["training"]["consolidation"] = report
            bundle[1]["retention_receipt"] = report["final_retention"]
            with self.subTest(how=how), self.assertRaises(ValueError):
                self.export(self.reseal(bundle))

    def test_failed_posttraining_consolidation_cannot_publish_success(self):
        p, c, cfg, work = setup("shared_421m_sparse_direct32_no_ndu")
        workload = self.root / "work.json"; write_json_exclusive(workload, work)
        fields = {k: c[k] for k in ("source_sha", "task_ids", "device_id", "observer_id", "train_cutoff_ns",
                                    "eval_start_ns", "eval_end_ns", "flops_caps", "tolerance_ppm", "max_peak_trainable_params")}
        c = freeze_contract(p, **fields, workload_sha256=file_sha256(workload))
        values = {k: v for k, v in cfg.items() if k not in ("schema", "config_id", "contract_id")}
        cfg = freeze_config(p, c, **values)
        output = self.root / "failed"
        with patch("matrix_runtime.verify_source", return_value={}), \
             patch("matrix_runtime.LocalHFEncoder", return_value=FixtureEncoder()):
            with self.assertRaises(ConsolidationRejected):
                run_bound(p, c, cfg, workload, self.root / "unused", output)
        failure = json.loads((output / "FAILED.json").read_text())
        self.assertEqual(failure["expected_task_ids"], c["task_ids"])
        self.assertEqual(failure["consolidation_disposition"]["disposition"], "consolidation_validation_failed")
        self.assertEqual(failure["consolidation_disposition"]["training"]["steps"], 3)
        self.assertFalse((output / "COMMITTED.json").exists())

    def test_payload_gate_happens_before_encoder_execution(self):
        p, c, cfg, work = setup()
        values = {k: v for k, v in cfg.items() if k not in ("schema", "config_id", "contract_id")}
        values["max_feature_bytes"] = 8*4*4 + 2*8*2*4 + 4*4*4 - 1
        cfg = freeze_config(p, c, **values)
        backend = FixtureEncoder()
        with self.assertRaisesRegex(ValueError, "feature allocation"):
            run_growth((p, c, cfg, work), backend=backend)
        self.assertEqual(backend.calls, 0)

    def test_final_reference_is_original_not_only_the_teacher(self):
        _, m, _, _, _ = self.bundle("refs")
        before = m["training"]["retention"]
        after = m["retention_receipt"]
        self.assertEqual(before["reference_parameter_sha256"], after["reference_parameter_sha256"])
        self.assertEqual(before["reference_logits_sha256"], after["reference_logits_sha256"])
        self.assertNotEqual(before["candidate_parameter_sha256"], after["candidate_parameter_sha256"])
        self.assertEqual(after["candidate_parameter_sha256"], m["trained_bank_sha256"])


if __name__ == "__main__":
    unittest.main()
