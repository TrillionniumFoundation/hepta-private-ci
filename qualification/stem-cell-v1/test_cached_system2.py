import copy
import tempfile
import unittest
from dataclasses import asdict
from pathlib import Path
from unittest.mock import patch

import torch

from cache_test_support import make_proposer, train_attention
from causal_cache import freeze_cache
from causal_snapshot import load_local_causal
from execution_meter import WorkLedger
from generation_test_support import structural_verifier
from matrix_materials import file_sha256
from next_round_matrix import _digest
from paired_capture import PairCollector, freeze_capture, create_capture
from paired_capture_export import read_pair
from paired_critic import freeze_protocol
from reasoning_baselines import PROFILE, freeze_baseline
from system2_execution import PublicTask, run_reasoning
from test_paired_capture import Clock
from test_reasoning_baselines import policy_inputs, ready_ndu
from ndu_continuation import PROFILE as NDU_PROFILE


class CachedSystemTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.model, cls.codec, cls.training = train_attention()

    def fixed(self, proposer, *, strategy='fixed_depth', cap=None):
        wp, caps = policy_inputs()
        if cap is not None: caps['search'] = cap
        depth = 1 if strategy == 'no_search' else 2
        profile = _digest([proposer.receipt()['policy'], 'format_verifier'])
        policy = freeze_baseline(strategy=strategy, objective_sha256='a'*64, callback_profile_sha256=profile,
                                 expires_at_ns=10**15, meter_policy=wp, phase_caps=caps, max_rounds=depth)
        return run_reasoning(PublicTask('colour red', 10**10+1), propose=proposer, verify=structural_verifier,
                             continue_values=None, value_profile=PROFILE, max_rounds=depth, max_calls=2*depth,
                             fixed_policy=policy, meter=WorkLedger(wp, caps), clock=lambda:10**10+5)

    def test_live_meter_counts_less_work_for_same_outputs_without_padding(self):
        plain, cached = [make_proposer(self.model, self.codec, cached=c) for c in (False, True)]
        a, b = self.fixed(plain), self.fixed(cached)
        self.assertEqual((a['candidate'], b['candidate'], a['calls'], b['calls']), ('red done','red done',4,4))
        self.assertEqual(b['work_observation']['unknown_operators'], {})
        self.assertLess(b['work_observation']['phase_flops']['search'], a['work_observation']['phase_flops']['search'])
        generations = [e['generation'] for e in b['trace'] if e['kind']=='propose']
        self.assertEqual([g['cache']['forwarded_tokens'] for g in generations], [6,11])
        self.assertTrue(all(g['cache']['released'] for g in generations))
        self.assertFalse(b['independent_success_established'])

    def test_same_cap_can_complete_cached_path_and_stop_reference(self):
        plain, cached = [make_proposer(self.model, self.codec, cached=c) for c in (False, True)]
        a, b = self.fixed(plain), self.fixed(cached)
        cap = (a['work_observation']['phase_flops']['search'] + b['work_observation']['phase_flops']['search']) // 2
        stopped, completed = self.fixed(plain, cap=cap), self.fixed(cached, cap=cap)
        self.assertEqual(stopped['status'], 'resource_budget_stop')
        self.assertEqual(completed['status'], 'verifier_accepted_not_independent_eval')
        self.assertFalse(completed['full_cost_qualification'])

    def test_budget_stop_releases_cache_and_fresh_run_can_succeed(self):
        proposer = make_proposer(self.model, self.codec)
        report = self.fixed(proposer, cap=1)
        self.assertEqual(report['status'], 'resource_budget_stop')
        self.assertIsNone(report['candidate'])
        self.assertEqual(self.fixed(proposer)['candidate'], 'red done')

    def test_synthetic_supported_critic_drives_same_cached_neural_callback(self):
        proposer = make_proposer(self.model, self.codec)
        profile = _digest([proposer.receipt()['policy'], 'format_verifier'])
        policy, critic = ready_ndu(proposer, structural_verifier, profile)
        wp, caps = policy_inputs()
        report = run_reasoning(PublicTask('colour red',10**10+1), propose=proposer, verify=structural_verifier,
                               continue_values=critic, value_profile=NDU_PROFILE, max_calls=5, max_rounds=2,
                               ndu_policy=policy, meter=WorkLedger(wp,caps), clock=lambda:10**10+5)
        self.assertEqual((report['calls'],report['candidate']), (5,'red done'))
        self.assertEqual([e['generation']['cache']['released'] for e in report['trace'] if e['kind']=='propose'], [True,True])
        self.assertFalse(report['learned_critic_validated'])

    def test_paired_capture_keeps_new_cache_source_and_actual_memory_record(self):
        import json
        proposer = make_proposer(self.model, self.codec)
        profile = _digest([proposer.receipt()['policy'], 'format_verifier'])
        groups=['f0','f1','c0','c1']; pairs=[]; boundaries=[]
        from empirical_continuation import case_fingerprint
        for group in groups:
            task=PublicTask('colour red '+group,5)
            pairs.append(dict(pair_id=group,group_id=group,case_sha256=case_fingerprint(task,'unsure','revise'),
                              candidate_bytes=6,feedback_bytes=6))
            boundaries.append(dict(pair_id=group,task=json.loads(json.dumps(asdict(task))),candidate='unsure',feedback='revise',
                                   available_at_ns=9,origin_receipt_sha256='d'*64,initial_verifier_accepted=False))
        p=freeze_protocol(objective_sha256='a'*64,subject_id='episode:cache-test',callback_profile_sha256=profile,
                          observer_sha256='c'*64,registered_at_ns=10,cutoff_ns=10**12,expires_at_ns=10**15,
                          fit_groups=groups[:2],calibration_groups=groups[2:],pairs=pairs,candidate_edges=[64],feedback_edges=[64],
                          alpha=.05,minimum_groups=2,max_calibration_gap=.25,duration_upper_ns=5*10**9,formula_work_upper=10**7,
                          coefficients=dict(discount_rate_per_second=0.,cost_per_formula_flop=0.,cost_per_latency_ns=0.))
        wp,caps=policy_inputs()
        reg=freeze_capture(p,expected_protocol_id=p['protocol_id'],boundaries=boundaries,meter_policy=wp,phase_caps=caps)
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)/'pairs';create_capture(root,reg)
            collector=PairCollector(root,expected_capture_id=reg['capture_id'],callback_profile_sha256=profile,
                                     propose=proposer,verify=structural_verifier)
            seal=collector.run_pair('f0',clock=Clock())
            record,_=read_pair(root,reg,0,seal['terminal_id'])
            generation=record['execution']['trace'][0]['generation']
            self.assertTrue(generation['cache']['released'])
            self.assertGreater(generation['cache']['max_boundary_storage_union_bytes'],0)
            self.assertEqual(reg['source_files_sha256']['causal_cache.py'],file_sha256(Path(__file__).with_name('causal_cache.py')))

    def test_stock_loader_rejects_unmatched_cache_geometry_before_factory(self):
        from test_causal_snapshot import CausalSnapshotTests
        # Reuse the real safetensor fixture setup, not its test methods/counts.
        f=CausalSnapshotTests(methodName='test_context_geometry_version_and_missing_safe_weights_preflight')
        f.setUp()
        try:
            policy=freeze_cache(layers=2,heads=3,head_dim=4,max_cache_bytes=4096,cache_format='hf_dynamic_gpt2_4_57_1')
            with self.assertRaisesRegex(ValueError,'geometry'): f.load(cache_policy=policy)
            f.loader.assert_not_called()
        finally: f.doCleanups()


if __name__=='__main__':unittest.main()
