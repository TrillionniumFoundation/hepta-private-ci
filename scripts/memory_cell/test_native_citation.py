"""Native IDs are not wire digests; test the real adapter boundary explicitly."""

import copy
import unittest
from types import SimpleNamespace

from citation_audit import request_payload, sha, validate_judgement
from native_citation import ROOT_PROFILE, capture_native, native_root_digest
from test_citation_audit import judgement, request


class NativeCitationTests(unittest.TestCase):
    def capture(self, root):
        record = request()
        q = SimpleNamespace(
            identity=record["query_id"],
            scope=record["scope"],
            content=record["question"],
            observed_at=record["question_time"],
        )
        record["sources"][0]["root"] = root
        receipt = {
            "input_ids_sha256": record["prompt_digest"],
            "delivered_evidence": record["sources"],
        }
        before = copy.deepcopy(receipt)
        result = capture_native(
            q,
            record["answer"],
            receipt,
            experiment_digest=record["experiment_digest"],
            family_digest=record["family_digest"],
        )
        self.assertEqual(receipt, before)
        return result

    def test_real_benchmark_root_and_propagated_withdrawal(self):
        queue = self.capture("locomo:conv-48")
        root = native_root_digest("locomo:conv-48")
        self.assertEqual(queue["source_root_profile"], ROOT_PROFILE)
        self.assertEqual(
            queue["source_root_bindings"],
            [{"native_root": "locomo:conv-48", "root_digest": root}],
        )
        self.assertEqual(queue["request"]["sources"][0]["root"], root)
        self.assertEqual(
            queue["request_sha256"], sha(request_payload(queue["request"]))
        )
        self.assertIsNone(queue["judgement"])
        self.assertIsNone(queue["generator_signature"])
        self.assertFalse(queue["production_accepted"])
        with self.assertRaisesRegex(ValueError, "revoked"):
            validate_judgement(queue["request"], judgement(), revoked_roots={root})

    def test_hex_looking_ids_are_not_misclassified_as_digests(self):
        raw = "a" * 64
        queue = self.capture(raw)
        self.assertNotEqual(queue["request"]["sources"][0]["root"], raw)
        self.assertNotEqual(native_root_digest(raw), native_root_digest("id:" + raw))
        self.assertEqual(self.capture(raw), queue)

    def test_unicode_is_exact_no_normalization_or_invalid_fallback(self):
        self.assertNotEqual(native_root_digest("é"), native_root_digest("e\u0301"))
        for root in (None, "", "bad\0root", "界" * 1366):
            with self.assertRaises((ValueError, TypeError)):
                self.capture(root)

    def test_source_content_and_prompt_are_still_bound(self):
        queue = self.capture("session:native")
        original = queue["request_sha256"]
        for field in ("answer", "question", "scope"):
            changed = copy.deepcopy(queue["request"])
            changed[field] += " altered"
            self.assertNotEqual(sha(request_payload(changed)), original)
        changed = copy.deepcopy(queue["request"])
        changed["sources"][0]["excerpt"] = "Undelivered replacement"
        self.assertNotEqual(sha(request_payload(changed)), original)
