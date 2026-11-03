"""Research-only mirror-alias admissibility cases; synthetic shared-storage data.

The stock-pretrained physical checkpoint test is separate and mandatory; these
regressions are NOT a claim of publisher authentication, task benefit, or
production readiness.
"""
from __future__ import annotations

from types import SimpleNamespace
import unittest

import torch
from torch import nn

from multimodal_exact_tied_alias_v11 import (
    DECODER, EMBEDDING, MissingTensorError, reconcile_loading_report,
    same_physical_view,
)


class ModernBertForMaskedLM(nn.Module):
    """Mechanics-only state_dict fixture, not a genuine Transformers class."""
    def __init__(self, tied=True):
        super().__init__()
        self.config = SimpleNamespace(model_type="modernbert", tie_word_embeddings=True)
        self.model = nn.Module()
        self.model.embeddings = nn.Module()
        self.model.embeddings.tok_embeddings = nn.Embedding(4, 3)
        self.decoder = nn.Linear(3, 4, bias=False)
        if tied:
            self.decoder.weight = self.model.embeddings.tok_embeddings.weight
        else:
            with torch.no_grad():
                self.decoder.weight.copy_(self.model.embeddings.tok_embeddings.weight)


ModernBertForMaskedLM.__module__ = "transformers.models.modernbert.modeling_modernbert"


class ReverseAliasTests(unittest.TestCase):
    def test_reviewed_decoder_only_serialization_requires_one_physical_view(self):
        model = ModernBertForMaskedLM()
        self.assertTrue(same_physical_view(model.state_dict()[DECODER],
                                           model.state_dict()[EMBEDDING]))
        self.assertEqual(reconcile_loading_report(
            model, {"missing_keys": [EMBEDDING]}, {DECODER}), [EMBEDDING])

    def test_legacy_embedding_only_serialization_retains_exact_behavior(self):
        model = ModernBertForMaskedLM()
        self.assertEqual(reconcile_loading_report(
            model, {"missing_keys": [DECODER]}, {EMBEDDING}), [DECODER])

    def test_no_fabricated_source_both_missing_or_unrecognized_weight(self):
        model = ModernBertForMaskedLM()
        cases = [
            ({"missing_keys": [EMBEDDING]}, set()),
            ({"missing_keys": [DECODER]}, {DECODER}),
            ({"missing_keys": [EMBEDDING]}, {EMBEDDING, DECODER}),
            ({"missing_keys": [DECODER]}, {EMBEDDING, DECODER}),
            ({"missing_keys": [EMBEDDING, DECODER]}, {DECODER}),
            ({"missing_keys": ["mlm.hidden.weight"]}, {DECODER}),
            ({"missing_keys": [EMBEDDING, EMBEDDING]}, {DECODER}),
            ({"missing_keys": [EMBEDDING], "unexpected_keys": ["extra.weight"]}, {DECODER}),
        ]
        for report, originals in cases:
            with self.subTest(report=report, originals=originals), self.assertRaises(MissingTensorError):
                reconcile_loading_report(model, report, originals)

    def test_equal_numeric_values_without_physical_tie_rejected(self):
        model = ModernBertForMaskedLM(tied=False)
        self.assertTrue(torch.equal(model.state_dict()[DECODER], model.state_dict()[EMBEDDING]))
        self.assertFalse(same_physical_view(model.state_dict()[DECODER],
                                            model.state_dict()[EMBEDDING]))
        for omitted, present in ((EMBEDDING, DECODER), (DECODER, EMBEDDING)):
            with self.subTest(omitted=omitted), self.assertRaisesRegex(
                MissingTensorError, "physical tied decoder"
            ):
                reconcile_loading_report(model, {"missing_keys": [omitted]}, {present})


if __name__ == "__main__":
    unittest.main()
