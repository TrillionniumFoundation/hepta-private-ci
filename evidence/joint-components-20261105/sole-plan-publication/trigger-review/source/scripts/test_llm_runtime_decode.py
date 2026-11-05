"""Decoder routing and tiny CPU tensors; no pretrained weights or model claim."""
import copy
import hashlib
import os
import struct
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import llm_runtime_pilot as runtime

c = runtime.contract_module()
from test_llm_adapter_contract import fixture_contract


class DecodeRoutingTests(unittest.TestCase):
    def test_existing_prompt_wrapper_delegates_exact_tokens_without_changing_context(self):
        tokenizer = Mock()
        tokenizer.apply_chat_template.return_value = 'original rendered prompt'
        tokenizer.encode.return_value = [1, 5, 7]
        row = dict(id='task', prompt='original prompt')
        plan = dict(input_tokens_max=128)
        with patch.object(runtime, 'decode_tokens', create=True, return_value='decoded') as decode:
            actual = runtime.decode('model', tokenizer, row, 'contract', 'cid', plan,
                                    'torch', 'device', artifact='artifact', role='candidate')
        self.assertEqual(actual, 'decoded')
        tokenizer.apply_chat_template.assert_called_once_with(
            [{'role': 'user', 'content': 'original prompt'}],
            tokenize=False, add_generation_prompt=True)
        tokenizer.encode.assert_called_once_with('original rendered prompt', add_special_tokens=False)
        decode.assert_called_once_with('model', tokenizer, [1, 5, 7], 'task',
            'contract', 'cid', plan, 'torch', 'device', artifact='artifact', role='candidate')

    def test_direct_tokens_reject_before_tensor_construction(self):
        self.assertTrue(callable(getattr(runtime, 'decode_tokens', None)))
        contract = fixture_contract()
        cid = c.freeze_target_contract(contract)[1]
        plan = dict(input_tokens_max=128, generation_tokens=8, backend='cpu', snapshot='s')
        for tokens in ([], (), [True], [1.0], [-1], [16], [[1]], '1', range(2), [1]*129):
            with self.subTest(tokens=repr(tokens)), self.assertRaises(ValueError):
                runtime.decode_tokens(Mock(), Mock(), tokens, 'task', contract, cid,
                                      plan, Mock(), SimpleNamespace(type='cpu'))

    def test_caller_growth_after_length_check_is_refused_before_contract_or_tensor(self):
        contract = fixture_contract()
        cid = c.freeze_target_contract(contract)[1]
        plan = dict(input_tokens_max=128, generation_tokens=8, backend='cpu', snapshot='s')
        tokens, copied_lengths, private_lengths = [1], [], []
        original_require, original_validate = runtime.require, c.validate_decoder_request
        grown = False

        def grow_after_check(value, code):
            nonlocal grown
            if code == 'RUNTIME_NO_TRUNCATION' and grown:
                private_lengths.append(len(sys._getframe(1).f_locals['tokens']))
            original_require(value, code)
            if code == 'RUNTIME_NO_TRUNCATION' and not grown:
                grown = True
                tokens.extend([1]*8191)

        def observe_copy(request, *args):
            copied_lengths.append(len(request['input_ids'][0]))
            return original_validate(request, *args)

        torch = Mock()
        with patch.object(runtime, 'require', grow_after_check), \
                patch.object(c, 'validate_decoder_request', observe_copy), \
                self.assertRaises(ValueError):
            runtime.decode_tokens(Mock(), Mock(), tokens, 'task', contract, cid,
                                  plan, torch, SimpleNamespace(type='cpu'))
        self.assertEqual(len(tokens), 8192)
        self.assertEqual(copied_lengths, [], 'oversized caller copy reached the validator')
        self.assertEqual(private_lengths, [plan['input_tokens_max']+1])
        torch.tensor.assert_not_called()


@unittest.skipUnless(os.environ.get('TRNM_ACTUAL_DECODER_TENSOR_TESTS') == '1',
                     'explicit CPU tensor opt-in absent; decoder tensor units NOT_RUN')
class ActualDecoderTensorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import torch
        cls.torch = torch
        torch.set_num_threads(1)
        torch.set_num_interop_threads(1)

    def setUp(self):
        self.contract = fixture_contract()
        self.cid = c.freeze_target_contract(self.contract)[1]
        self.plan = dict(input_tokens_max=128, generation_tokens=8, backend='cpu', snapshot='snapshot')
        self.device = self.torch.device('cpu')

    def tokenizer(self):
        tokenizer = Mock()
        tokenizer.apply_chat_template.return_value = 'original rendered prompt'
        tokenizer.encode.return_value = [1, 5, 7]
        tokenizer.decode.side_effect = lambda ids, **_: ','.join(map(str, ids))
        return tokenizer

    def model(self, change=None):
        torch = self.torch
        class TinyTensorDecoder:
            def __init__(self):
                self.calls, self.evaluations = [], 0

            def eval(self):
                self.evaluations += 1

            def __call__(self, **kwargs):
                self.calls.append({key: value.clone() if hasattr(value, 'clone') else value
                                   for key, value in kwargs.items()})
                logits = torch.full((1, kwargs['input_ids'].shape[1], 16), -3.0,
                                    dtype=torch.float32, device='cpu')
                # Token2 is also the fixture EOS: fixed-count decoding must continue.
                logits[..., 2] = 7.0
                logits[..., 5] = 7.0
                return SimpleNamespace(logits=change(logits) if change else logits)
        return TinyTensorDecoder()

    def run_tokens(self, tokens, *, model=None, tokenizer=None, plan=None, contract=None, cid=None):
        return runtime.decode_tokens(model or self.model(), tokenizer or self.tokenizer(), tokens,
            'task', contract or self.contract, cid or self.cid, plan or self.plan,
            self.torch, self.device, artifact='artifact', role='candidate')

    def test_existing_wrapper_rejects_wrong_vocabulary_shape(self):
        # Old decode accepted finite FP32 logits with the wrong vocabulary size.
        model = self.model(lambda logits: logits[..., :15])
        with self.assertRaisesRegex(ValueError, 'RUNTIME_LOGITS_SHAPE'):
            runtime.decode(model, self.tokenizer(), dict(id='task', prompt='prompt'),
                self.contract, self.cid, self.plan, self.torch, self.device)
        self.assertEqual(len(model.calls), 1)

    def test_wrapper_and_direct_path_match_independent_greedy_and_byte_roots(self):
        tokenizer, direct_tokenizer = self.tokenizer(), self.tokenizer()
        direct_tokenizer.encode.side_effect = AssertionError('direct tokens cannot be retokenized')
        direct_tokenizer.apply_chat_template.side_effect = AssertionError('direct tokens cannot be templated')
        model, direct_model = self.model(), self.model()
        expected = runtime.decode(model, tokenizer, dict(id='task', prompt='prompt'),
            self.contract, self.cid, self.plan, self.torch, self.device,
            artifact='artifact', role='candidate')
        actual = self.run_tokens([1, 5, 7], model=direct_model, tokenizer=direct_tokenizer)
        self.assertEqual(actual, expected)
        self.assertEqual(actual['response']['generated_token_ids'], [[2]*8])
        self.assertEqual(actual['response']['decoded_outputs'], [','.join(['2']*8)])
        vector = [-3.0]*16
        vector[2] = vector[5] = 7.0
        self.assertEqual(actual['logits_sha256'], hashlib.sha256(struct.pack('<16f', *vector)*8).hexdigest())
        self.assertEqual(actual['output_sha256'], hashlib.sha256(b'2,2,2,2,2,2,2,2').hexdigest())
        self.assertEqual(actual['request_id'], c.validate_decoder_request(actual['request'], self.contract, self.cid))
        direct_tokenizer.decode.assert_called_once_with([2]*8, skip_special_tokens=True,
                                                        clean_up_tokenization_spaces=False)
        for index, call in enumerate(direct_model.calls):
            ids = self.torch.tensor([[1, 5, 7]+[2]*index], dtype=self.torch.int64)
            self.assertTrue(self.torch.equal(call['input_ids'], ids))
            self.assertTrue(self.torch.equal(call['attention_mask'], self.torch.ones_like(ids, dtype=self.torch.bool)))
            self.assertTrue(self.torch.equal(call['position_ids'], self.torch.arange(ids.shape[1]).reshape(1, -1)))
            self.assertIs(call['use_cache'], False)

    def test_exact_non_prompt_tokens_are_snapshotted_and_not_silently_truncated(self):
        tokens = [4, 1, 7, 6]
        model = self.model(lambda logits: (tokens.__setitem__(0, 8), logits)[1])
        actual = self.run_tokens(tokens, model=model)
        self.assertEqual(actual['request']['input_ids'], [[4, 1, 7, 6]])
        self.assertEqual(model.calls[0]['input_ids'].tolist(), [[4, 1, 7, 6]])
        self.assertEqual(tokens, [8, 1, 7, 6])

    def test_original_family_caps_hold_even_when_contract_permits_more(self):
        contract = copy.deepcopy(self.contract)
        contract['architecture']['context'] = 256
        contract['ports'].update(input_tokens_max=128, output_tokens_max=16)
        cid = c.freeze_target_contract(contract)[1]
        plan = dict(self.plan, generation_tokens=16)
        actual = self.run_tokens([1]*128, contract=contract, cid=cid, plan=plan)
        self.assertEqual((actual['input_tokens'], actual['generated_tokens']), (128, 16))
        for changed in (dict(plan, generation_tokens=17), dict(plan, generation_tokens=True),
                        dict(plan, input_tokens_max=129), dict(plan, input_tokens_max=True)):
            model = self.model()
            with self.subTest(plan=changed), self.assertRaises(ValueError):
                self.run_tokens([1], model=model, contract=contract, cid=cid, plan=changed)
            self.assertEqual((model.evaluations, model.calls), (0, []))
        with self.assertRaises(ValueError):
            self.run_tokens([1]*129, contract=contract, cid=cid, plan=plan)
        with self.assertRaisesRegex(ValueError, 'LLM_REQUEST_CONTRACT'):
            self.run_tokens([1], cid='f'*64)

    def test_actual_tensor_shape_dtype_device_and_nonfinite_faults_refuse(self):
        torch = self.torch
        faults = [lambda x: x[0], lambda x: x.expand(2, -1, -1),
                  lambda x: x[:, :-1], lambda x: x.to(torch.float64),
                  lambda x: x.to('meta'), lambda x: x.fill_(float('nan')),
                  lambda x: x.fill_(float('inf'))]
        for fault in faults:
            model = self.model(fault)
            with self.subTest(fault=fault), self.assertRaisesRegex(ValueError, 'RUNTIME_LOGITS_'):
                self.run_tokens([1, 2], model=model)
            self.assertEqual(len(model.calls), 1)
        model = self.model()
        with self.assertRaisesRegex(ValueError, 'RUNTIME_DECODER_DEVICE'):
            runtime.decode_tokens(model, self.tokenizer(), [1], 'task', self.contract, self.cid,
                self.plan, torch, torch.device('meta'))
        self.assertEqual((model.evaluations, model.calls), (0, []))

    def test_malformed_constructed_input_tensors_refuse_before_model_entry(self):
        torch = self.torch
        for ids in (torch.zeros((1, 2), dtype=torch.float32),
                    torch.zeros((2, 2), dtype=torch.int64),
                    torch.zeros((1, 2), dtype=torch.int64, device='meta')):
            model = self.model()
            with self.subTest(ids=ids), patch.object(torch, 'tensor', return_value=ids), \
                    self.assertRaisesRegex(ValueError, 'RUNTIME_INPUT_TENSOR'):
                self.run_tokens([1, 2], model=model)
            self.assertEqual((model.evaluations, model.calls), (0, []))

    def test_checked_execution_scalars_do_not_follow_later_caller_plan_mutation(self):
        model = self.model()
        model.eval = lambda: self.plan.update(generation_tokens=9, backend='changed', snapshot='changed')
        actual = self.run_tokens([1, 2], model=model)
        self.assertEqual((actual['generated_tokens'], actual['snapshot']), (8, 'snapshot'))
        self.assertEqual(len(model.calls), 8)


if __name__ == '__main__':
    unittest.main()
