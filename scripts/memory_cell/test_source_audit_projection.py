"""Data identity and blinding tests; no test fixture is an independent review."""

import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from native import digest
from prepare_source_audit import prepare
from test_reviewed_bundle import fixture


class SourceAuditTests(unittest.TestCase):
    def source(self, root):
        plan, package = fixture()
        plan["cases"][0]["phase"] = "capability"
        plan["frozen_counts"] = {"capability": 1}
        q = plan["cases"][0]["question"]
        labels = {
            "q": dict(
                answer="March",
                unanswerable=False,
                publication_review={"raw_sha256": "a" * 64},
            )
        }
        root.mkdir()
        (root / "plan.json").write_text(json.dumps(plan))
        (root / "labels.json").write_text(json.dumps(labels))
        review = package["reviews"]["q"]
        audit = dict(
            schema="hepta.source-audit.model-assistance.v1",
            source_plan_sha256=hashlib.sha256(
                (root / "plan.json").read_bytes()
            ).hexdigest(),
            source_labels_sha256=hashlib.sha256(
                (root / "labels.json").read_bytes()
            ).hexdigest(),
            source_plan_digest=digest(plan),
            scope={"original_census": 1},
            reviewer=dict(
                kind="model_assisted_review",
                human=False,
                authenticated_external_identity=False,
                independent_of_implementation_author=False,
                id="fixture-not-a-reviewer",
                reviewed_at="2024-07-01",
            ),
            items=[
                dict(
                    question_id="q",
                    query_digest=digest(q),
                    source_frontier=plan["cases"][0]["frontier"],
                    publication_row_sha256="a" * 64,
                    decision="provisional_support",
                    rationale="fixture",
                    limits="not semantic review",
                    independent_human_disposition=None,
                    reviewed_spans=review["spans"],
                )
            ],
            independent_sufficiency_certified=False,
            training_permitted=False,
            production_accepted=False,
        )
        return audit

    def run_case(self, base, audit):
        file = base / "audit.json"
        file.write_text(json.dumps(audit))
        return prepare(
            base / "source",
            file,
            hashlib.sha256(file.read_bytes()).hexdigest(),
            base / "out",
        )

    def test_complete_blind_queue_and_reference_bytes_preserved(self):
        with tempfile.TemporaryDirectory() as d:
            base = Path(d)
            audit = self.source(base / "source")
            result = self.run_case(base, audit)
            self.assertEqual(result["labels.json"], audit["source_labels_sha256"])
            queue = json.loads((base / "out/independent-review-inputs.json").read_text())
            self.assertEqual(queue["pending"], 1)
            self.assertEqual(queue["completed"], 0)
            self.assertNotIn("decision", queue["cases"][0])
            self.assertNotIn("answer", queue["cases"][0])
            self.assertIsNone(queue["cases"][0]["judgement"])
            projection = json.loads((base / "out/reviews.json").read_text())
            self.assertEqual(
                projection["reviews"]["q"]["review_basis"], "model_assisted_review"
            )
            plan = json.loads((base / "out/plan.json").read_text())
            self.assertIn("retrieved1", plan["cases"][0]["conditions"])
            self.assertIn("retrieved2", plan["cases"][0]["conditions"])
            with self.assertRaises(FileExistsError):
                self.run_case(base, audit)

    def test_rejected_review_stays_in_census_without_invented_span(self):
        with tempfile.TemporaryDirectory() as d:
            base = Path(d)
            audit = self.source(base / "source")
            audit["items"][0]["decision"] = "needs_extra_premise"
            audit["items"][0]["reviewed_spans"] = []
            self.run_case(base, audit)
            self.assertEqual(
                json.loads((base / "out/reviews.json").read_text())["reviews"], {}
            )
            self.assertEqual(
                len(json.loads((base / "out/plan.json").read_text())["cases"]), 1
            )
            self.assertEqual(
                json.loads((base / "out/audit-census.json").read_text())["decisions"],
                {"needs_extra_premise": 1},
            )

    def test_no_reviewer_impersonation_or_source_drift(self):
        edits = (
            lambda a: a["reviewer"].update(human=True),
            lambda a: a.update(production_accepted=True),
            lambda a: a["items"][0].update(independent_human_disposition="accepted"),
            lambda a: a["items"][0].update(query_digest="0" * 64),
            lambda a: a["items"][0]["reviewed_spans"][0].update(source_digest="0" * 64),
            lambda a: a["items"].append(copy.deepcopy(a["items"][0])),
            lambda a: a["items"].clear(),
        )
        for edit in edits:
            with tempfile.TemporaryDirectory() as d:
                base = Path(d)
                audit = self.source(base / "source")
                edit(audit)
                with self.assertRaises(ValueError):
                    self.run_case(base, audit)
                self.assertFalse((base / "out").exists())


if __name__ == "__main__":
    unittest.main()
