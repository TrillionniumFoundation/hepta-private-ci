"""Synthetic tests: abstention is not a source-selection or Reader gain."""

import math
import unittest
from copy import deepcopy
from types import SimpleNamespace as Obj

from stem_native_null_ablation import (
    observe_null_choice,
    review_null_counterfactual,
)

PHASES = ("select", "retention", "test", "transfer")
ARMS = (
    "frozen_rerank",
    "prototype",
    "linear",
    "gated",
    "lineage_lora_gated",
    "independent_lora_gated",
)
STAGES = (16, 32, 48)


def fixture():
    qs = {"train": [f"train-{i}" for i in range(48)]}
    qs.update({p: [f"{p}-{i}" for i in range(8)] for p in PHASES})
    unanswerable = {
        f"{p}-{n}"
        for p, count in (("select", 2), ("retention", 2), ("test", 2), ("transfer", 1))
        for n in range(count)
    }
    targets = {
        q: Obj(
            unanswerable=q in unanswerable,
            evidence=("native-source",),
            unresolved_evidence=(),
        )
        for p in PHASES
        for q in qs[p]
    }
    plan = dict(
        arms=list(ARMS),
        curriculum_attempted_examples=list(STAGES),
        questions=qs,
    )
    scored = []
    for stage in STAGES:
        for phase in PHASES:
            for qid in qs[phase]:
                is_abs = targets[qid].unanswerable
                logits = [2.0, 1.0, 3.0 if is_abs else 0.0]
                diagnosis = observe_null_choice(logits, ("A", "B"), 0)
                for arm in ARMS:
                    scored.append(
                        dict(
                            stage=stage,
                            phase=phase,
                            question_id=qid,
                            arm=arm,
                            status="succeeded",
                            selected=0,
                            source_choice_correct=0 if is_abs else 1,
                            null_counterfactual=dict(diagnosis),
                        )
                    )
    return plan, scored, targets


class NullCounterfactualTests(unittest.TestCase):
    def test_equal_null_and_best_candidate_is_only_a_counterfactual(self):
        q = observe_null_choice([2.0, 1.0, 2.0], ("A", "B"), 0)
        self.assertTrue(q["zero_offset_would_abstain"])
        self.assertIsNone(q["counterfactual_choice"])
        self.assertEqual(q["observed_forced_top1_index"], 0)
        self.assertTrue(q["actual_reader_answer_not_recomputed"])
        self.assertFalse(q["posthoc_labels_used_to_select_cutoff"])

    def test_lexical_tie_break_and_empty_pool(self):
        same = observe_null_choice([0.0, 0.0, -1.0], ("B", "A"), 1)
        self.assertFalse(same["zero_offset_would_abstain"])
        self.assertEqual(same["counterfactual_choice"], 1)
        empty = observe_null_choice([0.0], (), None)
        self.assertTrue(empty["zero_offset_would_abstain"])
        self.assertIsNone(empty["null_minus_best_candidate"])

    def test_abstention_not_conflated_with_answerable_native_source_gain(self):
        plan, scored, targets = fixture()
        out = review_null_counterfactual(plan, scored, targets)
        self.assertEqual(out["original_policy_counts_preserved"], 576)
        select = out["per_arm_phase_checkpoint"]["48/select/gated"]
        transfer = out["per_arm_phase_checkpoint"]["48/transfer/gated"]
        self.assertEqual(select["attempted"], 8)
        self.assertEqual(select["native_unanswerable_count"], 2)
        self.assertEqual(select["native_unanswerable_recovered"], 2)
        self.assertEqual(select["native_answerable_harmed_by_abstention"], 0)
        self.assertEqual(select["native_source_correctness_delta_sum"], 2)
        self.assertEqual(transfer["native_unanswerable_recovered"], 1)
        self.assertTrue(out["posthoc_exploratory_not_preregistered_policy"])
        self.assertFalse(out["production_accepted"])

    def test_false_abstention_harms_answerable_but_does_not_make_reader_answer(self):
        plan, scored, targets = fixture()
        for r in scored:
            if (
                r["stage"] == 48
                and r["phase"] == "test"
                and r["question_id"] == "test-2"
            ):
                r["null_counterfactual"] = observe_null_choice(
                    [2.0, 1.0, 4.0], ("A", "B"), 0
                )
        report = review_null_counterfactual(plan, scored, targets)
        group = report["per_arm_phase_checkpoint"]["48/test/gated"]
        self.assertEqual(group["native_unanswerable_recovered"], 2)
        self.assertEqual(group["native_answerable_harmed_by_abstention"], 1)
        self.assertEqual(group["native_source_correctness_delta_sum"], 1)
        self.assertEqual(group["extra_reader_calls"], 0)

    def test_reader_failures_are_never_dropped_from_original_census(self):
        plan, scored, targets = fixture()
        row = next(
            x
            for x in scored
            if x["stage"] == 48
            and x["phase"] == "test"
            and x["question_id"] == "test-2"
            and x["arm"] == "gated"
        )
        row["status"] = "failed"
        x = review_null_counterfactual(plan, scored, targets)
        self.assertEqual(x["per_arm_phase_checkpoint"]["48/test/gated"]["attempted"], 8)
        row.pop("null_counterfactual")
        row.pop("selected")
        y = review_null_counterfactual(plan, scored, targets)
        stats = y["per_arm_phase_checkpoint"]["48/test/gated"]
        self.assertEqual(stats["attempted"], 8)
        self.assertEqual(stats["unobserved_or_unresolved"], 1)

    def test_wrong_forced_selection_and_nonfinite_logits_fail_closed(self):
        for values, ids, picked in (
            ([2.0, 1.0, 0.0], ("A", "B"), 1),
            ([2.0, 1.0, math.nan], ("A", "B"), 0),
            ([2.0, math.inf, 0.0], ("A", "B"), 0),
            ([True, 2.0], ("A",), 0),
            ([1.0, 1.0, 0.0], ("A", "A"), 0),
        ):
            with self.subTest(values=values), self.assertRaises(ValueError):
                observe_null_choice(values, ids, picked)

    def test_missing_tampered_and_duplicate_native_receipts_reject(self):
        plan, scored, targets = fixture()
        for mode in ("duplicate", "missing", "altered", "label", "threshold"):
            a = deepcopy(scored)
            if mode == "duplicate":
                a[-1] = dict(a[0])
            elif mode == "missing":
                a.pop()
            elif mode == "altered":
                a[0]["null_counterfactual"]["observed_forced_top1_index"] = 1
            elif mode == "threshold":
                a[0]["null_counterfactual"]["zero_offset_would_abstain"] = False
            else:
                wrong = dict(targets)
                wrong.pop("select-0")
            with self.subTest(mode=mode), self.assertRaises(ValueError):
                review_null_counterfactual(
                    plan, a, wrong if mode == "label" else targets
                )


if __name__ == "__main__":
    unittest.main()
