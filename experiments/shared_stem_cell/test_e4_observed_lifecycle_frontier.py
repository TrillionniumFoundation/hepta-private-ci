"""Read-only E4 cost/quality ancestry and completeness tests (synthetic receipts)."""
import copy
import unittest
from pathlib import Path

from e1_matched_gated_head import run_probe
from e4_observed_lifecycle_frontier import (MODELS, observed_frontier, sha,
                                            HEAD_PARAMETERS, POPULATION)
import test_e3_original_group_learning_curve as e3_source_fixture
import test_e3_original_human_score as e3_human_fixture

class ObservedLifecycleFrontierTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        human=e3_human_fixture.OriginalGroupHumanTests
        human.setUpClass()
        cls.fit=copy.deepcopy(human.fit)
        cls.blind=copy.deepcopy(human.blind)
        cls.e3_human=human().valid()
        src=e3_source_fixture.OriginalGroupCurveTests
        n=len(cls.fit['cases'])+len(cls.blind['cases'])
        tr=list(range(48));ca=list(range(48,56));held=list(range(56,72))
        r,_=run_probe(src.x,tr,[src.rows[i]['label'] for i in tr],
                       ca,[src.rows[i]['label'] for i in ca],held)
        cls.p0={};cls.e1={};cls.e2={};cls.e3={};cls.e3_reviews={}
        for m in MODELS:
            p0={'model':m,'fit_material_sha256':sha(cls.fit),
                'blind_material_sha256':sha(cls.blind),'local_process_wall_ms':1000.,
                'local_process_cpu_ms':850.,'local_peak_rss_bytes':123456789,
                'complete_source_profiles':{'physical_encoder_api_requests':n,
                  'physical_encoder_ms_by_case':{str(i):float(i+1) for i in range(n)},
                  'model_load_ms':300.},
                'physical_model_origin_independently_signed':False,
                'production_promotion_permitted':False,'authority':'DENY_ALL'}
            e1=copy.deepcopy(r)
            e1.update({'model':m,'original_report_sha256':sha(p0),
                       'original_fit_sha256':sha(cls.fit),
                       'original_blind_sha256':sha(cls.blind),
                       'physical_model_origin_independently_authenticated':False})
            e2=copy.deepcopy(human.e2_seals[m])
            e2.update({'original_report_sha256':sha(p0),
                       'probe_report_sha256':sha(e1),
                       'numeric_review_sha256':'a'*64,
                       'blind_material_sha256':sha(cls.blind),
                       'production_promotion_permitted':False})
            e3=copy.deepcopy(human.e3_reports[m])
            e3.update({'original_e1_probe_sha256':sha(e1),
                       'original_e1_numeric_sha256':e2['numeric_review_sha256'],
                       'p0_original_report_sha256':sha(p0)})
            nr=copy.deepcopy(human.e3_numeric[m])
            nr.update({'reviewed_e3_report_sha256':sha(e3),
                       'reviewed_e1_report_sha256':sha(e1),
                       'reviewed_original_fit_sha256':sha(cls.fit),
                       'reviewed_original_blind_sha256':sha(cls.blind),
                       'reviewed_e3_weights_sha256':e3['e3_trained_weights_sha256'],
                       'reviewed_model':m})
            cls.p0[m]=p0;cls.e1[m]=e1;cls.e2[m]=e2;cls.e3[m]=e3;cls.e3_reviews[m]=nr

    def valid(self,**kwargs):
        return observed_frontier(kwargs.get('fit',self.fit),kwargs.get('blind',self.blind),
          kwargs.get('p0',self.p0),kwargs.get('e1',self.e1),kwargs.get('e2',self.e2),
          kwargs.get('e3',self.e3),kwargs.get('reviews',self.e3_reviews),
          kwargs.get('human',self.e3_human),candidate_sha=kwargs.get('head','1'*40),
          run_id=kwargs.get('run',77))

    def test_source_ci_fetches_actual_ancestor_commit_before_verifying(self):
        # Regression for real GitHub run 38743232013/source, which failed with
        # "fatal: Not a valid commit name" on the default depth-1 checkout.
        workflow=(Path(__file__).resolve().parents[2] / '.github' / 'workflows' /
                  'hepta-e3-original-source-group.yml').read_text()
        source=workflow.split('  original-feature-source-budget:',1)[0]
        before, after=source.split('      - uses: actions/setup-python@v5',1)
        self.assertIn('fetch-depth: 16',before)
        self.assertIn('persist-credentials: false',before)
        self.assertIn('ref: ${{ github.event.pull_request.head.sha || github.sha }}',before)
        self.assertIn('git merge-base --is-ancestor '
                      '72c2316348b7537921ab5e3ef478c46be27a895e HEAD',after)

    def test_all_three_model_work_censuses_and_4096_head_math(self):
        out=self.valid()
        self.assertEqual(out['source_case_count'],72)
        self.assertEqual(set(out['model_costs']),set(MODELS))
        self.assertIsNone(out['selected_model'])
        self.assertFalse(out['complete_lifecycle_cost_matched'])
        for m in MODELS:
            c=out['model_costs'][m]
            self.assertGreater(c['all_recorded_stages_wall_ms_sum_not_end_to_end'],1000.)
            self.assertGreater(c['all_recorded_stages_cpu_ms_sum_not_end_to_end'],850.)
            self.assertEqual(c['theoretical_head_weight_bytes_by_population']['4096'],4096*HEAD_PARAMETERS*4)
            self.assertEqual(set(c['theoretical_head_weight_bytes_by_population']),set(map(str,POPULATION)))
            self.assertIsNone(c['actual_4096_cell_peak_rss_bytes'])
            self.assertIsNone(c['current_encoder_parameter_resident_bytes_verified'])
            self.assertFalse(c['head_resource_or_model_winner_certified'])
            self.assertEqual([c['trained_4_8_12_source_budgets'][str(n)]['trained_head_runs'] for n in (4,8,12)],
                             [6,6,6])

    def test_original_report_with_wrong_source_or_model_refused(self):
        for field,value in (('model','another'),('fit_material_sha256','f'*64),
                            ('blind_material_sha256','0'*64)):
            p=copy.deepcopy(self.p0);p[MODELS[0]][field]=value
            with self.subTest(field=field),self.assertRaises(ValueError):self.valid(p0=p)

    def test_source_report_different_and_rehashed_not_accepted(self):
        altered=copy.deepcopy(self.e1)
        altered[MODELS[0]]['original_report_sha256']='a'*64
        with self.assertRaises(ValueError):self.valid(e1=altered)
        altered=copy.deepcopy(self.e3)
        altered[MODELS[1]]['projection_extra_mac']=0
        with self.assertRaises(ValueError):self.valid(e3=altered)

    def test_population_actual_rss_claim_not_invented(self):
        o=self.valid()['model_costs'][MODELS[0]]
        self.assertIsNone(o['calibration_and_held_e3_inference_wall_ms'])
        self.assertIsNone(o['inference_work_to_evaluate_all_active_cells'])
        self.assertNotEqual(o['p0_original_process_peak_rss_bytes'],
                            o['theoretical_head_weight_bytes_by_population']['4096'])

    def test_duplicated_encoder_or_zero_projection_cost_refused(self):
        e=copy.deepcopy(self.e3);e[MODELS[0]]['additional_encoder_forwards']=1
        with self.assertRaises(ValueError):self.valid(e3=e)
        e=copy.deepcopy(self.e3);e[MODELS[0]]['projection_extra_physical_forwards']=0
        with self.assertRaises(ValueError):self.valid(e3=e)
        p=copy.deepcopy(self.e1);p[MODELS[0]]['shared_projection']['fp32_bytes']=0
        with self.assertRaises(ValueError):self.valid(e1=p)

    def test_training_update_budget_timings_and_infeasible_contradiction_refused(self):
        for key,value in (('optimizer_updates',0),('train_wall_ms',float('nan')),
                          ('head_parameter_count',770)):
            r=copy.deepcopy(self.e3);r[MODELS[0]]['records'][0][key]=value
            with self.subTest(key=key),self.assertRaises(ValueError):self.valid(e3=r)
        s=copy.deepcopy(self.e3_reviews);s[MODELS[0]]['budget_status']['4']='infeasible_missing_both_labels'
        with self.assertRaises(ValueError):self.valid(reviews=s)

    def test_absent_or_invalid_quality_model_cannot_become_winner(self):
        q=copy.deepcopy(self.e3_human);q['models'].pop(MODELS[1])
        with self.assertRaises(ValueError):self.valid(human=q)
        q=copy.deepcopy(self.e3_human);q['models'][MODELS[0]]['budgets']['12']['seeds']['41']['additive']['brier']=1.2
        with self.assertRaises(ValueError):self.valid(human=q)

    def test_false_production_promotion_and_security_authority_refused(self):
        q=copy.deepcopy(self.e3_human)
        q['production_promotion_permitted']=True
        with self.assertRaises(ValueError):self.valid(human=q)
        p=copy.deepcopy(self.p0);p[MODELS[0]]['authority']='GRANTED'
        with self.assertRaises(ValueError):self.valid(p0=p)

    def test_fabricated_matched_cost_or_independent_attestation_refused(self):
        e1=copy.deepcopy(self.e1);e1[MODELS[0]]['end_to_end_cost_equal']=True
        with self.assertRaises(ValueError):self.valid(e1=e1)
        r=copy.deepcopy(self.e3_reviews);r[MODELS[0]]['independent_cpu_performance_attested']=True
        with self.assertRaises(ValueError):self.valid(reviews=r)

    def test_missing_nonfinite_or_cost_overlap_claim_refused(self):
        p=copy.deepcopy(self.p0);p[MODELS[0]]['local_process_wall_ms']=None
        with self.assertRaises(ValueError):self.valid(p0=p)
        p=copy.deepcopy(self.p0);p[MODELS[0]]['complete_source_profiles']['model_load_ms']=2000.
        with self.assertRaises(ValueError):self.valid(p0=p)

    def test_no_train_labels_or_torch_import_in_cost_frontier(self):
        import subprocess,sys
        s=subprocess.run([sys.executable,'-c',
         "import sys,e4_observed_lifecycle_frontier; assert 'torch' not in sys.modules; assert 'e3_original_group_learning_curve' not in sys.modules"],
         capture_output=True,text=True)
        self.assertEqual(s.returncode,0,s.stderr)
        self.assertNotIn('human_training_labels',repr(self.valid()))

if __name__=='__main__':unittest.main()
