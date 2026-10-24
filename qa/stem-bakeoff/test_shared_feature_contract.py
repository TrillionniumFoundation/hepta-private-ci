"""Event provenance and local-detail custody; fixtures do not qualify models."""

from dataclasses import replace
import unittest

import torch

from feature_bundle import FeatureBundleError, FeatureBundleV1, FeatureIdentityV1
from shared_feature_contract import SharedFeatureBatch, SharedFeatureError, SourceEvent


def fixture_bundle(detail=True):
    identity = FeatureIdentityV1("a" * 64, "b" * 40, "c" * 64)
    kwargs = {}
    if detail:
        kwargs = {"token_features": torch.tensor([[[1., 2.], [3., 4.], [0., 0.]]]),
                  "token_valid": torch.tensor([[True, True, False]]),
                  "modality_ids": torch.tensor([[0, 0, -1]])}
    return FeatureBundleV1.from_tensors(
        global_features=torch.tensor([[.6, .8]]), source_record_digests=("d" * 64,),
        identity=identity, missing_mask=torch.tensor([[False, True, True, True, True]]), **kwargs)


class SharedFeatureContractTests(unittest.TestCase):
    def test_read_views_and_manifest_do_not_alias_bound_storage(self):
        event = SourceEvent("project:incident:17", "commit:abc", observed_at_ns=123,
                            time_start_ms=0, time_end_ms=100)
        spans = torch.tensor([[[0, 1], [2, 3], [0, 0]]])
        valid = torch.tensor([[True, True, False]])
        batch = SharedFeatureBatch.seal(fixture_bundle(), [event], extractor_sha256="e" * 64,
                                        char_spans=spans, char_valid=valid)
        original = batch.bundle_digest
        spans.fill_(90)
        batch.read_global().zero_()
        batch.read_tokens().zero_()
        batch.read_locations()["char_spans"].zero_()
        batch.manifest()["events"][0]["source_version"] = "forged"
        batch.verify_integrity()
        self.assertEqual(batch.bundle_digest, original)
        self.assertEqual(batch.read_locations()["char_spans"].tolist(), [[[0, 1], [2, 3], [0, 0]]])
        self.assertEqual(batch.events, (event,))

    def test_changed_retained_bytes_and_stale_generation_reject(self):
        batch = SharedFeatureBatch.seal(fixture_bundle(), [SourceEvent("x", "v1")],
                                        extractor_sha256="e" * 64)
        with self.assertRaises(FeatureBundleError):
            batch.require_identity(replace(batch.identity, generation=2))
        batch.bundle._tensors["global_features"].zero_()
        with self.assertRaises(FeatureBundleError):
            batch.read_global()

    def test_invalid_event_times_and_missing_source_identity_reject(self):
        for kwargs in ({"observed_at_ns": True}, {"time_start_ms": 1},
                       {"time_start_ms": 2, "time_end_ms": 1},
                       {"time_start_ms": -1, "time_end_ms": 1}):
            with self.subTest(kwargs=kwargs), self.assertRaises(SharedFeatureError):
                SourceEvent("source", "v1", **kwargs)
        with self.assertRaises(SharedFeatureError):
            SourceEvent("", "v1")

    def test_pooled_vector_cannot_be_given_invented_local_locations(self):
        bundle = fixture_bundle(detail=False)
        batch = SharedFeatureBatch.seal(bundle, [SourceEvent("x", "v1")],
                                        extractor_sha256="e" * 64)
        self.assertIsNone(batch.read_tokens())
        self.assertEqual(batch.read_locations(), {})
        with self.assertRaises(SharedFeatureError):
            SharedFeatureBatch.seal(bundle, batch.events, extractor_sha256="e" * 64,
                char_spans=torch.tensor([[[0, 1]]]), char_valid=torch.tensor([[True]]))

    def test_padding_or_reversed_character_spans_reject(self):
        for spans, valid in (([[[0, 1], [2, 3], [4, 5]]], [[True, True, True]]),
                             ([[[1, 0], [2, 3], [0, 0]]], [[True, True, False]])):
            with self.subTest(spans=spans), self.assertRaises(SharedFeatureError):
                SharedFeatureBatch.seal(fixture_bundle(), [SourceEvent("x", "v1")],
                    extractor_sha256="e" * 64, char_spans=torch.tensor(spans),
                    char_valid=torch.tensor(valid))

    def test_feature_identity_is_source_independent_but_request_key_is_not(self):
        one = SharedFeatureBatch.seal(fixture_bundle(), [SourceEvent("x", "v1")],
                                      extractor_sha256="e" * 64)
        two = SharedFeatureBatch.seal(fixture_bundle(), [SourceEvent("x", "v2")],
                                      extractor_sha256="e" * 64)
        self.assertEqual(one.feature_identity_digest, two.feature_identity_digest)
        self.assertNotEqual(one.cache_key, two.cache_key)
        self.assertNotEqual(one.bundle_digest, two.bundle_digest)


if __name__ == "__main__":
    unittest.main()
