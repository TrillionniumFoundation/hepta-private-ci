"""Run in the complete repository with its actual SharedStemEngine implementation."""

from dataclasses import replace
import unittest

from development_sharing import compare_shared_encoding
from shared_encoder_batch import FeatureRequest, FrozenFeature, SharedStemEngine, digest_text


class Backend:
    # Explicit instrument fixture, never mislabeled real pretrained weights.
    simulated = True
    encoder_digest = "c" * 64
    preprocessor_digest = "d" * 64
    runtime_digest = "e" * 64

    def __init__(self):
        self.calls = 0

    def encode_many(self, texts, representation):
        self.calls += 1
        return [FrozenFeature.from_values((float(len(text)), 1.), 2, representation) for text in texts]


def requests():
    return tuple(FeatureRequest(str(i), f'cell-{i}', 'a'*64, 1, 'b'*64, 'c'*64,
                                'd'*64, 'e'*64, digest_text('same text'), 'same text') for i in range(64))


class SharingTests(unittest.TestCase):
    def test_uses_existing_backend_and_measures_all_three_paths(self):
        report = compare_shared_encoding(SharedStemEngine(Backend()), requests())
        first = {r['arm']: r for r in report['arms'] if r['repetition'] == 0}
        self.assertEqual(first['uncached_single']['backend_calls'], 64)
        self.assertEqual(first['uncached_batch']['backend_calls'], 2)
        self.assertEqual(first['cached_batch']['backend_calls'], 1)
        self.assertTrue(report['simulated_encoder'])
        self.assertFalse(report['same_quality_established'])

    def test_whole_trial_preflight_blocks_second_batch_scope_change(self):
        backend = Backend()
        batch = list(requests())
        batch[-1] = replace(batch[-1], scope_digest='f'*64)
        with self.assertRaises(ValueError):
            compare_shared_encoding(SharedStemEngine(backend), tuple(batch))
        self.assertEqual(backend.calls, 0)

    def test_duplicate_and_boolean_budget_rejected_before_backend(self):
        backend = Backend()
        engine = SharedStemEngine(backend)
        with self.assertRaises(ValueError):
            compare_shared_encoding(engine, requests() + (requests()[0],))
        with self.assertRaises(ValueError):
            compare_shared_encoding(engine, requests(), cache_bytes=True)
        self.assertEqual(backend.calls, 0)


if __name__ == '__main__':
    unittest.main()
