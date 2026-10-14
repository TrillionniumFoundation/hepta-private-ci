"""Pretrained data-plane contracts. Synthetic scores never qualify E1/E2 efficacy."""
import unittest

import numpy as np
import torch

from experiments.shared_stem_cell.e2_modern_budget import BUDGETS,SEEDS,rank_for,train_one
from experiments.shared_stem_cell.e1_e2_joint_review import (
    paired_statistics,_predictions, BUDGETS as JOINT_BUDGETS,
    SEEDS as JOINT_SEEDS,
)
from experiments.shared_stem_cell.preflight_review import PreflightError
from experiments.shared_stem_cell.wire import canonical,sha


def fixture():
    truth={f'c-{i}':{'case_id':f'c-{i}','group':f'source-{i}',
                   'split':'holdout','scope':'research','cell':i%2,
                   'text':f'original sentence {i}','label':i%4}
           for i in range(32)}
    before,after={},{}
    for b in BUDGETS:
        for seed in SEEDS:
            for k,row in truth.items():
                gold=row['label']
                a=[.02]*4
                a[(gold+1)%4 if int(k.split('-')[1])<10 else gold]=.94
                z=[.02]*4
                z[gold if int(k.split('-')[1])<12 else (gold+1)%4]=.94
                before[(b,seed,k)]=a
                after[(b,seed,k)]=z
    return truth,before,after


class CrossStemTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        torch.set_num_threads(2)

    def test_exact_budgets_fit_768d_under_each_ceiling(self):
        self.assertEqual(BUDGETS, JOINT_BUDGETS)
        self.assertEqual(SEEDS, JOINT_SEEDS)
        expect=[1550,7734,16237,64936,262051]
        self.assertEqual([rank_for(768,4,b)[1] for b in BUDGETS],expect)
        self.assertTrue(all(p<=b for p,b in zip(expect,BUDGETS)))

    def test_real_768d_train_and_frozen_share_original_init(self):
        torch.manual_seed(2)
        x=torch.randn(14,768)
        y=torch.arange(14).remainder(4).long()
        e=torch.randn(8,768)
        a=train_one(x,y,e,seed=11,cell=0,ceiling=2048)
        b=train_one(x,y,e,seed=11,cell=0,ceiling=2048)
        self.assertEqual(a['parameters'],1550)
        self.assertEqual(a['minibatch_sha256'],b['minibatch_sha256'])
        self.assertEqual(a['checkpoint']['trained'],b['checkpoint']['trained'])
        self.assertNotEqual(a['checkpoint']['trained'],a['checkpoint']['frozen'])
        self.assertTrue(np.allclose(a['prediction']['trained'].sum(axis=1),1))
        self.assertEqual(a['prediction']['trained'].shape,(8,4))

    def test_all_five_paired_budgets_cluster_by_original_case(self):
        truth,before,after=fixture()
        rows=paired_statistics(before,after,truth,replicates=1000)
        self.assertEqual(len(rows),5)
        for row in rows:
            self.assertEqual(row['paired_original_cases'],32)
            self.assertEqual(row['repeated_seed_trajectories'],3)
            self.assertEqual(row['mmbert_correct_over_three_seeds'],22*3)
            self.assertEqual(row['modernbert_correct_over_three_seeds'],12*3)
            self.assertEqual(row['modern_only_correct'],10*3)
            self.assertEqual(row['mmbert_only_correct'],20*3)
            self.assertFalse(row['external_source_family_independence_verified'])

    def test_complete_packet_enforces_input_and_roles(self):
        truth,before,_=fixture()
        rows=[]
        for (budget,seed,case_id),p in before.items():
            case=truth[case_id]
            rows.append({'seed':seed,'ceiling':budget,'cell':case['cell'],
                'role':'trained','case_id':case_id,'scope':case['scope'],
                'split':'holdout','group':case['group'],
                'input_sha256':sha(canonical([case['scope'],case['text']])),
                'probabilities':p})
        self.assertEqual(_predictions({'predictions':rows},truth),before)
        rows[0]['input_sha256']='0'*64
        with self.assertRaisesRegex(PreflightError,'did not correspond'):
            _predictions({'predictions':rows},truth)

    def test_missing_seed_or_budget_is_not_silently_dropped(self):
        truth,before,after=fixture()
        del after[(8192,47,'c-0')]
        with self.assertRaisesRegex(PreflightError,'incomplete'):
            paired_statistics(before,after,truth,replicates=1000)

    def test_same_case_cannot_pretend_new_source_groups(self):
        truth,before,after=fixture()
        truth['c-1']['group']=truth['c-0']['group']
        with self.assertRaisesRegex(PreflightError,'unique'):
            paired_statistics(before,after,truth,replicates=1000)

    def test_bootstrap_is_deterministic_and_does_not_select(self):
        truth,before,after=fixture()
        a=paired_statistics(before,after,truth,replicates=1000)
        self.assertEqual(a,paired_statistics(before,after,truth,replicates=1000))
        self.assertFalse(any('production_accepted' in row for row in a))

if __name__=='__main__':unittest.main()
