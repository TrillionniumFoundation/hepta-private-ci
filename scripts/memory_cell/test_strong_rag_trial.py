"""Sealed real-reader RAG design tests; fixtures never substitute for model evidence."""

from copy import deepcopy
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import strong_rag_trial as trial


def rows_for(qids=("q1", "q2"), *, successes=None, failures=()):
    successes = successes or {}
    rows = []
    for qid in qids:
        for k in trial.KS:
            arm = f"k{k}"
            row = dict(
                question_id=qid,
                arm=arm,
                kind="new_fact",
                candidate_digest="pool-" + qid,
                selected=["source-" + qid],
                status="failed" if (qid, arm) in failures else "succeeded",
            )
            if row["status"] == "succeeded":
                row.update(
                    answer="site_11111111 [E1]"
                    if (qid, k) in successes
                    else "site_22222222 [E1]",
                    receipt=dict(input_tokens=100 * k, generated_tokens=6, seconds=1.0),
                )
            rows.append(row)
    return rows


def targets(qids=("q1", "q2")):
    return [
        dict(
            id=qid, kind="new_fact", expected="site_11111111", support=["source-" + qid]
        )
        for qid in qids
    ]


class StrongRagPolicyTests(unittest.TestCase):
    def test_top_k_does_not_consult_oracle_or_test_labels(self):
        case = dict(
            candidate_ids=[f"s{i}" for i in range(7)],
            candidate_digest=trial.digest(tuple(f"s{i}" for i in range(7))),
            controls={
                "hybrid": dict(selected=[f"s{i}" for i in range(4)]),
                "organized": dict(selected=["s3", "s6"]),
                "program_support": dict(selected=["s6"]),
                "empty": dict(selected=[]),
            },
        )
        baseline = trial.eval_selections(case, 2)
        other = deepcopy(case)
        other["controls"]["program_support"]["selected"] = ["s0"]
        other["controls"]["organized"]["selected"] = ["s4"]
        after = trial.eval_selections(other, 2)
        self.assertEqual(baseline["selected_k"], ("s0", "s1"))
        self.assertEqual(baseline["selected_k"], after["selected_k"])
        self.assertEqual(baseline["hybrid_k4"], after["hybrid_k4"])
        self.assertEqual(baseline["hybrid_k4_reversed"], ("s3", "s2", "s1", "s0"))
        self.assertEqual(baseline["hybrid_k6"], tuple(f"s{i}" for i in range(6)))
        for tamper in ("candidate_digest", "hybrid"):
            bad = deepcopy(case)
            if tamper == "candidate_digest":
                bad[tamper] = "tampered"
            else:
                bad["controls"]["hybrid"]["selected"] = ["s4"]
            with self.assertRaises(ValueError):
                trial.eval_selections(bad, 2)

    def test_calibration_export_excludes_test_index_hash_and_source_scope(self):
        cases = [dict(query=dict(identity=f"q{i}", scope=f"q{i}")) for i in range(8)]
        sources = [dict(identity=f"event{i}", scope=f"q{i}") for i in range(8)]
        indices = {f"q{i}": f"sha{i}" for i in range(8)}
        trial.assert_calibration_publication(cases, sources, indices)
        extra = dict(indices)
        extra["held_out_test_scope"] = "private_index_hash"
        with self.assertRaises(ValueError):
            trial.assert_calibration_publication(cases, sources, extra)
        sources.append(dict(identity="leaked", scope="held_out_test_scope"))
        with self.assertRaises(ValueError):
            trial.assert_calibration_publication(cases, sources, indices)

    def test_calibration_uses_actual_task_success_before_input_cost(self):
        correct = {("q1", 2), ("q2", 2), ("q1", 1)}
        rows = rows_for(successes=correct)
        chosen, stats = trial.choose_k(rows, targets(), ["q1", "q2"])
        self.assertEqual(chosen, 2)
        self.assertEqual(stats["k2"]["strict_success"], 2)
        self.assertEqual(stats["k1"]["strict_success"], 1)
        self.assertEqual(stats["k1"]["input_tokens"], 200)

    def test_ties_choose_lower_observed_token_cost(self):
        good = {(qid, k) for qid in ("q1", "q2") for k in trial.KS}
        chosen, _ = trial.choose_k(rows_for(successes=good), targets(), ["q1", "q2"])
        self.assertEqual(chosen, 1)

    def test_missing_attempt_cannot_be_optimized_away(self):
        rows = rows_for(successes={("q1", 2), ("q2", 2)}, failures={("q2", "k6")})
        chosen, stats = trial.choose_k(rows, targets(), ["q1", "q2"])
        self.assertIsNone(chosen)
        self.assertEqual(stats["k6"]["failed"], 1)
        for altered in (rows[:-1], rows + rows[:1]):
            with self.assertRaises(ValueError):
                trial.choose_k(altered, targets(), ["q1", "q2"])
        duplicate = deepcopy(rows)
        duplicate[0]["question_id"] = "q2"
        with self.assertRaises(ValueError):
            trial.choose_k(duplicate, targets(), ["q1", "q2"])

    def test_paired_failure_bounds_not_confidence_intervals(self):
        group = {
            "q1": {
                "a": dict(status="succeeded", strict_task_success=False),
                "b": dict(status="succeeded", strict_task_success=True),
            },
            "q2": {
                "a": dict(status="succeeded", strict_task_success=True),
                "b": dict(status="failed"),
            },
        }
        paired = trial.paired(group, "a", "b")
        self.assertEqual(paired["wins"], 1)
        self.assertEqual(paired["unknown_pairs"], 1)
        self.assertEqual(paired["planned_delta_lower"], 0.0)
        self.assertEqual(paired["planned_delta_upper"], 1.0)
        self.assertFalse(paired["interval_is_statistical"])

    def test_strict_census_rejects_missing_or_rewritten_answers(self):
        rows = rows_for()
        scored = trial._score(
            rows,
            targets(),
            expected=["q1", "q2"],
            arms=tuple(f"k{k}" for k in trial.KS),
        )
        self.assertTrue(all("strict_task_success" in r for r in scored))
        with self.assertRaises(ValueError):
            trial._score(
                rows[:-1],
                targets(),
                expected=["q1", "q2"],
                arms=tuple(f"k{k}" for k in trial.KS),
            )
        with self.assertRaises(ValueError):
            trial._score(
                rows + rows[:1],
                targets(),
                expected=["q1", "q2"],
                arms=tuple(f"k{k}" for k in trial.KS),
            )

    def test_sealed_policy_cannot_open_test_labels_before_all_answers(self):
        from native import Document, Question

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for folder in ("plan", "inputs", "model", "calibration"):
                (root / folder).mkdir()
            qids = [f"t{i}" for i in range(8)]
            cases, docs, answer_labels = [], {}, []
            for i, qid in enumerate(qids):
                question = Question(
                    qid, qid, qid, "What is the code?", "2026-01-01T00:00:00Z"
                )
                candidates = [f"{qid}-s{j}" for j in range(6)]
                original = Document(
                    candidates[0],
                    "root" + qid,
                    qid,
                    qid,
                    "2026-01-01T00:00:00Z",
                    "site_11111111",
                )
                docs[original.identity] = original
                cases.append(
                    dict(
                        query=asdict(question),
                        kind="new_fact",
                        frontier="frozen-frontier",
                        candidate_ids=candidates,
                        candidate_digest=trial.digest(tuple(candidates)),
                        controls=dict(
                            hybrid=dict(selected=candidates[:4]),
                            organized=dict(selected=[candidates[0]]),
                            program_support=dict(selected=[candidates[0]]),
                            empty=dict(selected=[]),
                        ),
                    )
                )
                answer_labels.append(
                    dict(
                        id=qid,
                        kind="new_fact",
                        expected="site_11111111",
                        support=[candidates[0]],
                    )
                )
            trial.dump(root / "inputs/labels.json", answer_labels)
            trial.dump(root / "model/stage.json", dict(tier="qwen-3b"))
            trial.dump(
                root / "calibration/frozen-policy.json",
                dict(
                    schema=trial.SCHEMA,
                    selected_k=2,
                    original_test_plan_sha256=trial.HISTORIC_PLAN_SHA,
                    stage_sha256="a" * 64,
                    reader_identity="reader",
                    frozen_before_evaluation=True,
                    candidate_accepted=False,
                ),
            )
            policy_sha = trial.file_sha(root / "calibration/frozen-policy.json")
            raw_read = trial.read
            original_journal = trial._journal_answers
            chronological = []

            def audited_read(path, sha):
                if path.name == "labels.json":
                    chronological.append("opened_test_labels")
                    raw = (root / "out/raw-answers.jsonl").read_text().splitlines()
                    self.assertEqual(len(raw), 8 * len(trial.EVAL_ARMS))
                    self.assertTrue(all("strict_task_success" not in x for x in raw))
                return raw_read(path, sha)

            def fake_journal(
                reader, test_cases, originals, arms, selections, journal, *, seed
            ):
                chronological.append("start_generation")
                entries = []
                with journal.open("x") as f:
                    for case in test_cases:
                        for arm in arms:
                            row = dict(
                                question_id=case["query"]["identity"],
                                kind="new_fact",
                                arm=arm,
                                status="succeeded",
                                answer="site_11111111 [E1]",
                                selected=list(selections(case, arm)),
                                candidate_digest=case["candidate_digest"],
                                receipt=dict(
                                    input_tokens=4, generated_tokens=2, seconds=0.1
                                ),
                            )
                            f.write(json.dumps(row) + "\n")
                            f.flush()
                            entries.append(row)
                chronological.append("all_answers_durable")
                return entries

            model = object()
            inventory = dict(inventory_digest="reader")
            with (
                patch.object(trial, "read", side_effect=audited_read),
                patch.object(trial, "_reader", return_value=(model, {}, inventory)),
                patch.object(trial, "_journal_answers", side_effect=fake_journal),
                patch(
                    "event_reader_experiment.preflight",
                    return_value=(
                        dict(
                            cases=cases,
                            labels_sha=trial.file_sha(root / "inputs/labels.json"),
                            extraction={},
                            frozen=dict(costs={}),
                        ),
                        docs,
                    ),
                ),
                patch.dict("os.environ", {"HEPTA_MEMORY_TESTED_COMMIT": "b" * 40}),
            ):
                result = trial.evaluate(
                    root / "plan",
                    root / "inputs",
                    root / "model",
                    root / "calibration",
                    root / "out",
                    plan_sha=trial.HISTORIC_PLAN_SHA,
                    stage_sha="a" * 64,
                    policy_sha=policy_sha,
                )
            self.assertEqual(
                chronological,
                ["start_generation", "all_answers_durable", "opened_test_labels"],
            )
            self.assertEqual(result["total_attempts"], 56)
            self.assertFalse(result["production_accepted"])
            self.assertFalse(result["statistical_superiority"])

    def test_readonly_original_archived_frozen_source(self):
        self.assertEqual(len(trial.KS), 5)
        self.assertIn(4, trial.KS)
        self.assertNotIn("parametric", trial.EVAL_ARMS)
        self.assertNotIn("trained_policy", trial.EVAL_ARMS)
        self.assertFalse(
            trial.eval_selections(
                {
                    "candidate_ids": [f"s{i}" for i in range(6)],
                    "candidate_digest": trial.digest(tuple(f"s{i}" for i in range(6))),
                    "controls": {
                        "hybrid": dict(selected=[f"s{i}" for i in range(4)]),
                        "organized": dict(selected=["s1"]),
                        "program_support": dict(selected=["s1"]),
                        "empty": dict(selected=[]),
                    },
                },
                4,
            )["empty"]
        )


if __name__ == "__main__":
    unittest.main()
