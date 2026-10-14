import copy
import unittest
import weakref
from unittest.mock import patch

import torch

from cache_test_support import make_proposer, train_attention, TinyAttentionLM
from causal_cache import RequestKV, freeze_cache, validate_cache_policy
from causal_generation import GenerationIncomplete, freeze_generation
from matrix_bank import state_digest
from system2_execution import PublicTask


class RequestCacheTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.model, cls.codec, cls.training = train_attention()

    def setUp(self):
        self.model = copy.deepcopy(type(self).model)
        self.proposer = make_proposer(self.model, self.codec)
        self.policy = self.proposer.receipt()['policy']['cache_policy']
        self.task = PublicTask('colour red', 5)

    def test_learned_cached_generation_matches_reference_with_less_input_work(self):
        plain = make_proposer(self.model, self.codec, cached=False)
        for colour in ('red', 'green', 'blue'):
            task = PublicTask('colour '+colour, 5)
            for prior, feedback, expected in ((None, None, 'unsure'), ('unsure', 'revise', colour+' done')):
                self.assertEqual(plain(task, prior, feedback), expected)
                self.assertEqual(self.proposer(task, prior, feedback), expected)
                a, b = plain.receipt()['last_generation'], self.proposer.receipt()['last_generation']
                self.assertEqual(a['generated_ids_sha256'], b['generated_ids_sha256'])
                self.assertEqual(b['cache']['forwarded_tokens'], b['prompt_tokens'] + b['forward_attempts'] - 1)
                self.assertLess(b['cache']['forwarded_tokens'], sum(s['prefix_tokens'] for s in a['token_steps']))
                self.assertTrue(b['cache']['released'])

    def test_every_incremental_logit_matches_full_attention_across_seeds(self):
        with torch.random.fork_rng(devices=[]):
            for seed in range(5):
                torch.manual_seed(seed)
                model = TinyAttentionLM().eval().requires_grad_(False)
                tokens = torch.randint(2, 15, (1, 7))
                session = RequestKV(model, self.policy, prompt_tokens=7, max_new_tokens=5)
                try:
                    with torch.inference_mode():
                        for _ in range(5):
                            expected = model(tokens, attention_mask=torch.ones_like(tokens)).logits[:, -1]
                            actual, _ = session.forward(tokens)
                            torch.testing.assert_close(actual[:, -1], expected, rtol=1e-5, atol=2e-6)
                            self.assertEqual(actual[:, -1].argmax(-1).tolist(), expected.argmax(-1).tolist())
                            tokens = torch.cat((tokens, torch.randint(2, 15, (1, 1))), dim=1)
                finally:
                    session.close()

    def test_masks_positions_and_no_cross_request_cache(self):
        original, calls = self.model.forward, []
        def observe(*args, **kwargs):
            calls.append((kwargs['input_ids'].shape[1], kwargs['attention_mask'].shape[1],
                          kwargs['cache_position'].tolist(), kwargs['past_key_values'] is None))
            return original(*args, **kwargs)
        with patch.object(self.model, 'forward', side_effect=observe):
            self.proposer(self.task, 'unsure', 'revise')
            self.proposer(PublicTask('colour blue', 5), None, None)
        self.assertEqual(calls, [(9, 9, list(range(9)), True), (1, 10, [9], False), (1, 11, [10], False),
                                 (5, 5, list(range(5)), True), (1, 6, [5], False)])

    def test_cache_objects_not_retained_in_adapter_or_reports(self):
        refs, original = [], self.model.forward
        def observe(*args, **kwargs):
            result = original(*args, **kwargs)
            refs.extend(weakref.ref(t) for layer in result.past_key_values for t in layer)
            return result
        with patch.object(self.model, 'forward', new=observe):
            self.proposer(self.task, 'unsure', 'revise')
        self.assertTrue(all(r() is None for r in refs))
        self.assertEqual(set(self.proposer.__dict__), {'_model','_tokenizer','_policy','_lock','_last'})
        self.assertEqual(state_digest(self.model), self.training['trained_sha256'])

    def test_cache_budget_rejects_before_first_forward(self):
        cfg = freeze_cache(layers=1, heads=3, head_dim=4, max_cache_bytes=1, cache_format='legacy_tuple')
        p = make_proposer(self.model, self.codec, cache_policy=cfg)
        with patch.object(self.model, 'forward') as forward:
            with self.assertRaisesRegex(ValueError, 'token envelope'): p(self.task, None, None)
            forward.assert_not_called()

    def test_old_plus_returned_storage_cap_stops_mid_generation(self):
        cfg = freeze_cache(layers=1, heads=3, head_dim=4, max_cache_bytes=1344, cache_format='legacy_tuple')
        p = make_proposer(self.model, self.codec, cache_policy=cfg)
        with self.assertRaisesRegex(ValueError, 'storage union'): p(self.task, 'unsure', 'revise')
        r = p.receipt()['last_generation']
        self.assertEqual(r['status'], 'failed'); self.assertIsNone(r['output_sha256'])
        self.assertTrue(r['cache']['released'])
        self.assertGreater(r['cache']['max_boundary_storage_union_bytes'], 1344)

    def test_incomplete_eos_releases_and_next_proposal_starts_fresh(self):
        p = make_proposer(self.model, self.codec, max_new_tokens=1)
        for _ in range(2):
            with self.assertRaises(GenerationIncomplete): p(self.task, None, None)
            self.assertTrue(p.receipt()['last_generation']['cache']['released'])
        self.assertEqual(self.proposer(self.task, None, None), 'unsure')

    def test_invalid_returned_cache_never_falls_back_to_full_recompute(self):
        original = self.model.forward
        for mode in ('missing', 'nan', 'shape', 'dtype', 'oversized_view'):
            calls = []
            def corrupt(*args, **kwargs):
                calls.append(1); result = original(*args, **kwargs)
                k, v = result.past_key_values[0]
                if mode == 'missing': result.past_key_values = None
                elif mode == 'nan': result.past_key_values = ((k*float('nan'), v),)
                elif mode == 'shape': result.past_key_values = ((k[:,:,:-1], v),)
                elif mode == 'dtype': result.past_key_values = ((k.double(), v),)
                else:
                    big = torch.zeros(1,3,10000,4); result.past_key_values = ((big[:,:,:k.shape[2]], v),)
                return result
            with self.subTest(mode=mode), patch.object(self.model, 'forward', side_effect=corrupt):
                with self.assertRaises(ValueError): self.proposer(self.task, None, None)
                self.assertEqual(len(calls), 1)
                self.assertTrue(self.proposer.receipt()['last_generation']['cache']['released'])

    def test_weight_alias_in_cache_is_rejected(self):
        original = self.model.forward
        def corrupt(*args, **kwargs):
            result = original(*args, **kwargs)
            k, v = result.past_key_values[0]
            alias = self.model.position.weight[:k.numel()//12].reshape(k.shape)
            result.past_key_values = ((alias, v),)
            return result
        with patch.object(self.model, 'forward', side_effect=corrupt):
            with self.assertRaisesRegex(ValueError, 'aliases'): self.proposer(self.task, None, None)

    def test_policy_hashes_preserve_legacy_and_reject_tampering(self):
        plain = make_proposer(self.model, self.codec, cached=False).receipt()['policy']
        self.assertEqual(plain['schema'], 'hepta.local-causal-proposer.v1')
        self.assertNotIn('cache_policy', plain)
        altered = copy.deepcopy(self.policy); altered['scope'] = 'all_cells'
        with self.assertRaises(ValueError): validate_cache_policy(altered)
        for value in (True, 0, -1, 1.5):
            with self.assertRaises(ValueError): freeze_cache(layers=value, heads=3, head_dim=4,
                                                            max_cache_bytes=100, cache_format='legacy_tuple')

    def test_direct_session_refuses_changed_prefix_and_closed_reuse(self):
        s = RequestKV(self.model, self.policy, prompt_tokens=3, max_new_tokens=3)
        with torch.inference_mode():
            s.forward(torch.tensor([[2,3,4]]))
            with self.assertRaisesRegex(ValueError, 'different prefix'): s.forward(torch.tensor([[2,3,5,6]]))
        s.close()
        with self.assertRaisesRegex(ValueError, 'closed'): s.forward(torch.tensor([[2,3,4,5]]))

    def test_receipts_are_independent_and_greedy_does_not_advance_rng(self):
        rng = torch.get_rng_state().clone()
        self.proposer(self.task, 'unsure', 'revise')
        r = self.proposer.receipt(); r['last_generation']['cache']['released'] = False
        self.assertTrue(self.proposer.receipt()['last_generation']['cache']['released'])
        torch.testing.assert_close(torch.get_rng_state(), rng, rtol=0, atol=0)


if __name__ == '__main__': unittest.main()
