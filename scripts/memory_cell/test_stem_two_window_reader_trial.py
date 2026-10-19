"""No pretrained model is used: synthetic two-evidence decoder contracts."""

from types import SimpleNamespace as Obj
import unittest
import torch

from native import Question, digest
from selector_answering import SYSTEM, GENERATION
from stem_two_window_reader_trial import answer_two


class FakeTokenizer:
    eos_token_id = 1
    chat_template = "pinned-template"

    def __init__(self):
        self.last = None

    def apply_chat_template(self, messages, tokenize, add_generation_prompt):
        self.last = messages
        return [5, 6, 7]

    def decode(self, tokens, *, skip_special_tokens, clean_up_tokenization_spaces):
        return "synthetic direct answer"


class FakeModel:
    def generate(self, *, input_ids, attention_mask, **options):
        assert options["max_new_tokens"] == GENERATION["max_new_tokens"]
        assert input_ids.shape == attention_mask.shape
        return torch.cat((input_ids, torch.tensor([[9, 10]])), dim=1)


def fixture():
    reader = Obj(
        tokenizer=FakeTokenizer(),
        model=FakeModel(),
        identity="fixed-reader",
        profile="fixed-system",
        quarantined=False,
    )
    q = Question("q", "family", "scope", "What happened?", "2024-01-01")
    evidence = (
        dict(
            label="E1",
            root="root-one",
            original_id="source-one",
            scope="scope",
            observed_at="2023-01-01",
            excerpt="old source one",
        ),
        dict(
            label="E2",
            root="root-two",
            original_id="source-two",
            scope="scope",
            observed_at="2023-01-02",
            excerpt="old source two",
        ),
    )
    return reader, q, evidence


class PairedGenerationTests(unittest.TestCase):
    def test_exact_original_prompt_and_generation_budget_with_two_sources(self):
        reader, q, evidence = fixture()
        answer, receipt = answer_two(reader, q, evidence, revoked=set())
        self.assertEqual(answer, "synthetic direct answer")
        self.assertEqual(reader.tokenizer.last[0]["content"], SYSTEM)
        self.assertEqual(reader.tokenizer.last[1]["role"], "user")
        self.assertIn('"label": "E2"', reader.tokenizer.last[1]["content"])
        self.assertEqual(receipt["delivered_evidence"], list(evidence))
        self.assertTrue(receipt["same_original_SYSTEM_and_GENERATION"])
        self.assertEqual(
            receipt["question_digest"],
            digest(
                {
                    "identity": q.identity,
                    "family": q.family,
                    "scope": q.scope,
                    "content": q.content,
                    "observed_at": q.observed_at,
                }
            ),
        )
        self.assertEqual(receipt["input_tokens"], 3)
        self.assertEqual(receipt["generated_tokens"], 2)
        self.assertFalse(receipt["production_accepted"])

    def test_future_withdrawn_cross_scope_and_same_source_fail_closed(self):
        for mutation in ("future", "revoked", "cross-scope", "same-root", "same-id"):
            reader, q, data = fixture()
            data = [dict(x) for x in data]
            revoked = set()
            if mutation == "future":
                data[1]["observed_at"] = "2026-01-02"
            elif mutation == "revoked":
                revoked = {"root-two"}
            elif mutation == "cross-scope":
                data[1]["scope"] = "different"
            elif mutation == "same-root":
                data[1]["root"] = "root-one"
            else:
                data[1]["original_id"] = "source-one"
            with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                answer_two(reader, q, tuple(data), revoked=revoked)
            self.assertIsNone(reader.tokenizer.last)

    def test_more_than_two_or_wrong_labels_not_silently_admitted(self):
        reader, q, data = fixture()
        for candidate in (
            data[:1],
            data + data,
            tuple(dict(x, label="E1") for x in data),
        ):
            with self.assertRaises(ValueError):
                answer_two(reader, q, candidate, revoked=set())

    def test_retrieval_encoder_checks_loaded_weights_and_staged_bytes(self):
        from pathlib import Path
        from tempfile import TemporaryDirectory

        from stem_two_window_reader_trial import verify_frozen_retrieval
        from pretrained import file_inventory, frozen_digest

        with TemporaryDirectory() as tmp:
            staged = Path(tmp)
            (staged / "config.json").write_text("frozen-source", encoding="utf-8")
            identity = digest(file_inventory(staged))
            model = torch.nn.Linear(2, 2).eval()
            model.requires_grad_(False)
            encoder = Obj(identity=identity, model=model)
            sealed = frozen_digest(model)

            def verify():
                verify_frozen_retrieval(
                    encoder,
                    staged,
                    inventory_digest=identity,
                    weights_digest=sealed,
                )

            verify()
            model.train()
            with self.assertRaisesRegex(ValueError, "frozen retrieval Encoder"):
                verify()
            model.eval()

            model.weight.requires_grad_(True)
            with self.assertRaisesRegex(ValueError, "frozen retrieval Encoder"):
                verify()
            model.weight.requires_grad_(False)

            original = model.weight.detach().clone()
            with torch.no_grad():
                model.weight.add_(0.5)
            with self.assertRaisesRegex(ValueError, "frozen retrieval Encoder"):
                verify()
            with torch.no_grad():
                model.weight.copy_(original)
            verify()

            (staged / "extra-file.txt").write_text("tampered", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "frozen retrieval Encoder"):
                verify()
            (staged / "extra-file.txt").unlink()
            verify()
            encoder.identity = "forged-reader"
            with self.assertRaisesRegex(ValueError, "frozen retrieval Encoder"):
                verify()

    def test_model_generation_failure_quarantines_isolated_reader(self):
        reader, q, data = fixture()

        class Broken:
            def generate(self, **kwargs):
                raise RuntimeError("a real failing generation call")

        reader.model = Broken()
        with self.assertRaisesRegex(RuntimeError, "failing"):
            answer_two(reader, q, data, revoked=set())
        self.assertTrue(reader.quarantined)


if __name__ == "__main__":
    unittest.main()
