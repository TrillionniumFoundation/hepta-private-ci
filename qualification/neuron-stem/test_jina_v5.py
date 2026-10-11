"""Offline conformance tests: no Hugging Face downloads or model weights."""
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from jina_v5 import FrozenJinaV5, MODELS, validate_identity, verify_vector_matrix
from jina_v5_multimodal import audit_multimodal, paired_ranking, safe_media
from jina_v5_trial import choose_train_rows, render_case
from statistical_gate import qualify
from q24_bridge import (Q24, quantize_q24, shadow_feature_digest,
                        rust_stem_feature_vector_digest_v1,
                        rust_stem_encoder_pipeline_digest_v1)


REV = "a" * 40


class FakeModel:
    def __init__(self, dimensions):
        self.dimensions = dimensions
        self.calls = []
        self.max_seq_length = None

    def eval(self):
        return self

    def _encode(self, intent, values, **options):
        self.calls.append((intent, tuple(values), options))
        return [[float((sum(map(ord, str(x))) % 7) + 1)] +
                [0.5] * (self.dimensions - 1) for x in values]

    def encode_document(self, values, **options):
        return self._encode("document", values, **options)

    def encode_query(self, values, **options):
        return self._encode("query", values, **options)


class Q24Tests(unittest.TestCase):
    def test_ties_to_even_and_dimension_reject(self):
        self.assertEqual(quantize_q24([0.5 / Q24, 1.5 / Q24, 2.5 / Q24]),
                         [0, 2, 2])
        self.assertEqual(quantize_q24([-0.5 / Q24, -1.5 / Q24]), [0, -2])
        with self.assertRaises(ValueError):
            quantize_q24([0.0] * 513)
        with self.assertRaises(ValueError):
            quantize_q24([9.0])
        self.assertFalse(shadow_feature_digest([.5])["production_receipt_verified"])
        self.assertEqual(
            rust_stem_feature_vector_digest_v1([.5, -.25]),
            "148ae0b91ab97729f72d745e989ac7b03614438cc6030edb2f79748049c70b59",
        )
        self.assertFalse(shadow_feature_digest([.5])["rust_owner_authenticated"])
        pipeline = rust_stem_encoder_pipeline_digest_v1(
            "jina-v5-text-nano", 7, 2,
            hashlib.sha256(b"stem").hexdigest(),
            hashlib.sha256(b"tokenizer").hexdigest(),
            hashlib.sha256(b"preprocessor").hexdigest(),
            hashlib.sha256(b"matryoshka256-q24").hexdigest(),
        )
        self.assertEqual(
            pipeline,
            "67d4c68e2092bcde7fdccca0386fb39442deac2a0ecb8ff8d98a5510067f5504",
        )
        self.assertNotEqual(
            pipeline,
            rust_stem_encoder_pipeline_digest_v1(
                "jina-v5-text-nano", 8, 2,
                hashlib.sha256(b"stem").hexdigest(),
                hashlib.sha256(b"tokenizer").hexdigest(),
                hashlib.sha256(b"preprocessor").hexdigest(),
                hashlib.sha256(b"matryoshka256-q24").hexdigest(),
            ),
        )


    def test_rust_stable_id_and_pipeline_contract_rejects_cross_language_drift(self):
        digest = hashlib.sha256(b"valid-weight-artifact").hexdigest()
        source = (digest, digest, digest, digest)

        def pipeline(model_id="jina-v5-text-nano", generation=7, digests=source):
            return rust_stem_encoder_pipeline_digest_v1(
                model_id, generation, 256, *digests)

        for invalid_id in ("", "中文", "has space", "has/slash", "x" * 129):
            with self.subTest(model_id=invalid_id), self.assertRaises(ValueError):
                pipeline(model_id=invalid_id)
        for invalid_gen in (0, -1, True, 1 << 64):
            with self.subTest(generation=invalid_gen), self.assertRaises(ValueError):
                pipeline(generation=invalid_gen)
        for position in range(4):
            digests = list(source)
            digests[position] = "0" * 64
            with self.subTest(position=position), self.assertRaises(ValueError):
                pipeline(digests=tuple(digests))
        self.assertEqual(pipeline(), pipeline())
        self.assertNotEqual(pipeline(), pipeline(generation=8))
        self.assertEqual(len(pipeline(model_id="scope:stem-1")), 64)


