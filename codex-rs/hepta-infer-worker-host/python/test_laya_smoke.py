"""Preparation tests only; these do not execute the model."""
import unittest

from laya_retrieval import encoded, prepare
from laya_smoke import binary_request, normalize_tokenizer, request
from hepta_retrieval_wire import decode_request


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

    def test_binary_smoke_keeps_native_identity_and_complete_source_bytes(self):
        value = decode_request(binary_request("1" * 64, 9999))
        self.assertEqual(value["bundle_digest"], "1" * 64)
        self.assertEqual(value["deadline_ms"], 9999)
        self.assertEqual(value["generation"], 1)
        self.assertEqual(value["workspace_id"], "qualification.synthetic.readonly")
        self.assertEqual([item["source_id"] for item in value["sources"]], ["source-1", "source-0"])
        self.assertEqual([item["revision"] for item in value["sources"]], [1, 1])


if __name__ == "__main__":
    unittest.main()
