"""Synthetic-only Ed25519 review-handoff contracts; NEVER human QA results."""
from __future__ import annotations

from copy import deepcopy
from hashlib import sha256
import json
import unittest

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

import amcn_original_blind_review as review
import amcn_causal_task_audit as task
from test_amcn_causal_task_audit import fixture


class BlindReviewSignedContracts(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.plan, cls.answers, _ = fixture()
        cls.secret = "45" * 32
        cls.commitment = sha256(bytes.fromhex(cls.secret)).hexdigest()
        cls.bundle, cls.mapping = review.make_blind_packets(
            cls.plan, cls.answers, blinding_seed_hex=cls.secret,
            externally_precommitted_seed_sha256=cls.commitment)
        cls.registry = {"schema": review.REGISTRY, "public_keys": {}}
        cls.privates = {}
        for rid in ("fixture-reviewer-one", "fixture-reviewer-two"):
            private = Ed25519PrivateKey.generate()
            cls.privates[rid] = private
            cls.registry["public_keys"][rid] = private.public_key().public_bytes(
                encoding=serialization.Encoding.Raw,
                format=serialization.PublicFormat.Raw).hex()
        cls.original_full_source = sha256(b"fixture-only-original-source").hexdigest()
        cls.kwargs = {
            "original_bundle_sha256": task.digest(cls.bundle),
            "original_private_index_sha256": task.digest(cls.mapping),
            "externally_registered_keys_sha256": task.digest(cls.registry),
            "independent_source_sha256": cls.original_full_source,
        }

    def sign(self, records=None):
        if records is None:
            records = []
            for ticket in self.bundle["tickets"]:
                for name in self.privates:
                    records.append({
                        "reviewer_id": name, "ticket_id": ticket["ticket_id"],
                        "ticket_sha256": task.digest(ticket),
                        "verdict": {
                            "independently_consulted_full_source": True,
                            "reference_source_sha256": self.original_full_source,
                            "factually_correct": False,
                            "citation_entailment": False,
                            "delivered_evidence_sufficient": False},
                        "signature_hex": "",
                    })
        for record in records:
            record["signature_hex"] = self.privates[
                record["reviewer_id"]].sign(
                    review._signature_message(
                        self.kwargs["original_bundle_sha256"], record)).hex()
        return records

    def review(self, records=None, **kwargs):
        return review.verify_reviews(self.bundle, self.mapping,
                                     self.sign() if records is None else records,
                                     self.registry, **(kwargs or self.kwargs))

    def test_full_synthetic_signed_review_never_grants_independence(self):
        out = self.review()
        self.assertEqual(out["reviewed_attempts"], 54)
        self.assertEqual(out["reviewer_signatures_verified"], 108)
        self.assertEqual(len(out["judgments"]), 54)
        self.assertFalse(out["reviewer_real_world_independence_verified"])
        self.assertFalse(out["external_source_truth_authenticated"])
        self.assertFalse(out["production_accepted"])
        checked = task.audit(self.plan, self.answers, out["judgments"])
        self.assertFalse(checked["external_reviewer_independence_verified"])
        self.assertFalse(checked["production_accepted"])

    def test_blinded_public_ticket_has_no_explicit_arm_fields_or_secret(self):
        packet = self.bundle["tickets"][0]
        self.assertNotIn("arm", packet)
        self.assertNotIn("question_id", packet)
        self.assertNotIn("split", packet)
        self.assertNotIn("source_root", packet)
        self.assertNotIn("original_answers_sha256", packet)
        self.assertNotIn(self.secret, json.dumps(self.bundle))
        self.assertEqual(len(self.bundle["tickets"]), 54)

    def test_changed_original_seed_fails_before_export(self):
        with self.assertRaisesRegex(task.Refused, "precommit"):
            review.make_blind_packets(
                self.plan, self.answers, blinding_seed_hex="66" * 32,
                externally_precommitted_seed_sha256=self.commitment)

    def test_incomplete_original_attempt_census_refused(self):
        with self.assertRaisesRegex(task.Refused, "incomplete"):
            review.make_blind_packets(
                self.plan, self.answers[:-1], blinding_seed_hex=self.secret,
                externally_precommitted_seed_sha256=self.commitment)

    def test_changed_original_answer_text_refused(self):
        x = deepcopy(self.answers)
        x[0]["raw_answer"] += " forged"
        with self.assertRaisesRegex(task.Refused, "edited"):
            review.make_blind_packets(
                self.plan, x, blinding_seed_hex=self.secret,
                externally_precommitted_seed_sha256=self.commitment)

    def test_gold_does_not_enter_review_plan(self):
        p = deepcopy(self.plan)
        p["publisher_answer"] = "target"
        with self.assertRaises(task.Refused):
            review.make_blind_packets(p, self.answers, blinding_seed_hex=self.secret,
                                      externally_precommitted_seed_sha256=self.commitment)

    def test_changed_review_statement_signature_refused(self):
        rows = self.sign()
        rows[0]["verdict"]["factually_correct"] = True
        with self.assertRaisesRegex(task.Refused, "signature invalid"):
            self.review(rows)

    def test_modified_private_mapping_refused(self):
        x = deepcopy(self.mapping)
        x[0]["arm"] = "unregistered-arm"
        with self.assertRaisesRegex(task.Refused, "byte commitments changed"):
            review.verify_reviews(self.bundle, x, self.sign(),
                                  self.registry, **self.kwargs)

    def test_review_key_substitution_refused(self):
        keys = deepcopy(self.registry)
        keys["public_keys"]["fixture-reviewer-one"] = "55" * 32
        with self.assertRaisesRegex(task.Refused, "registry not pinned"):
            review.verify_reviews(self.bundle, self.mapping,
                                  self.sign(), keys, **self.kwargs)

    def test_missing_second_reviewer_refused(self):
        rows = self.sign()[:-1]
        with self.assertRaisesRegex(task.Refused, "two complete"):
            self.review(rows)

    def test_double_signer_refused(self):
        rows = self.sign()
        rows[1]["reviewer_id"] = rows[0]["reviewer_id"]
        # Even correctly signed twice by the same legitimate key is not two reviewers.
        self.sign(rows)
        with self.assertRaisesRegex(task.Refused, "same reviewer"):
            self.review(rows)

    def test_sincerely_conflicting_review_fails_closed(self):
        rows = self.sign()
        rows[0]["verdict"]["factually_correct"] = True
        self.sign(rows)
        with self.assertRaisesRegex(task.Refused, "third-party adjudication"):
            self.review(rows)

    def test_no_citation_cannot_be_falsely_entailment_positive(self):
        rows = self.sign()
        rows[0]["verdict"]["citation_entailment"] = True
        self.sign(rows)
        with self.assertRaisesRegex(task.Refused, "missing or undelivered citation"):
            self.review(rows)

    def test_review_source_binding_requires_original_full_corpus(self):
        rows = self.sign()
        rows[0]["verdict"]["reference_source_sha256"] = "a" * 64
        self.sign(rows)
        with self.assertRaisesRegex(task.Refused, "source consultation"):
            self.review(rows)

    def test_unsigned_does_not_create_independence(self):
        rows = self.sign()
        rows[0]["signature_hex"] = "00" * 64
        with self.assertRaisesRegex(task.Refused, "signature invalid"):
            self.review(rows)

    def test_two_valid_keys_do_not_invent_production_authority(self):
        out = self.review()
        self.assertNotIn("independent_source_truth_verified", out)
        self.assertFalse(out["true_future_calendar_windows_verified"])
        self.assertFalse(out["model_host_independently_authenticated"])


if __name__ == "__main__":
    unittest.main()
