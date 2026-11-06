"""A complete census is necessary, not sufficient, for independent acceptance."""

import copy
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from benchmark_coverage import plan_coverage
from benchmark_review import (
    _validate_delivered_source_binding,
    audit_entry,
    paired_diagnostics,
    read_json,
    review,
)
from citation_audit import sha
from native import Document, Question, digest
from native_citation import capture_native
from test_coverage import benchmark, receipts


class BenchmarkReviewTests(unittest.TestCase):
    def setUp(self):
        self.plan = plan_coverage(benchmark(), folds=5, shards=2, per_fold_limit=None)
        self.records = receipts(self.plan)
        self.binding = {"code": "pinned"}

    def write_inputs(self, root):
        plan = root / "plan.json"
        plan.write_text(
            json.dumps(
                {
                    "schema": "hepta.memory-benchmark.preregistered.v1",
                    "coverage": self.plan.content(),
                    "execution_binding": self.binding,
                }
            )
        )
        for i, record in enumerate(self.records):
            shard = root / "reports" / str(i)
            shard.mkdir(parents=True)
            (shard / "report.json").write_text(json.dumps(record))
        return plan

    def unsigned_input(self):
        row = copy.deepcopy(self.records[0]["results"]["rag"][0])
        qid, family = next(
            (q, f) for q, f, _, _ in self.plan.cases if q == row["question_id"]
        )
        query = SimpleNamespace(
            identity=qid, scope="s", content="Which code?", observed_at="2024"
        )
        row["hypothesis"] = "Blue [E1]."
        row["receipt"] = {
            "input_ids_sha256": sha(b"prompt"),
            "delivered_evidence": [
                {
                    "id": "s/doc",
                    "root": "native-root",
                    "excerpt": "[E1] Blue",
                    "label": "E1",
                }
            ],
        }
        row["citation_audit"] = capture_native(
            query,
            row["hypothesis"],
            row["receipt"],
            experiment_digest=digest((self.plan.seal(), self.binding, "rag")),
            family_digest=digest(family),
        )
        return row, family

    def test_full_census_exports_every_failed_or_unreviewable_attempt(self):
        self.records[0]["results"]["rag"][0].update(
            status="failed", hypothesis=None, diagnostic_token_f1=None
        )
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            declared = self.write_inputs(root)
            result = review(
                declared, root / "reports", root / "out", validator_commit="b" * 40
            )
            self.assertEqual(result["all_attempts_exported"], 4 * 30)
            self.assertEqual(result["citation_census"]["rag"]["execution_failed"], 1)
            self.assertEqual(result["coverage"]["arms"]["rag"]["failed"], 1)
            self.assertIsNone(result["signed_semantic_citation_precision"])
            self.assertFalse(result["production_accepted"])
            rows = [
                json.loads(line)
                for line in (root / "out/review.jsonl").read_text().splitlines()
            ]
            self.assertEqual(len({r["review_id"] for r in rows}), 120)
            self.assertTrue(
                all("arm" not in r and "diagnostic_token_f1" not in r for r in rows)
            )
            with self.assertRaises(FileExistsError):
                review(
                    declared, root / "reports", root / "out", validator_commit="b" * 40
                )
            (root / "reports/0/report.json").unlink()
            with self.assertRaises(ValueError):
                review(
                    declared,
                    root / "reports",
                    root / "missing",
                    validator_commit="b" * 40,
                )
            self.assertFalse((root / "missing").exists())

    def test_pilot_cannot_be_reviewed_as_complete(self):
        self.plan = plan_coverage(benchmark(), folds=5, shards=2, per_fold_limit=1)
        self.records = receipts(self.plan)
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            declared = self.write_inputs(root)
            with self.assertRaisesRegex(ValueError, "every native question"):
                review(
                    declared, root / "reports", root / "out", validator_commit="b" * 40
                )

    def test_bound_native_request_is_ready_for_review_not_certified(self):
        row, family = self.unsigned_input()
        item, _ = audit_entry(self.plan, self.binding, "rag", row, family)
        self.assertEqual(item["status"], "awaiting_independent_judgement")
        self.assertIsNone(item["judgement"])
        self.assertIsNone(item["generator_signature"])
        self.assertIsNone(item["semantic_precision"])

    def test_delivered_evidence_rebinds_to_pinned_native_source_bytes(self):
        question = Question("q", "family", "scope", "Which code?", "2024")
        document = Document(
            "scope/doc", "native-root", "scope", "session", "2024", "Blue code."
        )
        receipt = {
            "delivered_evidence": [
                {
                    "id": "scope/doc",
                    "root": "native-root",
                    "excerpt": "Blue code.",
                    "label": "E1",
                }
            ]
        }
        _validate_delivered_source_binding(receipt, question, (document,))
        for field, value in (
            ("id", "scope/other"),
            ("root", "wrong-root"),
            ("excerpt", "Wrong"),
        ):
            altered = copy.deepcopy(receipt)
            altered["delivered_evidence"][0][field] = value
            with self.assertRaisesRegex(ValueError, "pinned|drift"):
                _validate_delivered_source_binding(altered, question, (document,))

    def test_delivered_native_chunk_rebinds_to_normalized_projection(self):
        question = Question("q", "family", "scope", "Which code?", "2024")
        words = " ".join(f"word-{i}" for i in range(200))
        document = Document(
            "scope/doc", "native-root", "scope", "session", "2024", words
        )
        receipt = {
            "delivered_evidence": [
                {
                    "id": "scope/doc#chunk:0",
                    "root": "native-root",
                    "excerpt": " ".join(f"word-{i}" for i in range(3)),
                    "label": "E1",
                }
            ]
        }
        _validate_delivered_source_binding(receipt, question, (document,))
        altered = copy.deepcopy(receipt)
        altered["delivered_evidence"][0]["id"] = "scope/doc#chunk:1"
        with self.assertRaisesRegex(ValueError, "offset|pinned"):
            _validate_delivered_source_binding(altered, question, (document,))

    def test_answer_prompt_family_source_and_mapping_drift_reject(self):
        row, family = self.unsigned_input()
        for change in (
            lambda r: r.update(hypothesis="altered"),
            lambda r: r["receipt"].update(input_ids_sha256=sha(b"wrong")),
            lambda r: r["receipt"]["delivered_evidence"][0].update(excerpt="altered"),
            lambda r: r["citation_audit"]["request"].update(
                family_digest=sha(b"wrong")
            ),
            lambda r: r["citation_audit"]["source_root_bindings"].clear(),
            lambda r: r["citation_audit"].update(generator_signature="forged"),
        ):
            changed = copy.deepcopy(row)
            change(changed)
            with self.assertRaises(ValueError):
                audit_entry(self.plan, self.binding, "rag", changed, family)

    def test_old_receipt_is_not_retroactively_signed_or_given_new_request(self):
        row, family = self.unsigned_input()
        row["citation_audit"] = {"status": "unavailable"}
        item, _ = audit_entry(self.plan, self.binding, "rag", row, family)
        self.assertEqual(item["status"], "unavailable")
        self.assertEqual(
            item["delivered_evidence"], row["receipt"]["delivered_evidence"]
        )
        self.assertNotIn("request", item)
        self.assertIsNone(item["generator_signature"])

    def test_missing_scores_expand_uncertainty_not_success_denominator(self):
        for report in self.records:
            for r in report["results"]["rag_lora"]:
                r["diagnostic_token_f1"] = None
        stats = paired_diagnostics(self.plan, self.records)
        comparison = next(
            c for c in stats["comparisons"] if c["candidate"] == "rag_lora"
        )
        self.assertEqual(comparison["identified_family_mean_difference"], [-0.5, 0.5])
        self.assertEqual(comparison["unmeasured_pairs"], 30)
        self.assertEqual(comparison["family_groups"], 10)
        self.assertFalse(stats["statistical_superiority_established"])

    def test_repeated_questions_in_a_family_do_not_increase_independent_n(self):
        stats = paired_diagnostics(self.plan, self.records)
        self.assertEqual({c["family_groups"] for c in stats["comparisons"]}, {10})
        self.assertEqual({c["paired_questions"] for c in stats["comparisons"]}, {30})
        self.assertFalse(stats["independence_verified"])

    def test_duplicate_json_nan_unbounded_and_symlink_inputs_reject(self):
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            p = root / "input.json"
            for text in ('{"key": 1, "key": 2}', '{"n": NaN}', " " * 50):
                p.write_text(text)
                with self.assertRaises(ValueError):
                    read_json(p, 40)
            p.write_text("{}")
            link = root / "alias.json"
            link.symlink_to(p)
            with self.assertRaises(ValueError):
                read_json(link, 40)
