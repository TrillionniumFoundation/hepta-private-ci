"""Real local Transformer forwards verify plumbing, not checkpoint quality."""

from dataclasses import replace
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import torch

from feature_bundle import FeatureBundleV1
from real_encoder import CANDIDATES, FrozenRealEncoder, pool_features
from shared_feature_contract import SharedFeatureError, SourceEvent
from shared_feature_extract import SharedFeatureEncoder
from teacher_snapshot import inventory


class SharedFeatureExtractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from tokenizers import Tokenizer, models, pre_tokenizers
        from transformers import ModernBertConfig, ModernBertModel, PreTrainedTokenizerFast
        cls.directory = tempfile.TemporaryDirectory()
        cls.root = Path(cls.directory.name)
        config = ModernBertConfig(vocab_size=8, hidden_size=8, intermediate_size=16,
            num_hidden_layers=1, num_attention_heads=2, pad_token_id=0,
            cls_token_id=1, sep_token_id=2, bos_token_id=1, eos_token_id=2)
        torch.manual_seed(73)
        ModernBertModel(config).save_pretrained(cls.root)
        tokenizer = Tokenizer(models.WordLevel(
            {"[PAD]": 0, "[UNK]": 1, "alpha": 2, "beta": 3}, unk_token="[UNK]"))
        tokenizer.pre_tokenizer = pre_tokenizers.Whitespace()
        PreTrainedTokenizerFast(tokenizer_object=tokenizer, pad_token="[PAD]",
            unk_token="[UNK]").save_pretrained(cls.root)
        cls.inventory = inventory(cls.root)
        cls.weight_hash = next(x["sha256"] for x in cls.inventory["entries"]
                               if x["path"] == "model.safetensors")

    @classmethod
    def tearDownClass(cls):
        cls.directory.cleanup()

    def setUp(self):
        with patch.dict(CANDIDATES["granite97m"], {"weight_sha256": self.weight_hash, "width": 8}):
            self.owner = FrozenRealEncoder(candidate="granite97m", snapshot=self.root,
                revision=CANDIDATES["granite97m"]["revision"],
                expected_inventory_sha256=self.inventory["inventory_sha256"],
                operator_accepted_terms=True)
        self.encoder = SharedFeatureEncoder(self.owner)
        self.texts = ["alpha beta", "alpha"]
        self.events = [SourceEvent("incident:1", "revision:1", observed_at_ns=123),
                       SourceEvent("incident:2", "revision:1")]

    def extract(self, **kwargs):
        return self.encoder.extract_text(self.texts, events=self.events,
            expected_identity=self.owner.identity, **kwargs)

    def test_one_forward_exposes_actual_states_and_source_character_spans(self):
        captured = []
        handle = self.owner._model.register_forward_hook(
            lambda module, args, output: captured.append(output.last_hidden_state.detach().clone()))
        try:
            batch = self.extract(retention="tokens")
        finally:
            handle.remove()
        self.assertEqual(len(captured), 1)
        mask = torch.tensor([[1, 1], [1, 0]])
        torch.testing.assert_close(batch.read_tokens(), captured[0] * mask.unsqueeze(-1))
        torch.testing.assert_close(batch.read_global(), pool_features(captured[0], mask, "cls"))
        self.assertEqual(batch.read_locations()["char_spans"].tolist(),
                         [[[0, 5], [6, 10]], [[0, 5], [0, 0]]])
        self.assertEqual(batch.read_locations()["char_valid"].tolist(), [[True, True], [True, False]])
        self.assertEqual(batch.manifest()["token_time_alignment"], "absent")
        self.assertEqual(self.encoder.last_receipt["model_forward_calls"], 1)
        self.assertEqual(self.owner._calls, 1)
        self.assertEqual(self.encoder.last_receipt["retained_tensor_bytes"], 306)

    def test_global_only_avoids_token_snapshot_and_preserves_pooling(self):
        detailed = self.extract(retention="tokens")
        with patch.object(FeatureBundleV1, "snapshot", side_effect=AssertionError("unneeded snapshot")), \
                patch.object(FeatureBundleV1, "read_tokens", side_effect=AssertionError("unneeded copy")):
            global_only = self.extract()
        self.assertIsNone(global_only.read_tokens())
        self.assertEqual(global_only.read_locations(), {})
        torch.testing.assert_close(global_only.read_global(), detailed.read_global())
        self.assertEqual(global_only.retained_tensor_bytes, 74)
        self.assertEqual(global_only.feature_identity_digest, detailed.feature_identity_digest)
        self.assertNotEqual(global_only.cache_key, detailed.cache_key)
        self.assertEqual(self.owner._calls, 2)

    def test_stale_identity_or_changed_preprocessing_rejects_before_tokenization(self):
        with patch.object(self.owner, "_tokenizer", side_effect=AssertionError("too late")):
            with self.assertRaisesRegex(SharedFeatureError, "stale"):
                self.encoder.extract_text(self.texts, events=self.events,
                    expected_identity=replace(self.owner.identity, generation=2))
        self.owner.prefix = "changed prefix "
        with self.assertRaisesRegex(SharedFeatureError, "stale"):
            self.extract()
        self.assertEqual(self.owner._calls, 0)

    def test_actual_text_and_source_revision_are_independently_bound(self):
        first = self.extract()
        self.events[0] = replace(self.events[0], source_version="revision:2")
        revised = self.extract()
        self.texts[0] = "beta alpha"
        changed = self.extract()
        self.assertNotEqual(first.source_record_digests[0], revised.source_record_digests[0])
        self.assertNotEqual(revised.source_record_digests[0], changed.source_record_digests[0])
        self.assertEqual(first.feature_identity_digest, changed.feature_identity_digest)
        self.assertEqual(first.source_record_digests[1], changed.source_record_digests[1])

    def test_invalid_detail_budget_fails_before_model_but_global_still_fits(self):
        with patch("shared_feature_extract.MAX_ELEMENTS", 30):
            with self.assertRaisesRegex(SharedFeatureError, "budget"):
                self.extract(retention="tokens")
            self.assertEqual(self.owner._calls, 0)
            self.extract()
        self.assertEqual(self.owner._calls, 1)

    def test_missing_events_and_unfrozen_owner_reject_before_forward(self):
        with self.assertRaises(SharedFeatureError):
            self.encoder.extract_text(self.texts, events=[], expected_identity=self.owner.identity)
        with self.assertRaises(SharedFeatureError):
            self.extract(retention="invented-detail")
        self.owner._model.train()
        with self.assertRaisesRegex(SharedFeatureError, "frozen"):
            self.extract()
        self.assertEqual(self.owner._calls, 0)

    def test_media_dependency_versions_change_feature_identity(self):
        with patch("shared_feature_extract.version", return_value="changed-runtime"):
            changed = SharedFeatureEncoder(self.owner)
        self.assertNotEqual(changed.extractor_sha256, self.encoder.extractor_sha256)
        self.assertEqual(changed.owner.identity, self.encoder.owner.identity)

    def test_text_only_owner_rejects_media_without_a_forward(self):
        with self.assertRaisesRegex(SharedFeatureError, "EmbeddingGemma2"):
            self.encoder.extract_records([{"text": "alpha", "image": "absent.png"}],
                media_root=self.root, events=self.events[:1], expected_identity=self.owner.identity)
        self.assertEqual(self.owner._calls, 0)


if __name__ == "__main__":
    unittest.main()
