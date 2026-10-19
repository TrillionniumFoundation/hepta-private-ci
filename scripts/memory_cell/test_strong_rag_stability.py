"""Model-free tests of calibration-only top-k selection stability."""

from copy import deepcopy
from dataclasses import asdict
import json
from pathlib import Path
import tempfile
import unittest
from types import ModuleType
from unittest.mock import patch

from strong_rag_stability import KS, leave_one_out


def cohort(winners, n=3):
    rows = []
    for i in range(n):
        for k in KS:
            rows.append(
                dict(
                    question_id=f"q{i}",
                    arm=f"k{k}",
                    status="succeeded",
                    strict_task_success=(i, k) in winners,
                    receipt=dict(input_tokens=10 * k),
                )
            )
    return rows


class CalibrationSensitivityTests(unittest.TestCase):
    def test_stable_full_cohort_recomputes_without_a_heldout_label(self):
        winners = {(i, 2) for i in range(3)}
        report = leave_one_out(cohort(winners), ["q0", "q1", "q2"])
        self.assertTrue(report["stable_to_one_calibration_case_removal"])
        self.assertEqual(report["chosen_k_counts"]["2"], 3)
        self.assertEqual(report["selected_wins_over_fixed_k4"], 3)
        self.assertEqual(report["all_planned_delta_lower"], 1)
        self.assertFalse(report["bounds_are_confidence_intervals"])
        self.assertFalse(report["production_accepted"])

    def test_each_heldout_label_does_not_choose_its_own_k(self):
        winners = {(0, 1), (1, 2), (2, 4)}
        baseline = leave_one_out(cohort(winners), ["q0", "q1", "q2"])
        modified = cohort(winners | {(0, 6)})
        mutated = leave_one_out(modified, ["q0", "q1", "q2"])
        self.assertEqual(
            baseline["folds"][0]["chosen_k_without_that_question"],
            mutated["folds"][0]["chosen_k_without_that_question"],
        )

    def test_instability_is_exposed_and_not_called_independent_validation(self):
        winners = {(0, 1), (1, 2), (2, 4)}
        report = leave_one_out(cohort(winners), ["q0", "q1", "q2"])
        self.assertFalse(report["stable_to_one_calibration_case_removal"])
        self.assertGreater(report["distinct_choices"], 1)
        self.assertFalse(report["folds_are_statistically_independent"])
        self.assertEqual(report["independent_future_task_count"], 0)

    def test_ties_use_fewer_tokens_then_smaller_k(self):
        winners = {(i, k) for i in range(3) for k in KS}
        report = leave_one_out(cohort(winners), ["q0", "q1", "q2"])
        self.assertEqual(report["chosen_k_counts"]["1"], 3)

    def test_missing_attempt_is_not_silently_marked_wrong(self):
        rows = cohort({(0, 2), (1, 2), (2, 2)})
        rows[0].update(status="failed", receipt=None)
        report = leave_one_out(rows, ["q0", "q1", "q2"])
        self.assertGreater(report["missing_comparisons"], 0)
        self.assertFalse(report["all_folds_qualified"])
        self.assertLess(
            report["all_planned_delta_lower"], report["all_planned_delta_upper"]
        )

    def test_duplicate_missing_and_invalid_score_or_token_reject(self):
        base = cohort({(0, 2)})
        for changed in (base[:-1], base + base[:1]):
            with self.assertRaises(ValueError):
                leave_one_out(changed, ["q0", "q1", "q2"])
        for field, value in (
            ("strict_task_success", 1),
            ("strict_task_success", None),
            ("receipt", {"input_tokens": -1}),
            ("receipt", {"input_tokens": 2049}),
            ("receipt", {"input_tokens": True}),
        ):
            altered = deepcopy(base)
            altered[0][field] = value
            with self.subTest(field=field, value=value), self.assertRaises(ValueError):
                leave_one_out(altered, ["q0", "q1", "q2"])

    def test_frozen_k_seals_calibration_sensitivity_after_original_answers(self):
        import strong_rag_trial as trial
        from native import Document, Question

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            inputs = root / "calibration-input"
            inputs.mkdir()
            qids = [f"q{i}" for i in range(8)]
            cases = [
                dict(
                    query=asdict(
                        Question(qid, qid, qid, "Which code?", "2026-01-01T00:00:00Z")
                    ),
                    kind="new_fact",
                    candidate_ids=[f"{qid}-{j}" for j in range(6)],
                    candidate_digest=f"pool-{qid}",
                    frontier="frozen",
                )
                for qid in qids
            ]
            originals = [
                asdict(
                    Document(
                        f"{qid}-0",
                        f"root-{qid}",
                        qid,
                        qid,
                        "2026-01-01T00:00:00Z",
                        "site_11111111",
                    )
                )
                for qid in qids
            ]
            labels = [
                dict(
                    id=qid,
                    kind="new_fact",
                    expected="site_11111111",
                    support=[f"{qid}-0"],
                )
                for qid in qids
            ]
            trial.dump(inputs / "calibration-sources.json", originals)
            trial.dump(inputs / "calibration-labels.json", labels)
            trial.dump(
                inputs / "calibration-plan.json",
                dict(
                    schema=trial.SCHEMA,
                    historical_plan_sha256=trial.HISTORIC_PLAN_SHA,
                    ks=trial.KS,
                    cases=cases,
                    calibration_only=True,
                    test_cases_materialized=False,
                    token_limit=trial.LIMIT,
                    calibration_sources_sha256=trial.file_sha(
                        inputs / "calibration-sources.json"
                    ),
                    calibration_labels_sha256=trial.file_sha(
                        inputs / "calibration-labels.json"
                    ),
                ),
            )
            read_before_label = trial.read
            chronological = []

            def observed_read(path, pin):
                if path.name == "calibration-labels.json":
                    chronological.append("labels_opened")
                    original = (
                        (root / "output/raw-answers.jsonl").read_text().splitlines()
                    )
                    self.assertEqual(len(original), 40)
                    self.assertTrue(
                        all("strict_task_success" not in line for line in original)
                    )
                return read_before_label(path, pin)

            def journal(_, case_rows, __, arms, ___, journal_path, *, seed):
                chronological.append("original_generation")
                rows = []
                with journal_path.open("x", encoding="utf-8") as target:
                    for case in case_rows:
                        for arm in arms:
                            row = dict(
                                question_id=case["query"]["identity"],
                                arm=arm,
                                kind="new_fact",
                                candidate_digest=case["candidate_digest"],
                                selected=[f"{case['query']['identity']}-0"],
                                status="succeeded",
                                answer=(
                                    "site_11111111" if arm == "k2" else "site_22222222"
                                ),
                                receipt=dict(
                                    input_tokens=int(arm[1:]) * 50,
                                    generated_tokens=3,
                                    seconds=0.1,
                                ),
                            )
                            target.write(json.dumps(row) + "\n")
                            target.flush()
                            rows.append(row)
                chronological.append("all_answers_saved")
                return rows

            with (
                # These synthetic Reader tests must not require a real torch
                # installation just to check chronology and source isolation.
                patch.dict("sys.modules", {"torch": ModuleType("torch")}),
                patch(
                    "runtime_preflight.capture_runtime",
                    return_value={"schema": "synthetic-host-fixture-only"},
                ),
                patch.object(trial, "read", side_effect=observed_read),
                patch.object(
                    trial,
                    "_reader",
                    return_value=(
                        object(),
                        {},
                        dict(inventory_digest="frozen-reference"),
                    ),
                ),
                patch.object(trial, "_journal_answers", side_effect=journal),
                patch.dict("os.environ", {"HEPTA_MEMORY_TESTED_COMMIT": "b" * 40}),
            ):
                report = trial.calibrate(
                    inputs,
                    root / "model",
                    root / "output",
                    prep_sha=trial.file_sha(inputs / "calibration-plan.json"),
                    stage_sha="a" * 64,
                )
            policy = json.loads((root / "output/frozen-policy.json").read_text())
            self.assertEqual(report["frozen_k"], 2)
            self.assertEqual(
                report["calibration_sensitivity"]["chosen_k_counts"]["2"], 8
            )
            self.assertEqual(
                policy["calibration_sensitivity_digest"],
                trial.digest(report["calibration_sensitivity"]),
            )
            self.assertEqual(
                chronological,
                ["original_generation", "all_answers_saved", "labels_opened"],
            )
            self.assertFalse(policy["candidate_accepted"])

    def test_subset_and_duplicate_identity_reject(self):
        rows = cohort({(0, 2)})
        for names in (["q0", "q1"], ["q0", "q0", "q2"], [], ["q0"]):
            with self.assertRaises(ValueError):
                leave_one_out(rows, names)


if __name__ == "__main__":
    unittest.main()
