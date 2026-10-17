"""Adversarial source-only and real CPU tensor tests; no pretrained HF forward."""
from __future__ import annotations

import copy
import json
import math
from pathlib import Path
import tempfile
import unittest

import stem_v4 as core
import review_v4 as review
import system2_v4 as bellman


def fixture():
    held=[{'case_id':f'heldout:{i:064x}','source_sha256':f'{i:064x}'} for i in range(32)]
    source={'source_plan_sha256':'a'*64,'heldout':held}
    probabilities=[.1,.7,.1,.1]
    result={
        'schema':core.SCHEMA,'cohort':core.COHORT,'candidate':core.ARM,
        'source_plan_sha256':source['source_plan_sha256'],
        'model_repo':core.REPO,'model_revision':core.REVISION,
        'actual_weight_sha256':core.WEIGHT_SHA,'model_precision':'fp32_cpu',
        'actual_loaded_parameters':270_000_000,
        'original_parameter_audit':{
            'profile':'hepta.stem.source-value-coverage-fp32.v5',
            'original_weight_sha256':core.WEIGHT_SHA,
            'runtime_parameter_elements':270_000_000,
            'runtime_unique_parameter_tensors':413,
            'original_archive_tensor_count':1376,
            'source_tensor_elements_including_unused_modalities':744_000_000,
            'source_value_coverage_verified':True,
            'strict_logical_name_mapping_verified':False,
            'model_issuer_signature_verified':False,
            'proof_digest':'a'*64,
            'audit_wall_seconds_unattested':1.5},
        'native_width':768,'projected_width':384,'projection':core.PROJECTION,
        'prompt_name':'Classification',
        'initial_head_sha256':'a'*64,'trained_head_sha256':'b'*64,
        'head_parameters':27656,'optimizer_steps':100,
        'fit_feature_witness_sha256':'e'*64,
        'rows':[{'case_id':r['case_id'],'source_sha256':r['source_sha256'],
                 'scores':{a:list(probabilities) for a in review.ARMS}} for r in held],
        'cost':{'physical_encoder_sequences':96,'physical_encoder_forward_batches':6,
                'model_load_seconds':1.0,'embedding_seconds':2.0,'head_train_seconds':.2,
                'complete_wall_seconds':4.,'complete_cpu_seconds':3.,
                'maxrss_bytes_linux_unattested':2_000_000_000,
                'energy_joules':None,'complete_request_p99_ms':None},
        'train_only_centroid':{
            'schema':'hepta.stem.train-loo-centroid-calibration.v5',
            'selected_temperature':1.0,
            'registered_temperatures':[1.0,0.5,0.25,0.125,0.0625,0.03125,0.015625],
            'fit_only_loocv_multiclass_brier':[0.1,0.2,0.3,0.4,0.5,0.6,0.7],
            'fit_examples':64,'fit_per_class_counts':[16]*4,
            'heldout_labels_used_for_calibration':False,
            'heldout_calibration_metric_selected':False,
            'new_head_sgd_steps':0,'train_feature_digest':'d'*64,
            'output_rows':[{'case_id':row['case_id'],
                            'source_sha256':row['source_sha256'],
                            'probabilities':list(probabilities)} for row in held],
            'fit_and_output_wall_seconds_unattested':0.1,
            'new_model_forward_calls':0,'production_authorized':False},
        'fleet':{'fleet_cell_count':4096,'active_heads_per_call':32,
                 'head_parameter_count':4096*6914,
                 'head_weight_bytes_fp32':4096*6914*4,'timed_batched_calls':64,
                 'head_batch_p95_ms':.2,'head_batch_p99_ms':.4,
                 'last_logit_sha256':'f'*64,
                 'real_pretrained_input_feature':True,'complete_request_p99':None,
                 'energy_joules':None,'target_host_attested':False},
        'future_windows':0,'human_verified_new_sources':0,
        'ndu_task_utility_qualified':False,'cell_split_authorized':False,
        'production_authorized':False,'authority':'DENY_ALL','disposition':'HOLD_NO_GO'}
    gold={r['case_id']:i%4 for i,r in enumerate(held)}
    return source,result,gold


def graph():
    return {'root':[
        {'name':'stop','cost':0,'forecast_utility':0,'children':[]},
        {'name':'direct','cost':1,'forecast_utility':150_000,'children':[]},
        {'name':'check','cost':2,'forecast_utility':-100_000,
         'children':[['success',500000],['fail',500000]]}],
        'success':[{'name':'stop','cost':0,'forecast_utility':0,'children':[]},
                   {'name':'continue','cost':1,'forecast_utility':800000,'children':[]}],
        'fail':[{'name':'stop','cost':0,'forecast_utility':0,'children':[]}]}


