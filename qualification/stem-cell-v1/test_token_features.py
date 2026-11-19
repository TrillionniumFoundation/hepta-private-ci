from dataclasses import replace
from hashlib import sha256
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest

import torch

from multirc_data import ReaderCase
from token_features import PUBLIC_FIELDS, TokenBank


class FakeTokenizer:
    cls_token_id, sep_token_id = 101, 102
    def num_special_tokens_to_add(self, pair=False):
        return 2

    def __call__(self, text, add_special_tokens=False, truncation=False):
        assert not truncation
        ids = [ord(char) for char in text]
        return {"input_ids": [101, *ids, 102] if add_special_tokens else ids}

    def prepare_for_model(self, payload, **kwargs):
        assert kwargs["truncation"] is False
        return dict(input_ids=[101, *payload, 102], attention_mask=[1] * (len(payload) + 2),
                    special_tokens_mask=[1, *([0] * len(payload)), 1])

    def pad(self, rows, **kwargs):
        width = max(len(row["input_ids"]) for row in rows)
        return {key: torch.tensor([row[key] + [0] * (width - len(row[key])) for row in rows])
                for key in ("input_ids", "attention_mask")}


class FakeModel(torch.nn.Module):
    def __init__(self):
        super().__init__()
        self.calls = 0
        self.saw_padding = False
        self.eval()

    def forward(self, input_ids, attention_mask):
        self.calls += 1
        self.saw_padding |= bool(attention_mask.eq(0).any())
        tokens = input_ids.float().unsqueeze(-1) + torch.arange(384) * .001
        tokens = torch.where(attention_mask.unsqueeze(-1).bool(), tokens, torch.full_like(tokens, 1e6))
        return SimpleNamespace(last_hidden_state=tokens)


class TokenFeaturesTests(unittest.TestCase):
    def bank(self, **kwargs):
        encoder = SimpleNamespace(tokenizer=FakeTokenizer(), model=FakeModel(), max_tokens=64,
                                  preprocess_digest="frozen-fake-encoder")
        return TokenBank(encoder, batch_size=3, chunk_tokens=8, **kwargs)

    def case(self, **kwargs):
        fields = dict(paragraph_id="p", question_id="q", answer_id="a", question="why",
                      candidate="yes", facts=("abcdefghi", "xy"), label=1, source_split="train",
                      source_hash=sha256(b"source paragraph").hexdigest())
        fields.update(kwargs)
        return ReaderCase(**fields)

    def test_exact_ids_survive_chunks_and_padding_with_deduplication(self):
        bank, case = self.bank(), self.case()
        bank.register([case, replace(case, answer_id="b", candidate="")])
        for text, values in bank.values.items():
            expected = torch.tensor([ord(c) for c in text]).float().unsqueeze(-1) + torch.arange(384) * .001
            torch.testing.assert_close(values, expected)
        self.assertEqual(bank.encoded_sequences, 5)
        self.assertEqual(bank.forward_batches, 2)
        self.assertTrue(bank.encoder.model.saw_padding)
        self.assertEqual(bank.values[""].shape, (0, 384))
        bank.register([case])
        self.assertEqual(bank.encoder.model.calls, 2)
        public = bank.public(case)
        self.assertEqual(public["sentence_indices"].tolist(), [[0, 0, 1]])
        self.assertEqual(public["fact_mask"].sum().item(), 11)
        recovered = torch.cat([chunk[mask] for chunk, mask in zip(public["facts"][0], public["fact_mask"][0])])
        torch.testing.assert_close(recovered, torch.cat([bank.values[f] for f in case.facts]))

    def test_inference_binding_excludes_targets_and_annotations_and_detects_changed_source(self):
        bank, case = self.bank(), self.case()
        bank.register([case])
        original = bank.public(case)
        changed_gold = replace(case, label=0, evidence_sentence_indices=(1,), sentence_ids=(1, 2))
        self.assertEqual(set(original), PUBLIC_FIELDS)
        self.assertEqual(bank.public(changed_gold)["feature_sha256"], original["feature_sha256"])
        deleted = bank.public(case, deleted=True)
        self.assertFalse(deleted["facts"].any())
        self.assertFalse(deleted["fact_mask"].any())
        self.assertNotEqual(original["feature_sha256"], deleted["feature_sha256"])
        torch.testing.assert_close(deleted["question"], original["question"])
        with self.assertRaisesRegex(ValueError, "source binding"):
            bank.public(replace(case, question="changed"))
        with self.assertRaisesRegex(ValueError, "identity changed"):
            bank.register([replace(case, facts=("changed",))])

    def test_bounds_reject_complete_case_before_encoder_execution(self):
        bank = self.bank(max_fact_chunks=2, max_role_tokens=4)
        with self.assertRaisesRegex(ValueError, "geometry"):
            bank.register([self.case()])
        with self.assertRaisesRegex(ValueError, "geometry"):
            bank.register([self.case(facts=("x",), question="toolong")])
        self.assertEqual(bank.encoder.model.calls, 0)
        with self.assertRaisesRegex(ValueError, "identity changed"):
            bank.register([self.case(facts=("x",)), self.case(facts=("y",))])
        self.assertEqual(bank.encoder.model.calls, 0)
        bank.encoder.model.train()
        with self.assertRaisesRegex(ValueError, "remain frozen"):
            bank.register([self.case(facts=("x",))])

    def test_roundtrip_and_tampering_are_bound_to_exact_text_tokens_and_tensor_bytes(self):
        bank, case = self.bank(), self.case()
        bank.register([case])
        with tempfile.TemporaryDirectory() as folder:
            cache = Path(folder) / "cache"
            bank.save_local(cache)
            restored = self.bank()
            restored.restore_local(cache)
            self.assertEqual(restored.public(case)["feature_sha256"], bank.public(case)["feature_sha256"])
            self.assertEqual(restored.encoded_sequences, bank.encoded_sequences)
            with (cache / "tokens.pt").open("ab") as stream:
                stream.write(b"tamper")
            with self.assertRaisesRegex(ValueError, "file or preprocessing"):
                self.bank().restore_local(cache)

    def test_dynamic_batch_preserves_empty_candidates_and_explicit_evidence_alignment(self):
        bank = self.bank()
        cases = (self.case(sentence_ids=(1, 2), evidence_sentence_indices=(1,)),
                 self.case(answer_id="b", candidate="", facts=("xy",)))
        bank.register(cases)
        batch = bank.batch(cases)
        batch.validate(384)
        self.assertEqual(batch.facts.shape, (2, 3, 6, 384))
        self.assertFalse(batch.candidate_mask[1].any())
        self.assertEqual(batch.evidence_supervision.tolist(), [True, False])
        torch.testing.assert_close(batch.evidence_targets[0], torch.tensor([.5, .5, 0.]))
        dataset = bank.dataset(cases).validate(384)
        selected = dataset.take(torch.tensor([1]))
        self.assertEqual(selected.facts.shape, (1, 1, 2, 384))
        self.assertEqual(selected.source_groups, (cases[1].source_hash,))


if __name__ == "__main__":
    unittest.main()
