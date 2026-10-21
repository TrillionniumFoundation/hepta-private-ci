import unittest
import importlib.util
from types import SimpleNamespace

from shared_encoder_batch import (
    FeatureRequest, FrozenFeature, FrozenLocalHfBackend, SharedStemEngine, digest_text,
)


D = lambda c: c * 64


class FakeBackend:
    simulated = True
    encoder_digest = D("a")
    preprocessor_digest = D("b")
    runtime_digest = D("c")

    def __init__(self, width=384, fail=None):
        self.calls = []
        self.width = width
        self.fail = fail

    def encode_many(self, texts, mode):
        self.calls.append((tuple(texts), mode))
        if self.fail == "wrong_count":
            return []
        if self.fail == "invalid_number":
            return [None] * len(texts)
        return [FrozenFeature.from_values([len(t) / 100.0] * self.width, 2, mode) for t in texts]


def req(number=1, text="identical input", scope="1", generation=1,
        frontier="2", encoder="a", preprocessor="b", runtime="c", mode="mean"):
    return FeatureRequest(
        f"request.{number}", f"cell.{number}", D(scope), generation,
        D(frontier), D(encoder), D(preprocessor), D(runtime), digest_text(text), text, mode,
    )


class BatchTests(unittest.TestCase):
    def test_one_encoder_invocation_shared_by_multiple_cells_in_one_scope(self):
        backend = FakeBackend()
        engine = SharedStemEngine(backend)
        result = engine.run([req(1), req(2), req(3)])
        self.assertEqual((result.distinct_inputs, result.backend_calls, result.backend_batch_widths), (1, 1, (1,)))
        self.assertEqual(len(backend.calls), 1)
        self.assertEqual(len({r.feature_digest for r in result.receipts}), 1)
        self.assertFalse(result.production_authorized)
        self.assertTrue(result.simulated)
        self.assertTrue(all(r.native_q24_compatible_width for r in result.receipts))
        self.assertEqual(result.cache_hits, 0)
        self.assertEqual(engine.run([req(4)]).cache_hits, 1)
        self.assertEqual(len(backend.calls), 1)

    def test_distinct_inputs_are_one_backend_batch_without_sequential_calls(self):
        backend = FakeBackend()
        engine = SharedStemEngine(backend)
        x = engine.run([req(1, "one"), req(2, "four"), req(3, "three")])
        self.assertEqual((x.distinct_inputs, x.backend_calls, x.backend_batch_widths), (3, 1, (3,)))
        self.assertEqual(len(backend.calls), 1)
        self.assertEqual(len({r.feature_digest for r in x.receipts}), 3)
        self.assertGreaterEqual(x.elapsed_ns, 0)

    def test_scope_mixing_denied_without_ever_calling_backend(self):
        backend = FakeBackend()
        engine = SharedStemEngine(backend)
        with self.assertRaisesRegex(ValueError, "mixed scope"):
            engine.run([req(1), req(2, scope="3")])
        with self.assertRaisesRegex(ValueError, "mixed scope"):
            engine.run([req(1), req(2, generation=2)])
        with self.assertRaisesRegex(ValueError, "mixed scope"):
            engine.run([req(1), req(2, frontier="4")])
        with self.assertRaisesRegex(ValueError, "mixed scope"):
            engine.run([req(1), req(2, mode="landmark8")])
        self.assertEqual(backend.calls, [])

    def test_distinct_scope_generation_and_revocation_frontier_cache_keys(self):
        backend = FakeBackend()
        engine = SharedStemEngine(backend)
        engine.run([req(1)])
        engine.run([req(2, scope="3")])
        engine.run([req(3, generation=2)])
        engine.run([req(4, frontier="4")])
        self.assertEqual(len(backend.calls), 4)
        engine.cache.invalidate_generation(D("1"), 2)
        engine.cache.invalidate_scope(D("3"))
        self.assertEqual(engine.run([req(5, generation=2)]).cache_hits, 1)
        self.assertEqual(engine.run([req(6)]).cache_hits, 0)

    def test_revoked_or_changed_weights_and_malformed_requests_rejected(self):
        backend = FakeBackend()
        engine = SharedStemEngine(backend)
        for case in [req(1, encoder="d"), req(1, preprocessor="d"), req(1, runtime="d")]:
            with self.assertRaises(ValueError):
                engine.run([case])
        invalid_digest = req(7).__dict__.copy()
        invalid_digest["input_digest"] = D("f")
        with self.assertRaisesRegex(ValueError, "input content digest mismatch"):
            engine.run([FeatureRequest(**invalid_digest)])
        with self.assertRaisesRegex(ValueError, "duplicate request_id"):
            engine.run([req(1), req(1)])
        self.assertEqual(backend.calls, [])

    def test_backend_wrong_count_or_nonfinite_refused_without_cache_poison(self):
        for kind in ("wrong_count", "invalid_number"):
            backend = FakeBackend(fail=kind)
            engine = SharedStemEngine(backend)
            with self.assertRaises(ValueError):
                engine.run([req(1)])
            self.assertEqual(engine.cache.size_bytes, 0)

    def test_boxed_python_float_cache_does_not_claim_raw_f32_budget(self):
        from shared_encoder_batch import ScopedFeatureCache

        key = req(1, "cache-test").cache_key()
        value = FrozenFeature.from_values([0.25] * 768, 20, "mean")
        payload_bytes = 768 * 4
        cache = ScopedFeatureCache(payload_bytes)
        cache.put(key, value)
        self.assertIsNone(cache.get(key))
        self.assertEqual(cache.size_bytes, 0)
        # Admission to a sufficiently large cache must charge key, object,
        # Python float storage and a conservative bookkeeping allowance.
        cache = ScopedFeatureCache(128 * 1024)
        cache.put(key, value)
        self.assertIs(cache.get(key), value)
        self.assertGreater(cache.size_bytes, payload_bytes)
        self.assertLessEqual(cache.size_bytes, cache.maximum_bytes)
        cache.invalidate_scope(req(1).scope_digest)
        self.assertEqual(cache.size_bytes, 0)

    def test_cache_eviction_is_bounded(self):
        backend = FakeBackend(width=8)
        engine = SharedStemEngine(backend, max_cache_bytes=3000)
        engine.run([req(1, "alpha")])
        engine.run([req(2, "beta")])
        self.assertGreater(engine.cache.size_bytes, 8 * 4)
        self.assertLessEqual(engine.cache.size_bytes, 3000)
        self.assertGreaterEqual(engine.cache.evictions, 1)
        engine.run([req(3, "alpha")])
        self.assertEqual(len(backend.calls), 3)

    def test_large_vector_is_never_silently_represented_as_native_512(self):
        backend = FakeBackend(width=768)
        engine = SharedStemEngine(backend)
        result = engine.run([req(1)])
        self.assertEqual(result.receipts[0].feature_width, 768)
        self.assertFalse(result.receipts[0].native_q24_compatible_width)

    def test_4096_logical_cells_are_bounded_batches_not_4096_encoder_invocations(self):
        backend = FakeBackend(width=8)
        engine = SharedStemEngine(backend, max_cache_bytes=4096)
        all_receipts = []
        counts = []
        for base in range(0, 4096, 32):
            observation = engine.run([req(base + i + 1) for i in range(32)])
            all_receipts.extend(observation.receipts)
            counts.append(observation.backend_calls)
        self.assertEqual(len(all_receipts), 4096)
        self.assertEqual(sum(counts), 1)
        self.assertEqual(len(backend.calls), 1)
        self.assertEqual(len({r.feature_digest for r in all_receipts}), 1)
        self.assertTrue(all(r.status == "shadow_only_not_authorized" for r in all_receipts))

    def test_frozen_feature_digest_is_float32_canonical(self):
        f = FrozenFeature.from_values([0.1, 0.2], 4, "mean")
        self.assertEqual(len(f.feature_digest), 64)
        self.assertEqual(f.values[0], 0.10000000149011612)
        with self.assertRaises(ValueError):
            FrozenFeature.from_values([float("nan")], 1, "mean")

    def test_no_raw_text_in_receipts_or_cache_values(self):
        phrase = "private to one scope: quince"
        engine = SharedStemEngine(FakeBackend())
        out = engine.run([req(1, text=phrase)])
        self.assertNotIn(phrase, repr(out))
        self.assertNotIn(phrase, repr(engine.cache._entries))

    def test_runtime_digest_is_part_of_cache_and_batch_identity(self):
        backend = FakeBackend()
        engine = SharedStemEngine(backend)
        a = engine.run([req(1)])
        with self.assertRaisesRegex(ValueError, "unselected or changed model"):
            engine.run([req(2, runtime="d")])
        b = engine.run([req(3)])
        self.assertNotEqual(a.batch_identity, b.batch_identity)
        self.assertEqual(b.cache_hits, 1)


    def test_optional_ephemeral_values_preserve_no_cache_and_receipt_only_api(self):
        engine = SharedStemEngine(FakeBackend(width=768), max_cache_bytes=0)
        standard = engine.run([req(1, "one")])
        self.assertFalse(hasattr(standard, "features"))
        observation, features = engine.run([
            req(2, "one"), req(3, "three"), req(4, "one")
        ], return_features=True)
        self.assertEqual(len(features), 3)
        self.assertEqual(features[0].feature_digest, features[2].feature_digest)
        self.assertEqual(observation.backend_batch_widths, (2,))
        self.assertEqual(engine.cache.size_bytes, 0)
        self.assertTrue(all(r.status == "shadow_only_not_authorized" for r in observation.receipts))

    def test_real_shared_engine_projection_binds_full_768_without_truncation(self):
        from stem_projection import Q, LowRankProjectionQ24, ProjectedStemEngine
        backend = FakeBackend(width=768)
        encoder = SharedStemEngine(backend, max_cache_bytes=0)
        a = [0] * 768
        a[-1] = Q
        projection = LowRankProjectionQ24(
            D("a"), D("b"), D("c"), D("d"), "mean", 768, 2, 1,
            tuple(a), (Q, 0), (0, 0),
        )
        bridge = ProjectedStemEngine(encoder, projection, maximum_projection_cache_bytes=4096)
        result = bridge.run([req(1, "one"), req(2, "one")])
        self.assertEqual(result.encoder_observation.backend_batch_widths, (1,))
        self.assertEqual(len(result.refs), 2)
        self.assertEqual(result.refs[0].vector_q24[0], result.refs[1].vector_q24[0])
        self.assertGreater(result.refs[0].vector_q24[0], 0)
        self.assertFalse(result.production_authorized)
        self.assertEqual(bridge.run([req(3, "one")]).projection_cache_hits, 1)