class StemTests(unittest.TestCase):
    def make_stem(self, model="jina-v5-text-nano", **kwargs):
        return FrozenJinaV5(
            model, REV, model_factory=lambda spec: FakeModel(spec.dimensions),
            task="classification", dimension=256, max_tokens=512, **kwargs)

    def test_revision_and_adapter_fail_closed(self):
        with self.assertRaises(ValueError):
            validate_identity("jina-v5-text-nano", "main", "classification", 256, "text", 512)
        with self.assertRaises(ValueError):
            validate_identity("jina-v5-text-nano", REV, "not-a-task", 256, "text", 512)
        with self.assertRaises(ValueError):
            validate_identity("jina-v5-text-nano", REV, "retrieval", 1024, "text", 512)
        with self.assertRaises(ValueError):
            validate_identity("jina-v5-text-nano", REV, "retrieval", 256, "vision", 512)
        with self.assertRaises(ValueError):
            FrozenJinaV5("jina-v5-text-nano", REV, allow_pinned_remote_code=False)

    def test_model_registry_matches_actual_spec(self):
        registry = json.loads(Path(__file__).with_name("models.json").read_text())
        self.assertEqual({m["id"] for m in registry["jina_v5_models"]}, set(MODELS))
        for row in registry["jina_v5_models"]:
            spec = MODELS[row["id"]]
            self.assertEqual((row["repository"], row["parameters"], row["embedding_dimension"]),
                             (spec.repository, spec.parameters, spec.dimensions))
            self.assertTrue(row["requires_pinned_remote_code_review"])

    def test_shape_nonfinite_and_mrl_norm(self):
        with self.assertRaises(ValueError):
            verify_vector_matrix([[1, 2]], 1, 768, 256)
        with self.assertRaises(ValueError):
            verify_vector_matrix([[0.] * 768], 1, 768, 256)
        with self.assertRaises(ValueError):
            verify_vector_matrix([[float("nan")] + [1.] * 767], 1, 768, 256)
        vec = verify_vector_matrix([[3., 4.] + [0.] * 766], 1, 768, 256)[0]
        self.assertAlmostEqual(vec[0], .6)
        self.assertAlmostEqual(vec[1], .8)

    def test_dedup_scope_and_generation_fence(self):
        stem = self.make_stem()
        kwargs = dict(scope_id="s", principal_id="p")
        vectors, trace = stem.encode_batch(["hello", "hello"], **kwargs)
        self.assertEqual(trace["encoder_examples"], 1)
        self.assertEqual(stem.encoder_calls, 1)
        self.assertEqual(vectors[0], vectors[1])
        _, trace = stem.encode_batch(["hello"], **kwargs)
        self.assertEqual(trace["cache_hits"], 1)
        stem.encode_batch(["hello"], scope_id="different", principal_id="p")
        stem.encode_batch(["hello"], scope_id="s", principal_id="other")
        stem.encode_batch(["hello"], **kwargs, generation=2)
        stem.encode_batch(["hello"], **kwargs, authority_epoch=2)
        self.assertEqual(stem.encoder_examples, 5)

    def test_no_cached_media_path_and_task_intent(self):
        stem = self.make_stem("jina-v5-omni-nano", modality="vision")
        stem.encode_batch(["image.jpg"], scope_id="s", principal_id="p", intent="query")
        stem.encode_batch(["image.jpg"], scope_id="s", principal_id="p", intent="query")
        self.assertEqual(stem.cache_hits, 0)
        self.assertEqual(stem.encoder_examples, 2)
        self.assertEqual(stem.model.calls[0][0], "query")

    def test_cache_capacity_and_bad_scope(self):
        stem = self.make_stem(cache_entries=1)
        stem.encode_batch(["hello", "world"], scope_id="s", principal_id="p")
        self.assertLessEqual(len(stem.cache), 1)
        with self.assertRaises(ValueError):
            stem.encode_batch(["hello"], scope_id="", principal_id="p")

    def test_task_representation_no_phantom_attention(self):
        case = {"state": "S", "question": "Q", "options": ["yes", "no"]}
        self.assertIn("Question: Q", render_case(case, "joint"))
        self.assertNotIn("Question", render_case(case, "state"))
        with self.assertRaises(ValueError):
            render_case(case, "cross_attention")


