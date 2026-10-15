"""Synthetic-only E2 Token Query vs pooled SGD and fault-injection tests."""
import copy
import hashlib
import unittest
import torch
import e2_token_query_ablation as e


def fixture(width=384):
    rows=[]; bank={}
    for split,n in e.SPLITS.items():
        for i in range(n):
            key=f'{split}-{i}'; label=i%2
            rows.append({'case_id':key,'label':label,'split':split,
                         'joint_input_digest':hashlib.sha256(key.encode()).hexdigest()})
            g=torch.Generator().manual_seed(i+{'train':0,'calibration':101,'test':201}[split])
            t=torch.randn(4+(i%3),width,generator=g)
            t[:,0]+=4 if label else -4
            t=torch.nn.functional.normalize(t,dim=-1)
            t=torch.round(t*e.Q24)/e.Q24
            p=torch.nn.functional.normalize(t.mean(0),dim=0)
            p=torch.round(p*e.Q24)/e.Q24
            bank[key]={'tokens':t,'native_pooled':p}
    return rows,bank


class Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        torch.set_num_threads(1)
        cls.rows,cls.bank=fixture()
        cls.report=e.study(cls.rows,cls.bank,width=384)

    def test_all_real_head_updates(self):
        r=self.report
        self.assertEqual(set(r['arms']),{'pooled_linear','pooled_gated','token_query'})
        self.assertEqual([r['arms'][x]['train_receipt']['trainable_parameters'] for x in r['arms']], [385,769,769])
        for v in r['arms'].values():
            self.assertNotEqual(v['train_receipt']['initial_head_sha256'],v['train_receipt']['final_head_sha256'])
            self.assertEqual(v['train_receipt']['train_steps'],40)
            self.assertEqual(len(v['predictions']),96)
        self.assertFalse(r['authentic_future_ndu_available'])
        self.assertFalse(r['stem_winner_selected'])

    def test_exact_768_budget(self):
        rows,bank=fixture(768)
        r=e.study(rows,bank,width=768)
        self.assertEqual([r['arms'][x]['train_receipt']['trainable_parameters'] for x in r['arms']], [769,1537,1537])
        self.assertFalse(r['pretrained_model_origin_independently_authenticated'])

    def test_holdout_label_change_does_not_change_predictions_or_weights(self):
        rows=copy.deepcopy(self.rows)
        for item in rows:
            if item['split']=='test':item['label']=1-item['label']
        outcome=e.study(rows,self.bank,width=384)
        for kind in self.report['arms']:
            a=outcome['arms'][kind];b=self.report['arms'][kind]
            self.assertEqual(a['predictions'],b['predictions'])
            self.assertEqual(a['train_receipt']['final_head_sha256'],b['train_receipt']['final_head_sha256'])

    def test_source_matrix_mutation_rejected(self):
        rows,bank=fixture()
        bank['train-0']['tokens'][0,0]=float('nan')
        with self.assertRaises(e.Invalid):e.study(rows,bank,width=384)

    def test_misaligned_case_or_token_dimension_rejected(self):
        rows,bank=fixture()
        del bank['test-0']
        with self.assertRaises(e.Invalid):e.study(rows,bank,width=384)
        rows,bank=fixture()
        bank['test-1']['tokens']=bank['test-1']['tokens'][:,:200]
        with self.assertRaises(e.Invalid):e.study(rows,bank,width=384)

    def test_test_rows_are_never_learner_target(self):
        rows,bank=fixture()
        altered=copy.deepcopy(rows)
        for row in altered:
            if row['split']=='calibration':row['label']=1-row['label']
        res=e.study(altered,bank,width=384)
        for kind in self.report['arms']:
            self.assertEqual(res['arms'][kind]['train_receipt']['final_head_sha256'],
                             self.report['arms'][kind]['train_receipt']['final_head_sha256'])

    def test_zero_or_nonunit_token_and_pool_rejected(self):
        rows,bank=fixture()
        bank['test-0']['tokens'][0].zero_()
        with self.assertRaisesRegex(e.Invalid,'unit-L2'):
            e.frozen_bank(rows,bank,width=384)
        rows,bank=fixture()
        p=bank['test-0']['native_pooled']
        bank['test-0']['native_pooled']=torch.round(p*0.5*e.Q24)/e.Q24
        with self.assertRaisesRegex(e.Invalid,'unit-L2'):
            e.frozen_bank(rows,bank,width=384)

    def test_one_snapshot_per_case_is_required(self):
        rows,bank=fixture()
        bank['test-2']['native_pooled']=torch.ones(384)*9
        with self.assertRaises(e.Invalid):e.frozen_bank(rows,bank,width=384)

    def test_parameter_limit_and_fail_closed(self):
        with self.assertRaises(e.Invalid):e.Head(2048,'token_query',torch.zeros(2048))
        with self.assertRaises(e.Invalid):e.study(*fixture(),width=384,steps=0)
        self.assertFalse(self.report['production_no_change_authenticated'])
        self.assertFalse(self.report['production_promotion_permitted'])
        self.assertEqual(self.report['authority'],'DENY_ALL')

if __name__=='__main__':unittest.main()
