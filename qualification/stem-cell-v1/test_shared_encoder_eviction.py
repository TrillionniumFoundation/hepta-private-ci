"""Regressions for actual SharedStemEngine; toy features are not model evidence."""

from dataclasses import replace
import unittest

from shared_encoder_batch import FeatureRequest, FrozenFeature, SharedStemEngine, digest_text


class ToyBackend:
    simulated = True
    encoder_digest, preprocessor_digest, runtime_digest = "1"*64, "2"*64, "3"*64

    def __init__(self):
        self.calls = []

    def encode_many(self, texts, representation):
        self.calls.append(tuple(texts))
        return [FrozenFeature.from_values([float(len(t)), 1.0], 1, representation) for t in texts]


def request(text, ident):
    return FeatureRequest(ident, "cell", "4"*64, 1, "5"*64, "1"*64, "2"*64, "3"*64,
                          digest_text(text), text)


class BatchEvictionTests(unittest.TestCase):
    def test_warm_hit_survives_cold_admission_eviction(self):
        backend = ToyBackend()
        engine = SharedStemEngine(backend)
        _, old = engine.run((request("old", "warm"),), return_features=True)
        engine.cache.maximum_bytes = engine.cache.size_bytes + 128
        result, features = engine.run((request("old", "hit"), request("new", "miss")), return_features=True)
        self.assertEqual(features[0], old[0])
        self.assertEqual((result.cache_hits, result.backend_calls, result.backend_batch_widths), (1, 1, (1,)))
        self.assertGreater(engine.cache.evictions, 0)
        self.assertEqual(backend.calls, [("old",), ("new",)])

    def test_repeated_hit_survives_many_cold_results(self):
        backend = ToyBackend()
        engine = SharedStemEngine(backend)
        engine.run((request("old", "warm"),))
        engine.cache.maximum_bytes = engine.cache.size_bytes + 128
        items = (request("old", "hit1"), request("new", "miss1"),
                 request("old", "hit2"), request("later", "miss2"))
        result, features = engine.run(items, return_features=True)
        self.assertEqual(features[0], features[2])
        self.assertEqual(result.cache_hits, 2)
        self.assertEqual(result.backend_batch_widths, (2,))

    def test_disabled_cache_still_coalesces_one_batch(self):
        backend = ToyBackend()
        engine = SharedStemEngine(backend, max_cache_bytes=0)
        result, features = engine.run((request("x", "a"), request("x", "b")), return_features=True)
        self.assertEqual(features[0], features[1])
        self.assertEqual((result.backend_calls, result.cache_bytes), (1, 0))

    def test_scope_mismatch_never_dispatches(self):
        backend = ToyBackend()
        engine = SharedStemEngine(backend)
        with self.assertRaises(ValueError):
            engine.run((request("x", "a"), replace(request("y", "b"), scope_digest="6"*64)))
        self.assertEqual(backend.calls, [])

    def test_poisoned_cold_batch_does_not_replace_warm_hit(self):
        backend = ToyBackend()
        engine = SharedStemEngine(backend)
        engine.run((request("old", "warm"),))
        old_key = request("old", "warm").cache_key()
        saved = engine.cache.get(old_key)
        backend.encode_many = lambda *_: [FrozenFeature((9.0,), 1, "mean", "0"*64)]
        with self.assertRaises(ValueError):
            engine.run((request("old", "hit"), request("new", "miss")))
        self.assertEqual(engine.cache.get(old_key), saved)


if __name__ == "__main__":
    unittest.main()
