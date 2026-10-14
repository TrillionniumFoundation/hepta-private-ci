"""Source-only numerical and adversarial tests, not efficacy or independence proof."""
import copy
import math
import unittest

from four_gate_common import digest
from fbsde_acquisition import JointKernel, Objective, solve
from fbsde_acquisition_data import INTENTS, TRAVEL_INTENTS, partition
from fbsde_acquisition_guard import CANDIDATES, bernoulli_bounds, calibrate, compile_guard, guarded_action
from fbsde_acquisition_study import choose
from fbsde_acquisition_audit import verify_calibration


class GuardTests(unittest.TestCase):
    def sample(self, n=400):
        sources = [(str(i), digest(i), i % 2) for i in range(n)]
        records = {a: [{'id': uid, 'source_input_sha256': h, 'action': f'answer:{y}',
                        'modeled_cost': .04} for uid,h,y in sources] for a in CANDIDATES}
        return sources, records

    def test_analytic_zero_failure_and_all_success_endpoints(self):
        for n in (1, 80, 320, 2000):
            low, upper = bernoulli_bounds(0, n, .00625)
            self.assertEqual(low, 0.)
            self.assertAlmostEqual(upper, 1-.00625**(1/n), places=13)
            low, upper = bernoulli_bounds(n, n, .00625)
            self.assertAlmostEqual(low, .00625**(1/n), places=13)
            self.assertEqual(upper, 1.)

    def test_empty_and_invalid_counts(self):
        self.assertEqual(bernoulli_bounds(0, 0, .05), (0., 1.))
        for a,n,d in ((True, 20, .05), (3,2,.05), (1,-1,.05), (1,20,0.), (1,20,float('nan'))):
            with self.assertRaises(ValueError): bernoulli_bounds(a,n,d)

    def test_sample_support_and_error_monotonicity(self):
        prev = 0.
        for errors in range(31):
            upper = bernoulli_bounds(errors, 30, .01)[1]
            self.assertGreaterEqual(upper, prev); prev = upper
        self.assertLess(bernoulli_bounds(0, 800, .01)[1], bernoulli_bounds(0, 80, .01)[1])

    def test_small_calibration_cannot_waive_source_floor(self):
        sources, rows = self.sample(80)
        result = calibrate(rows, sources, digest('model'))
        self.assertEqual(result['selected'], 'abstain')
        self.assertTrue(result['no_candidate_passes'])

    def test_good_candidate_frozen_selection_and_independent_audit(self):
        sources, rows = self.sample()
        result = calibrate(rows, sources, digest('model'))
        self.assertEqual(result['selected'], 'full_symbol')
        self.assertFalse(result['assumptions_authenticated'])
        originals = [{'id':uid,'text_sha256':h,'label':y} for uid,h,y in sources]
        verify_calibration(result, rows, originals, digest('model'))
        altered = copy.deepcopy(result); altered['profiles']['full_symbol']['accepted_error_ucb'] = 0.
        with self.assertRaisesRegex(ValueError, 'bound drift'):
            verify_calibration(altered, rows, originals, digest('model'))

    def test_reject_all_is_not_zero_conditional_risk(self):
        sources, rows = self.sample()
        for values in rows.values():
            for row in values: row['action'] = 'abstain'
        r=calibrate(rows, sources, digest('model'))
        self.assertTrue(r['no_candidate_passes'])
        self.assertTrue(all(p['accepted_error_ucb'] == 1 for p in r['profiles'].values()))

    def test_duplicate_and_unpaired_sources_rejected(self):
        sources, rows = self.sample()
        for change in ('hash','coverage'):
            ss, rr = copy.deepcopy(sources), copy.deepcopy(rows)
            if change == 'hash': ss[-1]=(ss[-1][0],ss[0][1],ss[-1][2])
            else: rr['ndu_bsde'].pop()
            with self.assertRaises(ValueError): calibrate(rr, ss, digest('model'))

    def test_pseudocounts_do_not_create_guard_support(self):
        raw=[(0,0,0,0)]*10+[(1,1,1,1)]*10
        kernel=JointKernel.fit(raw,2,{},alpha=1.)
        actions={}
        for symbol in (0,1): actions.update(solve(kernel,((0,symbol),),Objective())['actions'])
        guard=compile_guard(kernel,raw,actions,Objective())
        unsupported=((0,0),(1,1))
        self.assertEqual(guard['supports'][unsupported],0)
        self.assertEqual(guarded_action('ndu_backoff_5',kernel,unsupported,Objective(),guard),'read:2')
        self.assertEqual(guarded_action('ndu_backoff_5',kernel,unsupported+((2,1),),Objective(),guard),'answer:1')
        with self.assertRaisesRegex(ValueError,'stale'):
            guarded_action('ndu_backoff_5',kernel,unsupported,Objective(costs=(.2,.3)),guard)

    def test_risk_policy_has_no_unsealed_default(self):
        with self.assertRaisesRegex(ValueError,'calibration not sealed'):
            choose('risk_selected',None,(),Objective(),(),.8,None)

    def test_new_original_text_partitions_have_disjoint_calibration(self):
        data={split:[[f'{split} {intent} original {i}',intent] for intent in TRAVEL_INTENTS for i in range(n)]
              for split,n in (('train',100),('val',20),('test',30))}
        p=partition(data,'travel_guard_v1')
        self.assertEqual({k:len(v) for k,v in p.items()},
                         {'fit':320,'kernel':240,'selection':80,'validation':320,'test':240})
        all_hashes=[r['text_sha256'] for group in p.values() for r in group]
        self.assertEqual(len(all_hashes),len(set(all_hashes)))
        self.assertFalse(set(INTENTS)&set(TRAVEL_INTENTS))
