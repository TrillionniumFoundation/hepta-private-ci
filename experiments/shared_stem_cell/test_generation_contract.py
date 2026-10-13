"""Real token-tensor dispatch checks with a test decoder, NOT language-model quality."""
from types import SimpleNamespace
from pathlib import Path
import tempfile
from unittest.mock import patch
import unittest

import torch

from experiments.shared_stem_cell import execution as e


class FixtureTokenizer:
    eos_token_id = 2

    def __call__(self, text, *, truncation, return_tensors, add_special_tokens=True):
        assert truncation is False and return_tensors == "pt"
        ids = [int(x) for x in text.split()]
        # The fixture exposes duplicate-BOS behavior after formatting a chat.
        if add_special_tokens:
            ids = [1] + ids
        return {"input_ids": torch.tensor([ids], dtype=torch.long)}

    def decode(self, tokens, **kwargs):
        return " ".join(map(str, tokens.tolist()))


class FixtureDecoder:
    config = SimpleNamespace(max_position_embeddings=32)

    def __init__(self):
        self.inputs = []

    def generate(self, input_ids, **kwargs):
        self.inputs.append(input_ids.clone())
        return torch.cat([input_ids, torch.tensor([[4, 2]])], -1)


class GenerationContractTests(unittest.TestCase):
    def setUp(self):
        self.generator = object.__new__(e.LocalTextGenerator)
        self.generator.tokenizer = FixtureTokenizer()
        self.generator.loaded = FixtureDecoder()
        self.generator.maximum_tokens = 8
        self.generator.identity = "fixture-only"
        self.generator.close = lambda: None

    def test_preformatted_chat_not_double_special_tokenized(self):
        raw = self.generator.generate(["1 5 6"], maximum_new_tokens=2)
        chat = self.generator.generate(["1 5 6"], maximum_new_tokens=2, add_special_tokens=False)
        self.assertEqual(self.generator.loaded.inputs[0].tolist(), [[1, 1, 5, 6]])
        self.assertEqual(self.generator.loaded.inputs[1].tolist(), [[1, 5, 6]])
        self.assertEqual(raw["outputs"][0]["input_tokens"], 4)
        self.assertEqual(chat["outputs"][0]["input_tokens"], 3)
        self.assertFalse(chat["outputs"][0]["input_special_tokens_added"])
        self.assertEqual(chat["outputs"][0]["text"], "4 2")

    def test_late_oversized_prompt_spends_zero_decoder_calls(self):
        with self.assertRaises(e.InputError):
            self.generator.generate(["5", "5 " * 20], maximum_new_tokens=2)
        self.assertFalse(self.generator.loaded.inputs)

    def test_late_empty_prompt_spends_zero_decoder_calls(self):
        with self.assertRaises(e.InputError):
            self.generator.generate(["5", ""], maximum_new_tokens=2)
        self.assertFalse(self.generator.loaded.inputs)

    def test_context_includes_continuation_not_just_input(self):
        self.generator.loaded.config = SimpleNamespace(max_position_embeddings=4)
        with self.assertRaises(e.InputError):
            self.generator.generate(["5 6"], maximum_new_tokens=2)
        self.assertFalse(self.generator.loaded.inputs)

    def test_exact_bool_special_token_contract(self):
        with self.assertRaises(e.InputError):
            self.generator.generate(["5"], maximum_new_tokens=2, add_special_tokens=0)
        self.assertFalse(self.generator.loaded.inputs)

    def test_wrong_prefix_is_not_a_completed_answer(self):
        self.generator.loaded.generate = lambda **kw: torch.tensor([[7, 7, 4]])
        with self.assertRaises(e.InputError):
            self.generator.generate(["5"], maximum_new_tokens=2)

    def test_decoder_cannot_overrun_declared_output_budget(self):
        self.generator.loaded.generate = lambda input_ids, **kw: torch.cat([input_ids, torch.ones(1, 3, dtype=torch.long)], -1)
        with self.assertRaises(e.InputError):
            self.generator.generate(["5"], maximum_new_tokens=2)

    def test_mixed_scope_trial_refuses_before_model_loading(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            rows = [{"case_id": str(i), "group": str(i), "split": split,
                     "observed_at": None, "cell": 0, "scope": "a" if i < 3 else "b",
                     "text": f"case {i}", "label": i % 2}
                    for i, split in enumerate(("train", "train", "calibration", "holdout"))]
            raw = b"".join(e.canonical(row) for row in rows)
            (root / "data.jsonl").write_bytes(raw)
            e.write_once(root / "manifest.json", {"schema": "hepta.shared-stem-execution.v1",
                "classes": 2, "cells": 1, "dataset": {"path": "data.jsonl", "sha256": e.sha(raw)},
                "model": {"path": "absent", "revision": "a" * 40}})
            with patch.object(e, "LocalEncoder") as loader, self.assertRaises(e.InputError):
                e.run(root / "manifest.json", root / "out")
            loader.assert_not_called()
            self.assertFalse((root / "out/report.json").exists())

    def test_inputs_have_no_target_argument(self):
        with self.assertRaises(TypeError):
            self.generator.generate(["5"], maximum_new_tokens=2, target="A")
        self.assertFalse(self.generator.loaded.inputs)


if __name__ == "__main__":
    unittest.main()
