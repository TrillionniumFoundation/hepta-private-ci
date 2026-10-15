"""Strict alias-mechanics regressions: not a claim of pretrained execution."""
from __future__ import annotations

from types import SimpleNamespace
import unittest

import torch
from torch import nn

from multimodal_exact_tied_alias_v11 import (
    DECODER, EMBEDDING, MissingTensorError, reconcile_loading_report,
    same_physical_view,
)
from multimodal_meta_integrity_v14 import UnmaterializedCheckpoint, require_materialized


class TiedAliasContractTests(unittest.TestCase):
    def test_only_shared_storage_view_is_accepted(self):
        t = torch.randn(6, 4)
        self.assertTrue(same_physical_view(t, t))
        self.assertTrue(same_physical_view(t, t.view(6, 4)))
        self.assertFalse(same_physical_view(t, t.clone()))
        self.assertFalse(same_physical_view(t, t.t()))
        self.assertFalse(same_physical_view(t, t[1:]))
        self.assertFalse(same_physical_view(t, None))

    def test_missing_generic_decoder_is_not_reconciled(self):
        class UserNamedModernBertForMaskedLM(nn.Module):
            def __init__(self):
                super().__init__()
                self.config = SimpleNamespace(model_type="modernbert", tie_word_embeddings=True)
                self.decoder = nn.Linear(4, 4, bias=False)
            def state_dict(self):
                weights = self.decoder.weight
                return {EMBEDDING:weights, DECODER:weights}
        fake=UserNamedModernBertForMaskedLM()
        with self.assertRaisesRegex(MissingTensorError, "stock tied"):
            reconcile_loading_report(fake, {"missing_keys":[DECODER]}, {EMBEDDING})

    def test_arbitrary_missing_weight_even_with_empty_errors_is_denied(self):
        model = nn.Linear(4, 3)
        with self.assertRaisesRegex(MissingTensorError, "only stock"):
            reconcile_loading_report(model, {"missing_keys":["some.other.weight"]}, set())
        with self.assertRaisesRegex(MissingTensorError,"unrecognized failure"):
            reconcile_loading_report(model,{"missing_keys":[],"unexpected_keys":["bad"]},set())
        with self.assertRaisesRegex(MissingTensorError,"inventory"):
            reconcile_loading_report(model,{"missing_keys":None},set())

    def test_meta_weights_reported_without_initializing_or_moving(self):
        model = nn.Linear(4, 3, device="meta")
        with self.assertRaisesRegex(UnmaterializedCheckpoint, "meta_tensor_count=2") as caught:
            require_materialized(model, {"missing_keys": ["decoder.weight"]})
        self.assertIn("weight", str(caught.exception))
        self.assertIn("loader_missing_count=1", str(caught.exception))
        self.assertTrue(model.weight.is_meta)

    def test_meta_buffers_are_rejected_and_real_cpu_weights_allowed(self):
        model = nn.Linear(2, 2)
        require_materialized(model, {"missing_keys": []})
        model.register_buffer("unloaded_buffer", torch.empty(1, device="meta"))
        with self.assertRaisesRegex(UnmaterializedCheckpoint, "unloaded_buffer"):
            require_materialized(model, {"missing_keys": []})

    def test_jhu_decoder_only_source_reconciles_one_physical_embedding_alias(self):
        # Synthetic shared-storage mechanism, NOT a pretrained checkpoint.
        class ModernBertForMaskedLM(nn.Module):
            def __init__(self):
                super().__init__()
                self.config = SimpleNamespace(model_type="modernbert", tie_word_embeddings=True)
                self.model = nn.Module()
                self.model.embeddings = nn.Module()
                self.model.embeddings.tok_embeddings = nn.Embedding(4, 3)
                self.decoder = nn.Linear(3, 4, bias=False)
                self.decoder.weight = self.model.embeddings.tok_embeddings.weight
        ModernBertForMaskedLM.__module__ = "transformers.models.modernbert.modeling_modernbert"
        model = ModernBertForMaskedLM()
        self.assertTrue(same_physical_view(model.state_dict()[DECODER],
                                           model.state_dict()[EMBEDDING]))
        self.assertEqual(reconcile_loading_report(model, {"missing_keys": [EMBEDDING]},
                                                  {DECODER}), [EMBEDDING])
        self.assertEqual(reconcile_loading_report(model, {"missing_keys": [DECODER]},
                                                  {EMBEDDING}), [DECODER])

    def test_reverse_alias_rejects_absent_source_and_ambiguous_missing_keys(self):
        class ModernBertForMaskedLM(nn.Module):
            def __init__(self):
                super().__init__()
                self.config = SimpleNamespace(model_type="modernbert", tie_word_embeddings=True)
                self.model = nn.Module()
                self.model.embeddings = nn.Module()
                self.model.embeddings.tok_embeddings = nn.Embedding(4, 3)
                self.decoder = nn.Linear(3, 4, bias=False)
                self.decoder.weight = self.model.embeddings.tok_embeddings.weight
        ModernBertForMaskedLM.__module__ = "transformers.models.modernbert.modeling_modernbert"
        model = ModernBertForMaskedLM()
        cases = [
            ({"missing_keys": [EMBEDDING]}, set()),
            ({"missing_keys": [DECODER]}, {DECODER}),
            ({"missing_keys": [EMBEDDING]}, {EMBEDDING, DECODER}),
            ({"missing_keys": [EMBEDDING, DECODER]}, {DECODER}),
            ({"missing_keys": [EMBEDDING, EMBEDDING]}, {DECODER}),
            ({"missing_keys": ["mlm.hidden.weight"]}, {DECODER}),
            ({"missing_keys": [EMBEDDING], "unexpected_keys": ["bad"]}, {DECODER}),
        ]
        for report, original_keys in cases:
            with self.subTest(report=report, keys=original_keys), self.assertRaises(MissingTensorError):
                reconcile_loading_report(model, report, original_keys)

    def test_reverse_alias_rejects_equal_copied_not_tied_parameters(self):
        class ModernBertForMaskedLM(nn.Module):
            def __init__(self):
                super().__init__()
                self.config = SimpleNamespace(model_type="modernbert", tie_word_embeddings=True)
                self.model = nn.Module()
                self.model.embeddings = nn.Module()
                self.model.embeddings.tok_embeddings = nn.Embedding(4, 3)
                self.decoder = nn.Linear(3, 4, bias=False)
                with torch.no_grad():
                    self.decoder.weight.copy_(self.model.embeddings.tok_embeddings.weight)
        ModernBertForMaskedLM.__module__ = "transformers.models.modernbert.modeling_modernbert"
        model = ModernBertForMaskedLM()
        self.assertTrue(torch.equal(model.state_dict()[DECODER], model.state_dict()[EMBEDDING]))
        self.assertFalse(same_physical_view(model.state_dict()[DECODER],
                                            model.state_dict()[EMBEDDING]))
        for absent, source_key in ((EMBEDDING, DECODER), (DECODER, EMBEDDING)):
            with self.subTest(absent=absent), self.assertRaisesRegex(
                    MissingTensorError, "physical tied decoder"):
                reconcile_loading_report(model, {"missing_keys": [absent]}, {source_key})

    def test_no_missing_weights_still_requires_a_complete_report(self):
        self.assertEqual(reconcile_loading_report(nn.Linear(2,2),{"missing_keys":[],
            "unexpected_keys":[],"mismatched_keys":[],"error_msgs":[]},set()),[])
        with self.assertRaisesRegex(MissingTensorError,"inventory"):
            reconcile_loading_report(nn.Linear(2,2),{},set())


if __name__ == "__main__":
    unittest.main()