@unittest.skipUnless(importlib.util.find_spec("torch") is not None, "torch optional")
class RealTorchBatchPathTests(unittest.TestCase):
    def make_backend(self, *, left_padding=False):
        import torch

        class SyntheticTokenizer:
            def __call__(self, texts, *, return_tensors, padding, truncation):
                assert return_tensors == "pt" and padding and not truncation
                rows = [[int(v) for v in text.split()] for text in texts]
                width = max(len(row) for row in rows)
                if left_padding:
                    ids = [[0] * (width - len(row)) + row for row in rows]
                    masks = [[0] * (width - len(row)) + [1] * len(row) for row in rows]
                else:
                    ids = [row + [0] * (width - len(row)) for row in rows]
                    masks = [[1] * len(row) + [0] * (width - len(row)) for row in rows]
                return {
                    "input_ids": torch.tensor(ids),
                    "attention_mask": torch.tensor(masks),
                }

        class SyntheticModel(torch.nn.Module):
            def __init__(self):
                super().__init__()
                self.lookup = torch.nn.Embedding(32, 4)
                self.calls = 0

            def forward(self, input_ids, attention_mask):
                self.calls += 1
                return SimpleNamespace(last_hidden_state=self.lookup(input_ids))

        fake = FrozenLocalHfBackend.__new__(FrozenLocalHfBackend)
        fake.encoder_digest = D("a")
        fake.preprocessor_digest = D("b")
        fake.runtime_digest = D("c")
        fake.torch = torch
        fake.tokenizer = SyntheticTokenizer()
        fake.model = SyntheticModel().eval()
        fake.device = "cpu"
        fake.max_tokens = 8
        fake.invocations = 0
        # No snapshot exists here: injected weights are synthetic test fixtures.
        fake.simulated = True
        return fake

    def test_torch_forward_is_one_actual_batched_tensor_operation(self):
        model = self.make_backend()
        engine = SharedStemEngine(model)
        result = engine.run([req(1, "1 2"), req(2, "3 4 5"), req(3, "1 2")])
        self.assertEqual(model.model.calls, 1)
        self.assertEqual(model.invocations, 1)
        self.assertEqual((result.distinct_inputs, result.backend_batch_widths), (2, (2,)))
        self.assertFalse(result.production_authorized)
        self.assertTrue(result.simulated)
        self.assertEqual(result.receipts[0].feature_digest, result.receipts[2].feature_digest)
        self.assertNotEqual(result.receipts[0].feature_digest, result.receipts[1].feature_digest)

    def test_real_torch_forward_feeds_versioned_q24_projection(self):
        # Torch executes an actual tensor batch over synthetic local weights.
        # This is not evidence of a downloaded or audited pretrained Encoder.
        from stem_projection import Q, LowRankProjectionQ24, ProjectedStemEngine
        model = self.make_backend()
        engine = SharedStemEngine(model, max_cache_bytes=0)
        projector = LowRankProjectionQ24(
            D("a"), D("b"), D("c"), D("d"), "mean",
            4, 2, 1, (0, 0, 0, Q), (Q, Q), (0, 0),
        )
        bridge = ProjectedStemEngine(engine, projector)
        result = bridge.run([
            req(1, "1 2"), req(2, "3 4 5"), req(3, "1 2"),
        ])
        self.assertEqual(model.model.calls, 1)
        self.assertEqual(result.encoder_observation.backend_batch_widths, (2,))
        self.assertEqual(len(result.refs), 3)
        self.assertEqual(len(result.refs[0].vector_q24), 2)
        self.assertEqual(result.refs[0].vector_q24, result.refs[2].vector_q24)
        self.assertEqual(result.refs[0].projected_input_digest,
                         result.refs[2].projected_input_digest)
        self.assertFalse(result.production_authorized)

    def test_left_padded_batch_matches_unpadded_solo(self):
        model = self.make_backend(left_padding=True)
        batched = SharedStemEngine(model).run([
            req(1, "1 2"), req(2, "3 4 5"),
        ])
        single = SharedStemEngine(model, max_cache_bytes=0).run([
            req(3, "1 2"),
        ])
        self.assertEqual(
            batched.receipts[0].feature_digest,
            single.receipts[0].feature_digest,
        )
        self.assertEqual(model.invocations, 2)

    def test_torch_landmarks_and_frozen_token_cap(self):
        model = self.make_backend()
        engine = SharedStemEngine(model)
        result = engine.run([req(1, "1 2", mode="landmark8")])
        self.assertEqual(result.receipts[0].feature_width, 32)
        with self.assertRaisesRegex(ValueError, "token capacity"):
            engine.run([req(2, "1 2 3 4 5 6 7 8 9")])
        self.assertEqual(model.invocations, 1)


if __name__ == "__main__":
    unittest.main()
