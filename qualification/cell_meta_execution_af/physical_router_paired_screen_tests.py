"""Adversarial source-paired multi-seed screen; no Granite pretrained weights here."""
from __future__ import annotations

import copy
import inspect
import json
from pathlib import Path
import tempfile
import unittest

from qualification.cell_meta_execution_af import physical_router_trial as base
from qualification.cell_meta_execution_af import physical_router_top1 as top1
from qualification.cell_meta_execution_af import physical_router_hard_train as hard_train
from qualification.cell_meta_execution_af import physical_router_frozen_baseline as frozen
from qualification.cell_meta_execution_af import physical_router_fivearm_review as five
from qualification.cell_meta_execution_af import physical_router_paired_screen as screen


class PairedSourceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.items = {}
        reference = base.synthetic_panel(seed=41, rule="conditional", rows=64)
        for seed in screen.SEEDS:
            panel = copy.deepcopy(reference)
            panel["source"]["seed"] = seed
            soft = base.run(panel, steps=3)
            post = top1.create_report(panel, soft)
            hard = hard_train.produce(panel, soft, post)
            old = frozen.produce(panel, soft, post, hard)
            f = five.descriptive(panel, soft, post, hard, old)
            cls.items[seed] = {"panel":panel, "soft":soft, "posthoc":post,
                               "hard":hard, "frozen":old, "five":f}
        cls.observed = screen.screen(cls.items)

    def fail(self, mutated):
        with self.assertRaises((screen.PairedScreenDenied, five.FiveArmDenied,
                screen.frozen_audit.FrozenReviewDenied,
                screen.hard_audit.HardReplayDenied,
                screen.audit.AuditError,screen.top1_audit.Top1AuditError, ValueError)):
            screen.screen(mutated)

    def test_actual_torch_three_seed_five_arm_replay(self):
        self.assertEqual(self.observed["schema"],screen.SCHEMA)
        self.assertEqual(self.observed["authority_posture"],"DENY_ALL")
        self.assertTrue(self.observed["three_seeds_reuse_same_source_material"])

    def test_a_single_source_is_not_tripled(self):
        self.assertEqual(self.observed["seed_count_not_independent_source_multiplier"],3)
        self.assertEqual(self.observed["reused_original_source_rows"],384)
        self.assertEqual(
            self.observed["retrospective_paired"]["future_1"]["original_source_groups"],64)
        self.assertFalse(self.observed["independent_original_source_family_count_authenticated"])

    def test_source_paired_mean_matches_report_arithmetic(self):
        for part in ("future_1","future_2"):
            val=self.observed["retrospective_paired"][part]["comparisons"]["adaptive_minus_fixed"]
            expected=sum(self.items[seed]["five"]["arms"][4]["retrospective_scores"][part]["brier"]
                         -self.items[seed]["five"]["arms"][2]["retrospective_scores"][part]["brier"]
                         for seed in screen.SEEDS)/3
            self.assertAlmostEqual(val["mean_brier_delta"],expected,places=6)

    def test_conditional_interval_is_explicitly_not_a_valid_prospective_ci(self):
        for part in screen.PARTS:
            for obj in self.observed["retrospective_paired"][part]["comparisons"].values():
                self.assertFalse(obj["interval_is_valid_future_effect_CI"])
                self.assertFalse(obj["original_family_independence_verified"])
                self.assertEqual(obj["registered_comparisons"],6)
                self.assertEqual(obj["resamples"],1024)

    def test_three_seed_external_unverified_panel_is_also_processed_without_authority(self):
        # Exact same source rows across seeds; the "external" mode is a contract
        # test only, NOT actual pretrained Granite execution in this unit test.
        alt = {}
        for seed in screen.SEEDS:
            panel = copy.deepcopy(self.items[seed]["panel"])
            panel["source"]["kind"] = "external_unverified"
            panel["source"]["rule"] = "external"
            soft = base.run(panel, steps=2)
            post = top1.create_report(panel, soft)
            hard = hard_train.produce(panel, soft, post)
            old = frozen.produce(panel, soft, post, hard)
            f = five.descriptive(panel, soft, post, hard, old)
            alt[seed] = {"panel":panel,"soft":soft,"posthoc":post,
                         "hard":hard,"frozen":old,"five":f}
        observed=screen.screen(alt)
        self.assertEqual(observed["source_kind"],"external_unverified")
        self.assertFalse(observed["source_lineage_independently_signed"])
        self.assertFalse(observed["prospective_calendar_outcome_verified"])
        self.assertFalse(observed["selection_approved"])

    def test_deterministic_descriptive_bootstrap(self):
        a=screen.bootstrap([.1,-.1]*16,part="future_1",contrast="adaptive_minus_fixed")
        self.assertEqual(
            a, screen.bootstrap([.1,-.1]*16,part="future_1",contrast="adaptive_minus_fixed"))
        self.assertLessEqual(a["descriptive_conditional_resample_lower"],a["mean_brier_delta"])
        self.assertGreaterEqual(a["descriptive_conditional_resample_upper"],a["mean_brier_delta"])

    def test_frozen_and_continued_are_distinct_arms(self):
        self.assertEqual(set(self.observed["retrospective_paired"]["future_1"]["comparisons"]),
                         {key for key,_,_ in screen.CONTRASTS})
        self.assertFalse(self.observed["matched_complete_lifecycle_compute"])
        self.assertFalse(self.observed["ndu_accepted"])
        self.assertFalse(self.observed["selection_approved"])

    def test_three_seed_member_mandatory(self):
        e=copy.deepcopy(self.items);e.pop(41);self.fail(e)

    def test_extra_seed_rejected(self):
        e=copy.deepcopy(self.items);e[59]=copy.deepcopy(e[41]);self.fail(e)

    def test_swapped_original_seed_rejected(self):
        e=copy.deepcopy(self.items);e[47]["panel"]["source"]["seed"]=41;self.fail(e)

    def test_altered_source_feature_across_one_seed_rejected(self):
        e=copy.deepcopy(self.items)
        e[47]["panel"]["partitions"]["future_1"][0]["features"][0]+=0.001
        self.fail(e)

    def test_altered_outcome_across_one_seed_rejected(self):
        e=copy.deepcopy(self.items)
        e[53]["panel"]["partitions"]["future_1"][0]["label"]^=1
        self.fail(e)

    def test_source_order_rotation_rejected(self):
        e=copy.deepcopy(self.items)
        p=e[53]["panel"]["partitions"]["future_2"]
        p[0],p[1]=p[1],p[0]
        self.fail(e)

    def test_reused_source_group_rejected(self):
        e=copy.deepcopy(self.items)
        e[47]["panel"]["partitions"]["future_2"][0]["source_group"]=(
            e[47]["panel"]["partitions"]["future_1"][0]["source_group"])
        self.fail(e)

    def test_changed_stem_without_other_seeds_rejected(self):
        e=copy.deepcopy(self.items);e[53]["panel"]["source"]["stem_sha256"]="1"*64;self.fail(e)

    def test_changed_source_scope_rejected(self):
        e=copy.deepcopy(self.items);e[47]["panel"]["source"]["scope"]="foreign-scope";self.fail(e)

    def test_unregistered_seed_rule_rejected(self):
        e=copy.deepcopy(self.items);e[41]["panel"]["source"]["rule"]="future_test";self.fail(e)

    def test_missing_bundle_member_rejected(self):
        e=copy.deepcopy(self.items);e[41].pop("five");self.fail(e)

    def test_extra_bundle_member_rejected(self):
        e=copy.deepcopy(self.items);e[41]["new_untrusted_model"]=True;self.fail(e)

    def test_forged_cross_seed_fivearm_summary_rejected(self):
        e=copy.deepcopy(self.items)
        e[41]["five"]["arms"][4]["retrospective_scores"]["future_1"]["brier"]-=.1
        self.fail(e)

    def test_changed_true_frozen_probability_rejected_even_rehashed(self):
        e=copy.deepcopy(self.items)
        x=e[53]["frozen"]
        x["predictions"]["future_1"][0]["probability"]=.99
        x["prediction_sha256"]=screen.audit.digest(x["predictions"])
        self.fail(e)

    def test_hard_route_relabel_rejected(self):
        e=copy.deepcopy(self.items)
        e[47]["hard"]["results"][3]["stage2_selected_head_bitsets_le"][0]="ff"
        self.fail(e)

    def test_forged_future_or_selection_denied(self):
        for attr,value in (("retrospective_not_prospective",False),
                           ("statistical_winner_certified",True),
                           ("complete_lifecycle_compute_matched",True)):
            e=copy.deepcopy(self.items);e[41]["five"][attr]=value
            with self.subTest(field=attr):self.fail(e)

    def test_nonfinite_brier_prediction_rejected(self):
        e=copy.deepcopy(self.items)
        e[41]["hard"]["results"][3]["predictions"]["future_1"][0]["probability"]=(
            float('nan'))
        self.fail(e)

    def test_no_torch_numpy_trainer_in_review_source(self):
        s=inspect.getsource(screen)
        self.assertNotIn("import torch",s)
        self.assertNotIn("import numpy",s)
        self.assertNotIn("physical_router_hard_train",s)
        self.assertNotIn("physical_router_frozen_baseline",s)

    def test_bounded_group_inputs(self):
        with self.assertRaises(screen.PairedScreenDenied):
            screen.bootstrap([.1]*15,part="future_1",contrast="adaptive_minus_fixed")
        with self.assertRaises(screen.PairedScreenDenied):
            screen.bootstrap([.1]*257,part="future_1",contrast="adaptive_minus_fixed")

    def test_cli_bounded_read_and_create_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            suffix={"panel":"trial-panel","soft":"trial-report","posthoc":"top1-report",
                    "hard":"hard-train-report","frozen":"frozen-report","five":"fivearm-report"}
            for seed in screen.SEEDS:
                for field,tag in suffix.items():
                    (root/f"{seed}-{tag}.json").write_bytes(
                        screen.audit.canonical(self.items[seed][field]))
            outfile=root/"paired-result.json"
            self.assertEqual(screen.main(["--bundle-dir",str(root),"--out",str(outfile)]),0)
            self.assertEqual(json.loads(outfile.read_text()),self.observed)
            self.assertEqual(screen.main(["--bundle-dir",str(root),"--out",str(outfile)]),2)

    def test_symlink_source_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            (root/"41-trial-panel.json").symlink_to(Path(tmp)/"external.json")
            with self.assertRaises((OSError, screen.audit.AuditError)):
                screen.read_bundles(root)

    def test_non_registered_training_seed_not_counted_as_new_source(self):
        self.assertEqual(self.observed["source_kind"],"synthetic")
        self.assertFalse(self.observed["prospective_calendar_outcome_verified"])
        self.assertFalse(self.observed["source_lineage_independently_signed"])
        self.assertEqual(self.observed["production_admission"],"BLOCKED")


if __name__ == "__main__":
    unittest.main()
