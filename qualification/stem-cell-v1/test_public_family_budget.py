import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import torch

from budgeted_learning import step_upper_bound, train_to_budget
from family_routing import FamilyCellBank, transition_parity
from matrix_bank import train_bank, state_digest
from public_family_budget import make_bank, split_candidate, validate_results, train_family, policy, FamilyBudgetRejected
from shared_learning_probe import freeze_study, fit_controls, score_sealed
from execution_meter import WorkLedger
from matrix_materials import file_sha256
from test_shared_learning_probe import Encoder, rows


def study(**kw):
    args=dict(batch_size=4,width_units=4,training_flops_budget=2_000_000,
              max_budget_steps=512,family_split=True)
    args.update(kw)
    return freeze_study(**args)


def meter(cfg):
    return WorkLedger(cfg['measurement_policy'],{**cfg['phase_caps'],
        'train':cfg['training_flops_budget'],'migration':cfg['training_flops_budget']})


def make(cfg,topology='family_direct32',d=4):
    profile=dict(logical_cells=32,initial_logical_cells=32,split=False,ndu=False,
        resident_stem_copies=1,cell_head_budget_params=1_000_000,
        total_head_budget_params=32_000_000,active_cells_per_round_cap=2)
    with torch.random.fork_rng(devices=[]):
        torch.manual_seed(cfg['seed'])
        return make_bank(d,profile,cfg,topology)


