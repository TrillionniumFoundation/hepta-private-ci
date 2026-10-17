"""Negative controls for a blind SOURCE-FIRST review worklist, not human judgments."""

import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from locomo_blind_sufficiency import (
    ARMS,
    PLAN_SHA256,
    SOURCE_SHA256,
    SCHEMA,
    canonical,
    audit_public_receipt,
    check_source_return,
    create,
    pinned_file,
    sha,
)


def fixture():
    cases = [dict(qid=f"question-{i}", root_sha256=f"root-{i}") for i in range(8)]
    plan = dict(
        schema="hepta.memory.locomo-four-evidence-regimes.v1",
        sealed_inputs_sha256=SOURCE_SHA256,
        fixed_cases=cases,
        dataset_previously_public=True,
        no_answer_labels_opened_in_prepare=True,
        publisher_witness_independent_sufficiency=False,
    )
    requests = []
    for case in cases:
        for arm in ARMS:
            original = [
                dict(
                    id=f"doc-{case['qid']}-{arm}-{i}",
                    speaker="Alice",
                    text="The café opens today.",
                )
                for i in range(
                    3
                    if arm in ("bm25_top3", "annotated_witness")
                    else (2 if arm == "witness_lesion" else 0)
                )
            ]
            requests.append(
                dict(
                    qid=case["qid"],
                    root_sha256=case["root_sha256"],
                    question=f"Where is Alice {case['qid']}?",
                    arm=arm,
                    sources=original,
                    source_ids=[row["id"] for row in original],
                )
            )
    sealed = dict(
        schema="hepta.memory.locomo-fixed-reader-private-input.v1", requests=requests
    )
    return plan, sealed


def returned(packet, claimed):
    return dict(
        schema=SCHEMA,
        phase="source-first-review",
        claimed_reviewer_id=claimed,
        packet_sha256=sha(canonical(packet)),
        rows=[
            dict(
                ticket_id=item["ticket_id"],
                verdict="unassessable",
                answer_from_sources=None,
                supporting_spans=[],
                contradictory_labels=[],
            )
            for item in packet["tickets"]
        ],
    )


