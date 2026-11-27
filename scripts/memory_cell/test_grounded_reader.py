"""One-parameter trainer fixtures test invariants, never model quality.

The real pinned Transformer is exercised by grounded_development in hosted CI.
These explicit dependency substitutes do not escape the isolated module load.
"""

import importlib.util
from pathlib import Path
import types
import unittest
from unittest.mock import patch

import torch

from native import Document


class Tokenizer:
    eos_token_id = 256

    def encode(self, text, **_):
        return list(text.encode())

    def decode(self, ids, **_):
        return bytes(ids).decode()

    def apply_chat_template(self, messages, **_):
        # An intentionally tiny test tokenizer, not a pretrained model tokenizer.
        return [900] + list(messages[-1]["content"][-50:].encode())


class TensorModel(torch.nn.Module):
    def __init__(self):
        super().__init__()
        self.weight = torch.nn.Parameter(torch.tensor(1.0))
        self.labels = []
        self.fail = False

    def forward(self, *, labels, **_):
        self.labels.append(labels.tolist()[0])
        loss = (self.weight - 2).square()
        if self.fail:
            loss = loss * float("nan")
        return types.SimpleNamespace(loss=loss)


def reader():
    spec = importlib.util.spec_from_file_location(
        "isolated_grounded_trainer", Path(__file__).with_name("grounded_reader.py")
    )
    module = importlib.util.module_from_spec(spec)
    with patch.dict(
        "sys.modules",
        {
            "pretrained": types.SimpleNamespace(
                LoRAReader=object, frozen_digest=lambda _: "frozen"
            ),
            "peft": types.SimpleNamespace(
                get_peft_model_state_dict=lambda m: {"w": m.weight.detach().clone()}
            ),
        },
    ):
        spec.loader.exec_module(module)
    instance = module.GroundedReader()
    instance.model = TensorModel()
    instance.tokenizer = Tokenizer()
    instance.quarantined = False
    instance.scope = "scope"
    instance.roots = {"earlier-root"}
    instance.base_digest = "frozen"
    instance.trainable_parameters = 1
    return instance


def document():
    return Document(
        identity="source-one",
        root="root-one",
        scope="scope",
        session="session",
        observed_at="2024-01-01",
        content="A blue device.",
    )


class GroundedTrainingTests(unittest.TestCase):
    def test_sequential_training_keeps_all_ancestor_roots_and_masks_prompt(self):
        model = reader()
        result = model.adapt_grounded((document(),), steps=2, revoked=set())
        self.assertEqual(model.roots, {"earlier-root", "root-one"})
        self.assertEqual(result["roots"], ["earlier-root", "root-one"])
        self.assertGreater(result["adapter_delta_squared_norm"], 0)
        self.assertGreater(result["tokens"], result["supervised_tokens"])
        for labels in model.model.labels:
            self.assertEqual(labels[0], -100)
            self.assertEqual(labels[-1], 256)
            first_target = next(i for i, value in enumerate(labels) if value != -100)
            self.assertTrue(all(v == -100 for v in labels[:first_target]))
            self.assertTrue(all(v != -100 for v in labels[first_target:]))

    def test_revoked_prior_root_cannot_be_laundered_by_new_training(self):
        model = reader()
        before = model.model.weight.detach().clone()
        with self.assertRaises(ValueError):
            model.adapt_grounded((document(),), steps=1, revoked={"earlier-root"})
        torch.testing.assert_close(model.model.weight, before)
        self.assertEqual(model.model.labels, [])

    def test_failed_update_quarantines_the_entire_candidate(self):
        model = reader()
        model.model.fail = True
        with self.assertRaisesRegex(ValueError, "nonfinite"):
            model.adapt_grounded((document(),), steps=1, revoked=set())
        self.assertTrue(model.quarantined)
        self.assertIsNone(model.scope)
        self.assertFalse(model.model.training)


if __name__ == "__main__":
    unittest.main()
