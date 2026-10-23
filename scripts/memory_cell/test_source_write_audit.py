"""Disk/worker integration with authored answers, never pretrained evidence."""

from copy import deepcopy
from dataclasses import asdict, replace
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from event_experience import call_worker, question
from event_projection import EventProjection
from evidence_bundle import EvidenceBundle, EvidenceSpan
from experience_policy import INITIAL, choose, fit_policy, lookup_from_question
from native import digest
from native_citation import capture_native
from source_write_effects import ARMS, audit, procedure_equal
from test_experience_policy import sources


class SourceWriteAuditTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        rows = []
        for doc in sources("procedure"):
            value = json.loads(doc.content)
            if value["attribute"] == "location":
                value["attribute"] = "successful_mode"
                value["value"] = (
                    value["value"]
                    .replace("site_new", "mode_11112222")
                    .replace("site_", "mode_")
                )
            rows.append(replace(doc, content=json.dumps(value)))
        cls.documents = sources("calibration") + tuple(rows)
        cls.identity = digest("fixture-reader-not-a-model")
        cls.policy = fit_policy(
            cls.documents,
            ["calibration"],
            revision=2,
            reader_identity=cls.identity,
            revoked=set(),
        )

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        for name in ("plan", "inputs", "result/snapshot", "result/tasks"):
            (self.root / name).mkdir(parents=True)
        q, lookup = question(
            dict(
                id="procedure",
                entity="service",
                path=["component", "successful_mode"],
                revision=2,
            ),
            "2026-10-11T00:00:00+00:00",
        )
        self.query = q
        original = {d.identity: d for d in self.documents if d.scope == q.scope}
        projection = EventProjection(tuple(original.values()))
        pool = tuple(projection.facts)
        selected, _ = choose(
            projection, lookup, pool, self.policy["weights"], revoked=set()
        )
        controls = {
            "organized": {"selected": list(selected)},
            "hybrid": {"selected": [pool[0]]},
            "empty": {"selected": []},
        }
        recipe = dict(values=[2, 1], modes={"mode_11112222": "sort"}, target=[1, 2])
        labels = [
            dict(
                id=q.identity,
                kind="procedure",
                expected="mode_11112222",
                procedure=recipe,
            )
        ]
        label_sha = self.write("inputs/labels.json", labels)
        source_sha = self.write(
            "inputs/sources.json", [asdict(d) for d in self.documents]
        )
        case = dict(
            query=asdict(q),
            kind="procedure",
            candidate_digest=digest(pool),
            candidate_ids=list(pool),
            controls=controls,
        )
        self.plan_sha = self.write(
            "plan/plan.json", dict(cases=[case], labels_sha=label_sha)
        )
        self.ready_sha = self.write(
            "result/snapshot/READY.json",
            dict(
                schema="hepta.source-knowledge.snapshot.v1",
                writer_source="a" * 40,
                source_sha=source_sha,
                source_documents_digest=digest([asdict(d) for d in self.documents]),
                base_identity=self.identity,
                task_payload_consumed=False,
                production_accepted=False,
            ),
        )
        self.write(
            "result/tasks/execution.json",
            dict(
                source_commit="a" * 40,
                writer_source="a" * 40,
                ready_sha=self.ready_sha,
                plan_sha=self.plan_sha,
                snapshot_loaded_before_task_payload=True,
                learned_policy_training=self.policy,
            ),
        )
        raw, scored = [], []
        for arm in ARMS:
            condition = {"knowledge": "organized", "parameter_only": "empty"}.get(
                arm, arm
            )
            if condition in controls:
                ids = controls[condition]["selected"]
            else:
                weights = INITIAL if arm == "policy_initial" else self.policy["weights"]
                ids = list(
                    choose(
                        projection,
                        lookup_from_question(q),
                        pool,
                        weights,
                        revoked=set(),
                    )[0]
                )
            spans = tuple(
                EvidenceSpan(
                    d.identity,
                    d.root,
                    d.scope,
                    d.session,
                    d.observed_at,
                    0,
                    len(d.content.encode()),
                    d.content,
                    digest(d.content),
                )
                for d in (original[k] for k in ids)
            )
            bundle = EvidenceBundle(digest(asdict(q)), "frontier", spans, arm)
            delivered = bundle.delivered()
            receipt = dict(
                reader_identity=self.identity,
                reader_profile=digest("fixture-profile"),
                input_ids_digest=digest(ids),
                input_tokens=10,
                generated_tokens=2,
                seconds=0.1,
                knowledge_module_enabled=arm in ("knowledge", "parameter_only"),
                delivered_evidence=delivered,
                derived_evidence=[],
            )
            answer = "mode_11112222"
            queue = capture_native(
                q,
                answer,
                dict(input_ids_sha256=digest(ids), delivered_evidence=delivered),
                experiment_digest=digest((self.ready_sha, self.plan_sha, arm)),
                family_digest=digest(q.family),
            )
            row = dict(
                question_id=q.identity,
                kind="procedure",
                arm=arm,
                candidate_digest=digest(pool),
                selected=ids,
                answer=answer,
                status="succeeded",
                receipt=receipt,
                citation_audit=queue,
            )
            raw.append(row)
            item = deepcopy(row)
            item.update(
                parsed_identifier="mode_11112222",
                strict_task_success=True,
                procedure_verification=call_worker(
                    dict(operation="execute", recipe=recipe, supplied="mode_11112222")
                ),
            )
            scored.append(item)
        self.raw, self.scored = raw, scored
        (self.root / "result/tasks/raw-answers.jsonl").write_text(
            "".join(json.dumps(row) + "\n" for row in raw)
        )
        self.write("result/tasks/scored-answers.json", scored)

    def write(self, name, obj):
        value = json.dumps(obj, allow_nan=False).encode()
        (self.root / name).write_bytes(value)
        return hashlib.sha256(value).hexdigest()

    def run_audit(self):
        return audit(
            self.root / "plan",
            self.root / "inputs",
            self.root / "result",
            plan_sha=self.plan_sha,
            ready_sha=self.ready_sha,
            source_commit="a" * 40,
        )

    def test_complete_disk_consumer_replays_actual_worker_not_model(self):
        result = self.run_audit()
        self.assertEqual(result["original_answer_executions"], 7)
        self.assertEqual(result["repeated_procedure_checks"], 7)
        self.assertEqual(result["new_model_calls"], 0)
        self.assertFalse(result["production_accepted"])
        self.assertTrue((self.root / "result/tasks/source-effects.json").is_file())

    def test_outcome_drift_is_rejected_before_receipt_publication(self):
        self.scored[0]["procedure_verification"]["exit_code"] = 2
        self.write("result/tasks/scored-answers.json", self.scored)
        with self.assertRaises(ValueError):
            self.run_audit()
        self.assertFalse((self.root / "result/tasks/source-effects.json").exists())

    def test_citation_drift_rejects_even_when_copied_to_both_journals(self):
        self.raw[0]["citation_audit"]["request_sha256"] = "0" * 64
        self.scored[0]["citation_audit"] = deepcopy(self.raw[0]["citation_audit"])
        (self.root / "result/tasks/raw-answers.jsonl").write_text(
            "".join(json.dumps(row) + "\n" for row in self.raw)
        )
        self.write("result/tasks/scored-answers.json", self.scored)
        with self.assertRaises(ValueError):
            self.run_audit()

    def test_replay_clock_is_distinct_but_request_and_result_are_exact(self):
        original = self.scored[0]["procedure_verification"]
        repeated = original | {
            "seconds": 0.2,
            "observed_at": "2027-01-01T00:00:00+00:00",
        }
        self.assertTrue(procedure_equal(original, repeated))
        self.assertFalse(procedure_equal(original, repeated | {"stdout": "changed"}))
        with self.assertRaises(ValueError):
            procedure_equal(original, repeated | {"seconds": float("nan")})


if __name__ == "__main__":
    unittest.main()
