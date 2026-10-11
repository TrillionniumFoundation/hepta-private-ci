"""Synthetic fail-closed frozen RRF source-recall grid; no model downloads."""

from types import SimpleNamespace as Obj
import unittest

from stem_frozen_retrieval_grid import (
    GRID, BASELINE, PHASES, evaluate_fixed, label_key,
    select_from_train, validate_unlabelled,
)


def fixture():
    cohorts = {"train": [f"train-{n}" for n in range(48)]}
    cohorts.update({p: [f"{p}-{n}" for n in range(8)] for p in PHASES[1:]})
    plan = dict(
        questions=cohorts,
        question_families={
            q: ("family-%d" % (i % 6))
            for group in cohorts.values() for i, q in enumerate(group)
        },
        source_visibility_policy="strict-as-of-before-index-and-every-Encoder-v1",
    )
    records = []
    for phase in PHASES:
        for qid in cohorts[phase]:
            for config in GRID:
                pool = ["source-distractor"]
                docs = ["source-distractor", "source-positive"]
                # Train-only winner is a pre-injected scenario, never
                # determined by any held-out target.
                if config == (128, 0.75):
                    pool.append("source-positive")
                if config == BASELINE and qid.endswith("-7"):
                    pool.append("source-positive")
                records.append(dict(
                    phase=phase, question_id=qid,
                    source_family=plan["question_families"][qid],
                    policy=label_key(config),
                    retrieved_source_ids=docs,
                    window_source_ids=pool,
                    original_as_of_index_sha256="e" * 64,
                    pool_sha256="f" * 64,
                    replayed_original_pool_sha256=(
                        True if config == BASELINE else None
                    ),
                    source_text_exported=False,
                    read_targets_for_retrieval=False,
                ))
    targets = {
        q: Obj(unanswerable=False, evidence=("source-positive",),
               unresolved_evidence=())
        for group in cohorts.values() for q in group
    }
    return plan, records, targets


class FrozenGridTests(unittest.TestCase):
    def test_labels_enter_only_after_original_candidate_census(self):
        plan, rows, targets = fixture()
        records = validate_unlabelled(plan, rows)
        self.assertEqual(len(records), 800)
        self.assertTrue(all("weak_source_hit" not in r for r in rows))
        train = {q: targets[q] for q in plan["questions"]["train"]}
        selection = select_from_train(plan, records, train)
        self.assertEqual(selection["selected_policy"], "k128/lex0.75")
        self.assertEqual(selection["train_question_count"], 48)
        self.assertTrue(selection["evaluation_labels_were_not_read_to_select"])
        self.assertFalse(selection["production_accepted"])

    def test_matched_heldout_improvements_only_source_coverage(self):
        plan, rows, targets = fixture()
        bound = validate_unlabelled(plan, rows)
        train = {q: targets[q] for q in plan["questions"]["train"]}
        selection = select_from_train(plan, bound, train)
        evaluation = {q: targets[q] for phase in PHASES[1:]
                      for q in plan["questions"][phase]}
        result = evaluate_fixed(plan, bound, evaluation, selection)
        self.assertEqual(result["matched_question_count"], 32)
        self.assertEqual(result["results"]["test"]["planned"], 8)
        self.assertEqual(result["results"]["test"]["original_window_hits"], 1)
        self.assertEqual(result["results"]["test"]["selected_window_hits"], 8)
        self.assertEqual(result["results"]["test"]["window_rescues"], 7)
        self.assertEqual(result["results"]["test"]["retrieval_rescues"], 0)
        self.assertTrue(result["no_claim_of_original_Reader_QA_gain"])

    def test_missing_duplicate_or_changed_index_is_rejected(self):
        for scenario in ("missing", "duplicate", "index", "pool", "family"):
            plan, rows, targets = fixture()
            if scenario == "missing":
                rows.pop()
            elif scenario == "duplicate":
                rows[-1] = dict(rows[0])
            elif scenario == "index":
                rows[-1]["original_as_of_index_sha256"] = "a" * 64
            elif scenario == "pool":
                first = next(r for r in rows if r["policy"] == label_key(BASELINE))
                first["replayed_original_pool_sha256"] = False
            else:
                rows[0]["source_family"] = "different"
            with self.subTest(scenario=scenario), self.assertRaises(ValueError):
                validate_unlabelled(plan, rows)

    def test_cannot_send_unseen_labels_into_train_calibration(self):
        plan, rows, targets = fixture()
        bound = validate_unlabelled(plan, rows)
        with self.assertRaisesRegex(ValueError, "TRAIN-only"):
            select_from_train(plan, bound, targets)
        selection = select_from_train(
            plan, bound, {q: targets[q] for q in plan["questions"]["train"]}
        )
        with self.assertRaisesRegex(ValueError, "evaluation targets"):
            evaluate_fixed(plan, bound, targets, selection)

    def test_unanswerable_unresolved_or_no_support_are_unscored_not_wrong(self):
        plan, rows, targets = fixture()
        bound = validate_unlabelled(plan, rows)
        train = {q: targets[q] for q in plan["questions"]["train"]}
        chosen = select_from_train(plan, bound, train)
        eval_targets = {q: targets[q] for p in PHASES[1:]
                        for q in plan["questions"][p]}
        eval_targets["test-0"] = Obj(
            unanswerable=True, evidence=(), unresolved_evidence=()
        )
        eval_targets["test-1"] = Obj(
            unanswerable=False, evidence=("source-positive",),
            unresolved_evidence=("unreviewable",)
        )
        result = evaluate_fixed(plan, bound, eval_targets, chosen)
        self.assertEqual(result["results"]["test"]["planned"], 8)
        self.assertEqual(result["results"]["test"]["unscored_original_question"], 2)
        self.assertEqual(result["results"]["test"]["scored_original_question"], 6)

    def test_a_different_registered_grid_cannot_be_injected(self):
        with self.assertRaisesRegex(ValueError, "preregistered"):
            label_key((256, 0.5))
        with self.assertRaisesRegex(ValueError, "preregistered"):
            label_key((64, 0.125))


if __name__ == "__main__":
    unittest.main()
