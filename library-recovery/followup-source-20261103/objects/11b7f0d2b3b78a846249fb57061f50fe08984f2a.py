"""Adversarial, model-free source/budget/held-label checks for E1 partial receipts."""
from __future__ import annotations
import copy
import hashlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock
import zipfile

import e1_original_partial_two_model_audit_v1 as m


def fixture():
    data=[]
    for split,n in m.SPLITS.items():
        for i in range(n):
            state=f'fixture {split} document number {i} carefully selected for tests'
            joint={'state':state,'question':'Which category does the news report describe?',
                   'options':['world','sports']}
            digest=m.sha(state.encode())
            label=i%2
            data.append({'case_id':digest[:24],'group_id':digest,'joint_input':joint,
                         'joint_input_digest':m.sha(m.canonical(joint)),'label':label,
                         'label_name':('sports' if label else 'world'),'source_digest':digest,
                         'split':split})
    panel={'schema':'hepta.stem.agnews-binary-capability-panel.v1',
           'dataset':'szhuggingface/ag_news','dataset_commit_prefix':'98c5322',
           'dataset_file_sha256':m.SOURCE_FILES,'label_mapping':{'world':0,'sports':1},
           'production_promotion':'DENY_ALL','cross_sectional_not_future':True,
           'case_count':224,'cases':data}
    return panel


def make_models(panel,model='granite_97m_r2'):
    rev,width,params=m.MODEL_INFO[model]
    cases={c['case_id']:c for c in panel['cases']}
    predictions=[]
    for row in panel['cases']:
        if row['split'] in ('calibration','test'):
            predictions.append({'case_id':row['case_id'],
                                'joint_input_digest':row['joint_input_digest'],
                                'positive_probability':0.8 if row['label']==1 else 0.2,
                                'split':row['split']})
    b={'schema':'hepta.fixture.bank.v1','case_count':224,'feature_width':width,
       'authority':'DENY_ALL','model_origin_independently_verified':False,
       'case_q24_sha256':{cid:'a'*64 for cid in cases}}
    e1={'model':model,'model_revision':rev,'feature_width':width,
        'schema':'hepta.e1-english-public-pretrained-head.v1',
        'public_panel_sha256':m.PANEL_SHA256,'authority':'DENY_ALL',
        'production_promotion_permitted':False,'model_origin_independently_authenticated':False,
        'public_dataset_is_chronological_future':False,'future_ndu_verified':False,
        'frozen_feature_bank_identity':b,'features_q24_identity':{cid:'a'*64 for cid in cases},
        'tokens_per_case':{cid:32 for cid in cases},
        'physical_observations':{'local_model_api_requests':224,
            'physical_transformer_forward_count_attested':False},
        'actual_pretrained_local_weight_execution_claimed':True,
        'process_lifetime_peak_rss_bytes':1_000_000_000,'wall_ms':50000.,
        'fitting':{'train_case_ids_sha256':m.TRAIN_IDS_SHA256,'head_parameter_count':params,
                   'seed':20261014,'steps':40,'training_test_labels_accessed':False,
                   'retrospective_public_labels_available_in_process':True,
                   'controls':{'frozen_head':{'predictions':copy.deepcopy(predictions)},
                               'learned_head':{'predictions':copy.deepcopy(predictions)}}}}
    e2={'model':model,'source_model_revision':rev,'width':width,
        'schema':'hepta.e2-feature-gated-head-public.v1','public_panel_sha256':m.PANEL_SHA256,
        'source_e1_report_sha256':m.sha(m.canonical(e1)),'authority':'DENY_ALL',
        'production_promotion_permitted':False,'chronological_future_ndu_verified':False,
        'independent_no_change_production_arm_present':False,
        'additional_encoder_model_loads':0,'additional_encoder_feature_forwards':0,
        'existing_frozen_encoder_features_reused':True,
        'frozen_base_weight_storage_shared_among_residual_arms':True,
        'frozen_base_parameters_counted_as_shared_storage':params,
        'reader_sufficiency_evaluated':False,
        'cosine_uses_train_labels_not_no_fit':True,
        'head_kind':'post_encoder_feature_gated_residual_not_cell_state_film',
        'frozen_feature_bank_identity':b,'train_case_ids_sha256':m.TRAIN_IDS_SHA256,
        'steps':40,'seed':20261014,
        'arms':{a:{'trainable_parameters':
                    0 if a in ('cosine_prototype','frozen_head') else
                    params if a=='from_zero' else
                    1500 if a=='residual_2k' else 7000 if a=='residual_8k' else 15000,
                    'predictions':copy.deepcopy(predictions)} for a in m.E2_ARMS}}
    return e1,e2,m.canonical(e1)


class OriginalSourceEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.panel=fixture()
        self.panel_sha=m.sha(m.canonical(self.panel))
        self.train_sha=m.sha(m.canonical([c['case_id'] for c in self.panel['cases'] if c['split']=='train']))
        self.patch1=mock.patch.object(m,'PANEL_SHA256',self.panel_sha)
        self.patch2=mock.patch.object(m,'TRAIN_IDS_SHA256',self.train_sha)
        self.patch1.start();self.patch2.start()
        self.addCleanup(self.patch1.stop);self.addCleanup(self.patch2.stop)

    def test_original_example_panel_and_splits(self):
        self.assertEqual(len(m.validate_panel(self.panel)),224)

    def test_no_rehashed_changed_source_input(self):
        mutated=copy.deepcopy(self.panel)
        mutated['cases'][0]['joint_input']['state']='tampered original source text'
        with self.assertRaises(m.Invalid):m.validate_panel(mutated)

    def test_no_train_test_repartition(self):
        altered=copy.deepcopy(self.panel)
        altered['cases'][0]['split']='test'
        with self.assertRaises(m.Invalid):m.validate_panel(altered)

    def test_boolean_or_unregistered_label_refused(self):
        for bad in (True,2,'1',None):
            altered=copy.deepcopy(self.panel);altered['cases'][0]['label']=bad
            with self.subTest(label=bad),self.assertRaises(m.Invalid):m.validate_panel(altered)

    def test_actual_public_test_64_scored_and_not_hidden(self):
        cases=m.validate_panel(self.panel)
        e1,e2,raw=make_models(self.panel)
        p=e2['arms']['from_zero']['predictions']
        expected={cid for cid,c in cases.items() if c['split'] in ('calibration','test')}
        x=m.validate_predictions(p,cases,expected,context='fixture')
        self.assertEqual(x['original_public_test_cases'],64)
        self.assertEqual(x['correct'],64)
        self.assertAlmostEqual(x['brier'],0.04)
        self.assertFalse(x['independent_hidden_test_labels'])
        self.assertFalse(x['chronological_future_utility'])

    def test_predictions_cannot_duplicate_cases(self):
        cases=m.validate_panel(self.panel)
        e1,e2,_=make_models(self.panel)
        pred=e2['arms']['from_zero']['predictions']
        pred[1]['case_id']=pred[0]['case_id']
        with self.assertRaises(m.Invalid):m.validate_predictions(pred,cases,set(x['case_id'] for x in self.panel['cases'] if x['split']!='train'),context='repeat')

    def test_nonfinite_or_out_of_bounds_score_refused(self):
        cases=m.validate_panel(self.panel)
        expected={cid for cid,c in cases.items() if c['split']!='train'}
        for bad in (float('nan'),float('inf'),-0.1,1.01,True,'0.5'):
            _,e2,_=make_models(self.panel)
            e2['arms']['from_zero']['predictions'][0]['positive_probability']=bad
            with self.subTest(value=str(bad)),self.assertRaises(m.Invalid):m.validate_predictions(e2['arms']['from_zero']['predictions'],cases,expected,context='bad score')

    def test_source_id_drift_with_rehashed_probability_denied(self):
        cases=m.validate_panel(self.panel)
        expected={cid for cid,c in cases.items() if c['split']!='train'}
        _,e2,_=make_models(self.panel)
        e2['arms']['from_zero']['predictions'][0]['joint_input_digest']='f'*64
        with self.assertRaises(m.Invalid):m.validate_predictions(e2['arms']['from_zero']['predictions'],cases,expected,context='changed source')

    def test_source_bound_two_model_receipt_is_non_authorizing(self):
        cases=m.validate_panel(self.panel)
        e1,e2,raw=make_models(self.panel)
        result=m.assess_model('granite_97m_r2',cases,e1,e2,raw)
        self.assertEqual(result['residual_arcs']['from_zero']['correct'],64)
        self.assertFalse(result['original_model_publisher_independently_authenticated'])
        self.assertFalse(result['original_encoder_recomputed_by_this_audit'])
        self.assertFalse(result['production_promotion_permitted'])
        self.assertEqual(result['authority'],'DENY_ALL')

    def test_wrong_or_missing_original_e1_e2_hash_rejected(self):
        cases=m.validate_panel(self.panel)
        e1,e2,raw=make_models(self.panel)
        e2['source_e1_report_sha256']='f'*64
        with self.assertRaises(m.Invalid):m.assess_model('granite_97m_r2',cases,e1,e2,raw)

    def test_learner_vs_original_baseline_prediction_mismatch_rejected(self):
        cases=m.validate_panel(self.panel)
        e1,e2,raw=make_models(self.panel)
        e2['arms']['from_zero']['predictions'][0]['positive_probability']+=0.02
        with self.assertRaises(m.Invalid):m.assess_model('granite_97m_r2',cases,e1,e2,raw)

    def test_oversized_residual_head_never_admitted(self):
        cases=m.validate_panel(self.panel)
        e1,e2,raw=make_models(self.panel)
        e2['arms']['residual_2k']['trainable_parameters']=4096
        with self.assertRaises(m.Invalid):m.assess_model('granite_97m_r2',cases,e1,e2,raw)

    def test_false_future_or_authorization_denied(self):
        cases=m.validate_panel(self.panel)
        for mutate in ('future_ndu_verified','production_promotion_permitted'):
            e1,e2,raw=make_models(self.panel)
            e1[mutate]=True
            with self.subTest(key=mutate),self.assertRaises(m.Invalid):m.assess_model('granite_97m_r2',cases,e1,e2,raw)

    def test_bad_original_untyped_json_rejected(self):
        for bad in (b'{"x":1,"x":2}',b'{"score":NaN}',b'{}{}'):
            with self.subTest(bad=bad),self.assertRaises((m.Invalid,ValueError)):m.strict_json(bad)

    def test_exact_historical_zip_rejects_repacked_bytes(self):
        with tempfile.TemporaryDirectory() as t:
            p=Path(t)/'repacked.zip'
            with zipfile.ZipFile(p,'w',zipfile.ZIP_DEFLATED) as z:
                for name in m.ORIGINAL_MEMBERS_SHA256:z.writestr(name,'fake data')
            with self.assertRaises(m.Invalid):m.strict_original_artifact(p)

    def test_all_original_zip_members_required(self):
        with tempfile.TemporaryDirectory() as t:
            p=Path(t)/'repacked.zip'
            with zipfile.ZipFile(p,'w',zipfile.ZIP_DEFLATED) as z:
                z.writestr('e1-public/panel.json','{}')
            with mock.patch.object(m,'ZIP_SHA256',m.sha(p.read_bytes())):
                with self.assertRaises(m.Invalid):m.strict_original_artifact(p)

    def test_forged_extra_or_duplicate_historical_member_refused(self):
        with tempfile.TemporaryDirectory() as t:
            p=Path(t)/'repacked.zip'
            with zipfile.ZipFile(p,'w',zipfile.ZIP_DEFLATED) as z:
                for name in m.ORIGINAL_MEMBERS_SHA256:z.writestr(name,'fake data')
                z.writestr('e1-public/panel.json','extra duplicate')
            with mock.patch.object(m,'ZIP_SHA256',m.sha(p.read_bytes())):
                with self.assertRaises(m.Invalid):m.strict_original_artifact(p)

    def test_cli_result_must_be_create_only(self):
        with tempfile.TemporaryDirectory() as t:
            out=Path(t)/'receipt.json'
            out.write_text('preexisting')
            with mock.patch('sys.argv',['audit','--original-run-zip','/not-present','--output',str(out)]):
                with self.assertRaises(FileExistsError):m.main()

if __name__=='__main__':unittest.main()
