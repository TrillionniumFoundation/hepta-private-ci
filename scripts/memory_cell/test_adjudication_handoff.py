"""Test transfer integrity, not model quality or independent acceptance."""

import copy
import json
import tempfile
import unittest
from pathlib import Path

from adjudication_handoff import export, lines
from benchmark_coverage import ARMS, CoveragePlan
from benchmark_review import audit_entry
from citation_audit import request_payload, sha
from native import Question, digest
from native_citation import capture_native


class HandoffTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.review = self.root / "review"
        self.review.mkdir()
        self.plan = CoveragePlan(
            "longmemeval",
            sha(b"fixture corpus"),
            2,
            1,
            1,
            None,
            (
                ("longmemeval:q1", "family", 0, 0),
                ("longmemeval:q2_abs", "family", 0, 0),
            ),
        )
        self.binding = dict(source_commit="a" * 40)
        self.declared = dict(
            schema="hepta.memory-benchmark.preregistered.v1",
            coverage=self.plan.content(),
            execution_binding=self.binding,
        )
        self.plan_path = self.root / "plan.json"
        self.plan_path.write_text(json.dumps(self.declared))
        self.plan_hash = sha(self.plan_path.read_bytes())
        self.work, self.index = [], []
        for qid, family, _, _ in self.plan.cases:
            query = Question(qid, family, qid, "Which color?", "2024-01-01")
            for arm in ARMS:
                answer = "蓝色 [E1]." if arm == "no_memory" else "蓝色."
                receipt = dict(
                    input_ids_sha256=sha(b"fixture prompt"), delivered_evidence=[]
                )
                queue = capture_native(
                    query,
                    answer,
                    receipt,
                    experiment_digest=digest((self.plan.seal(), self.binding, arm)),
                    family_digest=digest(family),
                )
                item, index = audit_entry(
                    self.plan,
                    self.binding,
                    arm,
                    dict(
                        question_id=qid,
                        status="succeeded",
                        hypothesis=answer,
                        citation_audit=queue,
                        receipt=receipt,
                    ),
                    family,
                    query,
                )
                self.work.append(item)
                self.index.append(index)
        self.summary = dict(
            schema="hepta.memory-benchmark.review-result.v1",
            plan_file_sha256=self.plan_hash,
            execution_source_commit="a" * 40,
            all_attempts_exported=8,
            coverage=dict(
                execution_binding=self.binding,
                coverage_digest=self.plan.seal(),
                complete=True,
                all_native_questions_covered=True,
                native_cases=2,
                arms={a: dict(planned=2, succeeded=2, failed=0) for a in ARMS},
            ),
        )

    def seal(self):
        (self.review / "summary.json").write_text(json.dumps(self.summary))
        for name, rows in (
            ("review.jsonl", self.work),
            ("review-index.jsonl", self.index),
        ):
            (self.review / name).write_text(
                "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows)
            )
        manifest = "".join(
            sha((self.review / name).read_bytes()) + "  " + name + "\n"
            for name in ("review-index.jsonl", "review.jsonl", "summary.json")
        )
        (self.review / "SHA256SUMS").write_text(manifest)
        return sha(manifest.encode())

    def run_export(self, manifest=None, output=None, exporter_commit=None):
        return export(
            self.plan_path,
            self.review,
            output or self.root / "out",
            expected_plan_sha256=self.plan_hash,
            expected_manifest_sha256=manifest or self.seal(),
            exporter_commit=exporter_commit or self.binding["source_commit"],
        )

    def test_historical_execution_source_cannot_be_relabelled_as_current_head(self):
        with self.assertRaisesRegex(ValueError, "execution source commit"):
            self.run_export(exporter_commit="b" * 40)

    def test_complete_transfer_preserves_hypotheses_and_undefined_precision(self):
        result = self.run_export()
        self.assertEqual(result["all_attempts_exported"], 8)
        self.assertFalse(result["production_accepted"])
        self.assertFalse(result["official_judge_executed"])
        for arm in ARMS:
            stats = result["citation_structure"][arm]
            self.assertIsNone(stats["semantic_precision"])
            self.assertEqual(
                stats["structural_precision_ceiling_ppm"],
                0 if arm == "no_memory" else None,
            )
            rows = lines(
                (self.root / "out/official-qa-inputs" / (arm + ".jsonl")).read_bytes()
            )
            self.assertEqual([r["question_id"] for r in rows], ["q1", "q2_abs"])
            self.assertEqual(
                [r["hypothesis"] for r in rows],
                [r["answer"] for r, i in zip(self.work, self.index) if i["arm"] == arm],
            )
        for item in self.work:
            self.assertEqual(
                (
                    self.root / "out/requests" / (item["review_id"] + ".bin")
                ).read_bytes(),
                request_payload(item["request"]),
            )
        self.assertEqual(
            (self.root / "out/citation-review.jsonl").read_bytes(),
            (self.review / "review.jsonl").read_bytes(),
        )
        ready = json.loads((self.root / "out/READY.json").read_text())
        for name, hashed in ready["files"].items():
            self.assertEqual(sha((self.root / "out" / name).read_bytes()), hashed)
        with self.assertRaises(FileExistsError):
            self.run_export()

    def test_semantic_binding_drift_rejects_even_after_resealing_transport(self):
        for field, value in (
            ("answer", "substituted"),
            ("question", "wrong"),
            ("question_time", "2028"),
            ("original_prompt_sha256", sha(b"wrong")),
            ("generator_signature", "invented"),
            ("evaluator_signature", "invented"),
            ("semantic_precision", 1),
            ("production_accepted", True),
            ("status", "execution_failed"),
        ):
            with self.subTest(field=field):
                old = copy.deepcopy(self.work[0])
                self.work[0][field] = value
                with self.assertRaises(ValueError):
                    self.run_export()
                self.assertFalse((self.root / "out").exists())
                self.work[0] = old

    def test_missing_duplicate_and_wrong_family_are_not_a_smaller_census(self):
        original_work, original_index = (
            copy.deepcopy(self.work),
            copy.deepcopy(self.index),
        )
        for change in (
            lambda: self.work.pop(),
            lambda: self.work.append(self.work[0]),
            lambda: self.index[0].update(family="renamed"),
            lambda: self.index[0].update(question_id="longmemeval:invented"),
            lambda: self.index.__setitem__(0, self.index[1]),
        ):
            change()
            with self.assertRaises(ValueError):
                self.run_export()
            self.work, self.index = (
                copy.deepcopy(original_work),
                copy.deepcopy(original_index),
            )

    def test_no_missing_failure_or_false_integer_success_count(self):
        for field, value in (("failed", 1), ("succeeded", 1), ("failed", False)):
            old = self.summary["coverage"]["arms"]["rag"][field]
            self.summary["coverage"]["arms"]["rag"][field] = value
            with self.assertRaises(ValueError):
                self.run_export()
            self.summary["coverage"]["arms"]["rag"][field] = old

    def test_pins_and_original_source_must_match(self):
        manifest = self.seal()
        with self.assertRaises(ValueError):
            self.run_export("0" * 64)
        self.plan_hash = "0" * 64
        with self.assertRaises(ValueError):
            self.run_export(manifest)
        self.plan_hash = sha(self.plan_path.read_bytes())
        self.summary["execution_source_commit"] = "c" * 40
        with self.assertRaises(ValueError):
            self.run_export()

    def test_changed_delivered_source_is_not_posthoc_evidence(self):
        self.work[0]["delivered_evidence"] = [
            dict(id="invented", root="native", label="E1", excerpt="blue")
        ]
        with self.assertRaises(ValueError):
            self.run_export()

    def test_duplicate_json_nonfinite_and_symlink_rejected(self):
        for raw in (b'{"a":1,"a":2}\n', b'{"a":NaN}\n', b"null\n"):
            with self.assertRaises(ValueError):
                lines(raw)
        manifest = self.seal()
        p = self.review / "review.jsonl"
        p.rename(self.root / "redirected")
        p.symlink_to(self.root / "redirected")
        with self.assertRaises(ValueError):
            self.run_export(manifest)

    def test_pilot_cannot_be_exported_as_complete(self):
        self.declared["coverage"]["per_fold_limit"] = 1
        self.plan_path.write_text(json.dumps(self.declared))
        self.plan_hash = sha(self.plan_path.read_bytes())
        with self.assertRaises(ValueError):
            self.run_export()


if __name__ == "__main__":
    unittest.main()
