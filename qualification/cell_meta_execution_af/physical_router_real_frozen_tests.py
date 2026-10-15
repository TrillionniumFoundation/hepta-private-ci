"""Two-parent Meta/Granite/E2f convergence: real Head SGD on synthetic Q24 fixtures.

This is not an actual pretrained Encoder run, signed provenance, prospective
outcome, NDU selection, Codex tool action, or physical CellSplit permission.
"""
from __future__ import annotations

import copy
import unittest

from qualification.cell_meta_execution_af import physical_router_audit as fp32_audit
from qualification.cell_meta_execution_af import physical_router_frozen_old as frozen
from qualification.cell_meta_execution_af import physical_router_frozen_old_audit as frozen_audit
from qualification.cell_meta_execution_af import physical_router_real_bridge as bridge
from qualification.cell_meta_execution_af import physical_router_real_review as reviewer
from qualification.cell_meta_execution_af import physical_router_real_tests as fixtures
from qualification.cell_meta_execution_af import physical_router_trial as trial


class FrozenGraniteUnionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.source = fixtures.source_fixture()
        cls.source_sha = bridge.sha_object(cls.source)
        cls.old_bridge_sha, cls.old_reviewer_sha = bridge.SOURCE_PANEL_SHA, reviewer.ORIGINAL_SHA
        # Fixtures remain untrusted synthetic features; only swap the immutable
        # source identity for the synthetic test fixture inside this test class.
        bridge.SOURCE_PANEL_SHA = cls.source_sha
        reviewer.ORIGINAL_SHA = cls.source_sha
        cls.table = fixtures.fixture_table(cls.source)
        cls.panel, cls.receipt = bridge.convert(cls.source, cls.table, seed=41)

    @classmethod
    def tearDownClass(cls) -> None:
        bridge.SOURCE_PANEL_SHA = cls.old_bridge_sha
        reviewer.ORIGINAL_SHA = cls.old_reviewer_sha

    def test_exact_source_projection_then_true_frozen_and_continued_arms(self) -> None:
        independent = reviewer.independent_replay(
            self.source, self.table, self.panel, self.receipt, seed=41
        )
        self.assertEqual(independent["outcome"], "PINNED_SOURCE_AND_Q24_PROJECTION_REPLAY_ONLY")
        trial.validate(self.panel)
        original = trial.run(self.panel, steps=2)
        self.assertEqual(fp32_audit.validate(self.panel, original)["outcome"],
                         "NUMERIC_REPLAY_ONLY")
        old_only = frozen.run(self.panel, steps=2)
        audit = frozen_audit.validate(self.panel, old_only, continued=original)
        self.assertEqual(audit["outcome"], "FROZEN_OLD_PARENT_REPLAY_ONLY")
        self.assertFalse(audit["existing_v1_no_change_is_frozen"])
        self.assertEqual(audit["additional_continued_optimizer_steps"], 2)
        self.assertEqual(old_only["meters"]["optimizer_steps"], 2)
        self.assertEqual(original["results"][0]["meters"]["optimizer_steps"], 4)
        self.assertFalse(audit["ndu_selection_authorized"])
        self.assertEqual(audit["production_admission"], "BLOCKED")
        self.assertEqual(len(self.panel["partitions"]["old_train"]), 64)
        self.assertEqual(len(self.panel["partitions"]["future_1"]), 32)

    def test_three_seed_panels_reuse_one_q24_table_without_new_encoder(self) -> None:
        for seed in (41, 47, 53):
            with self.subTest(seed=seed):
                panel, receipt = bridge.convert(self.source, self.table, seed=seed)
                self.assertEqual(panel["partitions"], self.panel["partitions"])
                self.assertEqual(receipt["real_encoder_feature_table_sha256"],
                                 self.receipt["real_encoder_feature_table_sha256"])
                self.assertFalse(receipt["independent_model_origin_verified"])
                self.assertFalse(receipt["future_window_prospective"])
                independent = reviewer.independent_replay(
                    self.source, self.table, panel, receipt, seed=seed)
                self.assertEqual(independent["sources"], 224)
                baseline = frozen.run(panel, steps=2)
                self.assertEqual(
                    frozen_audit.validate(panel, baseline)["outcome"],
                    "FROZEN_OLD_PARENT_REPLAY_ONLY")
                self.assertFalse(baseline["real_pretrained_encoder_executed"])

    def test_source_labels_cannot_be_rewritten_into_authenticated_futures(self) -> None:
        panel = copy.deepcopy(self.panel)
        panel["partitions"]["future_1"][0]["label"] ^= 1
        with self.assertRaises(reviewer.Denied):
            reviewer.independent_replay(
                self.source, self.table, panel, self.receipt, seed=41)
        # The training baseline is numerically isolated from every holdout
        # label, but neither its digest nor its metrics authenticate provenance.
        a = frozen.run(self.panel, steps=2)
        b = frozen.run(panel, steps=2)
        self.assertEqual(a["weights_sha256"], b["weights_sha256"])
        self.assertNotEqual(a["source_panel_sha256"], b["source_panel_sha256"])
        self.assertFalse(a["independent_outcome_verified"])

    def test_mismatched_old_stage_budget_is_not_a_paired_contrast(self) -> None:
        a = frozen.run(self.panel, steps=2)
        different_steps = trial.run(self.panel, steps=3)
        self.assertEqual(fp32_audit.validate(self.panel, different_steps)["outcome"],
                         "NUMERIC_REPLAY_ONLY")
        with self.assertRaisesRegex(fp32_audit.AuditError, "same old-task training"):
            frozen_audit.validate(self.panel, a, continued=different_steps)

    def test_unchanged_authority_and_retrospective_truth(self) -> None:
        baseline = frozen.run(self.panel, steps=2)
        for key in ("independent_outcome_verified", "future_window_prospective",
                    "real_pretrained_encoder_executed", "ndu_selection_authorized",
                    "total_compute_matched"):
            self.assertIs(baseline[key], False)
        self.assertEqual(baseline["production_admission"], "BLOCKED")
        self.assertEqual(baseline["authority_posture"], "DENY_ALL")
        for key in ("future_1_2_are_retrospective_test_slices",
                    "ood_is_calibration_samesource_placeholder",
                    "artificial_step_order_not_observation_time"):
            self.assertIs(self.receipt[key], True)


if __name__ == "__main__":
    unittest.main()
