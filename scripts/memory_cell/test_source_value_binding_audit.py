"""Source value diagnostics use authored fixtures, never model success claims."""

import json
from pathlib import Path
import tempfile
import unittest

from source_value_binding_audit import audit, inspect, parse, sha


def fixture():
    def q(qid, scope):
        return dict(
            identity=qid,
            scope=scope,
            family=scope,
            content="source fact?",
            observed_at="2026-10-10T00:00:00+00:00",
        )

    q0, q1, q2 = q("q0", "scope-a"), q("q1", "scope-a"), q("q2", "scope-b")
    ready = dict(
        schema="hepta.source-knowledge.snapshot.v1",
        writer_source="a" * 40,
        base_identity="reader",
        reader_profile="profile",
        task_payload_consumed=False,
        production_accepted=False,
        training=dict(
            schedule_sha256="schedule-digest",
            write_schedule=dict(visits_per_example=[2, 0, 0]),
            source_supervision=[
                dict(query=q0, target="site_aaaaaaaa"),
                dict(query=q1, target="site_bbbbbbbb"),
                dict(query=q2, target="mode_cccccccc"),
            ],
        ),
    )
    plan = dict(
        schema="hepta.source-recall.probe-plan.v1",
        writer_source="a" * 40,
        probe_source="b" * 40,
        reader_identity="reader",
        reader_profile="profile",
        snapshot_sha256="a" * 64,
        question_mode="training",
        in_sample_training_recall=True,
        training_exposure_verified=True,
        training_schedule_sha256="schedule-digest",
        source_questions=[q0],
        source_training_question_ids=["q0"],
        source_example_optimizer_visits=[2],
    )
    raw = [
        dict(
            question_id="q0",
            arm=arm,
            scope="scope-a",
            status="succeeded",
            answer="I do not have enough evidence."
            if arm == "base"
            else "site_33333333",
            source_training_question_id="q0",
            source_example_optimizer_visits=2,
            result_is_in_sample_training_recall=True,
            delivered_evidence=[],
        )
        for arm in ("base", "memory")
    ]
    report = dict(
        schema="hepta.source-recall.diagnostic.v1",
        writer_source="a" * 40,
        generating_commit="b" * 40,
        model_calls=2,
        snapshot_sha256="a" * 64,
        training_exposure_verified=True,
        training_schedule_sha256="schedule-digest",
        arms={arm: dict(exact_targets=0, failed=0) for arm in ("base", "memory")},
    )
    return ready, plan, raw, report


