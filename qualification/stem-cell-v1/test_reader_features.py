from dataclasses import replace
from hashlib import sha256
from types import SimpleNamespace
import unittest

import torch

from multirc_data import ReaderCase
from reader_features import SentenceBank


class FakeTokenizer:
    def ids(self, text):
        pieces = []
        for word in text.split():
            pieces.extend([ord(char) % 97 + 1 for char in word] if len(word) > 20
                          else [sum(map(ord, word)) % 97 + 1])
        return [101, *pieces, 102]

    def __call__(self, text, return_tensors=None, padding=False, truncation=False):
        if truncation:
            raise AssertionError("feature path silently enabled truncation")
        if isinstance(text, str):
            ids = self.ids(text)
            return dict(input_ids=ids, attention_mask=[1] * len(ids))
        rows = [self.ids(value) for value in text]
        width = max(map(len, rows))
        return dict(input_ids=torch.tensor([row + [0] * (width - len(row)) for row in rows]),
                    attention_mask=torch.tensor([[1] * len(row) + [0] * (width - len(row)) for row in rows]))


class FakeModel:
    def __init__(self):
        self.calls = 0
        self.saw_padding = False

    def __call__(self, input_ids, attention_mask):
        self.calls += 1
        self.saw_padding |= bool(attention_mask.eq(0).any())
        offsets = torch.arange(384, dtype=torch.float32) * .001
        real = input_ids.float().unsqueeze(-1) + offsets
        # Padding deliberately carries extreme values: unmasked pooling fails.
        hidden = torch.where(attention_mask.unsqueeze(-1).bool(), real, torch.full_like(real, 10000))
        return SimpleNamespace(last_hidden_state=hidden)


class ReaderFeaturesTests(unittest.TestCase):
    def bank(self, batch_size=2):
        encoder = SimpleNamespace(tokenizer=FakeTokenizer(), model=FakeModel(),
                                  max_tokens=32, preprocess_digest="fake-frozen-preprocessing")
        return SentenceBank(encoder, batch_size=batch_size, chunk_tokens=8)

    def case(self, answer="A", facts=("red green", "one two three four five"), label=0):
        return ReaderCase("p", "q", answer, "Which color?", answer, facts, label,
                          "train", sha256("\n".join(facts).encode()).hexdigest())

    def test_chunking_preserves_all_words_and_overflow_is_explicit(self):
        bank = self.bank()
        text = " ".join(f"word{i}" for i in range(23))
        chunks = bank.chunks(text)
        self.assertEqual(" ".join(chunks).split(), text.split())
        self.assertGreater(len(chunks), 1)
        self.assertTrue(all(len(bank.encoder.tokenizer.ids(chunk)) <= 8 for chunk in chunks))
        with self.assertRaises(ValueError):
            bank.chunks("x" * 40)
        with self.assertRaises(ValueError):
            bank.register([self.case(facts=("word",) * 129)])
        with self.assertRaises(ValueError):
            bank.register([replace(self.case(), question=" ".join(["question"] * 40))])
        self.assertEqual(bank.encoder.model.calls, 0)

    def test_dedup_counts_actual_batches_and_masked_pool_ignores_padding(self):
        bank = self.bank()
        cases = [self.case(), self.case("A longer candidate", facts=("red green",), label=1)]
        bank.register(cases)
        self.assertEqual(bank.encoded_sequences, 4)
        self.assertEqual(bank.forward_batches, 2)
        self.assertEqual(bank.encoder.model.calls, 2)
        self.assertTrue(bank.encoder.model.saw_padding)
        for text, vector in bank.vectors.items():
            ids = bank.encoder.tokenizer.ids(text)
            expected = sum(ids) / len(ids) + torch.arange(384) * .001
            torch.testing.assert_close(vector, expected)
        bank.register(cases)
        self.assertEqual(bank.encoder.model.calls, 2)
        packed = bank.batch(cases)
        self.assertEqual(packed.mask.tolist(), [[True, True], [True, False]])
        self.assertTrue(torch.equal(packed.facts[1, 1], torch.zeros(384)))

    def test_label_never_changes_public_features_and_deletion_changes_provenance(self):
        bank = self.bank()
        case = self.case()
        bank.register([case])
        original = bank.public(case)
        relabeled = bank.public(replace(case, label=1))
        self.assertEqual(original["feature_sha256"], relabeled["feature_sha256"])
        self.assertEqual(set(original), {"facts", "query", "mask", "feature_sha256", "source_sha256"})
        self.assertTrue(torch.equal(original["facts"], relabeled["facts"]))
        deleted = bank.public(case, deleted=True)
        self.assertFalse(deleted["mask"].any())
        self.assertFalse(deleted["facts"].any())
        self.assertNotEqual(original["feature_sha256"], deleted["feature_sha256"])
        torch.testing.assert_close(original["query"], deleted["query"])


if __name__ == "__main__":
    unittest.main()
