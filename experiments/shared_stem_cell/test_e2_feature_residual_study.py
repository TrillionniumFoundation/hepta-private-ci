"""Physical PyTorch optimizer work on synthetic feature fixtures only."""
import copy
import hashlib
import unittest

import e2_feature_residual_study as e


def fixture(width=384):
    counts={'train':128, 'calibration':32, 'test':64}
    cases=[]; vectors={}
    for split,n in counts.items():
        for i in range(n):
            k=len(cases);label=k%2
            s=hashlib.sha256(f'{split}-{i}'.encode()).hexdigest()
            cases.append({'case_id':s[:24], 'label':label, 'split':split,
                          'joint_input_digest':s})
            vectors[s[:24]]=[(0.2 if label else -.2) + ((j%3)-1)*.001
                             for j in range(width)]
    panel={'case_count':224,'cross_sectional_not_future':True,
           'production_promotion':'DENY_ALL','cases':cases}
    return panel,vectors


class ResidualStudyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import torch
        torch.set_num_threads(1)
        cls.panel,cls.vectors=fixture()
        cls.result=e.study(cls.panel,'synthetic',cls.vectors)

    def test_zero_init_exact_and_trainable_update(self):
        o=self.result
        self.assertFalse(o['production_promotion_permitted'])
        for budget,name in zip(e.BUDGETS,('residual_2k','residual_8k','residual_16k')):
            self.assertTrue(o['arms'][name]['initial_baseline_logits_identical'])
            self.assertLessEqual(o['training'][name]['trainable_parameters'],budget)
            self.assertNotEqual(o['training'][name]['initial_head_sha256'],
                                o['training'][name]['final_head_sha256'])
            self.assertEqual(o['training'][name]['optimizer_steps'],40)
        self.assertEqual(o['arms']['from_zero']['trainable_parameters'],770)
        self.assertEqual(set(o['arms']),set(e.HEAD_ARMS))
        self.assertEqual(o['frozen_base_parameters_counted_as_shared_storage'],770)
    def test_256_mrl_head_budgets(self):
        p,v=fixture(256)
        x=e.study(p,'synthetic_mrl',v)
        self.assertEqual(x['arms']['from_zero']['trainable_parameters'],514)
        for name,cap in x['head_parameter_ceiling_by_arm'].items():
            self.assertLessEqual(x['training'][name]['trainable_parameters'],cap)
    def test_test_labels_cannot_affect_weights_or_predictions(self):
        p,v=fixture(384)
        a=e.study(p,'test',v)
        modified=copy.deepcopy(p)
        for row in modified['cases']:
            if row['split']=='test':row['label']=1-row['label']
        b=e.study(modified,'test',v)
        self.assertEqual(a['arms'],b['arms'])
        for name in a['training']:
            self.assertEqual(a['training'][name]['initial_head_sha256'],b['training'][name]['initial_head_sha256'])
            self.assertEqual(a['training'][name]['final_head_sha256'],b['training'][name]['final_head_sha256'])
    def test_calibration_labels_do_not_affect_weights(self):
        p,v=fixture(384);a=e.study(p,'test',v)
        modified=copy.deepcopy(p)
        for row in modified['cases']:
            if row['split']=='calibration':row['label']=1-row['label']
        b=e.study(modified,'test',v)
        for name in a['training']:
            self.assertEqual(a['training'][name]['final_head_sha256'],b['training'][name]['final_head_sha256'])
    def test_missing_features_rejected(self):
        p,v=fixture();v.pop(next(iter(v)))
        with self.assertRaises(e.Invalid):e.study(p,'x',v)
    def test_nonfinite_features_rejected(self):
        p,v=fixture();v[next(iter(v))][0]=float('nan')
        with self.assertRaises(e.Invalid):e.study(p,'x',v)
    def test_wrong_width_rejected(self):
        p,v=fixture(64)
        with self.assertRaises(e.Invalid):e.study(p,'x',v)
    def test_zero_steps_rejected(self):
        p,v=fixture()
        with self.assertRaises(e.Invalid):e.study(p,'x',v,steps=0)
    def test_missing_calibration_rejected(self):
        p,v=fixture();p['cases'][129]['split']='test'
        with self.assertRaises(e.Invalid):e.study(p,'x',v)
    def test_bad_lr_rejected(self):
        p,v=fixture()
        with self.assertRaises(e.Invalid):e.study(p,'x',v,learning_rate=float('nan'))
    def test_no_cell_state_or_ndu_claim(self):
        o=self.result
        self.assertEqual(o['head_kind'],'post_encoder_feature_gated_residual_not_cell_state_film')
        self.assertFalse(o['independent_no_change_production_arm_present'])
        self.assertFalse(o['chronological_future_ndu_verified'])

if __name__=='__main__':unittest.main()
