"""Sealed real-reader RAG design tests; fixtures never substitute for model evidence."""

from copy import deepcopy
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from types import ModuleType
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
    def test_reference_reader_sets_two_cpu_threads_before_loading(self):
        calls = []
        fake_torch = ModuleType("torch")
        fake_torch.set_num_threads = lambda n: calls.append(("threads", n))
        fake_torch.get_num_threads = lambda: 2
        fake_torch.get_num_interop_threads = lambda: 4

        def manifest(path, _expected):
            if path.name == "stage.json":
                return {"tier": "qwen-3b", "inventory_sha256": "inventory"}
            return {"inventory_digest": "pinned-reader"}

        def construct(_path, *, expected_inventory):
            calls.append(("model", expected_inventory))
            return object()

        with (
            patch.dict("sys.modules", {"torch": fake_torch}),
            patch.object(trial, "read", side_effect=manifest),
            patch(
                "event_reader_view.EventPresentationReader",
                side_effect=construct,
            ),
        ):
            reader, staged, inventory = trial._reader(Path("/model"), "stage")
        self.assertIsNotNone(reader)
        self.assertEqual(staged["tier"], "qwen-3b")
        self.assertEqual(inventory["inventory_digest"], "pinned-reader")
        self.assertEqual(
            calls,
            [("threads", 2), ("model", "pinned-reader")],
        )

    def test_top_k_does_not_consult_oracle_or_test_labels(self):
        case = dict(
            candidate_ids=[f"s{i}" for i in range(7)],
            candidate_digest=trial.digest(tuple(f"s{i}" for i in range(7))),
            controls={
                "hybrid": dict(selected=[f"s{i}" for i in range(4)]),
                "single_hop": dict(selected=["s3"]),
                "entity_time": dict(selected=["s3"]),
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
        self.assertEqual(baseline["entity_time"], ("s3",))
        self.assertEqual(baseline["single_hop"], ("s3",))
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

    def test_unviable_reader_speed_gate_keeps_execution_unqualified(self):
        trial.fail_if_unviable_reader(
            {"status": "succeeded", "receipt": {"seconds": 180.0}}
        )
        trial.fail_if_unviable_reader({"status": "failed"})
        for invalid in (True, -1, float("nan"), float("inf")):
            with self.subTest(invalid=invalid):
                with self.assertRaises(ValueError):
                    trial.fail_if_unviable_reader(
                        {"status": "succeeded", "receipt": {"seconds": invalid}}
                    )
        with self.assertRaisesRegex(RuntimeError, "slow frozen reader"):
            trial.fail_if_unviable_reader(
                {"status": "succeeded", "receipt": {"seconds": 180.01}}
            )

    def test_slow_reader_call_is_durable_before_resource_abort(self):
        from native import Question

        class SlowReader:
            def answer(self, *_args, **_kwargs):
                return "site_11111111 [E1]", {
                    "seconds": 181.0,
                    "input_ids_digest": "a" * 64,
                    "delivered_evidence": [],
                }

        query = Question("q1", "family", "scope", "Which site?", "2026-01-01T00:00:00Z")
        case = dict(
            query=asdict(query),
            kind="new_fact",
            candidate_digest="frozen",
            frontier="frontier",
        )
        with tempfile.TemporaryDirectory() as tmp:
            journal = Path(tmp) / "raw-answers.jsonl"
            with (
                patch.object(trial, "_bundle", return_value=object()),
                patch("native_citation.capture_native", return_value={}),
            ):
                with self.assertRaisesRegex(RuntimeError, "journal retained"):
                    trial._journal_answers(
                        SlowReader(),
                        [case],
                        {},
                        ("k1",),
                        lambda _case, _arm: (),
                        journal,
                        seed="fixed",
                    )
            raw = [json.loads(line) for line in journal.read_text().splitlines()]
            self.assertEqual(len(raw), 1)
            self.assertEqual(raw[0]["status"], "succeeded")
            self.assertEqual(raw[0]["receipt"]["seconds"], 181.0)
            self.assertNotIn("strict_task_success", raw[0])

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
                            single_hop=dict(selected=[candidates[0]]),
                            entity_time=dict(selected=[candidates[0]]),
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
            trial.dump(
                root / "inputs/questions.json",
                [dict(id=qid, kind="new_fact") for qid in qids],
            )
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
                                    input_tokens=4,
                                    generated_tokens=2,
                                    seconds=0.1,
                                    reader_identity="reader",
                                    reader_profile="profile",
                                    token_limit=2048,
                                    input_ids_digest="same-input",
                                    generated_ids_digest="same-output",
                                    delivered_evidence=[],
                                ),
                            )
                            f.write(json.dumps(row) + "\n")
                            f.flush()
                            entries.append(row)
                chronological.append("all_answers_durable")
                return entries

            def frozen_mock_hop(locked_cases, _inputs, _originals):
                enriched = deepcopy(locked_cases)
                for item in enriched:
                    item["controls"]["single_hop"] = dict(
                        selected=item["controls"]["entity_time"]["selected"]
                    )
                return enriched, dict(schema="fixture-single-hop", qualified=False)

            def fake_formal(rows, specs, labels, documents, *, expected_qids, arms):
                chronological.append("citation_audit_after_labels")
                self.assertEqual(len(rows), 8 * len(arms))
                self.assertEqual(len(labels), 8)
                self.assertEqual(len(expected_qids), 8)
                return dict(schema="test-fixture-citation", production_accepted=False)

            model = object()
            inventory = dict(inventory_digest="reader")
            with (
                # This fixture exercises label-read ordering with a fake
                # Reader, not the real pinned model. Preserve production
                # torch runtime capture, but avoid requiring the heavyweight
                # model dependency in the isolated source-only CI job.
                patch.dict("sys.modules", {"torch": ModuleType("torch")}),
                patch(
                    "runtime_preflight.capture_runtime",
                    return_value={"schema": "synthetic-host-fixture-only"},
                ),
                patch.object(trial, "read", side_effect=audited_read),
                patch.object(trial, "_reader", return_value=(model, {}, inventory)),
                patch.object(trial, "freeze_single_hop", side_effect=frozen_mock_hop),
                patch.object(trial, "_journal_answers", side_effect=fake_journal),
                patch(
                    "event_reader_experiment.preflight",
                    return_value=(
                        dict(
                            cases=cases,
                            labels_sha=trial.file_sha(root / "inputs/labels.json"),
                            extraction={
                                "files": {
                                    "questions.json": trial.file_sha(
                                        root / "inputs/questions.json"
                                    ),
                                },
                            },
                            frozen=dict(costs={}),
                        ),
                        docs,
                    ),
                ),
                patch(
                    "historical_event_citation_chain.audit_evaluation",
                    side_effect=fake_formal,
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
                [
                    "start_generation",
                    "all_answers_durable",
                    "opened_test_labels",
                    "citation_audit_after_labels",
                ],
            )
            preflight_path = root / "out/runtime-preflight.json"
            runtime_receipt = trial.read(preflight_path, trial.file_sha(preflight_path))
            self.assertEqual(runtime_receipt["schema"], "synthetic-host-fixture-only")
            self.assertEqual(result["total_attempts"], 72)
            self.assertEqual(
                result["formal_citation_chain"]["schema"], "test-fixture-citation"
            )
            self.assertIn("entity_time_minus_single_hop", result["paired_contrasts"])
            self.assertIn("single_hop_minus_hybrid4", result["paired_contrasts"])
            self.assertIn("entity_time_minus_hybrid4", result["paired_contrasts"])
            self.assertIn("organized_minus_entity_time", result["paired_contrasts"])
            self.assertFalse(result["production_accepted"])
            self.assertFalse(result["statistical_superiority"])

            # A bad literal citation must fail the research receipt, but it
            # cannot erase the original, already-generated task scores.
            with (
                # These synthetic Reader tests must not require a real torch
                # installation just to check chronology and source isolation.
                patch.dict("sys.modules", {"torch": ModuleType("torch")}),
                patch(
                    "runtime_preflight.capture_runtime",
                    return_value={"schema": "synthetic-host-fixture-only"},
                ),
                patch.object(trial, "read", side_effect=raw_read),
                patch.object(trial, "_reader", return_value=(model, {}, inventory)),
                patch.object(trial, "freeze_single_hop", side_effect=frozen_mock_hop),
                patch.object(trial, "_journal_answers", side_effect=fake_journal),
                patch(
                    "event_reader_experiment.preflight",
                    return_value=(
                        dict(
                            cases=cases,
                            labels_sha=trial.file_sha(root / "inputs/labels.json"),
                            extraction={
                                "files": {
                                    "questions.json": trial.file_sha(
                                        root / "inputs/questions.json"
                                    ),
                                },
                            },
                            frozen=dict(costs={}),
                        ),
                        docs,
                    ),
                ),
                patch(
                    "historical_event_citation_chain.audit_evaluation",
                    side_effect=ValueError("forced citation-integrity rejection"),
                ),
                patch.dict("os.environ", {"HEPTA_MEMORY_TESTED_COMMIT": "b" * 40}),
            ):
                with self.assertRaisesRegex(ValueError, "citation-integrity rejection"):
                    trial.evaluate(
                        root / "plan",
                        root / "inputs",
                        root / "model",
                        root / "calibration",
                        root / "rejected",
                        plan_sha=trial.HISTORIC_PLAN_SHA,
                        stage_sha="a" * 64,
                        policy_sha=policy_sha,
                    )
            persisted = json.loads((root / "rejected/scored-answers.json").read_text())
            self.assertEqual(len(persisted), 8 * len(trial.EVAL_ARMS))
            self.assertTrue(all(row["strict_task_success"] for row in persisted))
            self.assertFalse((root / "rejected/report.json").exists())

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
                        "single_hop": dict(selected=["s1"]),
                        "entity_time": dict(selected=["s1"]),
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