class SourceValueBindingTests(unittest.TestCase):
    def test_formatted_gibberish_is_not_memory(self):
        ready, plan, raw, report = fixture()
        result = audit(ready, plan, raw, report)
        self.assertEqual(result["arms"]["base"]["counts"], {"explicit_refusal": 1})
        self.assertEqual(
            result["arms"]["memory"]["counts"],
            {
                "fabricated_identifier_not_in_any_source_target": 1,
            },
        )
        self.assertFalse(result["production_accepted"])
        self.assertIsNone(result["semantic_citation_precision"])

    def test_known_wrong_relation_and_cross_scope_are_separate(self):
        for value, expected in (
            ("site_bbbbbbbb", "wrong_value_from_same_scope"),
            ("mode_cccccccc", "cross_scope_source_value"),
        ):
            ready, plan, raw, report = fixture()
            raw[1]["answer"] = value
            with self.subTest(value=value):
                result = audit(ready, plan, raw, report)
                self.assertEqual(result["arms"]["memory"]["counts"], {expected: 1})

    def test_exact_target_requires_actual_original_match_and_score_agreement(self):
        ready, plan, raw, report = fixture()
        raw[1]["answer"] = "site_aaaaaaaa"
        with self.assertRaises(ValueError):
            audit(ready, plan, raw, report)
        report["arms"]["memory"]["exact_targets"] = 1
        result = audit(ready, plan, raw, report)
        self.assertEqual(
            result["arms"]["memory"]["counts"],
            {
                "exact_source_target": 1,
            },
        )

    def test_citation_cannot_be_invented_for_empty_context(self):
        ready, plan, raw, report = fixture()
        raw[1]["answer"] += " [E1]"
        self.assertEqual(
            audit(ready, plan, raw, report)["arms"]["memory"]["counts"],
            {
                "unbacked_citation_in_empty_context": 1,
            },
        )

    def test_failures_are_not_deleted_or_turned_into_refusals(self):
        ready, plan, raw, report = fixture()
        raw[1].pop("answer")
        raw[1]["status"] = "failed"
        report["arms"]["memory"]["failed"] = 1
        self.assertEqual(
            audit(ready, plan, raw, report)["arms"]["memory"]["counts"],
            {
                "execution_failed": 1,
            },
        )
        report["arms"]["memory"]["failed"] = 0
        with self.assertRaises(ValueError):
            audit(ready, plan, raw, report)

    def test_identity_candidate_pools_and_numerators_reject_mutations(self):
        changes = (
            ("row", "question_id", "different"),
            ("row", "scope", "other"),
            ("row", "delivered_evidence", ["unreviewed"]),
            ("row", "source_training_question_id", "q1"),
            ("row", "result_is_in_sample_training_recall", False),
            ("row", "source_example_optimizer_visits", 999),
            ("plan", "probe_source", "c" * 40),
            ("ready", "base_identity", "another-reader"),
            ("report", "model_calls", 3),
        )
        for table, key, value in changes:
            ready, plan, raw, report = fixture()
            dest = {
                "row": raw[0],
                "plan": plan,
                "ready": ready,
                "report": report,
            }[table]
            dest[key] = value
            with self.subTest(table=table, key=key), self.assertRaises(ValueError):
                audit(ready, plan, raw, report)

    def test_duplicates_and_missing_original_answers_reject(self):
        ready, plan, raw, report = fixture()
        for records in (raw[:1], [raw[0], raw[0]], raw + [raw[1]]):
            with self.assertRaises(ValueError):
                audit(ready, plan, records, report)

    def test_original_bytes_hash_and_overwrite_are_strict(self):
        ready, plan, raw, report = fixture()
        with tempfile.TemporaryDirectory() as root:
            base = Path(root)
            for name, record in (
                ("snapshot/READY.json", ready),
                ("source-recall/plan.json", plan),
                ("source-recall/report.json", report),
            ):
                path = base / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(json.dumps(record))
            original_path = base / "source-recall/raw-answers.jsonl"
            original_path.write_text("".join(json.dumps(r) + "\n" for r in raw))
            plan["snapshot_sha256"] = sha((base / "snapshot/READY.json").read_bytes())
            (base / "source-recall/plan.json").write_text(json.dumps(plan))
            report["plan_sha256"] = sha((base / "source-recall/plan.json").read_bytes())
            report["snapshot_sha256"] = plan["snapshot_sha256"]
            report["raw_sha256"] = sha(original_path.read_bytes())
            (base / "source-recall/report.json").write_text(json.dumps(report))
            output = base / "binding.json"
            result = inspect(base, output, auditor_commit="c" * 40)
            self.assertEqual(
                result["arms"]["memory"]["counts"],
                {
                    "fabricated_identifier_not_in_any_source_target": 1,
                },
            )
            with self.assertRaises(ValueError):
                inspect(base, output, auditor_commit="c" * 40)
            original_path.write_text(
                original_path.read_text().replace("site_33333333", "site_44444444")
            )
            with self.assertRaises(ValueError):
                inspect(base, base / "changed.json", auditor_commit="c" * 40)

    def test_malformed_json_is_not_forgiven(self):
        for raw in (b'{"x":1,"x":2}', b'{"x":NaN}', b'{"x":Infinity}'):
            with self.assertRaises(ValueError):
                parse(raw)


if __name__ == "__main__":
    unittest.main()
