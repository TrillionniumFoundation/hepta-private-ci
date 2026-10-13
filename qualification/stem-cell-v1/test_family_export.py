import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import torch

import test_family_routing as family_fixtures
from growth_test_support import growth_setup, run_growth
from matrix_bank import state_digest
from matrix_export import export_observed, read_sealed
from matrix_growth import GrowthNotAdmitted, split_population
from matrix_materials import file_sha256, freeze_config
from matrix_runtime import publish_prediction_bundle, run_bound, write_json_exclusive
from matrix_test_support import FixtureEncoder
from next_round_matrix import _digest
from paired_execution import audit_pair, freeze_contract


class FamilyExportTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def bundle(self, name, arm, *, family=True):
        parts = family_fixtures.family_setup(arm) if family else growth_setup(arm)
        bank, execution, rows = run_growth(parts)
        p, c, _, _ = parts
        execution["predictions_complete_at_ns"] = 26
        path = self.root / name; path.mkdir()
        seal = publish_prediction_bundle(path, bank, execution, rows, clock=lambda: 27)
        observation = {"schema": "hepta.stem.independent-labels.v1", "seal_id": seal["seal_id"],
                       "contract_id": c["contract_id"], "observer_id": c["observer_id"], "created_at_ns": 31,
                       "rows": [dict(task_id=r["task_id"], input_digest=r["input_digest"], label=i, observed_at_ns=30)
                                for i, r in enumerate(rows)]}
        write_json_exclusive(path / "labels.json", observation)
        return parts, bank, execution, path, seal

    def export(self, parts, path, seal):
        return export_observed(parts[0], parts[1], path, expected_seal_id=seal["seal_id"],
                               observer_path=path / "labels.json", expected_observer_sha256=file_sha256(path / "labels.json"))

    def test_complete_family_pair_preserves_routing_protocol_counts_and_missingness(self):
        a, _, direct, ap, aseal = self.bundle("direct", "shared_421m_sparse_direct32_no_ndu")
        b, _, split, bp, bseal = self.bundle("split", "shared_421m_sparse_split_no_ndu")
        left, ls = self.export(a, ap, aseal)
        right, rs = self.export(b, bp, bseal)
        self.assertEqual(left["trainable_params"], right["trainable_params"])
        self.assertEqual(left["trainable_params"], 896)
        self.assertEqual((left["peak_trainable_params"], right["peak_trainable_params"]), (896, 1344))
        self.assertEqual(left["training_protocol_sha256"], right["training_protocol_sha256"])
        self.assertEqual(direct["inventory"]["routing_profile"], split["inventory"]["routing_profile"])
        self.assertTrue(rs["growth_receipt"]["transition_probe"]["passed"])
        self.assertGreater(sum(split["inventory"]["sibling_probe_rows"]), 0)
        self.assertGreater(right["phase_flops"]["migration"], 0)
        report = audit_pair(a[0], a[1], "adaptive_split", left, right)
        self.assertNotIn("unmatched_training_protocol", report["blockers"])
        self.assertNotIn("unmatched_actual_trainable_params", report["blockers"])
        self.assertIn("candidate:not_pretrained_model_execution", report["blockers"])
        self.assertIn("candidate:missing_energy_joules", report["blockers"])
        self.assertFalse(report["statistical_superiority_established"])

    def test_flat_and_family_pairs_cannot_claim_same_training_protocol(self):
        a, _, _, ap, aseal = self.bundle("direct", "shared_421m_sparse_direct32_no_ndu", family=False)
        b, _, _, bp, bseal = self.bundle("split", "shared_421m_sparse_split_no_ndu")
        left, _ = self.export(a, ap, aseal); right, _ = self.export(b, bp, bseal)
        report = audit_pair(a[0], a[1], "adaptive_split", left, right)
        self.assertIn("unmatched_training_protocol", report["blockers"])

    def test_forged_parity_or_route_record_rejects_even_after_resealing(self):
        parts, _, original, root, seal = self.bundle("split", "shared_421m_sparse_split_no_ndu")
        labels = json.loads((root / "labels.json").read_text())
        for field, value in (("routing", "flat"), ("preservation", False), ("passed", False),
                             ("examples", 1), ("atol", 1.), ("ratio", 2.), ("ratio", True),
                             ("error", float("inf")), ("counts", [-1] * 32), ("count", True),
                             ("scope", "global_float_bitwise_identity"), ("missing", None)):
            record = copy.deepcopy(original)
            g, inv = record["growth_receipt"], record["inventory"]
            if field == "routing": inv["routing_profile"] = value
            elif field == "preservation": g["function_preserving"] = value
            elif field == "scope": g["preservation_scope"] = value
            elif field == "counts": inv["sibling_probe_rows"] = value
            elif field == "count": inv["sibling_supervised_rows"] = value
            elif field == "missing": del g["transition_probe"]
            else:
                key = {"ratio": "max_tolerance_ratio", "error": "max_absolute_logit_error"}.get(field, field)
                g["transition_probe"][key] = value
            record["training"]["growth"] = copy.deepcopy(g)
            (root / "execution.json").write_text(json.dumps(record))
            marker = {k: v for k, v in seal.items() if k != "seal_id"}
            marker["files"] = {n: file_sha256(root / n) for n in marker["files"]}
            marker["seal_id"] = _digest(marker)
            (root / "COMMITTED.json").write_text(json.dumps(marker))
            labels["seal_id"] = marker["seal_id"]
            (root / "labels.json").write_text(json.dumps(labels))
            with self.subTest(field=field, value=value), self.assertRaises(ValueError):
                self.export(parts, root, marker)

    def test_full_entry_failure_seals_no_parity_violating_candidate(self):
        p, c, cfg, work = family_fixtures.family_setup()
        workload = self.root / "work.json"; write_json_exclusive(workload, work)
        names = ("source_sha", "task_ids", "device_id", "observer_id", "train_cutoff_ns", "eval_start_ns",
                 "eval_end_ns", "flops_caps", "max_peak_trainable_params")
        c = freeze_contract(p, **{k: c[k] for k in names}, workload_sha256=file_sha256(workload))
        cfg = freeze_config(p, c, **{k: v for k, v in cfg.items() if k not in ("schema", "contract_id", "config_id")})
        def damaged(*args, **kwargs):
            child, report = split_population(*args, **kwargs)
            with torch.no_grad():
                for head in child.heads: head[-1].bias.add_(1)
            return child, report
        output = self.root / "failed"
        with patch("matrix_runtime.verify_source", return_value={}), \
             patch("matrix_runtime.LocalHFEncoder", return_value=FixtureEncoder()), \
             patch("matrix_growth.split_population", side_effect=damaged):
            with self.assertRaises(GrowthNotAdmitted): run_bound(p, c, cfg, workload, self.root / "unused", output)
        failure = json.loads((output / "FAILED.json").read_text())
        self.assertEqual(failure["expected_task_ids"], c["task_ids"])
        self.assertEqual(failure["growth_disposition"]["disposition"], "transition_parity_failed")
        self.assertFalse((output / "COMMITTED.json").exists())
        with self.assertRaises(ValueError): read_sealed(output, "a" * 64)

    def test_strict_and_observe_family_training_are_identical(self):
        p, c, cfg, work = family_fixtures.family_setup()
        bank, manifest, rows = run_growth((p, c, cfg, work))
        # No meter bypass in production: use observe vs strict, both actual ledgers.
        cfg2 = copy.deepcopy(cfg)
        fields = {k: v for k, v in cfg2.items() if k not in ("schema", "contract_id", "config_id")}
        fields["measurement_policy"]["mode"] = "observe"
        cfg2 = freeze_config(p, c, **fields)
        b2, m2, r2 = run_growth((p, c, cfg2, work))
        self.assertEqual(state_digest(bank), state_digest(b2))
        self.assertEqual([r["logits"] for r in rows], [r["logits"] for r in r2])
        self.assertEqual(manifest["work_observation"]["unknown_operators"], {})
        self.assertEqual(m2["work_observation"]["unknown_operators"], {})

    def test_no_trigger_keeps_the_existing_no_completed_split_semantics(self):
        with self.assertRaises(GrowthNotAdmitted) as failure: run_growth(family_fixtures.family_setup(threshold=100))
        self.assertFalse(failure.exception.report["split_performed"])
        self.assertEqual(failure.exception.report["disposition"], "growth_not_triggered")

    def test_evaluation_labels_reject_before_any_encoding_or_growth(self):
        from matrix_runtime import execute
        from execution_meter import WorkLedger
        p, c, cfg, work = family_fixtures.family_setup()
        work["eval"][0]["label"] = 0
        backend = FixtureEncoder()
        with self.assertRaises(ValueError):
            execute(p, c, cfg, work, backend, clock=lambda: 25,
                    meter=WorkLedger(cfg["measurement_policy"], c["flops_caps"]))
        self.assertEqual(backend.calls, 0)

    def test_auxiliary_work_consumes_the_frozen_training_budget(self):
        from execution_meter import BudgetStop
        p, c, cfg, w = family_fixtures.family_setup()
        _, observed, _ = run_growth((p, c, cfg, w))
        old = c
        names = ("source_sha", "task_ids", "workload_sha256", "device_id", "observer_id", "train_cutoff_ns",
                 "eval_start_ns", "eval_end_ns", "max_peak_trainable_params")
        c = freeze_contract(p, **{k: old[k] for k in names},
                            flops_caps={**old["flops_caps"], "train": observed["phase_flops"]["train"] - 1})
        cfg = freeze_config(p, c, **{k: v for k, v in cfg.items() if k not in ("schema", "contract_id", "config_id")})
        with self.assertRaisesRegex(BudgetStop, "formula_flop_budget:train"):
            run_growth((p, c, cfg, w))


if __name__ == "__main__":
    unittest.main()
