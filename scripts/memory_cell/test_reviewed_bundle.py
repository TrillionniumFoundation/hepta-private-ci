"""Structural test fixtures are NOT independent semantic reviews."""

import copy
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from evidence_bundle import EvidenceBundle
from native import Document, Question, digest
from reviewed_bundle import SCHEMA, augment, strict_read


def fixture():
    docs = (
        Document("d1", "r1", "s", "a", "2024-01-01", "奈良: moved in May."),
        Document("d2", "r2", "s", "b", "2024-01-02", "Training started two months earlier."),
    )
    q = Question("q", "f", "s", "When did training start?", "2024-06-01")
    frontier = digest([asdict(d) for d in docs])
    empty = EvidenceBundle(digest(asdict(q)), frontier, (), "empty", 0)
    case = dict(question=asdict(q), originals=[asdict(d) for d in docs],
                frontier=frontier, phase="fixture", family="f",
                conditions={"empty": dict(bundle=asdict(empty),
                            bundle_digest=empty.seal(), delivered_evidence=[], token_limit=2048)})
    plan = dict(schema="hepta.bundle-diagnostic.plan.v1", source_commit="a" * 40,
                cases=[case])
    review = dict(query_digest=digest(asdict(q)), source_frontier=frontier,
                  reviewer_id="fixture-not-person", reviewed_at="2024-06-02",
                  review_basis="authored_fixture",
                  claim="jointly_sufficient_and_each_requirement_necessary",
                  requirements=["date", "offset"], spans=[
                      dict(source_id=d.identity, source_digest=digest(d.content),
                           start=0, end=len(d.content.encode()), requirement=r)
                      for d, r in zip(docs, ("date", "offset"))])
    package = dict(schema=SCHEMA, base_plan_digest=digest(plan), reviews={"q": review})
    return plan, package


class ReviewedBundleTests(unittest.TestCase):
    def test_roundtrip_original_bytes_and_leave_requirement_out(self):
        from bundle_trial import decode_bundle
        plan, reviews = fixture()
        untouched = copy.deepcopy(plan)
        projected = augment(plan, reviews, revoked=set())
        self.assertEqual(plan, untouched)
        conditions = projected["cases"][0]["conditions"]
        self.assertEqual(conditions["empty"], plan["cases"][0]["conditions"]["empty"])
        self.assertEqual(len(decode_bundle(conditions["reviewed_minimal"]).selected), 2)
        missing = decode_bundle(conditions["reviewed_without_date"])
        self.assertEqual([s.source_id for s in missing.selected], ["d2"])
        self.assertFalse(conditions["reviewed_minimal"]["sufficient_context_certified"])
        self.assertTrue(conditions["reviewed_without_date"]["world_answerability_unchanged"])

    def test_absent_review_keeps_case_and_explicit_unavailable(self):
        plan, reviews = fixture()
        reviews["reviews"] = {}
        result = augment(plan, reviews, revoked=set())
        self.assertEqual(len(result["cases"]), 1)
        self.assertEqual(result["cases"][0]["conditions"]["reviewed_minimal"],
                         dict(status="unavailable", reason="missing_external_review"))

    def test_query_frontier_source_changes_and_revocation_reject(self):
        for field, value in (("query_digest", "0" * 64), ("source_frontier", "bad"),
                             ("review_basis", "certified"), ("claim", "probably")):
            with self.subTest(field=field):
                plan, reviews = fixture()
                reviews["reviews"]["q"][field] = value
                with self.assertRaises(ValueError):
                    augment(plan, reviews, revoked=set())
        plan, reviews = fixture()
        with self.assertRaises(ValueError):
            augment(plan, reviews, revoked={"r1"})
        plan["cases"][0]["originals"][0]["content"] += "changed"
        reviews["base_plan_digest"] = digest(plan)
        with self.assertRaises(ValueError):
            augment(plan, reviews, revoked=set())

    def test_unicode_boundaries_no_bool_offsets_or_overlap(self):
        for mutation in (lambda r: r["spans"][0].update(start=1),
                         lambda r: r["spans"][0].update(start=False),
                         lambda r: r["spans"].append(r["spans"][0]),
                         lambda r: r["requirements"].append("absent")):
            plan, reviews = fixture()
            mutation(reviews["reviews"]["q"])
            with self.assertRaises((ValueError, UnicodeError)):
                augment(plan, reviews, revoked=set())

    def test_unregistered_metadata_and_duplicate_requirements_reject(self):
        for mutate in (lambda r: r.update(answer="March"),
                       lambda r: r["requirements"].append("date"),
                       lambda r: r["spans"][0].update(requirement="unknown")):
            plan, reviews = fixture()
            mutate(reviews["reviews"]["q"])
            with self.assertRaises(ValueError):
                augment(plan, reviews, revoked=set())

    def test_future_source_and_supplied_source_beyond_budget_not_oracle(self):
        plan, reviews = fixture()
        plan["cases"][0]["originals"][0]["observed_at"] = "2027-01-01"
        reviews["base_plan_digest"] = digest(plan)
        with self.assertRaises(ValueError):
            augment(plan, reviews, revoked=set())

    def test_plan_pin_duplicate_unknown_and_second_projection_reject(self):
        plan, reviews = fixture()
        bad = copy.deepcopy(reviews)
        bad["base_plan_digest"] = "0" * 64
        with self.assertRaises(ValueError):
            augment(plan, bad, revoked=set())
        bad = copy.deepcopy(reviews)
        bad["reviews"]["new"] = bad["reviews"]["q"]
        with self.assertRaises(ValueError):
            augment(plan, bad, revoked=set())
        result = augment(plan, reviews, revoked=set())
        reviews["base_plan_digest"] = digest(result)
        with self.assertRaises(ValueError):
            augment(result, reviews, revoked=set())

    def test_file_pins_nonfinite_duplicate_keys_and_symlink_reject(self):
        with tempfile.TemporaryDirectory() as directory:
            p = Path(directory) / "review.json"
            for raw in (b'{"x":1,"x":2}', b'{"x":NaN}'):
                p.write_bytes(raw)
                with self.assertRaises(ValueError):
                    strict_read(p, hashlib.sha256(raw).hexdigest(), 1000)
            raw = json.dumps({"x": "original"}).encode()
            p.write_bytes(raw)
            self.assertEqual(strict_read(p, hashlib.sha256(raw).hexdigest(), 1000),
                             {"x": "original"})
            with self.assertRaises(ValueError):
                strict_read(p, "0" * 64, 1000)
            with self.assertRaises(ValueError):
                strict_read(p, hashlib.sha256(raw).hexdigest(), 2)
            alias = p.with_name("alias.json")
            alias.symlink_to(p)
            with self.assertRaises(ValueError):
                strict_read(alias, hashlib.sha256(raw).hexdigest(), 1000)


if __name__ == "__main__":
    unittest.main()
