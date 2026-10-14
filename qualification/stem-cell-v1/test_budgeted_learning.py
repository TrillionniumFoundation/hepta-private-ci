import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import torch

from budgeted_learning import step_upper_bound, train_to_budget, used_training_work, validate_budget_results
from execution_meter import WorkLedger
from matrix_bank import CellBank, train_bank, state_digest
from shared_learning_probe import freeze_study, fit_controls, score_sealed, TOPOLOGIES
import test_shared_learning_probe as fixture


def bank_for(n=16, k=2, d=4, q=3):
    profile = dict(logical_cells=n, initial_logical_cells=n, split=False, ndu=False,
        resident_stem_copies=1, cell_head_budget_params=32_000_000//n,
        total_head_budget_params=32_000_000, active_cells_per_round_cap=k)
    with torch.random.fork_rng(devices=[]):
        torch.manual_seed(7347)
        return CellBank(d,4,profile,q)


def measured(study):
    return WorkLedger(study['measurement_policy'], {**study['phase_caps'], 'train':study['training_flops_budget']})


class BudgetLearningTests(unittest.TestCase):
    def test_whole_steps_equal_legacy_adamw_when_budget_does_not_bind(self):
        bank=bank_for(); other=copy.deepcopy(bank)
        cfg=freeze_study(batch_size=4,width_units=3,training_flops_budget=10**7,max_budget_steps=4)
        x=torch.eye(4); y=torch.arange(4)
        out=train_to_budget(bank,x,y,cfg,11,meter=measured(cfg))
        old=train_bank(other,x,y,{**cfg,'train_steps':4},11)
        self.assertEqual(state_digest(bank),state_digest(other))
        self.assertEqual(out['losses'],old['losses'])
        self.assertEqual(out['budget']['stop_reason'],'step_limit')

    def test_actual_steps_fit_the_shape_bounds_across_geometries(self):
        for d,q in ((1,2),(8,4),(33,7)):
            for n,k in ((16,16),(16,2),(32,2)):
                for b in (1,4):
                    with self.subTest(d=d,q=q,n=n,k=k,b=b):
                        bank=bank_for(n,k,d,q)
                        cfg=freeze_study(batch_size=b,width_units=q,training_flops_budget=10**9,max_budget_steps=2)
                        x=torch.arange(4*d,dtype=torch.float32).reshape(4,d)/max(d,1)
                        out=train_to_budget(bank,x,torch.arange(4),cfg,3,meter=measured(cfg))
                        self.assertEqual(out['steps'],2)
                        for step in out['budget']['updates']:
                            self.assertLessEqual(step['actual_formula_flops'],step['reserved_upper_bound'])
                            self.assertEqual(step['reserved_upper_bound'],step_upper_bound(bank,b))

    def test_too_small_budget_runs_no_forward_and_keeps_weights(self):
        bank=bank_for(); before=state_digest(bank)
        cfg=freeze_study(training_flops_budget=1000)
        with self.assertRaisesRegex(ValueError,'no complete'):
            train_to_budget(bank,torch.eye(4),torch.arange(4),cfg,3,meter=measured(cfg))
        self.assertEqual(state_digest(bank),before)
        self.assertEqual(bank.calls,0)

    def test_bound_not_actual_cost_is_never_written_as_executed(self):
        bank=bank_for()
        cfg=freeze_study(batch_size=4,training_flops_budget=200000,max_budget_steps=2)
        meter=measured(cfg)
        out=train_to_budget(bank,torch.eye(4),torch.arange(4),cfg,2,meter=meter)
        self.assertLess(out['budget']['observed'],sum(s['reserved_upper_bound'] for s in out['budget']['updates']))
        self.assertEqual(out['budget']['observed'],meter.report()['phase_flops']['train'])

    def test_idle_meter_policy_and_cap_binding(self):
        bank=bank_for(); cfg=freeze_study(training_flops_budget=10**6,max_budget_steps=1)
        wrong=WorkLedger(cfg['measurement_policy'],cfg['phase_caps'])
        with self.assertRaises(ValueError):train_to_budget(bank,torch.eye(4),torch.arange(4),cfg,1,meter=wrong)
        m=measured(cfg);x=torch.eye(4);y=torch.arange(4)
        with m.scope('train','bank'):
            with self.assertRaises(ValueError):train_to_budget(bank,x,y,cfg,1,meter=m)

    def test_unsupported_geometry_precision_and_batch_reject(self):
        for variant in ('precision','gelu','bias','batch'):
            bank=bank_for()
            if variant=='precision':bank.double()
            if variant=='gelu':bank.heads[0][1]=torch.nn.ReLU()
            if variant=='bias':bank.heads[0][0].bias=None
            with self.subTest(variant=variant),self.assertRaises(ValueError):step_upper_bound(bank,True if variant=='batch' else 4)

    def test_frozen_or_nonfinite_training_inputs_reject(self):
        for variant in ('grad','nan','target'):
            bank=bank_for(); cfg=freeze_study(training_flops_budget=10**6,max_budget_steps=1)
            x=torch.eye(4);y=torch.arange(4)
            if variant=='grad':x.requires_grad_()
            if variant=='nan':x[0,0]=float('nan')
            if variant=='target':y[0]=4
            with self.subTest(variant=variant),self.assertRaises(ValueError):train_to_budget(bank,x,y,cfg,1,meter=measured(cfg))

    def test_tampered_upper_bound_fails_not_silent_success(self):
        bank=bank_for();cfg=freeze_study(training_flops_budget=10**6,max_budget_steps=1)
        with patch('budgeted_learning.step_upper_bound',return_value=1):
            with self.assertRaisesRegex(ValueError,'admission bound'):
                train_to_budget(bank,torch.eye(4),torch.arange(4),cfg,1,meter=measured(cfg))

    def test_failed_kernel_has_no_complete_training_claim(self):
        m=measured(freeze_study(training_flops_budget=10**6))
        with self.assertRaises(RuntimeError):
            with m.scope('train','bank'):torch.ones(2,3) @ torch.ones(4,2)
        with self.assertRaises(ValueError):used_training_work(m)
        self.assertIsNone(m.report()['phase_flops']['train'])

    def test_v1_content_identity_unchanged(self):
        from next_round_matrix import _digest
        cfg=freeze_study()
        self.assertNotIn('training_flops_budget',cfg)
        self.assertEqual(cfg['schema'],'hepta.public-shared-learning-config.v1')
        for bad in (True,0,-1,5_000_000_000_001):
            with self.subTest(bad=bad),self.assertRaises(ValueError):freeze_study(training_flops_budget=bad)
        with self.assertRaises(ValueError):freeze_study(training_flops_budget=100000,max_budget_steps=4097)


class BudgetControlTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp=tempfile.TemporaryDirectory();cls.addClassCleanup(cls.tmp.cleanup)
        cls.root=Path(cls.tmp.name)/'run'
        cls.study=freeze_study(batch_size=4,width_units=3,training_flops_budget=2_000_000,max_budget_steps=1024)
        cls.seal=fit_controls(fixture.Encoder(),fixture.rows('train'),[0,1,2,3],fixture.rows('eval'),
                             cls.root,dimension=4,study=cls.study)
        cls.observation=json.loads((cls.root/'predictions.json').read_text())

    def test_equal_budget_yields_different_useful_update_counts(self):
        records=validate_budget_results(self.study,self.observation['arms'])
        self.assertTrue(all(r['status']=='completed' and r['formula_flops']<=2_000_000 for r in records))
        self.assertGreater(records[1]['steps'],records[0]['steps'])
        self.assertGreater(records[2]['steps'],records[0]['steps'])
        self.assertTrue(all(r['utilization']>.96 for r in records))
        self.assertEqual(len({a['inventory']['parameters'] for a in self.observation['arms']}),1)
        for arm in self.observation['arms']:
            b=arm['training']['budget']
            self.assertLess(b['remaining'],b['smallest_complete_update_bound'])
            self.assertIsNone(arm['work']['stopped'])
            self.assertEqual(arm['work']['unknown_operators'],{})

    def test_matching_is_checked_on_observed_not_reserved_work(self):
        report=score_sealed(self.root,[0,1,2,3],expected_seal_id=self.seal['seal_id'])
        self.assertTrue(report['observed_training_work_matched_within_one_percent'])
        self.assertFalse(report['fixed_update_schedule_not_compute_matching'])
        self.assertFalse(report['full_system_efficiency_established'])
        self.assertFalse(report['learning_superiority_established'])

    def test_budget_score_rejects_contradictory_denominators(self):
        for field,value in (('observed',1),('remaining',-1),('unit','other'),('utilization',1.0)):
            arms=copy.deepcopy(self.observation['arms']);arms[0]['training']['budget'][field]=value
            with self.subTest(field=field),self.assertRaises(ValueError):validate_budget_results(self.study,arms)
        arms=copy.deepcopy(self.observation['arms']);arms[0]['training']['examples_seen']+=1
        with self.assertRaises(ValueError):validate_budget_results(self.study,arms)

    def test_final_labels_cannot_retrain_or_reselect(self):
        from matrix_materials import file_sha256
        files=[self.root/n/'bank.safetensors' for n,_,_ in TOPOLOGIES]
        hashes=[file_sha256(p) for p in files]
        with patch('budgeted_learning.train_to_budget',side_effect=AssertionError('no training')):
            a=score_sealed(self.root,[0,1,2,3],expected_seal_id=self.seal['seal_id'])
            b=score_sealed(self.root,[3,2,1,0],expected_seal_id=self.seal['seal_id'])
        self.assertNotEqual(a['labels_sha256'],b['labels_sha256'])
        self.assertEqual(hashes,[file_sha256(p) for p in files])

    def test_tiny_budget_retains_all_failed_arms(self):
        with tempfile.TemporaryDirectory() as td:
            study=freeze_study(training_flops_budget=1)
            seal=fit_controls(fixture.Encoder(),fixture.rows('train'),[0,1,2,3],fixture.rows('eval'),
                              Path(td)/'run',dimension=4,study=study)
            report=score_sealed(Path(td)/'run',[0,1,2,3],expected_seal_id=seal['seal_id'])
            self.assertEqual([a['status'] for a in report['arms']],['failed']*3)
            self.assertFalse(report['observed_training_work_matched_within_one_percent'])

    def test_optimizer_exception_keeps_failed_status_and_missing_cost(self):
        with tempfile.TemporaryDirectory() as td,patch('torch.optim.AdamW.step',side_effect=RuntimeError('update failed')):
            study=freeze_study(training_flops_budget=200000,width_units=3)
            seal=fit_controls(fixture.Encoder(),fixture.rows('train'),[0,1,2,3],fixture.rows('eval'),
                              Path(td)/'run',dimension=4,study=study)
            report=score_sealed(Path(td)/'run',[0,1,2,3],expected_seal_id=seal['seal_id'])
            self.assertTrue(all(a['status']=='failed' for a in report['arms']))
            run=json.loads((Path(td)/'run/predictions.json').read_text())
            self.assertTrue(all(a['work']['phase_flops']['train'] is None for a in run['arms']))


if __name__=='__main__':
    unittest.main()
