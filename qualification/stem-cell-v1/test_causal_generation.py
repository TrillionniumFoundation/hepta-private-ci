import copy
import unittest
from types import SimpleNamespace
from unittest.mock import patch

import torch

from causal_generation import GenerationIncomplete, LocalCausalProposer, freeze_generation, render_prompt
from generation_test_support import adapter, train_tiny
from matrix_bank import state_digest
from system2_execution import PublicTask


class CausalGenerationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.model, cls.codec, cls.training = train_tiny()

    def setUp(self):
        self.m, self.t = copy.deepcopy(self.model), copy.deepcopy(self.codec)
        self.p = adapter(self.m, self.t)
        self.task = PublicTask("colour red", 5)

    def test_actually_trained_next_token_weights_generate_revision(self):
        self.assertNotEqual(self.training['initial_sha256'], self.training['trained_sha256'])
        self.assertEqual(self.p(self.task, None, None), "unsure")
        self.assertEqual(self.p(self.task, "unsure", "revise"), "red done")
        report = self.p.receipt()['last_generation']
        self.assertEqual((report['forward_attempts'], report['generated_tokens'], report['eos_observed']), (3, 2, True))
        self.assertEqual([s['prefix_tokens'] for s in report['token_steps']], [9, 10, 11])
        self.assertFalse(self.p.receipt()['pretrained_provenance_verified'])

    def test_future_suffix_cannot_change_an_earlier_position_logit(self):
        prefix=torch.tensor([[2,3,7,8]])
        extended=torch.cat((prefix,torch.tensor([[4,11,5,12]])),dim=1)
        with torch.inference_mode():
            def forward(ids):
                return self.m(ids,attention_mask=torch.ones_like(ids),past_key_values=None,
                              use_cache=False,return_dict=True).logits
            torch.testing.assert_close(forward(prefix)[:, -1],forward(extended)[:, 3])

    def test_greedy_replay_has_no_cross_request_kv_or_rng_mutation(self):
        before, rng = state_digest(self.m), torch.get_rng_state().clone()
        a = self.p(self.task, "unsure", "revise")
        self.assertEqual(self.p(PublicTask("colour blue", 5), "unsure", "revise"), "blue done")
        self.assertEqual(self.p(self.task, "unsure", "revise"), a)
        self.assertEqual(state_digest(self.m), before)
        torch.testing.assert_close(torch.get_rng_state(), rng, rtol=0, atol=0)

    def test_shared_model_not_copied_and_snapshot_detached(self):
        q = adapter(self.m, self.t)
        self.assertIs(q._model, self.p._model)
        self.p(self.task, None, None)
        receipt = self.p.receipt(); receipt['policy']['max_new_tokens'] = 1
        receipt['last_generation']['token_steps'].clear()
        self.assertEqual(len(self.p.receipt()['last_generation']['token_steps']), 2)
        self.assertEqual(self.p.receipt()['policy']['max_new_tokens'], 6)

    def test_token_exhaustion_cannot_publish_partial_answer(self):
        p = adapter(self.m, self.t, max_new_tokens=1)
        with self.assertRaises(GenerationIncomplete): p(self.task, None, None)
        r = p.receipt()['last_generation']
        self.assertEqual((r['status'], r['forward_attempts'], r['generated_tokens']), ('failed', 1, 1))
        self.assertIsNone(r['output_sha256'])

    def test_context_preflight_happens_before_any_model_forward(self):
        p = adapter(self.m, self.t, context_tokens=8, max_new_tokens=3)
        with patch.object(self.m, 'forward', side_effect=AssertionError('must not call')) as f:
            with self.assertRaises(GenerationIncomplete): p(self.task, "unsure", "revise")
            f.assert_not_called()
        self.assertEqual(p.receipt()['last_generation']['forward_attempts'], 0)

    def test_output_byte_limit_rejects_without_silent_truncation(self):
        p = adapter(self.m, self.t, max_output_bytes=2)
        with self.assertRaises(GenerationIncomplete): p(self.task, None, None)
        self.assertTrue(p.receipt()['last_generation']['eos_observed'])
        self.assertIsNone(p.receipt()['last_generation']['output_sha256'])

    def test_material_mutation_and_train_mode_reject_before_forward(self):
        with torch.no_grad(): self.m.output.bias.add_(1)
        with self.assertRaisesRegex(ValueError, 'material'): self.p(self.task, None, None)
        self.assertEqual(self.p.receipt()['last_generation']['forward_attempts'], 0)
        self.m = copy.deepcopy(self.model); self.m.train()
        with self.assertRaisesRegex(ValueError, 'frozen eval'): adapter(self.m, self.t)

    def test_model_mutation_during_generation_rejects_success(self):
        original = self.m.forward
        def mutating(*args, **kwargs):
            out = original(*args, **kwargs)
            self.m.output.bias.data.add_(.0001)
            return out
        with patch.object(self.m, 'forward', side_effect=mutating):
            with self.assertRaisesRegex(ValueError, 'material'): self.p(self.task, None, None)
        self.assertIsNone(self.p.receipt()['last_generation']['output_sha256'])

    def test_tokenizer_mutation_and_invalid_ids_reject(self):
        self.t.special_tokens_map = {'eos_token': 'changed'}
        with self.assertRaisesRegex(ValueError, 'material'): self.p(self.task, None, None)
        self.t.special_tokens_map = self.codec.special_tokens_map
        for ids in ([True], [-1], [len(self.t.words)], []):
            with self.subTest(ids=ids), patch.object(self.t, 'encode', return_value=ids):
                with self.assertRaises(ValueError): self.p(self.task, None, None)

    def test_nonfinite_wrong_geometry_and_persistent_cache_reject(self):
        original = self.m.forward
        for kind in ('nan', 'shape', 'cache'):
            def wrong(*args, **kwargs):
                out = original(*args, **kwargs)
                if kind == 'nan': return SimpleNamespace(logits=out.logits * float('nan'))
                if kind == 'shape': return SimpleNamespace(logits=out.logits[:, :, :2])
                return SimpleNamespace(logits=out.logits, past_key_values=object())
            with self.subTest(kind=kind), patch.object(self.m, 'forward', side_effect=wrong):
                with self.assertRaises(ValueError): self.p(self.task, None, None)

    def test_empty_eos_and_reentrant_calls_fail_closed(self):
        with torch.no_grad(): self.m.output.weight.zero_(); self.m.output.bias.zero_(); self.m.output.bias[1]=100
        p = adapter(self.m, self.t)
        with self.assertRaises(GenerationIncomplete): p(self.task, None, None)
        self.p._lock.acquire()
        try:
            with self.assertRaisesRegex(ValueError, 'concurrent'): self.p(self.task, None, None)
        finally: self.p._lock.release()

    def test_prompt_only_contains_declared_public_fields(self):
        for prev, feed in ((None, 'feedback'), ('candidate', None)):
            with self.assertRaises(ValueError): render_prompt(self.task, prev, feed)
        with self.assertRaises(ValueError): render_prompt(PublicTask('colour red', 5, (('future', 6),)), None, None)
        with self.assertRaises(ValueError): render_prompt(PublicTask('x'*65536, 5), 'y'*65536, 'z')
        text = render_prompt(self.task, 'unsure', 'revise')
        self.assertNotIn('label', text)
        with self.assertRaises(ValueError): render_prompt({'prompt': 'bad'}, None, None)

    def test_config_rehash_or_geometry_change_is_rejected(self):
        policy = self.p.receipt()['policy']; policy['persistent_kv_cache'] = True
        with self.assertRaises(ValueError): LocalCausalProposer(self.m, self.t, policy)
        for key, value in (('max_new_tokens', True), ('eos_token_id', -1), ('context_tokens', 2)):
            params = {k:v for k,v in self.p.receipt()['policy'].items() if k in
                      ('model_sha256','tokenizer_sha256','vocab_size','eos_token_id','context_tokens','max_new_tokens','max_output_bytes')}
            params[key] = value
            with self.subTest(key=key), self.assertRaises(ValueError): freeze_generation(**params)


if __name__ == '__main__': unittest.main()
