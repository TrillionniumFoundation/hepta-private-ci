"""Authored source/review fixtures: no human verdict and no pretrained model."""

from copy import deepcopy
import unittest

from project_pr_parent_review_packet import join
from project_pr_review_packet import compile_packet
from project_pr_source_materialize import canonical, digest
from test_project_pr_parent_context import SourceFixtures
from test_project_pr_review_packet import BlindPacketTests

PIN = "ef2a46ce037db4a91affddd2498eb8e089771ae5734bc13c56cb8a97b840a463"


def fixture():
    case = SourceFixtures()
    context, _ = case.inspect()
    packet_fixture = BlindPacketTests()
    packet_fixture.manifest = case.manifest
    inventory, checked = packet_fixture.fixture()
    for row, source in zip(inventory["originals"], case.originals, strict=True):
        row["sha256"] = source["sha256"]
    packet = compile_packet(
        case.manifest, inventory, checked, inventory_sha256="b" * 64
    )
    context.update(
        original_source_manifest_sha256=PIN,
        original_inventory_sha256="b" * 64,
        original_ready_sha256="c" * 64,
    )
    ready = dict(
        schema="hepta.memorycell.first-parent-context-ready.v1",
        original_source_manifest_sha256=PIN,
        context_sha256=digest(canonical(context) + b"\n"),
        complete_pr_diff_certified=False,
        independent_semantic_review=False, model_calls=0,
        production_accepted=False,
    )
    inspected = dict(
        schema="hepta.memorycell.first-parent-offline-reopen.v1",
        original_file_count=80, offline_source_hash_verification=True,
        human_review_performed=False, model_calls=0,
        production_accepted=False,
    )
    return case.manifest, packet, context, ready, inspected


class ReviewBindingTests(unittest.TestCase):
    def test_all_eight_pr_histories_two_questions_and_eighty_files(self):
        data = fixture()
        report = join(*data)
        self.assertEqual(report["unsigned_questions"], 16)
        self.assertEqual(report["source_file_bindings"], 80)
        self.assertEqual(report["unsigned_question_file_references"], 160)
        self.assertEqual(
            report["comparison_counts"]["ambiguous-multi-parent-head"], 31
        )
        self.assertEqual(
            report["comparison_counts"]["unresolved-renamed-previous-path"], 1
        )
        self.assertTrue(any(
            f["comparison_status"] == "byte-different-versus-first-parent"
            for q in report["questions"] for f in q["verified_first_parent_files"]
        ))
        self.assertTrue(all(
            q["answer_gold"] is None
            and q["reviewer_verdict"] == "unreviewed"
            and q["decoded_parent_diff_available"] is False
            for q in report["questions"]
        ))
        self.assertFalse(report["full_pr_diff_certified"])
        self.assertFalse(report["production_accepted"])
        self.assertIsNone(report["semantic_citation_precision"])

    def test_tampering_cannot_transform_source_into_authoritative_reviews(self):
        for field in ("head", "parent", "status", "digest", "question", "review",
                      "drop", "promote", "reopen", "merge"):
            data = deepcopy(fixture())
            manifest, packet, context, ready, verified = data
            if field == "head":
                context["files"][0]["original_head_sha256"] = "f" * 64
            elif field == "parent":
                context["files"][0]["first_parent_commit_sha"] = "x" * 40
            elif field == "status":
                context["files"][0]["comparison_status"] = "forged"
            elif field == "digest":
                ready["context_sha256"] = "e" * 64
            elif field == "question":
                packet["questions"][0]["verified_head_files"][0]["byte_sha256"] = "f" * 64
            elif field == "review":
                packet["questions"][0]["reviewer_verdict"] = "accepted"
            elif field == "drop":
                context["files"].pop()
            elif field == "promote":
                context["complete_pr_change_intent_verified"] = True
            elif field == "reopen":
                verified["offline_source_hash_verification"] = False
            else:
                next(r for r in context["files"] if
                     r["comparison_status"] == "ambiguous-multi-parent-head")[
                    "first_parent_commit_sha"
                ] = "f" * 40
            if field != "digest":
                ready["context_sha256"] = digest(canonical(context) + b"\n")
            with self.subTest(field=field), self.assertRaises(ValueError):
                join(manifest, packet, context, ready, verified)

    def test_missing_or_duplicate_questions_are_not_new_independent_samples(self):
        for field in ("missing", "duplicate", "swap"):
            data = deepcopy(fixture())
            questions = data[1]["questions"]
            if field == "missing":
                questions.pop()
            elif field == "duplicate":
                questions[-1] = deepcopy(questions[0])
            else:
                questions[0]["source_project"] = "numpy/numpy"
            with self.subTest(field=field), self.assertRaises(ValueError):
                join(*data)
