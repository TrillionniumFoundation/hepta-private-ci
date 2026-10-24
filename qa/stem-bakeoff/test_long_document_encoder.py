"""Actual tiny local Transformer verifies chunk forwards, pooling and custody."""

from dataclasses import replace
import math
import unittest
from unittest.mock import patch

import numpy as np
import torch

from long_document_chunks import ChunkPolicy, tokenize_documents
from long_document_encoder import LongDocumentEncoder
from real_encoder import CANDIDATES, FrozenRealEncoder
from shared_feature_contract import SourceEvent
import test_shared_feature_extract as tiny_fixture


class LongDocumentEncoderTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        tiny_fixture.SharedFeatureExtractTests.setUpClass()

    @classmethod
    def tearDownClass(cls):
        tiny_fixture.SharedFeatureExtractTests.tearDownClass()

    def setUp(self):
        fixture = tiny_fixture.SharedFeatureExtractTests
        with patch.dict(CANDIDATES["granite97m"], {"weight_sha256": fixture.weight_hash, "width": 8}):
            self.owner = FrozenRealEncoder(candidate="granite97m", snapshot=fixture.root,
                revision=CANDIDATES["granite97m"]["revision"], max_tokens=8,
                expected_inventory_sha256=fixture.inventory["inventory_sha256"],
                operator_accepted_terms=True)
        self.policy = ChunkPolicy(max_tokens=8, overlap_tokens=2)
        self.encoder = LongDocumentEncoder(self.owner, self.policy)
        self.texts = ["alpha beta " * 13 + "alpha", "beta alpha"]
        self.plans = tokenize_documents(self.owner._tokenizer, self.texts, prefix="", policy=self.policy)
        self.events = [SourceEvent("long", "v1"), SourceEvent("short", "v1")]

    def encode(self, **kwargs):
        return self.encoder.encode(self.plans, events=self.events,
            expected_identity=self.owner.identity, batch_size=2, **kwargs)

    def test_every_native_window_is_forwarded_once_and_weighted_pooling_matches(self):
        result, local = self.encode()
        chunks, pooled = result.read_chunks().numpy(), result.read_global().numpy()
        cursor = 0
        for index, plan in enumerate(self.plans):
            weights = np.array([c.weight for c in plan.chunks])
            expected = (chunks[cursor:cursor + len(weights)].astype(np.float64) * weights[:, None]).sum(0)
            expected /= plan.content_tokens
            expected /= np.linalg.norm(expected)
            np.testing.assert_array_equal(pooled[index], expected.astype(np.float32))
            cursor += len(weights)
        self.assertEqual(self.owner._calls, math.ceil(cursor / 2))
        self.assertEqual(self.encoder.last_receipt["chunks"], cursor)
        self.assertEqual(self.encoder.last_receipt["cache"]["hits"], 0)
        self.assertEqual(local, ())
        exposed = result.read_chunks(); exposed[:] = 99
        self.assertFalse(torch.equal(exposed, result.read_chunks()))
        result.verify_integrity()

    def test_global_only_and_optional_native_tokens_preserve_the_same_global_result(self):
        global_only, _ = self.encode(retention="global")
        with self.assertRaisesRegex(ValueError, "not retained"): global_only.read_chunks()
        detailed, views = self.encode(retention="tokens")
        torch.testing.assert_close(global_only.read_global(), detailed.read_global(), rtol=0, atol=0)
        self.assertEqual(global_only.feature_identity_digest, detailed.feature_identity_digest)
        self.assertGreater(sum(v["token_features"].numel() for v in views), 0)
        self.assertTrue(all(v["char_spans"].dtype == torch.int64 for v in views))
        self.assertEqual(self.encoder.last_receipt["retained_local_view_bytes"],
                         sum(v.numel() * v.element_size() for batch in views for v in batch.values()))

    def test_policy_revision_and_source_revision_have_separate_boundaries(self):
        original, _ = self.encode()
        self.events[0] = replace(self.events[0], source_version="v2")
        revised, _ = self.encode()
        self.assertNotEqual(original.source_record_digests[0], revised.source_record_digests[0])
        self.assertEqual(original.source_record_digests[1], revised.source_record_digests[1])
        changed = LongDocumentEncoder(self.owner, replace(self.policy, overlap_tokens=0))
        self.assertNotEqual(changed.feature_identity, self.encoder.feature_identity)
        with self.assertRaisesRegex(ValueError, "different tokenizer"):
            changed.encode(self.plans, events=self.events, expected_identity=self.owner.identity)

    def test_stale_tampered_or_oversized_plans_reject_before_any_forward(self):
        with self.assertRaises(ValueError):
            self.encoder.encode(self.plans, events=self.events,
                expected_identity=replace(self.owner.identity, generation=2))
        with patch("long_document_encoder.MAX_LOCAL_BYTES", 1), self.assertRaisesRegex(ValueError, "before forward"):
            self.encode(retention="tokens")
        object.__setattr__(self.plans[1], "source_text", "changed")
        with self.assertRaisesRegex(ValueError, "changed"): self.encode()
        self.assertEqual(self.owner._calls, 0)


if __name__ == "__main__":
    unittest.main()
