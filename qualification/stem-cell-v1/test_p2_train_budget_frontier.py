"""Actual CPU Torch budget/fission versus stdlib+NumPy independent tamper tests."""
from __future__ import annotations

import copy
import unittest
from unittest.mock import patch

import torch

import p1_real_granite_cohort as p1
import p1_real_granite_review as p1review
import p2_real_cell_split as p2
import p2_train_sparse_equal_compute as trained
import p2_backward_cost_profiler as prior
import p2_counterbalanced_cpu_training as physical
import p2_train_budget_frontier as frontier
import p2_train_budget_frontier_review as reviewer
from test_p1_real_granite_cohort import setup_fixture,FakePhysicalStem


class BudgetFrontierSourceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.panel,cls.tr,cls.blind,cls.owner,cls.panel_sha=setup_fixture()
        torch.set_num_threads(1);torch.manual_seed(7347)
        cls.backend=FakePhysicalStem()
        with patch.object(p1,'PANEL_SHA',cls.panel_sha),patch.object(p1review,'PANEL_SHA',cls.panel_sha):
            cls.old=p2.execute(cls.tr,cls.blind,cls.backend,seed=7347)
            cls.learned=trained.execute(cls.tr,cls.blind,cls.backend,seed=7347,parent_p2=cls.old)
            cls.profiler=prior.execute(cls.tr,cls.blind,cls.backend,cls.old,cls.learned,real=False)
            cls.balanced=physical.execute(cls.tr,cls.blind,cls.backend,cls.old,cls.learned,real=False,rounds=8)
            cls.budget=frontier.execute(cls.tr,cls.blind,cls.backend,cls.old,cls.learned,cls.balanced,
                                        real=False,seed=20261015)
            cls.reviewed=reviewer.review(cls.panel,cls.tr,cls.blind,cls.owner,
                              cls.old,cls.learned,cls.profiler,cls.balanced,cls.budget)

    def rescore(self,report=None,*,train=None,blind=None,owner=None,original=None,learned=None,profile=None,balanced=None):
        with patch.object(p1review,'PANEL_SHA',self.panel_sha):
            return reviewer.review(self.panel,train if train is not None else self.tr,
                    blind if blind is not None else self.blind,
                    owner if owner is not None else self.owner,
                    original if original is not None else self.old,
                    learned if learned is not None else self.learned,
                    profile if profile is not None else self.profiler,
                    balanced if balanced is not None else self.balanced,
                    report if report is not None else self.budget)

    def corrupt(self,fn):
        doc=copy.deepcopy(self.budget)
        fn(doc)
        doc['report_sha256']=trained.digest({k:v for k,v in doc.items() if k!='report_sha256'})
        return doc

    def rejects(self,fn,regex=None):
        x=self.corrupt(fn)
        with self.assertRaisesRegex(ValueError,regex or '.'):self.rescore(x)

    def test_genuine_training_calibration_original_source_and_final_complete(self):
        self.assertEqual(self.budget['physical_encoder_calls_in_this_job'],224)
        self.assertEqual(len(self.budget['pilot_records']),32)
        self.assertEqual(len(self.budget['final_arms']),4)
        self.assertEqual(self.reviewed['full_training_pilots_paid'],32)
        self.assertFalse(self.reviewed['matched_exact_total_flops'])
        self.assertFalse(self.reviewed['model_winner_selected'])
        self.assertEqual({a:x['test_total'] for a,x in self.reviewed['compare'].items()},
                         dict.fromkeys(frontier.ARMS,64))

    def test_seeded_order_each_arm_each_position_twice(self):
        self.assertEqual(self.budget['pilot_orders'],frontier.orders(20261015))
        self.assertEqual(self.budget['pilot_orders'],reviewer.crossover(20261015))
        for a in frontier.ARMS:
            counts=[sum(row[a_pos]==a for row in self.budget['pilot_orders']) for a_pos in range(4)]
            self.assertEqual(counts,[2]*4)

    def test_prelabel_only_calibration_original_40_step_final_weights(self):
        for row in self.budget['pilot_records']:
            name=row['arm']
            self.assertEqual(row['final_weights_sha256'],self.learned['compared_arms'][name]['final_weights_sha256'])
        self.assertTrue(self.budget['calibration_uses_training_labels_only'])
        self.assertFalse(self.budget['blinded_labels_opened_during_training'])
        self.assertFalse(self.budget['test_cohorts_are_retrospective_not_future'] is False)

    def test_original_trained_40_step_single_exact_weight_and_logits_identity(self):
        a=self.budget['final_arms']['single_active'];b=self.learned['compared_arms']['single_active']
        self.assertEqual(a['final_weights_sha256'],b['final_weights_sha256'])
        self.assertEqual(a['heldout_logits'],b['heldout_logits'])
        self.assertEqual(a['budget_selected_steps'],40)

    def test_actual_budget_changes_with_cost_not_test_accuracy(self):
        reference=self.budget['calibrated_single_40_step_cpu_ns']
        for a in frontier.LEARNED:
            self.assertEqual(self.budget['allocated_steps'][a],
               40 if a=='single_active' else frontier.allotted_steps(reference,
                   self.budget['final_arms'][a]['pilot_median_full_40_cpu_ns']))
        self.assertTrue(all(v in (20,22,24,26,28,30,32,34,36,38,40) for v in
                            self.budget['allocated_steps'].values() if v>0))
        self.assertTrue(self.budget['calibrated_cpu_budget_is_not_exact_matching'])

    def test_cpu_calibration_entire_cost_includes_all_pilots(self):
        expected=sum(t['full_40_step_training_cpu_ns'] for t in self.budget['pilot_records'])
        self.assertEqual(self.reviewed['calibration_training_cpu_ns_sum'],expected)
        self.assertGreater(self.reviewed['budgeted_train_cpu_ns_sum'],0)
        self.assertFalse(self.reviewed['equal_cpu_budget_exact'])

    def test_all_equal_resident_but_different_exposures_must_be_reported(self):
        for a,detail in self.budget['final_arms'].items():
            self.assertEqual(detail['model_parameter_count'],14868)
            self.assertEqual(detail['active_head_parameters'],7434)
            n=detail['budget_selected_steps']
            self.assertEqual(detail['train_exposures'],96*n)
            self.assertEqual(sum(detail['training_selected_expert_rows']),96*n)
            self.assertEqual(self.reviewed['compare'][a]['training_exposure'],96*n)

    def test_unfavorable_quality_results_not_clamped_or_rejected(self):
        baseline=self.reviewed['compare']['single_active']['test_correct']
        self.assertTrue(any(v['test_correct']<baseline for a,v in self.reviewed['compare'].items()
                            if a!='single_active') or baseline<=64)
        self.assertFalse(self.reviewed['predictor_backward_history_independently_authenticated'])

    def test_reviewer_refuses_changed_preregistered_order(self):
        self.rejects(lambda d:d['pilot_orders'].reverse(),'schedule')
        self.rejects(lambda d:d.update(calibration_seed=2),'schedule')
        self.rejects(lambda d:d.update(pilot_rounds=7),'schedule')

    def test_reviewer_refuses_pilot_deleted_or_duplicate(self):
        self.rejects(lambda d:d['pilot_records'].pop(),'32')
        self.rejects(lambda d:d['pilot_records'][0].update(arm=('single_active' if d['pilot_records'][0]['arm']!='single_active' else 'fixed_top1')),'false')
        self.rejects(lambda d:d['pilot_records'][4].update(position=1),'false')

    def test_reviewer_refuses_forged_cold_cpu_and_false_pilot_count(self):
        self.rejects(lambda d:d['pilot_records'][3].update(full_40_step_training_cpu_ns=0),'false')
        self.rejects(lambda d:d['pilot_records'][3].update(full_40_step_training_wall_ns=-1),'false')
        self.rejects(lambda d:d['pilot_records'][0].update(final_weights_sha256='c'*64),'false')

    def test_reviewer_refuses_modified_training_cpu_median_or_budget_selection(self):
        self.rejects(lambda d:d.update(calibrated_single_40_step_cpu_ns=d['calibrated_single_40_step_cpu_ns']+10),'reference')
        self.rejects(lambda d:d['allocated_steps'].update(fixed_top1=40 if d['allocated_steps']['fixed_top1']!=40 else 32),'budget')

    def test_reviewer_refuses_changed_schedule_even_after_updating_steps_metadata(self):
        def fudge(doc):
            name='adaptive_top1'; n=doc['allocated_steps'][name]
            doc['allocated_steps'][name]=38 if n!=38 else 30
            doc['final_arms'][name]['budget_selected_steps']=doc['allocated_steps'][name]
        self.rejects(fudge,'budget')

    def test_reviewer_refuses_wrong_original_model_digest(self):
        self.rejects(lambda d:d.update(frozen_model_weights_sha256='c'*64),'original')
        self.rejects(lambda d:d.update(model_parameter_count=10),'original')
        self.rejects(lambda d:d.update(pretrained_model_loaded_in_this_job=True),'original')

    def test_reviewer_refuses_fabricated_future_or_promotion_or_exact_compute(self):
        self.rejects(lambda d:d.update(future_task_quality_established=True),'unqualified')
        self.rejects(lambda d:d.update(model_winner_selected=True),'unqualified')
        self.rejects(lambda d:d.update(total_backward_flops_equalized=True),'unqualified')
        self.rejects(lambda d:d.update(production_promotion_permitted=True),'nonauthorizing')
        self.rejects(lambda d:d.update(calibrated_cpu_budget_is_not_exact_matching=False),'disclaimer')

    def test_reviewer_refuses_owner_label_rewrite(self):
        v=copy.deepcopy(self.owner);v['rows'][0]['label']=1-v['rows'][0]['label']
        v['seal_id']=p1.digest({k:v for k,v in v.items() if k!='seal_id'})
        with self.assertRaises(ValueError):self.rescore(owner=v)

    def test_reviewer_refuses_wrong_source_q24_even_rehashed(self):
        def change(v):
            task=next(iter(v['source_features_q24']))
            v['source_features_q24'][task][0]+=1
        self.rejects(change,'source')

    def test_reviewer_refuses_changed_logits_even_resealed(self):
        def change(v):v['final_arms']['fixed_top1']['heldout_logits'][4][0]+=.10
        self.rejects(change,'logits')

    def test_reviewer_refuses_changed_weights_even_if_rehashed_entire_report(self):
        def tweak(v):
            w=v['final_arms']['single_active']['weights']['down']
            data=w['bytes_le_hex'];w['bytes_le_hex']=('fe' if data[:2]!='fe' else 'ee')+data[2:]
        self.rejects(tweak,'bytes|weights|Head|finite|altered|tensor|nonfinite')

    def test_reviewer_refuses_changed_steps_or_sample_exposures(self):
        self.rejects(lambda d:d['final_arms']['single_active'].update(training_steps=39),'stage')
        self.rejects(lambda d:d['final_arms']['fixed_top1'].update(train_exposures=999),'training')
        self.rejects(lambda d:d['final_arms']['fixed_top1'].update(training_head_batch_calls=0),'training')

    def test_reviewer_refuses_free_clone_and_migration(self):
        # If adaptive did NOT split this fixture, forcing one without train-only
        # Brier-trigger proof is still disallowed.
        def spoof(v):
            a=v['final_arms']['adaptive_top1']
            a['split_proposed']=not a['split_proposed']
        self.rejects(spoof,'route|migration|adaptive|weights|heldout')

    def test_reviewer_refuses_missing_dormant_weight_or_fake_head_row_cost(self):
        self.rejects(lambda d:d['final_arms']['frozen_single']['weights'].pop('out_bias'),'tensor')
        self.rejects(lambda d:d['final_arms']['single_active'].update(heldout_expert_rows=[0,0]),'expert|incomplete')

    def test_no_real_pretrained_promotion_with_fake_weights(self):
        with patch.object(p1,'PANEL_SHA',self.panel_sha):
            with self.assertRaises(ValueError):
                frontier.execute(self.tr,self.blind,self.backend,self.old,self.learned,
                                 self.balanced,real=True)

    def test_real_retrospective_train_material_label_not_rewritable(self):
        bad=copy.deepcopy(self.tr);bad['rows'][2]['label']=1-bad['rows'][2]['label']
        bad['seal_id']=p1.digest({k:v for k,v in bad.items() if k!='seal_id'})
        with patch.object(p1,'PANEL_SHA',self.panel_sha):
            with self.assertRaises(ValueError):
                frontier.execute(bad,self.blind,self.backend,self.old,self.learned,self.balanced)

    def test_missing_blind_source_or_fabricated_test_label_cannot_train(self):
        bad=copy.deepcopy(self.blind)
        bad['rows'][0]['label']=1
        bad['seal_id']=p1.digest({k:v for k,v in bad.items() if k!='seal_id'})
        with patch.object(p1,'PANEL_SHA',self.panel_sha):
            with self.assertRaises(ValueError):frontier.execute(self.tr,bad,self.backend,self.old,self.learned,self.balanced)

    def test_reviewer_rejects_added_unsupported_claim_and_unsealed_previous_cost(self):
        self.rejects(lambda d:d.update(independent_publisher_signatures_verified=True),'fields')
        bad=copy.deepcopy(self.balanced)
        bad['measured_trials'].pop()
        with self.assertRaises(ValueError):self.rescore(balanced=bad)

    def test_minimal_update_schedule_is_even_and_stable(self):
        self.assertEqual(frontier.allotted_steps(100,200),20)
        self.assertEqual(frontier.allotted_steps(100,100),40)
        self.assertEqual(frontier.allotted_steps(100,120),32)
        self.assertEqual(frontier.allotted_steps(100,60),40)
        self.assertEqual(frontier.allotted_steps(100,1000),20)
        for a,b in ((-1,20),(0,100),(100,0),(True,1),(1,False)):
            with self.assertRaises(ValueError):frontier.allotted_steps(a,b)

    def test_bad_pilot_seed_looks_like_randomness_tuning_and_is_rejected(self):
        for seed in (0,-1,True,2**31):
            with self.assertRaises(ValueError):frontier.orders(seed)
        with self.assertRaises(ValueError):frontier.orders(20261015,4)


if __name__=='__main__':unittest.main()
