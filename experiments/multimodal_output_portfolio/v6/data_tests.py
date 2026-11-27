"""Source-pair and public-observation boundary tests using explicit fixtures."""

import hashlib
import unittest

import torch

from .data import SourceCorpus, SourceSplit, make_batch, render_tokens


class PairBoundaryTests(unittest.TestCase):
    def setUp(self):
        # Synthetic fixtures test indexing only; no benchmark evidence uses them.
        pixels = torch.arange(20, dtype=torch.uint8).reshape(20, 1, 1, 1).expand(-1, 1, 28, 28).clone()
        hashes = tuple(hashlib.sha256(bytes([i]) * 784).hexdigest() for i in range(20))
        split = SourceSplit(pixels, torch.arange(20) % 10,
                            tuple(f"fixture:{i}" for i in range(20)), hashes)
        self.corpus = SourceCorpus({"test": split}, {"fixture_only": True})

    def test_evaluation_offsets_do_not_reuse_source_images(self):
        first = make_batch(self.corpus, "test", 3, 3, offset=0)
        second = make_batch(self.corpus, "test", 3, 3, offset=3)
        first_ids = {item for pair in first.source_ids for item in pair}
        second_ids = {item for pair in second.source_ids for item in pair}
        self.assertEqual(len(first_ids), 6)
        self.assertTrue(first_ids.isdisjoint(second_ids))
        with self.assertRaises(ValueError):
            make_batch(self.corpus, "test", 2, 3, offset=9)

    def test_missing_source_hint_is_public_and_can_be_removed(self):
        with_hint = make_batch(self.corpus, "test", 3, 3, "missing", offset=0)
        without_hint = make_batch(self.corpus, "test", 3, 3, "missing", offset=0, drop_hint=True)
        self.assertTrue(torch.equal(with_hint.target.pixels, without_hint.target.pixels))
        self.assertTrue(torch.equal(with_hint.observation.pixels, without_hint.observation.pixels))
        self.assertFalse(torch.equal(with_hint.observation.text_tokens, without_hint.observation.text_tokens))
        self.assertFalse(hasattr(with_hint.observation, "labels"))
        self.assertFalse(hasattr(with_hint.observation, "target"))

    def test_renderer_preserves_bad_grammar_and_content(self):
        self.assertEqual(render_tokens([1, 4, 8, 14, 2, 3]), "right greater 0")


if __name__ == "__main__":
    unittest.main()