class MultimodalTests(unittest.TestCase):
    def test_safe_media_digest_and_path_fence(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            image = root / "x.png"
            image.write_bytes(b"fixture-image")
            row = {"modality": "image", "path": "x.png",
                   "media_sha256": hashlib.sha256(b"fixture-image").hexdigest()}
            file, observed = safe_media(root, row)
            self.assertEqual(Path(file), image)
            self.assertEqual(observed, row["media_sha256"])
            with self.assertRaises(ValueError):
                safe_media(root, {**row, "path": "../x.png"})
            with self.assertRaises(ValueError):
                safe_media(root, {**row, "media_sha256": "0" * 64})

    def test_pair_rank_and_duplicate_positive_rejected(self):
        def item(case, text, media):
            return {"case_id": case, "scope_id": "s", "split": "test",
                    "modality": "image", "media_sha256": "b" * 64,
                    "text_vector": text, "media_vector": media,
                    "text_wall_ms": 1., "media_wall_ms": 2., "rss_bytes": 10}
        out = paired_ranking([item("a", (1., 0.), (1., 0.)),
                              item("b", (0., 1.), (0., 1.))])
        self.assertEqual([x["recall_at_1"] for x in out], [1, 1])
        row = {"case_id": "a", "group_id": "g1", "scope_id": "s", "split": "test",
               "modality": "image", "path": "a.png", "paired_text": "same",
               "media_sha256": "a" * 64, "event_time": "2026-01-01T00:00:00Z"}
        with self.assertRaises(ValueError):
            audit_multimodal([row, {**row, "case_id": "b", "group_id": "g2"}])


    def test_media_temporal_order_and_content_leakage(self):
        base = {"scope_id": "s", "modality": "image", "path": "a.png"}
        cases = [
            {**base, "case_id": "a", "group_id": "a", "split": "test",
             "paired_text": "A", "media_sha256": "a" * 64,
             "event_time": "2026-01-01T00:00:00Z"},
            {**base, "case_id": "b", "group_id": "b", "split": "test",
             "paired_text": "B", "media_sha256": "b" * 64,
             "event_time": "2026-01-01T00:00:01Z"},
            {**base, "case_id": "c", "group_id": "c", "split": "future",
             "paired_text": "C", "media_sha256": "c" * 64,
             "event_time": "2026-01-02T00:00:00Z"},
            {**base, "case_id": "d", "group_id": "d", "split": "future",
             "paired_text": "D", "media_sha256": "d" * 64,
             "event_time": "2026-01-02T00:00:01Z"},
        ]
        self.assertTrue(audit_multimodal(cases)["future_temporal_order_checked"])
        with self.assertRaises(ValueError):
            audit_multimodal([*cases[:2], {**cases[2],
                                          "event_time": "2025-12-31T23:00:00Z"}, cases[3]])
        with self.assertRaises(ValueError):
            audit_multimodal([*cases[:2], {**cases[2], "media_sha256": "a" * 64}, cases[3]])


class GateTests(unittest.TestCase):
    def make_data(self):
        data, baseline, candidate = [], [], []
        for split, count, day in (("train", 2, 1), ("calibration", 2, 2),
                                  ("test", 3, 3), ("future", 40, 4), ("ood", 2, 5)):
            for index in range(count):
                ident = f"{split}-{index}"
                data.append({"case_id": ident, "scope_id": "s", "group_id": ident,
                             "task_id": "decision", "split": split, "language": "zh",
                             "state": "S" + ident, "question": "Q",
                             "options": ["yes", "no"], "label": 0,
                             "event_time": f"2026-01-0{day}T00:00:00Z"})
                common = {"case_id": ident, "scope_id": "s", "model_revision": REV,
                          "encoder_digest": "encoder", "head_digest": "head",
                          "runtime_generation": 1, "status": "Succeeded"}
                if split != "train":
                    baseline.append({**common, "model_id": "old",
                                     "probabilities": [.3, .7]})
                    candidate.append({**common, "model_id": "new",
                                      "probabilities": [.99, .01]})
        return data, baseline, candidate

    def test_paired_future_quality_only_never_promotion(self):
        rows, before, after = self.make_data()
        report = qualify(rows, before, after, replicates=1000)
        self.assertTrue(report["offline_quality_gate_passed"])
        self.assertFalse(report["production_promotion_permitted"])
        self.assertFalse(report["ndu_independent_signature_verified"])
        self.assertEqual(report["evaluation"]["future"]["independent_groups"], 40)
        report = qualify(rows, before, before, replicates=1000)
        self.assertFalse(report["offline_quality_gate_passed"])

    def test_insufficient_future_independence(self):
        rows, before, after = self.make_data()
        report = qualify(rows, before, after, min_future_groups=41, replicates=1000)
        self.assertFalse(report["offline_quality_gate_passed"])
        with self.assertRaises(ValueError):
            qualify(rows, before, after, replicates=10)


if __name__ == "__main__":
    unittest.main()
