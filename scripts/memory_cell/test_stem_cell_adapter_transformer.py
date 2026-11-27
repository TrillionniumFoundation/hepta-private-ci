"""Tiny real-Transformer mechanics fixtures, not pretrained quality evidence."""

from dataclasses import dataclass, replace
from pathlib import Path
import tempfile
import unittest

import torch
from peft import LoraConfig, get_peft_model
from transformers import BertConfig, BertForSequenceClassification

from pretrained import frozen_digest
from selector_head import Features, Supervision, TrainingCut
from stem_cell_adapter import DifferentiatedEncoder


@dataclass(frozen=True)
class Query:
    identity: str = "train"
    content: str = "Which passage supports this question?"
    observed_at: int = 2
    scope: str = "scope"


@dataclass(frozen=True)
class Window:
    name: str
    text: str
    observed_at: int = 1

    def identity(self):
        return self.name


class Pool:
    windows = (Window("a", "warm topic"), Window("b", "cold topic"))
    inspected = ({"root": "root"},)

    def seal(self):
        return "pool"

    def revalidate(self, query, revoked):
        if query.scope != "scope" or "root" in revoked:
            raise ValueError("denied source")


class Tokenizer:
    def encode(self, *args, **kwargs):
        return [1, 2, 3]

    def __call__(self, questions, passages, **kwargs):
        ids = torch.tensor([[1, 2 if "warm" in p else 3, 4] for p in passages])
        return {"input_ids": ids, "attention_mask": torch.ones_like(ids)}


def tiny_encoder():
    encoder = object.__new__(DifferentiatedEncoder)
    with torch.random.fork_rng(devices=[]):
        torch.manual_seed(987)
        base = BertForSequenceClassification(
            BertConfig(
                vocab_size=16,
                hidden_size=8,
                intermediate_size=16,
                num_hidden_layers=1,
                num_attention_heads=2,
                num_labels=1,
                hidden_dropout_prob=0.0,
                attention_probs_dropout_prob=0.0,
                max_position_embeddings=32,
            )
        )
        base.requires_grad_(False)
        encoder.model = get_peft_model(
            base,
            LoraConfig(
                r=4,
                lora_alpha=8,
                lora_dropout=0.0,
                target_modules=["query", "value"],
                bias="none",
            ),
        ).eval()
    encoder.dimension = 8
    encoder.tokenizer = Tokenizer()
    encoder.parent_identity = encoder.identity = "test-parent"
    encoder.base_digest = frozen_digest(encoder.model)
    encoder.roots = set()
    encoder.frozen = encoder.quarantined = False
    encoder.adapter_digest = encoder.receipt = None
    return encoder


def row(identity="train"):
    return Supervision(
        Features(
            identity,
            "family",
            "test-parent",
            "pool",
            ("a", "b"),
            frozenset({"root"}),
            torch.zeros(2, 8),
            torch.zeros(2),
        ),
        (0,),
    )


def cut():
    return TrainingCut(
        frozenset({"train", "second"}),
        frozenset({"family"}),
        frozenset({"root"}),
        frozenset({"held-out"}),
        "fixture-admission",
    )


def fit(encoder, rows=(row(),), steps=4):
    queries = {
        r.features.question_id: Query(identity=r.features.question_id) for r in rows
    }
    pools = {identity: Pool() for identity in queries}
    return encoder.fit(rows, queries, pools, cut(), revoked=set(), steps=steps)


class AdapterTests(unittest.TestCase):
    def test_real_lora_update_preserves_base_and_freezes_representation(self):
        encoder = tiny_encoder()
        base = frozen_digest(encoder.model)
        before = encoder.tensor_bytes()
        receipt = fit(encoder)
        self.assertGreater(receipt["adapter_delta_squared_norm"], 0)
        self.assertNotEqual(encoder.tensor_bytes(), before)
        self.assertEqual(frozen_digest(encoder.model), base)
        self.assertTrue(encoder.frozen)
        self.assertFalse(any(p.requires_grad for p in encoder.model.parameters()))
        encoder.verify_frozen()

    def test_receipt_distinguishes_prepared_from_consumed_questions(self):
        encoder = tiny_encoder()
        receipt = fit(encoder, (row(), row("second")), steps=1)
        self.assertEqual(receipt["prepared_questions"], ["train", "second"])
        self.assertEqual(receipt["consumed_questions"], ["train"])
        self.assertEqual(receipt["steps"], 1)
        self.assertEqual(receipt["tokens"], 6)

    def test_invalid_second_row_cannot_partially_train(self):
        encoder = tiny_encoder()
        bad = replace(row("second"), positive_indices=(9,))
        before = encoder.tensor_bytes()
        with self.assertRaises(ValueError):
            fit(encoder, (row(), bad))
        self.assertEqual(encoder.tensor_bytes(), before)
        self.assertFalse(encoder.frozen)

    def test_frozen_encoder_cannot_resume_hidden_adaptation(self):
        encoder = tiny_encoder()
        fit(encoder)
        before = encoder.tensor_bytes()
        with self.assertRaises(ValueError):
            fit(encoder)
        self.assertEqual(encoder.tensor_bytes(), before)

    def test_adapter_only_restore_has_exact_feature_parity(self):
        encoder = tiny_encoder()
        fit(encoder)
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp) / "adapter"
            metadata = encoder.export(directory)
            restored = tiny_encoder()
            restored.restore_into(
                directory,
                expected_metadata=metadata,
                allowed_roots={"root"},
                revoked=set(),
            )
            before, _ = encoder.encode(Query(), "family", Pool(), revoked=set())
            after, _ = restored.encode(Query(), "family", Pool(), revoked=set())
            self.assertEqual(before.seal(), after.seal())
            self.assertEqual(encoder.identity, restored.identity)
            restored.verify_frozen()

    def test_revoked_adapter_training_source_blocks_restore_and_use(self):
        encoder = tiny_encoder()
        fit(encoder)
        with self.assertRaises(ValueError):
            encoder.encode(Query(), "family", Pool(), revoked={"root"})
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp) / "adapter"
            metadata = encoder.export(directory)
            with self.assertRaises(ValueError):
                tiny_encoder().restore_into(
                    directory,
                    expected_metadata=metadata,
                    allowed_roots={"root"},
                    revoked={"root"},
                )

    def test_corrupted_adapter_is_not_loaded(self):
        encoder = tiny_encoder()
        fit(encoder)
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp) / "adapter"
            metadata = encoder.export(directory)
            (directory / "adapter.safetensors").write_bytes(b"corrupted")
            with self.assertRaises(ValueError):
                tiny_encoder().restore_into(
                    directory,
                    expected_metadata=metadata,
                    allowed_roots={"root"},
                    revoked=set(),
                )

    def test_mutation_after_freeze_is_detected(self):
        encoder = tiny_encoder()
        fit(encoder)
        with torch.no_grad():
            for name, parameter in encoder.model.named_parameters():
                if "lora_" in name:
                    parameter.add_(0.5)
                    break
        with self.assertRaises(ValueError):
            encoder.verify_frozen()


if __name__ == "__main__":
    unittest.main()
