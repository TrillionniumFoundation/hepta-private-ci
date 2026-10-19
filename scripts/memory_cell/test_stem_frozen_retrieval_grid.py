"""Synthetic fail-closed frozen RRF source-recall grid; no model downloads."""

from types import SimpleNamespace as Obj
from copy import deepcopy
import unittest

from stem_frozen_retrieval_grid import (
    GRID,
    BASELINE,
    PHASES,
    evaluate_fixed,
    label_key,
    select_from_train,
    verify_train_selection,
    validate_unlabelled,
)
from stem_frozen_retrieval_grid_trial import verify_pinned_replay_question
from stem_frozen_retrieval_grid import posthoc_all_registered_grid_ceiling


def fixture():
    cohorts = {"train": [f"train-{n}" for n in range(48)]}
    cohorts.update({p: [f"{p}-{n}" for n in range(8)] for p in PHASES[1:]})
    plan = dict(
        questions=cohorts,
        question_families={
            q: ("family-%d" % (i % 6))
            for group in cohorts.values()
            for i, q in enumerate(group)
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
                records.append(
                    dict(
                        phase=phase,
                        question_id=qid,
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
                    )
                )
    targets = {
        q: Obj(
            unanswerable=False, evidence=("source-positive",), unresolved_evidence=()
        )
        for group in cohorts.values()
        for q in group
    }
    return plan, records, targets


class FrozenGridTests(unittest.TestCase):
    def test_replay_must_use_frozen_registered_family_not_repartition(self):
        # Public native LongMemEval can have fewer than three source families
        # when its historical source partitioner is invoked out of context.
        # The original 80-question trial already pinned the partitions.
        question = Obj(identity="q0", scope="scope-0", family="native-kind")

        class OneFamily:
            families = {"native-kind": "pinned-source-family"}

            def partition(self, ignored):
                raise AssertionError("would re-split a frozen test cohort")

        self.assertEqual(
            verify_pinned_replay_question(
                question,
                OneFamily(),
                {"q0"},
                {"q0": "pinned-source-family"},
            ),
            "q0",
        )

    def test_pinned_replay_rejects_other_native_question_and_source_family(self):
        question = Obj(identity="q0", scope="scope-0", family="native-kind")
        benchmark = Obj(families={"native-kind": "registered-family"})
        for ids, declared in (
            ({"other"}, {"q0": "registered-family"}),
            ({"q0"}, {"q0": "forged-family"}),
            ({"q0"}, {}),
        ):
            with (
                self.subTest(ids=ids, declared=declared),
                self.assertRaises(ValueError),
            ):
                verify_pinned_replay_question(question, benchmark, ids, declared)

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
        evaluation = {
            q: targets[q] for phase in PHASES[1:] for q in plan["questions"][phase]
        }
        result = evaluate_fixed(plan, bound, evaluation, selection)
        self.assertEqual(result["matched_question_count"], 32)
        self.assertEqual(result["results"]["test"]["planned"], 8)
        self.assertEqual(result["results"]["test"]["original_window_hits"], 1)
        self.assertEqual(result["results"]["test"]["selected_window_hits"], 8)
        self.assertEqual(result["results"]["test"]["window_rescues"], 7)
        self.assertEqual(result["results"]["test"]["retrieval_rescues"], 0)
        self.assertTrue(result["no_claim_of_original_Reader_QA_gain"])

    def test_posthoc_grid_ceiling_is_not_a_heldout_selected_policy(self):
        plan, rows, targets = fixture()
        bound = validate_unlabelled(plan, rows)
        chosen = select_from_train(
            plan,
            bound,
            {q: targets[q] for q in plan["questions"]["train"]},
        )
        heldout = {
            q: targets[q] for phase in PHASES[1:] for q in plan["questions"][phase]
        }
        report = posthoc_all_registered_grid_ceiling(plan, bound, heldout, chosen)
        self.assertEqual(report["planned_evaluation_questions"], 32)
        self.assertEqual(report["by_phase"]["test"]["baseline_window_hits"], 1)
        self.assertEqual(
            report["by_phase"]["test"]["any_registered_grid_window_hits"], 8
        )
        self.assertEqual(
            report["by_phase"]["test"]["hindsight_grid_could_rescue_missing_window"], 7
        )
        self.assertTrue(report["upper_bound_requires_forbidden_per_question_oracle"])
        self.assertFalse(report["trained_or_tuned_on_evaluation_labels"])
        self.assertFalse(report["task_answer_gain_proven"])

    def test_posthoc_oracle_upper_bound_does_not_change_train_selected_baseline(self):
        plan, rows, targets = fixture()
        for row in rows:
            if row["phase"] == "train":
                row["window_source_ids"] = (
                    ["source-distractor", "source-positive"]
                    if row["policy"] == label_key(BASELINE)
                    else ["source-distractor"]
                )
        bound = validate_unlabelled(plan, rows)
        chosen = select_from_train(
            plan,
            bound,
            {q: targets[q] for q in plan["questions"]["train"]},
        )
        self.assertEqual(chosen["selected_policy"], label_key(BASELINE))
        report = posthoc_all_registered_grid_ceiling(
            plan,
            bound,
            {q: targets[q] for phase in PHASES[1:] for q in plan["questions"][phase]},
            chosen,
        )
        self.assertEqual(report["by_phase"]["test"]["train_selected_window_hits"], 1)
        self.assertEqual(
            report["by_phase"]["test"]["any_registered_grid_window_hits"], 8
        )
        self.assertEqual(
            report["by_phase"]["test"]["hindsight_grid_could_rescue_missing_window"], 7
        )
        self.assertEqual(report["fixed_train_selected_policy"], label_key(BASELINE))

    def test_posthoc_grid_cannot_score_absent_or_leaked_evaluation_targets(self):
        plan, rows, targets = fixture()
        bound = validate_unlabelled(plan, rows)
        chosen = select_from_train(
            plan,
            bound,
            {q: targets[q] for q in plan["questions"]["train"]},
        )
        with self.assertRaises(ValueError):
            posthoc_all_registered_grid_ceiling(plan, bound, {}, chosen)
        heldout = {
            q: targets[q] for phase in PHASES[1:] for q in plan["questions"][phase]
        }
        bound[("test", "test-0", label_key(GRID[0]))]["read_targets_for_retrieval"] = (
            True
        )
        with self.assertRaisesRegex(ValueError, "hindsight labels"):
            posthoc_all_registered_grid_ceiling(plan, bound, heldout, chosen)

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
        eval_targets = {q: targets[q] for p in PHASES[1:] for q in plan["questions"][p]}
        eval_targets["test-0"] = Obj(
            unanswerable=True, evidence=(), unresolved_evidence=()
        )
        eval_targets["test-1"] = Obj(
            unanswerable=False,
            evidence=("source-positive",),
            unresolved_evidence=("unreviewable",),
        )
        result = evaluate_fixed(plan, bound, eval_targets, chosen)
        self.assertEqual(result["results"]["test"]["planned"], 8)
        self.assertEqual(result["results"]["test"]["unscored_original_question"], 2)
        self.assertEqual(result["results"]["test"]["scored_original_question"], 6)

    def test_train_grid_scorecard_is_sealed_before_heldout_review(self):
        plan, rows, targets = fixture()
        unlabeled = validate_unlabelled(plan, rows)
        train = {qid: targets[qid] for qid in plan["questions"]["train"]}
        selected = select_from_train(plan, unlabeled, train)
        self.assertEqual(verify_train_selection(plan, selected)["id"], "k128/lex0.75")
        eval_targets = {
            qid: targets[qid]
            for phase in PHASES[1:]
            for qid in plan["questions"][phase]
        }
        score = evaluate_fixed(plan, unlabeled, eval_targets, selected)
        self.assertTrue(score["train_policy_revalidated_against_original_scorecard"])
        self.assertEqual(score["results"]["test"]["original_planned_family_count"], 6)
        self.assertEqual(score["results"]["test"]["native_scored_family_count"], 6)
        self.assertEqual(score["distinct_heldout_question_source_families"], 6)
        self.assertTrue(score["independent_family_effect_not_verified"])

    def test_forged_train_winner_or_source_cohort_is_rejected(self):
        plan, rows, targets = fixture()
        unlabelled = validate_unlabelled(plan, rows)
        chosen = select_from_train(
            plan,
            unlabelled,
            {qid: targets[qid] for qid in plan["questions"]["train"]},
        )
        cases = (
            "winner",
            "cohort",
            "domain",
            "score",
            "candidate",
            "order",
            "flag",
            "baseline",
            "ntrain",
        )
        for mode in cases:
            forged = deepcopy(chosen)
            if mode == "winner":
                forged["selected_policy"] = "k64/lex0.00"
            elif mode == "cohort":
                forged["train_cohort_sha256"] = "0" * 64
            elif mode == "domain":
                forged["eligible_policy_ids"] = forged["eligible_policy_ids"][:-1]
            elif mode == "score":
                forged["all_candidates"][0]["family_macro_window_recall"] = float("nan")
            elif mode == "candidate":
                forged["all_candidates"][0]["channel_k"] = 999
            elif mode == "order":
                forged["all_candidates"].reverse()
            elif mode == "flag":
                forged["evaluation_labels_were_not_read_to_select"] = 1
            elif mode == "baseline":
                forged["baseline_policy"] = "k128/lex0.75"
            else:
                forged["train_question_count"] = 16
            with self.subTest(mode=mode), self.assertRaises(ValueError):
                verify_train_selection(plan, forged)

    def test_weak_candidate_digest_and_replay_flag_must_be_canonical(self):
        for mode in (
            "index-nonhex",
            "pool-nonhex",
            "replay-truthy-string",
            "baseline-truthy-string",
            "nonbaseline-false",
        ):
            plan, rows, _ = fixture()
            row = rows[0]
            if mode == "index-nonhex":
                row["original_as_of_index_sha256"] = "g" * 64
            elif mode == "pool-nonhex":
                row["pool_sha256"] = "!" * 64
            elif mode == "replay-truthy-string":
                row["replayed_original_pool_sha256"] = "yes"
            elif mode == "baseline-truthy-string":
                baseline = next(r for r in rows if r["policy"] == label_key(BASELINE))
                baseline["replayed_original_pool_sha256"] = "yes"
            else:
                row["replayed_original_pool_sha256"] = False
            with self.subTest(mode=mode), self.assertRaises(ValueError):
                validate_unlabelled(plan, rows)

    def test_posthoc_ceiling_cannot_accept_forged_evaluation_winner(self):
        plan, rows, targets = fixture()
        unlabeled = validate_unlabelled(plan, rows)
        selected = select_from_train(
            plan,
            unlabeled,
            {qid: targets[qid] for qid in plan["questions"]["train"]},
        )
        selected["selected_policy"] = "k64/lex0.00"
        eval_targets = {
            qid: targets[qid]
            for phase in PHASES[1:]
            for qid in plan["questions"][phase]
        }
        with self.assertRaises(ValueError):
            posthoc_all_registered_grid_ceiling(
                plan,
                unlabeled,
                eval_targets,
                selected,
            )

    def test_a_different_registered_grid_cannot_be_injected(self):
        with self.assertRaisesRegex(ValueError, "preregistered"):
            label_key((256, 0.5))
        with self.assertRaisesRegex(ValueError, "preregistered"):
            label_key((64, 0.125))


if __name__ == "__main__":
    unittest.main()
