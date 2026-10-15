"""Source-only controls: synthetic fixtures, no claims of pretrained efficacy."""
import copy, hashlib, json, sys, tempfile, unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent))
import archive_cascade_policy as fit
import archive_cascade_review as score


def fixture():
    common=dict(archive_original_sha256='e5d945c655112139fce51b989023abd5111c9e7ab28d9bd4e8a771b86dd95f9d',
       archive_physical_sha256='d8e2af397d7ea862245fae0337588ab491dd70e8a8a9a42879e4a7f2d4be3afa',
       original_model_prediction_sha256={'granite97':score.GRANITESHA,'mmbert_small':score.MMBERTSHA},
       source_panel_sha256=score.PANEL,source_split_salt='fixture-hash',model_forward_newly_executed=False,
       true_future_window=False,external_source_signer_verified=False,production_authorized=False,authority='DENY_ALL')
    result={}
    for part in ('calibration','evaluation'):
        rows=[]
        for i in range(64):
            x={'case_id':f'{part}-case-{i:03}', 'source_group':f'{part}-group-{i:03}',
                'joint_input_digest':hashlib.sha256(f'{part}:input:{i}'.encode()).hexdigest(),
                'granite_probability':.75 if i%2 else .25,'mmbert_probability':.7 if i%2 else .3,
                'granite_encoder_ns':43_000_000+i,'mmbert_encoder_ns':66_000_000+i,
                'granite_head_ns':87_000,'mmbert_head_ns':92_000}
            if part=='calibration':x['label']=i%2
            rows.append(x)
        result[part]=dict(schema=fit.MATERIAL,partition=part,rows=rows,**common)
        result[part]['material_id']=fit.digest(result[part])
    return result['calibration'],result['evaluation']


def reseal(d):d['material_id']=fit.digest({k:v for k,v in d.items() if k!='material_id'})

class SourceMechanism(unittest.TestCase):
    def setUp(self):self.c,self.e=fixture()
    def rejected(self,change):
        c,e=copy.deepcopy((self.c,self.e));change(c,e)
        with self.assertRaises(ValueError):
            for x in (c,e):reseal(x)
            fit.fit(c,e)
    def test_complete_64_64(self):self.assertTrue(fit.validate(self.c,self.e))
    def test_historical_inputs_do_not_claim_new_forwards(self):self.assertFalse(self.c['model_forward_newly_executed'])
    def test_no_holdout_label_in_fit(self):self.assertNotIn('label',self.e['rows'][0])
    def test_training_owner_labels_are_available_only_in_calibration(self):self.assertIn('label',self.c['rows'][0])
    def test_same_source_group_denied(self):self.rejected(lambda c,e:e['rows'][0].update(source_group=c['rows'][0]['source_group']))
    def test_wrong_source_panel(self):self.rejected(lambda c,e:c.update(source_panel_sha256='0'*64))
    def test_false_real_forward(self):self.rejected(lambda c,e:e.update(model_forward_newly_executed=True))
    def test_false_future(self):self.rejected(lambda c,e:c.update(true_future_window=True))
    def test_false_authority(self):self.rejected(lambda c,e:e.update(authority='PRODUCTION'))
    def test_test_label_leak(self):self.rejected(lambda c,e:e['rows'][0].update(label=1))
    def test_eval_duplicate_case(self):self.rejected(lambda c,e:e['rows'][1].update(case_id=e['rows'][0]['case_id']))
    def test_eval_duplicate_source_group(self):self.rejected(lambda c,e:e['rows'][1].update(source_group=e['rows'][0]['source_group']))
    def test_wrong_probability_nan(self):self.rejected(lambda c,e:e['rows'][0].update(granite_probability=float('nan')))
    def test_wrong_probability_boundary(self):self.rejected(lambda c,e:e['rows'][0].update(granite_probability=0))
    def test_wrong_cost_zero(self):self.rejected(lambda c,e:e['rows'][0].update(mmbert_encoder_ns=0))
    def test_changed_model_revision(self):self.rejected(lambda c,e:e['original_model_prediction_sha256'].update(granite97='different'))
    def test_changed_case_order(self):self.rejected(lambda c,e:e['rows'].reverse())
    def test_unknown_calibration_label(self):self.rejected(lambda c,e:c['rows'][0].update(label=None))
    def test_extra_calibration_fields(self):self.rejected(lambda c,e:c['rows'][0].update(hidden='a'))
    def test_independent_model_does_not_use_calibration_labels_in_output(self):
        d=fit.fit(self.c,self.e)
        self.assertFalse(d['selected_after_evaluation_labels'])
        self.assertFalse(d['full_model_inference_reexecuted'])
        self.assertFalse(d['joint_model_request_physically_timed'])
    def test_all_budget_branches_present(self):
        d=fit.fit(self.c,self.e)
        for v in (0,10,25,50,100):
            self.assertIn(f'fallback_{v}',d['observations']);self.assertIn(f'random_matched_{v}',d['observations'])
    def test_fallback_selects_no_model_if_always_worse(self):
        d=fit.fit(self.c,self.e)
        for v in fit.BUDGETS:self.assertEqual(d['rules'][f'fallback_{v}']['calibration_calls'],0)
    def test_registered_fixed_negative_controls_are_nonempty_for_constructed_midconfidence(self):
        c,e=fixture()
        for r in e['rows']:r['granite_probability']=.51
        reseal(e)
        p=fit.fit(c,e)
        self.assertEqual(sum(x['secondary_called'] for x in p['observations']['fixed_margin_020']),64)
        self.assertEqual(sum(x['secondary_called'] for x in p['observations']['random_equal_fixed_margin_020']),64)
    def test_mmbert_only_billed_one_model_not_two(self):
        r=self.e['rows'][0];p=fit.make_prediction(r,True,'mmbert_only')
        self.assertEqual(p['observed_ledger_encoder_sum_ns'],r['mmbert_encoder_ns'])
    def test_dual_pays_two_models(self):
        r=self.e['rows'][0];p=fit.make_prediction(r,True,'dual_most_confident')
        self.assertEqual(p['observed_ledger_encoder_sum_ns'],r['granite_encoder_ns']+r['mmbert_encoder_ns'])
    def test_wrong_gate_budget_rejected(self):
        with self.assertRaises(ValueError):fit.pick_threshold(self.c['rows'],17)
    def test_rank_is_nearest_rank_and_not_request_p99(self):
        self.assertEqual(score.rank_values([1,2,3,4],.95),4)
        self.assertEqual(score.rank_values([1,2,3,4],.5),2)
    def test_there_is_no_model_loader_imported(self):
        import inspect
        data=inspect.getsource(fit)
        self.assertNotIn('import torch',data)
        self.assertNotIn('AutoModel',data)

if __name__=='__main__':unittest.main()
