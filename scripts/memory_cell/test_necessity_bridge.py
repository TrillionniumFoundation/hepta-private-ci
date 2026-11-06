"""Publisher vote transfer has byte-level tests; no semantic certificate is issued."""

import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from bundle_trial import decode_bundle
from composition_evidence import sha
from native import digest
from necessity_bridge import CLAIM, REVIEWER, _read_binary, project
from necessity_data import CHAIN_BLOB, LIMITS, OBQA_SHA, PROFILE, make_case
from reviewed_bundle import augment
from test_necessity_data import fixture


def cohort():
    originals, questions, cases, labels = [], {}, [], {}
    phases = [phase for phase, count in LIMITS.items() for _ in range(count)]
    for i, phase in enumerate(phases):
        original, question = fixture(i)
        originals.append(original)
        questions[question["id"]] = question
        record = original | {"family": "eobqa-group:" + digest([str(i)])}
        case, label = make_case(
            record,
            question,
            [f"noise unrelated {i}"],
            "2026-10-01T00:00:00Z",
            phase,
        )
        cases.append(case)
        labels[case["question"]["identity"]] = label
    raw = b"pre-pinned fixture bytes"
    plan = dict(
        schema="hepta.bundle-diagnostic.plan.v1",
        profile=PROFILE,
        source_commit="a" * 40,
        cases=cases,
        frozen_counts=LIMITS,
        chain_blob=CHAIN_BLOB,
        dataset_sha256=sha(raw),
        original_question_archive_sha256=OBQA_SHA,
    )
    return plan, labels, originals, questions, raw


def project_fixture(plan, labels, records, questions, raw, *, revoked=None):
    with (
        patch("necessity_bridge.verified_chains", return_value=records),
        patch("necessity_bridge.verified_questions", return_value=(questions, b"")),
    ):
        return project(plan, labels, raw, b"archive", revoked=revoked or set())


class NecessityBridgeTests(unittest.TestCase):
    def test_real_source_bytes_preserved_for_complete_publisher_cohort(self):
        plan, labels, records, questions, raw = cohort()
        snapshot = copy.deepcopy(plan)
        pkg, projected, cap, votes, stats = project_fixture(
            plan, labels, records, questions, raw
        )
        self.assertEqual(plan, snapshot)
        self.assertEqual(stats["selected_records"], 24)
        self.assertEqual(stats["capability_questions"], 8)
        self.assertEqual(stats["independently_reviewed_minimal_sets"], 0)
        self.assertFalse(stats["production_accepted"])
        self.assertEqual(len(votes), len(pkg["reviews"]))
        for claim in pkg["reviews"].values():
            self.assertEqual(claim["reviewer_id"], REVIEWER)
            self.assertIsNone(claim["reviewed_at"])
            self.assertEqual(claim["claim"], CLAIM)
        for before, after in zip(plan["cases"], projected["cases"], strict=True):
            self.assertEqual(
                {k: after["conditions"][k] for k in before["conditions"]},
                before["conditions"],
            )
            a = after["conditions"]
            for claimed, original in (
                ("publisher_claim_pair", "publisher_pair"),
                ("publisher_claim_without_fact1", "without_fact1"),
                ("publisher_claim_without_fact2", "without_fact2"),
            ):
                self.assertEqual(
                    decode_bundle(a[claimed]).selected,
                    decode_bundle(a[original]).selected,
                )
                self.assertFalse(a[claimed]["independent_review"])
                self.assertFalse(a[claimed]["sufficient_context_certified"])
        self.assertEqual(len(cap["cases"]), 8)
        self.assertTrue(all(c["phase"] == "capability" for c in cap["cases"]))

    def test_persisted_json_normalizes_tuple_assets_without_detaching_sources(self):
        plan, labels, records, questions, raw = cohort()
        persisted_plan = json.loads(json.dumps(plan))
        persisted_labels = json.loads(json.dumps(labels))
        package, projected, cap, _, stats = project_fixture(
            persisted_plan, persisted_labels, records, questions, raw
        )
        self.assertEqual(len(package["reviews"]), 24)
        self.assertEqual(len(projected["cases"]), 24)
        self.assertEqual(len(cap["cases"]), 8)
        self.assertFalse(stats["production_accepted"])

    def test_mutated_question_vote_source_or_answer_fail(self):
        plan, labels, records, questions, raw = cohort()
        changes = (
            lambda p, l: p["cases"][0]["originals"][0].update(content="tampered"),
            lambda p, l: l["eobqa:0"]["publication_review"]["row"].update(
                Turks="yes no yes"
            ),
            lambda p, l: l["eobqa:0"].update(answer="forged answer"),
            lambda p, l: p["cases"][0].update(family="new family"),
            lambda p, l: p["cases"][1].update(phase="transfer"),
            lambda p, l: p["cases"][0]["conditions"]["publisher_pair"].update(
                token_limit=128
            ),
        )
        for change in changes:
            with self.subTest(change=change):
                p, l = copy.deepcopy(plan), copy.deepcopy(labels)
                change(p, l)
                with self.assertRaises(ValueError):
                    project_fixture(p, l, records, questions, raw)

    def test_missing_duplicate_and_revoked_claims_never_get_certificate(self):
        plan, labels, records, questions, raw = cohort()
        with self.assertRaises(ValueError):
            project_fixture(
                plan,
                {k: v for k, v in labels.items() if k != "eobqa:0"},
                records,
                questions,
                raw,
            )
        with self.assertRaises(ValueError):
            project_fixture(
                plan,
                labels,
                records,
                questions,
                raw,
                revoked={plan["cases"][0]["originals"][0]["root"]},
            )
        with self.assertRaises(ValueError):
            project_fixture(plan, labels, records[:-1], questions, raw)
        package, projected, _, _, _ = project_fixture(
            plan, labels, records, questions, raw
        )
        package["base_plan_digest"] = digest(projected)
        with self.assertRaises(ValueError):
            augment(projected, package, revoked=set())

    def test_anonymous_publisher_votes_cannot_claim_independent_minimality(self):
        plan, labels, records, questions, raw = cohort()
        pkg, _, _, _, _ = project_fixture(plan, labels, records, questions, raw)
        for field, value in (
            ("claim", "jointly_sufficient_and_each_requirement_necessary"),
            ("review_basis", "external_review"),
            ("reviewed_at", "2026-10-01"),
            ("reviewer_id", "invented-person"),
        ):
            with self.subTest(field=field):
                copy_pkg = copy.deepcopy(pkg)
                copy_pkg["reviews"]["eobqa:0"][field] = value
                with self.assertRaises(ValueError):
                    augment(plan, copy_pkg, revoked=set())

    def test_symlink_or_oversized_publication_rejected(self):
        with tempfile.TemporaryDirectory() as dirname:
            src = Path(dirname) / "row"
            src.write_bytes(b"original")
            self.assertEqual(_read_binary(src, 8), b"original")
            with self.assertRaises(ValueError):
                _read_binary(src, 3)
            link = Path(dirname) / "alias"
            link.symlink_to(src)
            with self.assertRaises(ValueError):
                _read_binary(link, 8)


if __name__ == "__main__":
    unittest.main()
