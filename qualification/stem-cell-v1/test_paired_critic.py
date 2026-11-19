import copy
import math
import unittest

from paired_critic import fit_critic, freeze_protocol, validate_artifact
from next_round_matrix import _digest


def fixture(*, fit_count=8, cal_count=64, repetitions=1, success=.9, failed=False, coefficient=0.):
    fit = [f'f{i:03d}' for i in range(fit_count)]
    cal = [f'c{i:03d}' for i in range(cal_count)]
    pairs = [dict(pair_id=f'{g}-{j}',group_id=g,case_sha256=_digest(g),candidate_bytes=1,feedback_bytes=9)
             for g in fit+cal for j in range(repetitions)]
    p = freeze_protocol(objective_sha256='a'*64, subject_id='episode:critic-test',
                        callback_profile_sha256='b'*64,observer_sha256='c'*64,
                        registered_at_ns=10,cutoff_ns=10**10,expires_at_ns=10**14,
                        fit_groups=fit,calibration_groups=cal,pairs=pairs,candidate_edges=[32],feedback_edges=[32],
                        alpha=.05,minimum_groups=2,max_calibration_gap=.25,
                        duration_upper_ns=5*10**9,formula_work_upper=100,
                        coefficients=dict(discount_rate_per_second=0.,cost_per_formula_flop=coefficient,cost_per_latency_ns=0.))
    rows = [dict(pair_id=q['pair_id'],protocol_id=p['protocol_id'],decision_at_ns=100,
                 observed_at_ns=9*10**9,stop_utility=.1,continue_utility=0. if failed else success,
                 status='failed' if failed else 'completed',duration_ns=10**6,formula_work=6,
                 outcome_receipt_sha256=_digest(['external-fixture-observer',q['pair_id']])) for q in pairs]
    return p,rows


def fit(p,rows):
    return fit_critic(p,rows,expected_protocol_id=p['protocol_id'],expected_dataset_sha256=_digest(rows))[0]