class BlindSufficiencyTests(unittest.TestCase):
    def setUp(self):
        self.plan, self.sealed = fixture()
        self.packet, self.private, self.receipt = create(
            self.plan, self.sealed, b"A" * 32
        )

    def test_complete_32_ticket_blind_packet(self):
        self.assertEqual(len(self.packet["tickets"]), 32)
        self.assertEqual(self.receipt["original_plan_sha256"], PLAN_SHA256)
        self.assertEqual(self.receipt["decision"], "DENY_ALL")
        self.assertIsNone(self.receipt["independent_sufficiency"])
        self.assertFalse(self.packet["model_answers_included"])
        self.assertFalse(self.packet["publisher_answers_included"])
        self.assertFalse(self.packet["condition_names_included"])
        self.assertFalse(self.packet["independent_review_completed"])
        self.assertEqual(set(x["arm"] for x in self.private["entries"]), set(ARMS))
        self.assertEqual(len(set(x["ticket_id"] for x in self.packet["tickets"])), 32)
        for item in self.packet["tickets"]:
            self.assertNotIn("arm", item)
            self.assertNotIn("qid", item)
            self.assertNotIn("gold_answer", item)
            self.assertNotIn("reference_answer", item)

    def test_secret_does_not_enter_public_packet_and_blinds_role(self):
        packet2, private2, receipt2 = create(self.plan, self.sealed, b"B" * 32)
        self.assertNotEqual(self.receipt["packet_sha256"], receipt2["packet_sha256"])
        self.assertNotEqual(
            set(x["ticket_id"] for x in self.packet["tickets"]),
            set(x["ticket_id"] for x in packet2["tickets"]),
        )
        self.assertFalse("A" * 32 in json.dumps(self.packet))
        self.assertNotIn("bm25_top3", json.dumps(self.packet))
        self.assertIn("bm25_top3", json.dumps(self.private))
        self.assertIn("bm25_top3", json.dumps(private2))

    def test_missing_source_role_and_duplicate_denied(self):
        sealed = copy.deepcopy(self.sealed)
        sealed["requests"].pop()
        with self.assertRaisesRegex(ValueError, "32 fixed contexts"):
            create(self.plan, sealed, b"A" * 32)
        sealed = copy.deepcopy(self.sealed)
        sealed["requests"][0] = copy.deepcopy(sealed["requests"][1])
        with self.assertRaisesRegex(ValueError, "duplicate or unknown"):
            create(self.plan, sealed, b"A" * 32)

    def test_no_evidence_hidden_or_gold_field_denied(self):
        sealed = copy.deepcopy(self.sealed)
        sealed["requests"][0]["sources"].append(
            dict(id="hidden", speaker="A", text="yes")
        )
        sealed["requests"][0]["source_ids"].append("hidden")
        with self.assertRaisesRegex(ValueError, "no-evidence condition"):
            create(self.plan, sealed, b"A" * 32)
        sealed = copy.deepcopy(self.sealed)
        sealed["requests"][0]["expected_answer"] = "yes"
        with self.assertRaisesRegex(ValueError, "no answer metadata"):
            create(self.plan, sealed, b"A" * 32)

    def test_real_public_receipt_does_not_disclose_source_or_verdict(self):
        path = (
            Path(__file__).with_name("data") / "locomo-blind-source-first-20261016.json"
        )
        original = pinned_file(
            path, "0157a1358fa28072d8e95b74b22bc708325821a259c54c5ac6309468e1ec500d"
        )
        record = audit_public_receipt(original)
        self.assertEqual(record["decision"], "DENY_ALL")
        self.assertFalse(record["independent_sufficiency_certified"])
        modified = copy.deepcopy(original)
        modified["private_arm_map"] = self.private
        with self.assertRaisesRegex(ValueError, "receipt or NO-GO"):
            audit_public_receipt(modified)
        modified = copy.deepcopy(original)
        modified["independent_sufficiency"] = True
        with self.assertRaisesRegex(ValueError, "receipt or NO-GO"):
            audit_public_receipt(modified)

    def test_cross_arm_question_and_source_id_forgery_denied(self):
        sealed = copy.deepcopy(self.sealed)
        sealed["requests"][3]["question"] = "Injected different question"
        with self.assertRaisesRegex(ValueError, "question/family changed"):
            create(self.plan, sealed, b"A" * 32)
        sealed = copy.deepcopy(self.sealed)
        sealed["requests"][2]["source_ids"][0] = "different"
        with self.assertRaisesRegex(ValueError, "delivered source bytes"):
            create(self.plan, sealed, b"A" * 32)

    def test_review_return_claims_are_never_human_authenticated(self):
        report = check_source_return(
            self.packet,
            self.private,
            [
                returned(self.packet, "reviewer.one"),
                returned(self.packet, "reviewer.two"),
            ],
        )
        self.assertEqual(report["reviewed_ticket_rows"], 64)
        self.assertEqual(report["agreed_verdicts"], 32)
        self.assertFalse(report["reviewer_identities_externally_authenticated"])
        self.assertFalse(report["source_sufficiency_human_certified"])
        self.assertFalse(report["production_accepted"])

    def test_duplicate_reviewers_or_missing_ticket_denied(self):
        with self.assertRaisesRegex(ValueError, "identical identity"):
            check_source_return(
                self.packet,
                self.private,
                [
                    returned(self.packet, "same.person"),
                    returned(self.packet, "same.person"),
                ],
            )
        a = returned(self.packet, "reviewer.one")
        b = returned(self.packet, "reviewer.two")
        b["rows"].pop()
        with self.assertRaisesRegex(ValueError, "denominator"):
            check_source_return(self.packet, self.private, [a, b])
        b = returned(self.packet, "reviewer.two")
        b["rows"][0]["ticket_id"] = b["rows"][1]["ticket_id"]
        with self.assertRaisesRegex(ValueError, "duplicate, missing"):
            check_source_return(self.packet, self.private, [a, b])

    def test_quote_needs_source_byte_exactness(self):
        a = returned(self.packet, "reviewer.one")
        b = returned(self.packet, "reviewer.two")
        row = next(
            x
            for x in a["rows"]
            if len(
                next(
                    t
                    for t in self.packet["tickets"]
                    if t["ticket_id"] == x["ticket_id"]
                )["delivered_evidence"]
            )
            > 0
        )
        row["verdict"] = "sufficient"
        row["answer_from_sources"] = "café"
        row["supporting_spans"] = [dict(label="E1", start=4, end=9, quote="café")]
        record = check_source_return(self.packet, self.private, [a, b])
        self.assertEqual(len(record["discordant_tickets"]), 1)
        self.assertFalse(record["source_sufficiency_human_certified"])
        row["supporting_spans"][0]["quote"] = "cafe"
        with self.assertRaisesRegex(ValueError, "quotation differs"):
            check_source_return(self.packet, self.private, [a, b])
        row["supporting_spans"][0].update(start=8, end=9, quote="é")
        with self.assertRaisesRegex(ValueError, "UTF-8"):
            check_source_return(self.packet, self.private, [a, b])

    def test_unsupported_sufficient_and_undelivered_conflict_denied(self):
        a = returned(self.packet, "reviewer.one")
        b = returned(self.packet, "reviewer.two")
        a["rows"][0]["verdict"] = "sufficient"
        with self.assertRaisesRegex(ValueError, "needs source spans"):
            check_source_return(self.packet, self.private, [a, b])
        a = returned(self.packet, "reviewer.one")
        a["rows"][0]["verdict"] = "conflicting"
        a["rows"][0]["contradictory_labels"] = ["E999"]
        with self.assertRaisesRegex(ValueError, "undelivered source"):
            check_source_return(self.packet, self.private, [a, b])

    def test_tampered_secret_map_denied(self):
        mapping = copy.deepcopy(self.private)
        mapping["packet_sha256"] = "0" * 64
        with self.assertRaisesRegex(ValueError, "private mapping"):
            check_source_return(
                self.packet,
                mapping,
                [returned(self.packet, "one.two"), returned(self.packet, "two.one")],
            )

    def test_regular_sha_pins_and_json_duplicate_fields(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / "pinned.json"
            path.write_text('{"q":1,"q":2}')
            value = sha(path.read_bytes())
            with self.assertRaisesRegex(ValueError, "duplicate JSON field"):
                pinned_file(path, value)
            path.write_text('{"x":1}')
            with self.assertRaisesRegex(ValueError, "digest"):
                pinned_file(path, value)
            link = Path(root) / "linked.json"
            link.symlink_to(path)
            with self.assertRaisesRegex(ValueError, "regular"):
                pinned_file(link, sha(path.read_bytes()))


if __name__ == "__main__":
    unittest.main()
