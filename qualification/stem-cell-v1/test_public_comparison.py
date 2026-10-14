"""Actual training/sealing integration plus bounded descriptive accounting checks."""
import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import torch

from execution_meter import WorkLedger
from matrix_materials import file_sha256
from public_comparison import cost_accounting, quality_cost_comparison, _sum_known
from shared_learning_probe import fit_controls, freeze_study, score_sealed
from test_shared_learning_probe import Encoder, rows


class PublicComparisonTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp=tempfile.TemporaryDirectory();cls.addClassCleanup(cls.tmp.cleanup)
        cls.root=Path(cls.tmp.name)/'run'
        cls.study=freeze_study(train_steps=3,batch_size=4,width_units=3)
        cls.seal=fit_controls(Encoder(),rows('train'),[0,1,2,3],rows('eval'),cls.root,dimension=4,study=cls.study)
        cls.observed_run=json.loads((cls.root/'predictions.json').read_text())

    def setUp(self):
        self.record=copy.deepcopy(self.observed_run)

    def summary(self):
        return quality_cost_comparison(self.record,self.study,[0,1,2,3])

    def test_actual_scoring_integrates_complete_cost_and_all_pairs(self):
        report=score_sealed(self.root,[0,1,2,3],expected_seal_id=self.seal['seal_id'])
        comparison=report['quality_cost_comparison']
        self.assertEqual(len(comparison['paired_quality']),3)
        self.assertEqual(len(comparison['before_after']),3)
        self.assertFalse(comparison['equal_quality_established'])
        self.assertFalse(comparison['cost_accounting']['hardware_speedup_established'])
        for pair in comparison['paired_quality']:
            counts=pair['overall']
            self.assertEqual(sum(counts[k] for k in ('recovered','lost','both_correct','both_wrong')),4)

    def test_generators_and_missing_values_do_not_become_zero_subtotals(self):
        self.assertEqual(_sum_known(i for i in (2,3)),5)
        self.assertIsNone(_sum_known(i for i in (2,None)))
        self.record['shared_encoder_work']['phase_flops']['train']=None
        result=cost_accounting(self.record,self.study)
        self.assertIsNone(result['shared_encoder_total'])
        self.assertIsNone(result['physical_campaign_complete_observed_formula_work'])
        self.assertTrue(all(a['standalone_training_formula_work'] is None for a in result['arms']))

    def test_campaign_pays_once_standalone_pays_full_encoding(self):
        ledger=WorkLedger(self.study['measurement_policy'],self.study['phase_caps'])
        x=torch.ones(20000)
        for phase in ('train','inference'):
            with ledger.scope(phase,'encoder'): x.add(1)
        self.record['shared_encoder_work']=ledger.report()
        result=cost_accounting(self.record,self.study)
        self.assertEqual(result['shared_encoder_total'],40000)
        self.assertEqual(result['physical_campaign_complete_observed_formula_work'],
                         40000+sum(a['complete_bank_trial_formula_work'] for a in result['arms']))
        for a in result['arms']:
            self.assertEqual(a['standalone_observed_trial_formula_work'],40000+a['complete_bank_trial_formula_work'])
            self.assertEqual(a['standalone_training_formula_work'],20000+a['bank_training_formula_work'])
        p=result['comparisons'][0]
        self.assertGreater(p['bank_training_formula_work_candidate_reduction'],
                           p['standalone_training_formula_work_candidate_reduction'])

    def test_identical_average_can_hide_opposite_class_changes(self):
        def logits(pred):return [[10. if j==x else 0. for j in range(4)] for x in pred]
        self.record['predictions'][0]['after']=logits([0,1,0,0])
        self.record['predictions'][1]['after']=logits([1,0,2,3])
        p=self.summary()['paired_quality'][0]
        self.assertEqual(p['overall']['accuracy_delta'],0.)
        self.assertEqual((p['overall']['recovered'],p['overall']['lost']),(2,2))
        self.assertEqual(p['observed_class_regressions'],['0','1'])
        self.assertEqual(p['worst_observed_class_delta'],-1.)
        self.assertFalse(self.summary()['equal_quality_established'])

    def test_failed_arm_and_its_spent_prefix_never_disappear(self):
        arm=self.record['arms'][1]; arm['status']='failed'
        self.record['predictions'][1].update(before=None,after=None)
        arm['work']['phase_flops']['inference']=None
        result=self.summary(); accounting=result['cost_accounting']
        self.assertEqual(len(accounting['arms']),3)
        self.assertGreater(accounting['arms'][1]['known_bank_prefix_formula_work'],0)
        self.assertIsNone(accounting['physical_campaign_complete_observed_formula_work'])
        self.assertIsNone(accounting['comparisons'][0]['bank_training_formula_work_candidate_reduction'])
        self.assertEqual(result['paired_quality'][0]['status'],'unavailable_failed_arm')
        self.assertEqual(result['paired_quality'][0]['rows'],4)

    def test_failed_output_may_not_retain_success_logits(self):
        self.record['arms'][0]['status']='failed'
        with self.assertRaisesRegex(ValueError,'failed arm'):self.summary()

    def test_unknown_cost_cannot_be_resealed_as_complete(self):
        work=self.record['arms'][0]['work']
        work['scopes'][0]['unknown_operators']=1
        work['operators']['aten.sin.default']=1;work['unknown_operators']['aten.sin.default']=1
        with self.assertRaisesRegex(ValueError,'cannot claim complete'):self.summary()

    def test_wrong_arithmetic_unit_or_policy_is_not_comparable(self):
        work=self.record['arms'][0]['work'];work['profile']='other'
        with self.assertRaisesRegex(ValueError,'incompatible'):self.summary()
        self.record=copy.deepcopy(self.observed_run);self.record['arms'][0]['work']['policy']['mode']='observe'
        with self.assertRaisesRegex(ValueError,'frozen configuration'):self.summary()

    def test_unexpected_executed_phase_is_not_silently_dropped(self):
        work=self.record['arms'][0]['work']
        scope=copy.deepcopy(work['scopes'][0]);scope.update(phase='search',component='bank')
        work['scopes'].append(scope)
        with self.assertRaisesRegex(ValueError,'declared accounting phases'):self.summary()

    def test_dropped_reordered_and_unresolved_arms_reject(self):
        for change in ('drop','reorder','unresolved'):
            self.record=copy.deepcopy(self.observed_run)
            if change=='drop':self.record['arms'].pop()
            elif change=='reorder':self.record['predictions'].reverse()
            else:self.record['arms'][0]['status']='unknown'
            with self.subTest(change=change),self.assertRaises(ValueError):self.summary()

    def test_duplicate_final_identity_or_invalid_labels_reject(self):
        self.record['heldout_inputs'][1]=copy.deepcopy(self.record['heldout_inputs'][0])
        with self.assertRaisesRegex(ValueError,'duplicate'):self.summary()
        for labels in ([0,1,2],[True,1,2,3],[4,1,2,3]):
            with self.subTest(labels=labels),self.assertRaises(ValueError):
                quality_cost_comparison(self.observed_run,self.study,labels)

    def test_bad_logits_are_not_scored(self):
        for value in (float('nan'),True):
            self.record['predictions'][0]['after'][0][0]=value
            with self.subTest(value=value),self.assertRaises(ValueError):self.summary()

    def test_reporting_neither_trains_nor_mutates_inputs(self):
        before=copy.deepcopy(self.record)
        files=[self.root/name/'bank.safetensors' for name in ('dense16','sparse16','direct32')]
        digests=[file_sha256(p) for p in files]
        with patch('shared_learning_probe.train_bank',side_effect=AssertionError('no training')):
            first=self.summary()
            second=quality_cost_comparison(self.record,self.study,[3,2,1,0])
        self.assertEqual(before,self.record)
        self.assertEqual(first['cost_accounting'],second['cost_accounting'])
        self.assertNotEqual(first['comparison_id'],second['comparison_id'])
        self.assertEqual(digests,[file_sha256(p) for p in files])

    def test_budgeted_family_accounts_transition_and_closes_pool(self):
        study=freeze_study(batch_size=4,width_units=4,training_flops_budget=2_000_000,
                           max_budget_steps=512,family_split=True)
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)/'family'
            seal=fit_controls(Encoder(),rows('train'),[0,1,2,3],rows('eval'),root,dimension=4,study=study)
            run=json.loads((root/'predictions.json').read_text())
            result=score_sealed(root,[0,1,2,3],expected_seal_id=seal['seal_id'])
            accounting=result['quality_cost_comparison']['cost_accounting']
            self.assertEqual(accounting['training_pool'],['train','migration'])
            for arm,summary in zip(run['arms'],accounting['arms'],strict=True):
                self.assertEqual(summary['bank_training_formula_work'],
                                 arm['training']['observed_offline_formula_flops'])
                self.assertGreater(arm['work']['phase_flops']['migration'],0)
            self.assertEqual(len(result['quality_cost_comparison']['paired_quality']),1)


if __name__=='__main__':unittest.main()
