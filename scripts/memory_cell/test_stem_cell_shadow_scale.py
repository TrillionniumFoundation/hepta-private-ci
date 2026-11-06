"""Shadow scale is chosen using TRAIN only, never Reader/test labels."""

from types import SimpleNamespace as Row
import math
import unittest

from stem_cell_shadow_scale import (
    GRID,
    calibrate_shadow_scale,
    choose_shadow,
    summarize_shadow_heldout,
    verify_shadow_source_receipts,
    _pin,
)


def training():
    return [
        dict(
            question_id=f"train-{n}",
            family=f"family-{n}",
            candidate_ids=("A", "B"),
            positive_indices=(1,),
            frozen_logits=[8.0, 2.0],
            head_logits=[7.5, 2.5],
        )
        for n in range(2)
    ]


def calibrate(rows=None):
    return calibrate_shadow_scale(
        rows or training(),
        arm="gated",
        cell="general",
        stage=16,
        admitted_ids={"train-0", "train-1"},
    )


class ShadowScaleTests(unittest.TestCase):
    def test_train_only_grid_finds_possible_rank_flip(self):
        receipt = calibrate()
        self.assertEqual(receipt["chosen_scale"], 8.0)
        self.assertIn(receipt["chosen_scale"], GRID)
        self.assertEqual(
            receipt["equal_family_weighted_train_source_accuracy_by_scale"]["0.0"],
            0.0,
        )
        self.assertEqual(
            receipt["equal_family_weighted_train_source_accuracy_by_scale"]["8.0"],
            1.0,
        )
        self.assertFalse(receipt["production_accepted"])

    def test_missing_contrastive_train_label_never_selects_scale(self):
        rows = training()
        rows[0]["positive_indices"] = ()
        rows[1]["positive_indices"] = (0, 1)
        result = calibrate(rows)
        self.assertEqual(result["chosen_scale"], 0.0)
        self.assertEqual(result["positive_negative_eligible_train_count"], 0)

    def test_training_tie_prefers_frozen_base(self):
        rows = training()
        for row in rows:
            row["positive_indices"] = (0,)
        self.assertEqual(calibrate(rows)["chosen_scale"], 0.0)
        self.assertEqual(choose_shadow(("B", "A"), [1, 1], [1, 1], 0), 1)

    def test_unregistered_or_duplicate_train_questions_fail_closed(self):
        for rows, allowed in (
            (training(), {"train-0"}),
            (training() + training()[:1], {"train-0", "train-1"}),
        ):
            with self.subTest(size=len(rows)), self.assertRaises(ValueError):
                calibrate_shadow_scale(
                    rows,
                    arm="gated",
                    cell="general",
                    stage=16,
                    admitted_ids=allowed,
                )

    def test_invalid_nonfinite_bool_duplicate_id_and_overflow_fail(self):
        for ids, base, after, scale in (
            (("A", "A"), [1, 2], [1, 2], 1),
            (("A", "B"), [1, math.nan], [2, 3], 1),
            (("A", "B"), [1, 2], [2], 1),
            (("A", "B"), [True, 2], [1, 2], 1),
            (("A", "B"), [8, 2], [7, 3], 65),
            (("A", "B"), [1e308, -1e308], [-1e308, 1e308], 64),
        ):
            with self.subTest(scores=base), self.assertRaises(ValueError):
                choose_shadow(ids, base, after, scale)

    def test_all_480_shadow_choices_accounted_with_native_answerability(self):
        phases = ("select", "retention", "test", "transfer")
        qids = {p: [f"{p}-{i}" for i in range(8)] for p in phases}
        routes = {qid: "general" for group in qids.values() for qid in group}
        targets = {
            qid: Row(unanswerable=False, unresolved_evidence=(), evidence=("source",))
            for qid in routes
        }
        targets["test-0"] = Row(
            unanswerable=True,
            unresolved_evidence=(),
            evidence=(),
        )
        arms = (
            "prototype",
            "linear",
            "gated",
            "lineage_lora_gated",
            "independent_lora_gated",
        )
        rows = [
            dict(
                stage=stage,
                phase=phase,
                question_id=qid,
                arm=arm,
                cell="general",
                status="succeeded",
                selected_source_id="source",
                frozen_selected_source_id="source",
                changed_frozen_top1=False,
            )
            for stage in (16, 32, 48)
            for phase in phases
            for qid in qids[phase]
            for arm in arms
        ]
        result = summarize_shadow_heldout(rows, qids, routes, targets)
        check = result["results"]["48/gated/general/test"]
        self.assertEqual(result["planned_shadow_choices"], 480)
        self.assertEqual(check["native_unanswerable"], 1)
        self.assertEqual(check["native_weak_source_correct"], 7)
        self.assertEqual(check["shadow_weak_source_gains"], 0)
        with self.assertRaises(ValueError):
            summarize_shadow_heldout(rows[:-1], qids, routes, targets)

    def test_shadow_provenance_binds_all_480_choices_to_train_calibration(self):
        class Window:
            source_id = "source"

            def identity(self):
                return "fixed-window"

        class Pool:
            windows = (Window(),)

            def seal(self):
                return "sealed-original-pool"

        phases = ("select", "retention", "test", "transfer")
        arms = (
            "prototype",
            "linear",
            "gated",
            "lineage_lora_gated",
            "independent_lora_gated",
        )
        pools = {f"{p}-{n}": Pool() for p in phases for n in range(8)}
        calibration = [
            dict(
                stage=stage,
                arm=arm,
                cell=cell,
                status="succeeded",
                checkpoint_head_sha256="a" * 64,
                receipt=dict(
                    stage=stage,
                    arm=arm,
                    cell=cell,
                    chosen_scale=0.0,
                    winner_chosen_from_train_only=True,
                    all_test_and_transfer_answers_and_labels_unseen=True,
                ),
            )
            for stage in (16, 32, 48)
            for arm in arms
            for cell in ("general", "temporal")
        ]
        selected = [
            dict(
                stage=stage,
                phase=phase,
                arm=arm,
                cell="general",
                question_id=f"{phase}-{n}",
                status="succeeded",
                chosen_scale=0.0,
                selected_index=0,
                frozen_index=0,
                selected_source_id="source",
                frozen_selected_source_id="source",
                changed_frozen_top1=False,
                original_pool_digest="sealed-original-pool",
                candidate_identity_sha256=_pin(("fixed-window",)),
                head_sha256="a" * 64,
                native_targets_unread=True,
                actual_reader_executions=0,
            )
            for stage in (16, 32, 48)
            for phase in phases
            for n in range(8)
            for arm in arms
        ]
        census = verify_shadow_source_receipts(selected, calibration, pools)
        self.assertEqual(census["source_choices_verified"], 480)
        self.assertEqual(census["failed_source_choices"], 0)
        for field, wrong in (
            ("chosen_scale", 8.0),
            ("selected_source_id", "fabricated"),
            ("head_sha256", "b" * 64),
            ("original_pool_digest", "another"),
            ("candidate_identity_sha256", "other"),
            ("changed_frozen_top1", True),
        ):
            damaged = [dict(row) for row in selected]
            damaged[0][field] = wrong
            with self.subTest(field=field), self.assertRaises(ValueError):
                verify_shadow_source_receipts(damaged, calibration, pools)
        damaged = [dict(row) for row in selected]
        damaged[0]["status"] = "failed"
        result = verify_shadow_source_receipts(damaged, calibration, pools)
        self.assertEqual(result["source_choices_verified"], 479)
        self.assertEqual(result["failed_source_choices"], 1)

    def test_weak_source_gain_is_not_reader_or_semantic_gain(self):
        phases = ("select", "retention", "test", "transfer")
        qids = {p: [f"{p}-{i}" for i in range(8)] for p in phases}
        routes = {qid: "general" for group in qids.values() for qid in group}
        targets = {
            qid: Row(unanswerable=False, unresolved_evidence=(), evidence=("source",))
            for qid in routes
        }
        rows = [
            dict(
                stage=stage,
                phase=phase,
                question_id=qid,
                arm=arm,
                cell="general",
                status="succeeded",
                selected_source_id="source",
                frozen_selected_source_id="other",
                changed_frozen_top1=True,
            )
            for stage in (16, 32, 48)
            for phase in phases
            for qid in qids[phase]
            for arm in (
                "prototype",
                "linear",
                "gated",
                "lineage_lora_gated",
                "independent_lora_gated",
            )
        ]
        result = summarize_shadow_heldout(rows, qids, routes, targets)
        check = result["results"]["48/gated/general/test"]
        self.assertEqual(check["shadow_weak_source_gains"], 8)
        self.assertFalse(check["reader_called_for_shadow"])
        self.assertFalse(check["semantic_entailment_judged"])


if __name__ == "__main__":
    unittest.main()