class PairedCriticTests(unittest.TestCase):
    def test_actual_fit_and_heldout_group_bound(self):
        p,rows=fixture();art=fit(p,rows); validate_artifact(art,art['artifact_id'])
        cell=art['table']['0:0']
        self.assertEqual((cell['fit_groups'],cell['calibration_groups']),(8,64))
        self.assertAlmostEqual(cell['fit_mean'],.8)
        self.assertAlmostEqual(cell['radius'],2*math.sqrt(math.log(4/.05)/(2*64)))
        self.assertGreater(cell['net_gain_lower'],0.)
        self.assertTrue(cell['supported'])
        self.assertNotIn('rows',art)
        self.assertFalse(art['final_efficacy_established'])

    def test_outcome_changes_change_fitted_estimates(self):
        p,rows=fixture();a=fit(p,rows)
        for r in rows:r['continue_utility']=.2
        b=fit(p,rows)
        self.assertNotEqual(a['artifact_id'],b['artifact_id'])
        self.assertLess(b['table']['0:0']['net_gain_lower'],0.)

    def test_repetitions_do_not_inflate_independent_support(self):
        a=fit(*fixture(repetitions=1));b=fit(*fixture(repetitions=4))
        self.assertEqual(a['table'],b['table'])
        self.assertNotEqual(a['artifact_id'],b['artifact_id'])

    def test_failed_attempts_stay_in_denominator_and_costs(self):
        p,rows=fixture(failed=True,coefficient=.01);a=fit(p,rows)
        self.assertEqual(a['failed_attempts'],len(rows))
        self.assertAlmostEqual(a['table']['0:0']['fit_mean'],-.16)
        self.assertLess(a['table']['0:0']['net_gain_lower'],0.)
        rows.pop()
        with self.assertRaises(ValueError):fit(p,rows)

    def test_observed_envelope_violation_blocks_whole_release(self):
        for key,value in (('duration_ns',5*10**9+1),('formula_work',101),('formula_work',None)):
            p,rows=fixture();rows[0][key]=value
            with self.subTest(key=key),self.assertRaises(ValueError):fit(p,rows)

    def test_complete_pair_identity_and_dataset_binding(self):
        p,rows=fixture()
        digest=_digest(rows);rows.reverse()
        with self.assertRaises(ValueError):fit_critic(p,rows,expected_protocol_id=p['protocol_id'],expected_dataset_sha256=digest)
        with self.assertRaises(ValueError):fit(p,rows)
        p,rows=fixture();rows[0]['protocol_id']='d'*64
        with self.assertRaises(ValueError):fit(p,rows)

    def test_future_labels_pre_registration_and_bad_values_rejected(self):
        for key,value in (('observed_at_ns',10**10+1),('decision_at_ns',1),('stop_utility',True),
                          ('continue_utility',float('nan')),('status','unknown'),('duration_ns',0)):
            p,rows=fixture();rows[0][key]=value
            with self.subTest(key=key),self.assertRaises(ValueError):fit(p,rows)
        p,rows=fixture(failed=True);rows[0]['continue_utility']=1.
        with self.assertRaises(ValueError):fit(p,rows)

    def test_sparse_and_shifted_calibration_abstain(self):
        p,rows=fixture(cal_count=1);a=fit(p,rows)
        self.assertFalse(a['table']['0:0']['supported'])
        self.assertFalse(a['table']['1:1']['supported'])
        p,rows=fixture()
        for pair,row in zip(p['pairs'],rows):
            if pair['group_id'] in p['calibration_groups']:row['continue_utility']=.1
        a=fit(p,rows)
        self.assertFalse(a['table']['0:0']['supported'])
        self.assertAlmostEqual(a['table']['0:0']['fit_mean'],.8)

    def test_artifact_tamper_and_rehashed_inconsistent_table_reject(self):
        a=fit(*fixture());identity=a['artifact_id']
        a['table']['0:0']['net_gain_lower']=1.
        with self.assertRaises(ValueError):validate_artifact(a,identity)
        a['artifact_id']=_digest({k:v for k,v in a.items() if k!='artifact_id'})
        with self.assertRaisesRegex(ValueError,'inconsistent'):validate_artifact(a,a['artifact_id'])

    def test_protocol_bins_folds_and_case_identity_fixed_before_labels(self):
        p,rows=fixture();args={k:v for k,v in p.items() if k not in ('schema','protocol_id')}
        for key,value in (('candidate_edges',[32,32]),('alpha',True),('minimum_groups',True),
                          ('fit_groups',p['calibration_groups']),('cutoff_ns',10)):
            with self.subTest(key=key),self.assertRaises(ValueError):freeze_protocol(**{**args,key:value})
        args=copy.deepcopy(args);args['pairs'][1]['case_sha256']=args['pairs'][0]['case_sha256']
        with self.assertRaisesRegex(ValueError,'inflate'):freeze_protocol(**args)

    def test_groups_not_samples_set_mean_weights(self):
        p,rows=fixture(repetitions=2)
        rows[0]['continue_utility']=0.
        art=fit(p,rows)
        # Group f000 contributes one average, despite two attempts.
        self.assertAlmostEqual(art['table']['0:0']['fit_mean'],(.35+7*.8)/8)

    def test_refit_does_not_mutate_protocol_or_input_rows(self):
        p,rows=fixture();before=_digest([p,rows]);a=fit(p,rows)
        self.assertEqual(_digest([p,rows]),before)
        a['protocol']['pairs'].clear()
        self.assertEqual(_digest([p,rows]),before)

    def test_net_gain_uses_actual_joint_time_cost_and_reward(self):
        p,rows=fixture(coefficient=.01)
        for row in rows:row['formula_work']=50
        a=fit(p,rows)
        self.assertAlmostEqual(a['table']['0:0']['fit_mean'],.3)
        self.assertAlmostEqual(a['table']['0:0']['radius'],3*math.sqrt(math.log(80)/128))


if __name__=='__main__':unittest.main()
