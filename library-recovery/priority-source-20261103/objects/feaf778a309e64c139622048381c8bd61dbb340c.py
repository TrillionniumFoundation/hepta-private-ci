"""Synthetic fixtures exercise the P1 gate implementation, not neural evidence."""
import copy
import random
import unittest
from .paired_gate import analyze, ContractError, CONTRASTS


def synthetic_fixture(*, improvement=.2, n=10):
    rng=random.Random(202610305)
    protocol={
        'source_sha':'1'*40,
        'protocol_sha256':'2'*64,
        'train_dataset_sha256':'3'*64,
        'holdout_sha256':'4'*64,
        'cpu_penalty':.0001,
        'joule_penalty':.00001,
        'practical_gain':.01,
        'frozen_before_holdout':True,
        'holdout_access_prohibited_pre_registration':True,
    }
    c={}
    for k in CONTRASTS:
        arm=[]
        for seed in range(n):
            candidate_quality=min(.95,max(.05,.55+improvement+rng.uniform(-.015,.015)))
            arm.append(dict(
                seed=seed,batch_sha256=f'{seed+1:064x}',
                candidate_quality=candidate_quality, baseline_quality=.55,
                candidate_active_params=1002, baseline_active_params=1000,
                candidate_train_cpu_s=100., baseline_train_cpu_s=100.,
                candidate_worker_cpu_s=110., baseline_worker_cpu_s=109.,
                candidate_energy_j=25., baseline_energy_j=25.,
                candidate_local_value=.5, baseline_local_value=.5,
                candidate_local_slope=.25, baseline_local_slope=.25,
                same_optimizer=True,same_head=True,same_tokens=True,
                both_actual_trainable=True))
        c[k]=arm
    return dict(schema='hcsn-p1-paired-v1',protocol=protocol,contrasts=c)


class P1PairedGateTests(unittest.TestCase):
    def test_synthetic_positive_metric_gate_only(self):
        r=analyze(synthetic_fixture())
        self.assertEqual(len(r),4)
        for case in r:
            self.assertTrue(case.wins_practical_gate)
            self.assertLessEqual(case.holm_adjusted_p,.05)
            self.assertGreater(case.bonferroni_lower_95,.01)
        # This is only a statistics/data-shape diagnostic, not a scientific
        # confirmation. External source/registration receipts are unavailable.

    def test_synthetic_negative_preserves_four_failures(self):
        r=analyze(synthetic_fixture(improvement=-.2))
        self.assertTrue(all(not x.wins_practical_gate for x in r))
        self.assertTrue(all(x.mean_net_utility_gain<0 for x in r))

    def test_exact_p_for_ten_all_positive_pairs(self):
        from .paired_gate import _exact_sign_flip_p
        self.assertAlmostEqual(_exact_sign_flip_p([.2]*10),2/1024)
        self.assertEqual(_exact_sign_flip_p([0.]*10),1.)

    def test_missing_or_unfrozen_protocol_rejected(self):
        p=synthetic_fixture(); p['protocol']['frozen_before_holdout']=False
        with self.assertRaises(ContractError): analyze(p)
        p=synthetic_fixture();p['protocol'].pop('holdout_sha256')
        with self.assertRaises(ContractError): analyze(p)

    def test_empty_energy_is_not_measured_zero(self):
        p=synthetic_fixture();p['contrasts'][CONTRASTS[0]][0]['candidate_energy_j']=None
        with self.assertRaises(ContractError): analyze(p)

    def test_nonfinite_or_boolean_cost_rejected(self):
        for value in (float('nan'),float('inf'),True,-1):
            p=synthetic_fixture()
            p['contrasts'][CONTRASTS[0]][0]['candidate_worker_cpu_s']=value
            with self.subTest(value=value),self.assertRaises(ContractError): analyze(p)

    def test_worker_cpu_must_include_train_cpu(self):
        p=synthetic_fixture();p['contrasts'][CONTRASTS[0]][0]['candidate_worker_cpu_s']=20.
        with self.assertRaises(ContractError): analyze(p)

    def test_effective_trainable_param_count_is_not_padded(self):
        p=synthetic_fixture();p['contrasts'][CONTRASTS[0]][0]['candidate_active_params']=1200
        with self.assertRaises(ContractError): analyze(p)
        p=synthetic_fixture();p['contrasts'][CONTRASTS[0]][0]['both_actual_trainable']=False
        with self.assertRaises(ContractError): analyze(p)

    def test_training_budget_mismatch_rejected(self):
        p=synthetic_fixture();p['contrasts'][CONTRASTS[0]][0]['candidate_train_cpu_s']=80.
        with self.assertRaises(ContractError): analyze(p)

    def test_local_gradient_and_anchor_mismatch_rejected(self):
        for name,value in [('candidate_local_value',.6),('candidate_local_slope',-.25),
                           ('baseline_local_slope',0.)]:
            p=synthetic_fixture();p['contrasts'][CONTRASTS[0]][0][name]=value
            with self.subTest(field=name),self.assertRaises(ContractError): analyze(p)

    def test_data_leakage_or_different_minibatch_prefix_rejected(self):
        p=synthetic_fixture();p['contrasts'][CONTRASTS[1]][0]['batch_sha256']='f'*64
        with self.assertRaises(ContractError): analyze(p)

    def test_duplication_or_cross_arm_seed_mismatch_rejected(self):
        p=synthetic_fixture();p['contrasts'][CONTRASTS[0]][1]['seed']=0
        with self.assertRaises(ContractError): analyze(p)
        p=synthetic_fixture();p['contrasts'][CONTRASTS[0]][1]['seed']=90
        with self.assertRaises(ContractError): analyze(p)

    def test_holm_four_comparisons_required(self):
        p=synthetic_fixture();p['contrasts'].pop('margin_vs_gate')
        with self.assertRaises(ContractError): analyze(p)

    def test_minimum_seed_count_rejected(self):
        p=synthetic_fixture(n=9)
        with self.assertRaises(ContractError): analyze(p)

    def test_backend_or_optimizer_mismatch_rejected(self):
        for name in ('same_optimizer','same_head','same_tokens'):
            p=synthetic_fixture();p['contrasts'][CONTRASTS[0]][0][name]=False
            with self.subTest(field=name),self.assertRaises(ContractError):analyze(p)


if __name__=='__main__':
    unittest.main()