class FamilyBudgetTests(unittest.TestCase):
    def test_legacy_study_ids_unchanged_and_new_policy_explicit(self):
        old=freeze_study(training_flops_budget=1000000)
        self.assertEqual(old,freeze_study(training_flops_budget=1000000,family_split=False))
        self.assertNotIn('family_policy',old)
        for kwargs in ({'training_flops_budget':None},{'width_units':3},{'max_budget_steps':1},{'family_split':1}):
            with self.subTest(kwargs=kwargs),self.assertRaises(ValueError):study(**kwargs)

    def test_actual_family_updates_respect_bounds_and_auxiliary_rows(self):
        for d in (1,8,33):
            for b in (1,4):
                with self.subTest(d=d,b=b):
                    cfg=study(batch_size=b,max_budget_steps=2,training_flops_budget=10**9)
                    bank=make(cfg,d=d); x=torch.arange(4*d,dtype=torch.float32).reshape(4,d)/(4*d)
                    r=train_to_budget(bank,x,torch.arange(4),cfg,7,meter=meter(cfg))
                    self.assertEqual(r['steps'],2)
                    self.assertEqual(sum(bank.sibling_probe_rows),4*r['examples_seen'])
                    for u in r['budget']['updates']:
                        self.assertLessEqual(u['actual_formula_flops'],step_upper_bound(bank,b))

    def test_unconstrained_family_optimizer_matches_original_training(self):
        cfg=study(max_budget_steps=3,training_flops_budget=10**8)
        a=make(cfg);b=copy.deepcopy(a)
        x=torch.eye(4);y=torch.arange(4)
        r=train_to_budget(a,x,y,cfg,3,meter=meter(cfg))
        original=train_bank(b,x,y,{**cfg,'train_steps':3},3)
        self.assertEqual(state_digest(a),state_digest(b))
        self.assertEqual(r['losses'],original['losses'])

    def test_stage_limits_do_not_replace_global_meter_cap(self):
        cfg=study();bank=make(cfg);m=meter(cfg)
        r=train_to_budget(bank,torch.eye(4),torch.arange(4),cfg,3,meter=m,stop_at_work=300000)
        self.assertEqual(m.caps['train'],2_000_000)
        self.assertLessEqual(r['budget']['observed'],300000)
        for bad in (True,0,-1,2_000_001):
            with self.subTest(bad=bad),self.assertRaises(ValueError):
                train_to_budget(bank,torch.eye(4),torch.arange(4),cfg,3,meter=m,stop_at_work=bad)

    def test_clone_has_independent_storage_and_parent_parity(self):
        cfg=study();parent=make(cfg,'family_split16to32');old=state_digest(parent)
        child=split_candidate(parent,cfg,parameter_cap=2304)
        self.assertEqual(state_digest(parent),old)
        self.assertEqual(parent.inventory()['parameters'],576)
        self.assertEqual(child.inventory()['parameters'],1152)
        probe=transition_parity(parent,child,torch.eye(4),cfg['family_policy'])
        self.assertTrue(probe['passed'])
        for i in range(16):
            self.assertNotEqual(parent.heads[i][0].weight.data_ptr(),child.heads[i][0].weight.data_ptr())
            self.assertNotEqual(child.heads[i][0].weight.data_ptr(),child.heads[i+16][0].weight.data_ptr())

    def test_peak_rejection_precedes_successor_allocation(self):
        cfg=study();parent=make(cfg,'family_split16to32')
        with patch('public_family_budget.FamilyCellBank') as factory:
            with self.assertRaisesRegex(ValueError,'live model'):
                split_candidate(parent,cfg,parameter_cap=1727)
            factory.assert_not_called()

    def test_unfunded_transition_keeps_measured_prefix(self):
        cfg=study(training_flops_budget=150000,max_budget_steps=8)
        bank=make(cfg,'family_split16to32');m=meter(cfg)
        with self.assertRaises(FamilyBudgetRejected) as caught:
            train_family(bank,torch.eye(4),torch.arange(4),cfg,meter=m,topology='family_split16to32')
        self.assertEqual(caught.exception.report['reason'],'transition_not_funded')
        self.assertGreater(m.report()['phase_flops']['train'],0)

    def test_real_low_residual_is_not_relabelled_as_a_split(self):
        cfg=study(max_budget_steps=4);bank=make(cfg,'family_split16to32');m=meter(cfg)
        with torch.no_grad():
            for h in bank.heads:
                h[2].weight.zero_();h[2].bias.zero_();h[2].bias[0]=30
        with self.assertRaises(FamilyBudgetRejected) as caught:
            train_family(bank,torch.eye(4),torch.zeros(4,dtype=torch.long),cfg,meter=m,topology='family_split16to32')
        self.assertEqual(caught.exception.report['reason'],'residual_did_not_trigger_split')
        self.assertIsNone(m.report()['phase_flops']['migration'])

    def test_corrupt_transition_rejects_before_post_training(self):
        cfg=study(max_budget_steps=4);bank=make(cfg,'family_split16to32')
        real=split_candidate
        def corrupt(*a,**kw):
            child=real(*a,**kw)
            with torch.no_grad():
                for h in child.heads:h[2].bias.add_(10)
            return child
        with patch('public_family_budget.split_candidate',side_effect=corrupt):
            with self.assertRaises(FamilyBudgetRejected) as caught:
                train_family(bank,torch.eye(4),torch.arange(4),cfg,meter=meter(cfg),topology='family_split16to32')
        self.assertEqual(caught.exception.report['reason'],'transition_parity_failed')


class FamilyPublicIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp=tempfile.TemporaryDirectory();cls.addClassCleanup(cls.tmp.cleanup)
        cls.root=Path(cls.tmp.name)/'run';cls.cfg=study();backend=Encoder()
        cls.seal=fit_controls(backend,rows('train'),[0,1,2,3],rows('eval'),cls.root,dimension=4,study=cls.cfg)
        cls.observation=json.loads((cls.root/'predictions.json').read_text())
        cls.calls=backend.calls

    def test_same_final_parameters_measured_pooled_budget_and_real_growth(self):
        report=score_sealed(self.root,[0,1,2,3],expected_seal_id=self.seal['seal_id'])
        self.assertTrue(report['all_arms_completed']);self.assertTrue(report['parameter_matched'])
        self.assertEqual(self.calls,8)
        self.assertEqual([r['inventory']['parameters'] for r in self.observation['arms']],[1152,1152])
        self.assertEqual([r['training']['peak_live_model_parameters'] for r in self.observation['arms']],[1152,1728])
        for r in self.observation['arms']:
            counts=r['work']['phase_flops'];t=r['training']
            self.assertEqual(t['observed_offline_formula_flops'],counts['train']+counts['migration'])
            self.assertLessEqual(t['observed_offline_formula_flops'],2_000_000)
            self.assertGreater(t['transition_formula_flops'],0)
            self.assertEqual(t['optimizer_reset_count'],1)
            self.assertEqual(r['work']['unknown_operators'],{})
        self.assertTrue(self.observation['arms'][1]['training']['transition_probe']['passed'])
        self.assertFalse(report['learning_superiority_established'])

    def test_step_ceiling_and_reservations_retained(self):
        for r in self.observation['arms']:
            t=r['training'];self.assertLessEqual(t['steps'],512)
            self.assertEqual(t['steps'],sum(s['steps'] for s in t['stages']))
            self.assertGreater(t['remaining'],0)
            self.assertNotEqual(t['transition_reserved_bound'],t['transition_formula_flops'])

    def test_scoring_different_labels_cannot_change_training_or_cloning(self):
        paths=[self.root/a['topology']/'bank.safetensors' for a in self.observation['arms']]
        hashes=[file_sha256(p) for p in paths]
        with patch('public_family_budget.train_family',side_effect=AssertionError('no training')):
            for labels in ([0,1,2,3],[3,2,1,0]):
                score_sealed(self.root,labels,expected_seal_id=self.seal['seal_id'])
        self.assertEqual(hashes,[file_sha256(p) for p in paths])

    def test_partial_update_migration_and_auxiliary_tampering_reject(self):
        for change in ('pooled','migration','reservation','steps','probes','parity','bool'):
            arms=copy.deepcopy(self.observation['arms']);t=arms[1]['training']
            if change=='pooled':t['observed_offline_formula_flops']-=1
            if change=='migration':t['transition_formula_flops']=0
            if change=='reservation':t['stages'][1]['budget']['updates'][0]['reserved_upper_bound']=10**20
            if change=='steps':t['steps']+=1
            if change=='probes':arms[1]['inventory']['sibling_probe_rows'][0]+=1
            if change=='parity':t['transition_probe']['passed']=False
            if change=='bool':t['stages'][1]['budget']['updates'][0]['batch_size']=True
            with self.subTest(change=change),self.assertRaises(ValueError):validate_results(self.cfg,arms)

    def test_reloaded_family_weights_reproduce_sealed_predictions(self):
        from safetensors.torch import load_file
        bank=make(self.cfg)
        for arm,out in zip(self.observation['arms'],self.observation['predictions'],strict=True):
            bank.load_state_dict(load_file(str(self.root/arm['topology']/'bank.safetensors')))
            bank.eval()
            with torch.inference_mode():logits=bank(torch.eye(4)).tolist()
            self.assertEqual(logits,out['after'])

    def test_same_input_weights_reproducible(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)/'again'
            fit_controls(Encoder(),rows('train'),[0,1,2,3],rows('eval'),root,dimension=4,study=self.cfg)
            new=json.loads((root/'predictions.json').read_text())
            self.assertEqual([r['trained_sha256'] for r in new['arms']],
                             [r['trained_sha256'] for r in self.observation['arms']])
            self.assertEqual(new['predictions'],self.observation['predictions'])

    def test_tiny_budget_keeps_both_failed_controls(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)/'failed'
            seal=fit_controls(Encoder(),rows('train'),[0,1,2,3],rows('eval'),root,dimension=4,
                              study=study(training_flops_budget=1))
            scored=score_sealed(root,[0,1,2,3],expected_seal_id=seal['seal_id'])
            self.assertEqual([r['status'] for r in scored['arms']],['failed','failed'])
            self.assertFalse(scored['observed_training_work_matched_within_one_percent'])


if __name__=='__main__':unittest.main()
