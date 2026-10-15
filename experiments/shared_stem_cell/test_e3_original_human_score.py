"""Isolated source-bound human scorer fault tests, synthetic panel ONLY."""
import copy
import unittest
from e1_matched_gated_head import run_probe
from e3_original_group_learning_curve import forward_study
from e3_group_learning_review import review
from e3_original_human_score import review_human,sha
from e2_seal_blind_predictions import MODELS,P0_SOURCE,P0_RUN,SEEDS
import test_e3_original_group_learning_curve as fixture


class OriginalGroupHumanTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        fixture.OriginalGroupCurveTests.setUpClass()
        base=fixture.OriginalGroupCurveTests
        cls.fit={'metadata':{'panel_id':base.panel},'cases':base.rows}
        cls.blind={'metadata':{'panel_id':base.panel},'cases':[]}
        cls.labels={}
        for i,row in enumerate(base.held):
            x={'case_id':f'held-{i}','source_group':row['source_group'],
               'condition':'original'}
            cls.blind['cases'].append(x)
            cls.labels[x['case_id']]=i%2
        # Synthetic fixture: original frozen arms are neutral placeholders;
        # trained full-budget forecasts are the actually computed E3 tensors,
        # already checked against E1 by the source-budget mechanism tests.
        e1={'arms':[]}
        for seed in SEEDS:
            for arm in ('frozen_additive','trained_additive','frozen_gated','trained_gated'):
                if arm.startswith('frozen_'):
                    pred=[0.5]*len(base.held)
                else:
                    kind=arm.split('_',1)[1]
                    pred=next(r['blind_predictions'] for r in base.report['records']
                              if (r['budget_source_groups'],r['seed'],r['architecture'])==(12,seed,kind))
                e1['arms'].append({'seed':seed,'arm':arm,'blind_probabilities':pred})
        cls.e2_seals={};cls.e3_reports={};cls.e3_numeric={}
        # Same physical synthetic Head arrays/model-independent source for all
        # three fixture model names; one independent numeric replay is enough.
        base_numeric=review(base.x,base.parent,base.rows,base.held,
                            base.panel,base.report,base.weights)
        for model in MODELS:
            es={'model':model,'candidate_head_sha':'1'*40,'candidate_run_id':77,
                'p0_source_sha':P0_SOURCE,'p0_run_id':P0_RUN,
                'blind_material_sha256':sha(cls.blind),
                'probe_report_sha256':model+'a'*20,
                'numeric_review_sha256':model+'b'*20,'authority':'DENY_ALL'}
            es['forecasts']=[{'seed':r['seed'],'arm':r['arm'],
                              'probabilities':r['blind_probabilities']} for r in e1['arms']]
            cls.e2_seals[model]=es
            r=copy.deepcopy(base.report)
            r.update({'model':model,'original_fit_sha256':sha(cls.fit),
                      'original_blind_sha256':sha(cls.blind),
                      'original_e1_probe_sha256':es['probe_report_sha256'],
                      'original_e1_numeric_sha256':es['numeric_review_sha256'],
                      'candidate_head_sha':'1'*40,'candidate_run_id':77,
                      'e3_trained_weights_sha256':'e'*64})
            cls.e3_reports[model]=r
            num=copy.deepcopy(base_numeric)
            num.update({'reviewed_e3_report_sha256':sha(r),
                        'reviewed_e3_weights_sha256':r['e3_trained_weights_sha256'],
                        'reviewed_original_fit_sha256':sha(cls.fit),
                        'reviewed_original_blind_sha256':sha(cls.blind),
                        'reviewed_e1_report_sha256':es['probe_report_sha256'],
                        'reviewed_model':model})
            cls.e3_numeric[model]=num
        cls.e2_scored={'schema':'hepta.e2.original-human-matched-gated-independent-score.v1',
                       'original_p0_human_review_replayed':True,'production_promotion_permitted':False,
                       'authority':'DENY_ALL','original_human_cases':len(cls.labels)}

    def valid(self,**kwargs):
        return review_human(kwargs.get('fit',self.fit),kwargs.get('blind',self.blind),
                            kwargs.get('labels',self.labels),kwargs.get('e2_score',self.e2_scored),
                            kwargs.get('e2_seals',self.e2_seals),kwargs.get('e3_reports',self.e3_reports),
                            kwargs.get('e3_reviews',self.e3_numeric),
                            candidate_sha=kwargs.get('sha','1'*40),run_id=kwargs.get('run',77))

    def test_complete_original_human_scores_all_three_budgets_and_models(self):
        result=self.valid()
        self.assertEqual(set(result['models']),set(MODELS))
        self.assertEqual(result['independent_original_source_groups'],8)
        self.assertFalse(result['stem_or_head_winner_selected'])
        for model in MODELS:
            for budget in ('4','8','12'):
                self.assertEqual(set(result['models'][model]['budgets'][budget]['seeds']),{'41','47','53'})
                for seed in ('41','47','53'):
                    scored=result['models'][model]['budgets'][budget]['seeds'][seed]
                    self.assertEqual(scored['additive']['original_rows'],16)
                    self.assertEqual(len(scored['paired']['per_original_source_passage_gains']),8)

    def test_preserves_all_negative_and_unfavorable_measurements(self):
        result=self.valid()
        for model in MODELS:
            self.assertEqual(len(result['models'][model]['budgets']),3)
        self.assertFalse(result['95pct_superiority_certified'])
        self.assertFalse(result['old_task_retention_verified'])

    def test_missing_model_or_numeric_review_refused(self):
        r=dict(self.e3_reports);r.pop(MODELS[1])
        with self.assertRaises(ValueError):self.valid(e3_reports=r)
        r=dict(self.e3_numeric);r.pop(MODELS[2])
        with self.assertRaises(ValueError):self.valid(e3_reviews=r)

    def test_old_e2_review_must_be_signed_off_as_replayed_not_just_present(self):
        r=dict(self.e2_scored);r['original_p0_human_review_replayed']=False
        with self.assertRaises(ValueError):self.valid(e2_score=r)

    def test_wrong_original_label_source_or_missing_passage_refused(self):
        r=dict(self.labels);r.pop(next(iter(r)))
        with self.assertRaises(ValueError):self.valid(labels=r)
        r=dict(self.labels);r[next(iter(r))]=True
        with self.assertRaises(ValueError):self.valid(labels=r)

    def test_all_budget_forecasts_must_link_to_separate_e3_num_review(self):
        r=copy.deepcopy(self.e3_reports)
        x=r[MODELS[0]]['records'][0]['blind_predictions']
        x[0]=0.99 if x[0]<.5 else 0.01
        with self.assertRaises(ValueError):self.valid(e3_reports=r)

    def test_changed_and_rehashed_num_review_rejected_if_parent_mismatched(self):
        r=copy.deepcopy(self.e3_reports)
        r[MODELS[0]]['records'][0]['blind_predictions'][0]=0.6
        reviews=copy.deepcopy(self.e3_numeric)
        reviews[MODELS[0]]['reviewed_e3_report_sha256']=sha(r[MODELS[0]])
        # Source-level hashes still cannot prove physical execution. This test
        # deliberately does not claim to reject coordinated forged review+run.
        self.assertNotEqual(self.e3_numeric[MODELS[0]],reviews[MODELS[0]])
        with self.assertRaises(ValueError):self.valid(e3_reports=r)  # original review differs

    def test_wrong_current_head_sha_run_and_p0_baseline_refused(self):
        for args in ({'sha':'2'*40},{'run':78}):
            with self.assertRaises(ValueError):self.valid(**args)
        s=copy.deepcopy(self.e2_seals);s[MODELS[0]]['p0_source_sha']='9'*40
        with self.assertRaises(ValueError):self.valid(e2_seals=s)

    def test_full_budget_must_match_original_e1_parent_predictions(self):
        s=copy.deepcopy(self.e2_seals)
        s[MODELS[0]]['forecasts'][1]['probabilities'][0]+=0.1
        with self.assertRaisesRegex(ValueError,'E3 budget parity'):self.valid(e2_seals=s)

    def test_bad_source_group_budget_or_duplicate_trial_refused(self):
        r=copy.deepcopy(self.e3_reports);r[MODELS[0]]['records'].pop()
        with self.assertRaises(ValueError):self.valid(e3_reports=r)

    def test_false_production_or_winner_flag_refused(self):
        for key in ('production_promotion_permitted','statistical_winner_selected'):
            r=copy.deepcopy(self.e3_reports);r[MODELS[0]][key]=True
            with self.assertRaises(ValueError):self.valid(e3_reports=r)

    def test_human_reviewer_has_no_torch_or_producer_dependency(self):
        import subprocess,sys
        from pathlib import Path
        p=subprocess.run([sys.executable,'-c',
          "import sys,e3_original_human_score; assert 'torch' not in sys.modules; assert 'e3_original_group_learning_curve' not in sys.modules"],
          cwd=Path(__file__).parent,capture_output=True,text=True)
        self.assertEqual(p.returncode,0,p.stderr)


if __name__=='__main__':unittest.main()
