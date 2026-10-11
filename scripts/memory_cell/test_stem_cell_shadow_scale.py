"""Shadow scale is chosen using TRAIN only, never Reader/test labels."""

from types import SimpleNamespace as Row
import math
import unittest

from stem_cell_shadow_scale import (
    GRID, calibrate_shadow_scale, choose_shadow, summarize_shadow_heldout,
)


def training():
    return [
        dict(
            question_id=f"train-{n}", family=f"family-{n}",
            candidate_ids=("A", "B"), positive_indices=(1,),
            frozen_logits=[8.0, 2.0], head_logits=[7.5, 2.5],
        )
        for n in range(2)
    ]


def calibrate(rows=None):
    return calibrate_shadow_scale(
        rows or training(), arm="gated", cell="general", stage=16,
        admitted_ids={"train-0", "train-1"},
    )


class ShadowScaleTests(unittest.TestCase):
    def test_train_only_grid_finds_possible_rank_flip(self):
        receipt = calibrate()
        self.assertEqual(receipt["chosen_scale"], 8.0)
        self.assertIn(receipt["chosen_scale"], GRID)
        self.assertEqual(
            receipt["equal_family_weighted_train_source_accuracy_by_scale"]["0.0"], 0.0,
        )
        self.assertEqual(
            receipt["equal_family_weighted_train_source_accuracy_by_scale"]["8.0"], 1.0,
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
        self.assertEqual(
            choose_shadow(("B", "A"), [1, 1], [1, 1], 0), 1
        )

    def test_unregistered_or_duplicate_train_questions_fail_closed(self):
        for rows, allowed in (
            (training(), {"train-0"}),
            (training() + training()[:1], {"train-0", "train-1"}),
        ):
            with self.subTest(size=len(rows)), self.assertRaises(ValueError):
                calibrate_shadow_scale(
                    rows, arm="gated", cell="general", stage=16,
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
            qid: Row(unanswerable=False, unresolved_evidence=(),
                     evidence=("source",))
            for qid in routes
        }
        targets["test-0"] = Row(
            unanswerable=True, unresolved_evidence=(), evidence=(),
        )
        arms = ("prototype", "linear", "gated",
                "lineage_lora_gated", "independent_lora_gated")
        rows = [
            dict(
                stage=stage, phase=phase, question_id=qid, arm=arm,
                cell="general", status="succeeded",
                selected_source_id="source", frozen_selected_source_id="source",
                changed_frozen_top1=False,
            )
            for stage in (16, 32, 48) for phase in phases
            for qid in qids[phase] for arm in arms
        ]
        result = summarize_shadow_heldout(rows, qids, routes, targets)
        check = result["results"]["48/gated/general/test"]
        self.assertEqual(result["planned_shadow_choices"], 480)
        self.assertEqual(check["native_unanswerable"], 1)
        self.assertEqual(check["native_weak_source_correct"], 7)
        self.assertEqual(check["shadow_weak_source_gains"], 0)
        with self.assertRaises(ValueError):
            summarize_shadow_heldout(rows[:-1], qids, routes, targets)

    def test_weak_source_gain_is_not_reader_or_semantic_gain(self):
        phases = ("select", "retention", "test", "transfer")
        qids = {p: [f"{p}-{i}" for i in range(8)] for p in phases}
        routes = {qid: "general" for group in qids.values() for qid in group}
        targets = {
            qid: Row(unanswerable=False, unresolved_evidence=(),
                     evidence=("source",))
            for qid in routes
        }
        rows = [
            dict(
                stage=stage, phase=phase, question_id=qid, arm=arm,
                cell="general", status="succeeded",
                selected_source_id="source", frozen_selected_source_id="other",
                changed_frozen_top1=True,
            )
            for stage in (16, 32, 48) for phase in phases
            for qid in qids[phase] for arm in (
                "prototype", "linear", "gated",
                "lineage_lora_gated", "independent_lora_gated",
            )
        ]
        result = summarize_shadow_heldout(rows, qids, routes, targets)
        check = result["results"]["48/gated/general/test"]
        self.assertEqual(check["shadow_weak_source_gains"], 8)
        self.assertFalse(check["reader_called_for_shadow"])
        self.assertFalse(check["semantic_entailment_judged"])


if __name__ == "__main__":
    unittest.main()
