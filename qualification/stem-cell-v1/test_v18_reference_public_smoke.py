"""Synthetic API tests: never treat these mocks as a pretrained forward."""
from contextlib import nullcontext
import unittest
from types import SimpleNamespace
import v18_reference_public_smoke as p

class Tokens:
    def __init__(self, ids): self.ids=ids
    def __getitem__(self, idx): return SimpleNamespace(tolist=lambda:self.ids)

class Tokenizer:
    eos_token_id=42
    def apply_chat_template(self, messages, tokenize, add_generation_prompt, enable_thinking):
        if messages != p.PUBLIC_MESSAGES or enable_thinking is not False:
            raise AssertionError('not source-frozen public-only template')
        return [1,2,3]
    def decode(self, ids, skip_special_tokens):
        if ids != [4,5] or skip_special_tokens is not True:
            raise AssertionError('changed output ids')
        return 'Paris [E1]'

class Model:
    def __init__(self, tokens):self.tokens=tokens
    def generate(self, input_ids,do_sample,max_new_tokens,pad_token_id):
        if input_ids!=[[1,2,3]] or do_sample or max_new_tokens!=p.OUT_CAP or pad_token_id!=42:
            raise AssertionError('wrong public generation schedule')
        return Tokens(self.tokens)

class Smoke(unittest.TestCase):
    def call(self, ids):
        return p.public_probe(Tokenizer(),Model(ids),lambda x:x,nullcontext)
    def test_public_mock_contract(self):
        r=self.call([1,2,3,4,5]);self.assertEqual(r['input_tokens'],3)
        self.assertEqual(r['output_tokens'],2)
        self.assertEqual(r['public_answer_sha256'],p.digest_text('Paris [E1]'))
    def test_no_empty_output(self):
        with self.assertRaises(ValueError):self.call([1,2,3])
    def test_bad_prefix(self):
        with self.assertRaises(ValueError):self.call([1,2,5,4])
    def test_over_budget(self):
        with self.assertRaises(ValueError):self.call([1,2,3]+[4]*25)
    def test_reject_negative_or_noninteger_tokens(self):
        for bad in ([1,2,3,-4], [1,2,3,4.0], [1,2,3,True]):
            with self.subTest(tokens=bad), self.assertRaises(ValueError):
                self.call(bad)
    def test_no_private_inputs_in_static_messages(self):
        self.assertEqual(len(p.PUBLIC_MESSAGES),2)
        self.assertEqual(p.PUBLIC_MESSAGES[1]['content'],
                         'Question: What is the capital of France?\n[E1] Paris is the capital of France.')
if __name__=='__main__':unittest.main()
