"""Real Torch arithmetic + independent, nonauthorizing five-arm fault gates.

All fixture input features and labels are synthetic; these tests never claim
pretrained Encoder execution or prospective scientific observation.
"""
from __future__ import annotations

import copy
import inspect
import json
from pathlib import Path
import tempfile
import unittest

from qualification.cell_meta_execution_af import physical_router_trial as base
from qualification.cell_meta_execution_af import physical_router_top1 as posthoc
from qualification.cell_meta_execution_af import physical_router_hard_train as hardtrain
from qualification.cell_meta_execution_af import physical_router_frozen_baseline as frozen
from qualification.cell_meta_execution_af import physical_router_fivearm_review as reviewer


class FiveArmTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.panel = base.synthetic_panel(seed=41, rule="conditional", rows=64)
        cls.soft = base.run(cls.panel, steps=5)
        cls.post = posthoc.create_report(cls.panel, cls.soft)
        cls.hard = hardtrain.produce(cls.panel, cls.soft, cls.post)
        cls.frozen = frozen.produce(cls.panel, cls.soft, cls.post, cls.hard)
        cls.summary = reviewer.descriptive(cls.panel, cls.soft, cls.post,
                                           cls.hard, cls.frozen)

    def rejected(self, *, panel=None, soft=None, post=None, hard=None, frozen_report=None):
        with self.assertRaises((reviewer.FiveArmDenied,
                                reviewer.frozen_audit.FrozenReviewDenied,
                                reviewer.hard_audit.HardReplayDenied,
                                reviewer.baseline_audit.AuditError,
                                reviewer.top1_audit.Top1AuditError)):
            reviewer.descriptive(self.panel if panel is None else panel,
                                 self.soft if soft is None else soft,
                                 self.post if post is None else post,
                                 self.hard if hard is None else hard,
                                 self.frozen if frozen_report is None else frozen_report)

    def test_actual_cpu_and_audited_five_arm_identity(self):
        self.assertEqual(self.summary["schema"], reviewer.SCHEMA)
        self.assertEqual(tuple(x["arm"] for x in self.summary["arms"]), reviewer.ARMS)
        self.assertEqual(self.summary["seed"], 41)

    def test_all_scores_are_same_source_retrospective_groups(self):
        for item in self.summary["arms"]:
            for p in reviewer.PARTS:
                self.assertEqual(item["retrospective_scores"][p]["count"], 64)
        self.assertTrue(self.summary["retrospective_not_prospective"])
        self.assertTrue(self.summary["same_source_calibration_not_ood"])

    def test_frozen_second_stage_has_exact_zero_updates(self):
        frozen_cost = self.summary["arms"][0]["cost_observation"]
        self.assertEqual(frozen_cost["additional_stage2_training_head_rows"], 0)
        self.assertEqual(frozen_cost["additional_stage2_optimizer_updates"], 0)
        self.assertEqual(frozen_cost["train_router_rows"], 0)
        self.assertEqual(frozen_cost["common_stage1_training_head_rows_reused"], 320)

    def test_unsplit_continued_is_not_no_update(self):
        continued = self.summary["arms"][1]
        self.assertEqual(continued["arm"], "unsplit_continued_update")
        self.assertFalse(continued["split_proposed"])
        self.assertEqual(continued["cost_observation"]["additional_stage2_training_head_rows"], 640)
        self.assertEqual(continued["cost_observation"]["additional_stage2_optimizer_updates"], 5)

    def test_hard_top1_resource_and_four_arm_accounting(self):
        for item in self.summary["arms"][1:]:
            cost = item["cost_observation"]
            self.assertEqual(cost["additional_stage2_training_head_rows"], 640)
            self.assertEqual(cost["evaluated_head_rows"], 256)
            self.assertGreaterEqual(cost["diagnostic_head_rows_in_existing_arm"], 256)

    def test_independent_reviewer_has_no_torch_numpy_or_training_import(self):
        source = inspect.getsource(reviewer)
        self.assertNotIn("import torch\n", source)
        self.assertNotIn("import numpy\n", source)
        self.assertNotIn("import physical_router_hard_train", source)
        self.assertNotIn("import physical_router_frozen_baseline", source)

    def test_no_authorization_flags_and_total_compute_not_matched(self):
        for k in ("complete_lifecycle_compute_matched", "statistical_winner_certified",
                  "ndu_selection_authorized", "original_worker_model_origin_signed",
                  "physical_cell_split_permitted"):
            self.assertIs(self.summary[k], False)
        self.assertEqual(self.summary["production_admission"], "BLOCKED")
        self.assertEqual(self.summary["authority_posture"], "DENY_ALL")
        self.assertTrue(self.summary["training_budget_unequal_across_five_arms"])

    def test_source_feature_change_is_rejected(self):
        t = copy.deepcopy(self.panel)
        t["partitions"]["future_1"][0]["features"][0] += 0.1234
        self.rejected(panel=t)

    def test_source_label_change_is_rejected(self):
        t = copy.deepcopy(self.panel)
        t["partitions"]["future_2"][0]["label"] ^= 1
        self.rejected(panel=t)

    def test_stage1_tensor_substitution_rejected(self):
        t = copy.deepcopy(self.frozen)
        t["stage1_parent_fp32"]["data_le_hex"] = "00" * 20
        self.rejected(frozen_report=t)

    def test_fake_frozen_stage2_update_denied(self):
        t = copy.deepcopy(self.frozen)
        t["meters"]["additional_stage2_optimizer_updates"] = 1
        self.rejected(frozen_report=t)

    def test_fake_future_window_denied(self):
        t = copy.deepcopy(self.frozen)
        t["future_window_prospective"] = True
        self.rejected(frozen_report=t)

    def test_fake_ood_denied(self):
        t = copy.deepcopy(self.frozen)
        t["true_ood_verified"] = True
        self.rejected(frozen_report=t)

    def test_forged_frozen_accuracy_even_rehashed_denied(self):
        t = copy.deepcopy(self.frozen)
        t["predictions"]["future_1"][0]["probability"] = 0.56789
        t["prediction_sha256"] = reviewer.baseline_audit.digest(t["predictions"])
        self.rejected(frozen_report=t)

    def test_hard_split_trace_change_denied(self):
        t = copy.deepcopy(self.hard)
        t["results"][1]["split_proposed"] = False
        self.rejected(hard=t)

    def test_pre_split_diagnostic_tamper_denied(self):
        t = copy.deepcopy(self.hard)
        t["results"][1]["train_only_new_brier"] += .05
        self.rejected(hard=t)

    def test_invalid_arm_name_denied(self):
        t = copy.deepcopy(self.hard)
        t["results"][0]["arm"] = "frozen_no_change"
        self.rejected(hard=t)

    def test_diff_is_against_both_distinct_bases(self):
        fixed = self.summary["arms"][2]
        old = self.summary["arms"][1]
        stage1 = self.summary["arms"][0]
        for p in reviewer.PARTS:
            self.assertAlmostEqual(
                fixed["brier_delta_vs_frozen"][p],
                round(fixed["retrospective_scores"][p]["brier"]-
                      stage1["retrospective_scores"][p]["brier"], 7))
            self.assertAlmostEqual(
                fixed["brier_delta_vs_unsplit_continued"][p],
                round(fixed["retrospective_scores"][p]["brier"]-
                      old["retrospective_scores"][p]["brier"], 7))

    def test_wrong_source_seed_denied_without_selection(self):
        t = copy.deepcopy(self.panel)
        t["source"]["seed"] = 777
        self.rejected(panel=t)

    def test_create_only_cli_and_exact_result(self):
        with tempfile.TemporaryDirectory() as root:
            folder = Path(root)
            inputs = (self.panel, self.soft, self.post, self.hard, self.frozen)
            paths = []
            for i, content in enumerate(inputs):
                p = folder / f"in{i}.json"
                p.write_bytes(base.canonical(content))
                paths.append(p)
            out = folder / "five.json"
            args = []
            for name, path in zip(("panel", "soft-report", "posthoc-report",
                                   "hard-report", "frozen-report"), paths):
                args.extend(("--"+name, str(path)))
            args.extend(("--out", str(out)))
            self.assertEqual(reviewer.main(args), 0)
            self.assertEqual(json.loads(out.read_text()), self.summary)
            self.assertEqual(reviewer.main(args), 2)  # refuse overwrite


if __name__ == "__main__":
    unittest.main()
