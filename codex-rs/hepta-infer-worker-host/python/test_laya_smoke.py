"""Preparation tests only; these do not execute the model."""
import unittest

from laya_retrieval import encoded, prepare
from laya_smoke import normalize_tokenizer, request


class PreparationTests(unittest.TestCase):
    def test_explicit_tokenizer_derivation_does_not_modify_original(self):
        original = {"tokenizer_class": "TokenizersBackend", "backend": "tokenizers",
                    "is_local": True, "extra_special_tokens": ["<one>", "<two>"]}
        normalized, changes = normalize_tokenizer(original)
        self.assertEqual(original["tokenizer_class"], "TokenizersBackend")
        self.assertEqual(original["extra_special_tokens"], ["<one>", "<two>"])
        self.assertEqual(changes, ["tokenizer_class", "extra_special_tokens"])
        self.assertEqual(normalized["tokenizer_class"], "PreTrainedTokenizerFast")
        self.assertNotIn("backend", normalized)
        self.assertEqual(normalized["extra_special_tokens"], {"extra_0": "<one>", "extra_1": "<two>"})

    def test_compatible_tokenizer_has_no_preparation_change(self):
        value = {"tokenizer_class": "PreTrainedTokenizerFast", "extra_special_tokens": {"a": "b"}}
        normalized, changes = normalize_tokenizer(value)
        self.assertEqual(normalized, value)
        self.assertEqual(changes, [])

    def test_smoke_request_uses_production_input_contract_but_qualification_scope(self):
        value, state, questions = prepare(encoded(request()))
        self.assertEqual(value["scope"], "qualification.synthetic.readonly")
        self.assertEqual(len(value["candidates"]), 2)
        self.assertIn("abstain", questions["source"]["criteria"])
        self.assertTrue(state)


if __name__ == "__main__":
    unittest.main()