class ReceiptTests(unittest.TestCase):
    def test_valid_descriptive_scores_never_authorize(self):
        src,r,g=fixture()
        out=review.check_fourth(src,r,g)
        self.assertEqual(out['learned']['n'],32)
        self.assertEqual(out['learned']['correct'],8)
        self.assertGreater(out['learned']['brier'],0)

    def test_quarantine_mmbert_original_random_init_even_if_high_score(self):
        # Model load SUCCESS is not sufficient: historical V3 logged a fresh
        # randomly initialized token embedding.  Never show that candidate as
        # a qualified pretrained Stem regardless of its scored accuracy.
        original = {'models': {'granite47': {'score': 0},
                               'granite97': {'score': 0},
                               'mmbert140': {'score': 32}}}
        out = review.quarantine_unqualified_mmbert(original)
        self.assertEqual(set(out['models']), {'granite47', 'granite97'})
        self.assertNotIn('score', out['disqualified_comparator'])
        self.assertEqual(out['disqualified_comparator']['pretrained_model_qualified'], False)
        self.assertEqual(original['models']['mmbert140']['score'], 32)
        self.assertFalse(out['all_checkpoint_parameters_independently_qualified'])
        with self.assertRaises(ValueError):
            review.quarantine_unqualified_mmbert({'models': {'granite47': {}, 'granite97': {}}})

    def test_fixed_temperature_control_never_optimizes_on_heldout(self):
        src,r,g=fixture()
        old=[{'candidate':name,'rows':copy.deepcopy(r['rows'])}
             for name in ('granite47','granite97','mmbert140')]
        sensitivity=review.postseal_centroid_temperature_sensitivity(old,g)
        self.assertEqual(set(sensitivity['models']),{'granite47','granite97'})
        self.assertFalse(sensitivity['heldout_temperature_selected'])
        self.assertFalse(sensitivity['train_only_calibrated'])
        self.assertEqual(sensitivity['additional_head_sgd_steps'],0)
        self.assertEqual(len(sensitivity['temperatures_fixed_in_advance']),4)
        for measures in sensitivity['models'].values():
            self.assertEqual(set(v['correct'] for v in measures.values()),{8})
            self.assertEqual(measures['1.0']['n'],32)
        old[0]['rows'][0]['scores']['centroid']=[1.0,1.0,0.0,0.0]
        with self.assertRaises(ValueError):
            review.postseal_centroid_temperature_sensitivity(old,g)

    def test_denied_authority_and_outcome_leak(self):
        src,r,g=fixture()
        for key,value in [('authority','ALLOW'),('production_authorized',True),
                          ('future_windows',1),('ndu_task_utility_qualified',True),
                          ('cell_split_authorized',True)]:
            bad=copy.deepcopy(r);bad[key]=value
            with self.subTest(key=key),self.assertRaises(ValueError):
                review.check_fourth(src,bad,g)
        bad=copy.deepcopy(r);bad['rows'][0]['label']=1
        with self.assertRaises(ValueError):review.check_fourth(src,bad,g)

    def test_train_only_centroid_outputs_and_no_heldout_tuning(self):
        src,r,g=fixture()
        scored=review.check_fourth(src,r,g)
        self.assertIn('train_only_loocv_centroid',scored)
        self.assertFalse(scored['train_only_loocv_centroid'][
            'independent_source_future_qualified'])
        for key,value in [('selected_temperature',0.02),
                          ('heldout_labels_used_for_calibration',True),
                          ('heldout_calibration_metric_selected',True),
                          ('new_head_sgd_steps',1),('new_model_forward_calls',1),
                          ('production_authorized',True),
                          ('train_feature_digest','0'),
                          ('fit_only_loocv_multiclass_brier',[0])]:
            bad=copy.deepcopy(r)
            bad['train_only_centroid'][key]=value
            with self.subTest(key=key), self.assertRaises(ValueError):
                review.check_fourth(src,bad,g)
        bad=copy.deepcopy(r)
        bad['train_only_centroid']['output_rows'][0]['case_id']='false'
        with self.assertRaises(ValueError):review.check_fourth(src,bad,g)

    def test_calibrated_output_cannot_be_forged_under_identical_source_receipt(self):
        src, receipt, gold = fixture()
        # A forged probability can otherwise inflate quality without any
        # observed feature or additional Encoder forward.
        bad = copy.deepcopy(receipt)
        bad['train_only_centroid']['output_rows'][0]['probabilities'] = [0.7, 0.1, 0.1, 0.1]
        with self.assertRaisesRegex(ValueError, 'not derived from original'):
            review.check_fourth(src, bad, gold)

    def test_calibrated_temperature_is_bound_to_existing_centroid(self):
        src, receipt, gold = fixture()
        bad = copy.deepcopy(receipt)
        # Even if a fake FIT-only loss vector is re-sealed, the heldout
        # calibrated scores must change according to the new selected T.
        bad['train_only_centroid']['selected_temperature'] = 0.5
        bad['train_only_centroid']['fit_only_loocv_multiclass_brier'] = [0.4, 0.1, 0.5, 0.6, 0.7, 0.8, 0.9]
        with self.assertRaisesRegex(ValueError, 'not derived from original'):
            review.check_fourth(src, bad, gold)

    def test_real_torch_centroid_softmax_matches_stdlib_replay(self):
        import torch
        import torch.nn.functional as F
        torch.manual_seed(20261017)
        torch.set_num_threads(2)
        raw = F.normalize(torch.randn(32, 384, dtype=torch.float32), dim=-1)
        centers = F.normalize(torch.randn(4, 384, dtype=torch.float32), dim=-1)
        similarity = raw @ centers.T
        base = torch.softmax(similarity, dim=-1).tolist()
        for t in (1.0, 0.5, 0.25, 0.015625):
            adjusted = torch.softmax(similarity / t, dim=-1).tolist()
            for left, right in zip(base, adjusted):
                review.verify_temperature_probability_link(left, right, t)
        tampered = list(adjusted[0]); tampered[0] += 0.01; tampered[1] -= 0.01
        with self.assertRaises(ValueError):
            review.verify_temperature_probability_link(base[0], tampered, 0.015625)

    def test_missing_random_or_forged_original_parameter_census(self):
        src, r, g = fixture()
        for key, val in [
            ('source_value_coverage_verified',False),
            ('runtime_parameter_elements',1000),
            ('original_weight_sha256','0'*64),
            ('model_issuer_signature_verified',True),
            ('original_archive_tensor_count',1),
        ]:
            bad=copy.deepcopy(r)
            bad['original_parameter_audit'][key]=val
            with self.subTest(key=key), self.assertRaises(ValueError):
                review.check_fourth(src,bad,g)
        bad=copy.deepcopy(r)
        del bad['original_parameter_audit']
        with self.assertRaises(ValueError):review.check_fourth(src,bad,g)

    def test_real_text_tower_parameter_census_and_initial_tensor_parity(self):
        src,r,g=fixture()
        old=[{'initial_head_sha256':'a'*64} for _ in range(3)]
        review.ensure_matched_initial_heads(old,r)
        old[-1]['initial_head_sha256']='f'*64
        with self.assertRaises(ValueError):review.ensure_matched_initial_heads(old,r)
        bad=copy.deepcopy(r);bad['actual_loaded_parameters']=740_000_000
        with self.assertRaises(ValueError):review.check_fourth(src,bad,g)

    def test_model_revision_weight_projection_and_optimizer_must_match(self):
        src,r,g=fixture()
        for key,value in [('model_revision','0'*40),('actual_weight_sha256','f'*64),
                          ('projection','learned_from_heldout'),('optimizer_steps',0),
                          ('head_parameters',4)]:
            bad=copy.deepcopy(r);bad[key]=value
            with self.subTest(key=key),self.assertRaises(ValueError):
                review.check_fourth(src,bad,g)

    def test_bad_gold_and_missing_changed_heldout(self):
        src,r,g=fixture()
        bad=copy.deepcopy(g);bad.pop(next(iter(bad)))
        with self.assertRaises(ValueError):review.check_fourth(src,r,bad)
        bad=copy.deepcopy(r);bad['rows'][0]['case_id']='fake'
        with self.assertRaises(ValueError):review.check_fourth(src,bad,g)

    def test_nan_and_nonprobability(self):
        src,r,g=fixture()
        for prob in [[.1,float('nan'),.3,.6],[.2,.2,.2,.2],[2,-1,0,0]]:
            bad=copy.deepcopy(r);bad['rows'][0]['scores']['learned']=prob
            with self.assertRaises(ValueError):review.check_fourth(src,bad,g)

    def test_missing_real_fleet_or_unattested_costs(self):
        src,r,g=fixture()
        mutations=(('fleet','head_parameter_count',4),
                   ('fleet','fleet_cell_count',4),
                   ('fleet','target_host_attested',True),
                   ('cost','energy_joules',0.0),
                   ('cost','physical_encoder_forward_batches',0))
        for group,key,value in mutations:
            bad=copy.deepcopy(r);bad[group][key]=value
            with self.subTest(key=key),self.assertRaises(ValueError):
                review.check_fourth(src,bad,g)

    def test_canonical_io_duplicate_nonfinite_symlink_create_once(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            a=root/'a.json';a.write_text('{"a":1,"a":2}')
            with self.assertRaises(ValueError):core.read_json(a)
            a.write_text('{"a":NaN}')
            with self.assertRaises(ValueError):core.read_json(a)
            a.write_text('{"a":4}')
            symlink=root/'sym';symlink.symlink_to(a)
            with self.assertRaises(ValueError):core.read_json(symlink)
            out=root/'out.json';core.write_private(out,{'science':'HOLD_NO_GO'})
            self.assertEqual(json.loads(out.read_text())['science'],'HOLD_NO_GO')
            self.assertEqual(out.stat().st_mode & 0o777,0o600)
            with self.assertRaises(FileExistsError):core.write_private(out,{})

    def test_wrong_actual_model_file_cannot_load(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'model.safetensors';p.write_bytes(b'fixture not weights')
            with self.assertRaises(ValueError):core.verify_weight_file(p)


class ControlTests(unittest.TestCase):
    def test_budget_stop_and_nonleak(self):
        g=graph();best=bellman.solve(g,'root',budget=0)
        self.assertEqual(best['chosen_action'],'stop')
        self.assertFalse(best['oracle_outcomes_used'])
        self.assertEqual(best['authority'],'DENY_ALL')

    def test_search_uses_genuine_continuation_and_discount(self):
        g=graph()
        self.assertEqual(bellman.solve(g,'root',budget=3,horizon=1)['chosen_action'],'direct')
        self.assertEqual(bellman.solve(g,'root',budget=3,horizon=2)['chosen_action'],'check')
        self.assertEqual(bellman.solve(g,'root',budget=3,horizon=2,
                                      discount_ppm=0)['chosen_action'],'direct')

    def test_tree_probability_cost_and_nonanticipation(self):
        for mutate in (
            lambda g:g['root'][2]['children'][0].__setitem__(1,999999),
            lambda g:g['root'][2].__setitem__('target',1),
            lambda g:g['root'][2]['children'][0].__setitem__(0,'root'),
            lambda g:g['root'][0].__setitem__('cost',1),
            lambda g:g['root'][2].__setitem__('forecast_utility',10**20),
        ):
            g=graph();mutate(g)
            with self.assertRaises(ValueError):bellman.solve(g,'root',budget=3)

    def test_abstain_when_all_predictions_negative(self):
        g={'root':[{'name':'stop','cost':0,'forecast_utility':0,'children':[]},
                   {'name':'bad','cost':2,'forecast_utility':-900000,'children':[]}]}
        self.assertEqual(bellman.solve(g,'root',budget=2)['chosen_action'],'stop')


class PhysicalMechanismTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import torch
        cls.torch=torch
        torch.set_num_threads(2)

    def test_proj_uses_all_768_features_and_normalizes(self):
        torch=self.torch
        x=torch.zeros(2,768)
        x[0,0]=1;x[0,1]=1
        x[1,766]=1;x[1,767]=1
        y=core.project_768_to_384(x)
        self.assertEqual(tuple(y.shape),(2,384))
        self.assertEqual(y[0,0].item(),1.0)
        self.assertEqual(y[1,383].item(),1.0)
        with self.assertRaises(ValueError):core.project_768_to_384(torch.zeros(1,768))
        with self.assertRaises(ValueError):core.project_768_to_384(torch.zeros(1,384))

    def test_hook_counts_real_forward_not_logical_borrows(self):
        torch=self.torch
        class Inner(torch.nn.Module):
            def forward(self,x):return x
        class Encoder:
            def __init__(self):self.enc=Inner()
            def __getitem__(self,i):return self.enc
            def encode(self,texts,**kwargs):
                x=torch.ones(len(texts),768)
                return self.enc(x)
        features,count=core.physical_embedding(['a']*96,Encoder())
        self.assertEqual(count,6)
        self.assertEqual(tuple(features.shape),(96,384))

    def test_physically_allocated_head_fleet_64(self):
        torch=self.torch
        x=torch.nn.functional.normalize(torch.ones(384),dim=0)
        f=core.physical_fleet(x,64)
        self.assertEqual(f['head_parameter_count'],64*6914)
        self.assertEqual(f['timed_batched_calls'],64)
        self.assertIsNone(f['complete_request_p99'])
        self.assertTrue(f['head_batch_p99_ms']>=f['head_batch_p95_ms'])

    def test_physically_allocated_head_fleet_4096(self):
        torch=self.torch
        x=torch.nn.functional.normalize(torch.ones(384),dim=0)
        f=core.physical_fleet(x,4096)
        self.assertEqual(f['head_parameter_count'],28_319_744)
        self.assertEqual(f['head_weight_bytes_fp32'],113_278_976)
        self.assertFalse(f['target_host_attested'])


if __name__=='__main__':unittest.main()
