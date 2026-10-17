"""Source-only micro fixtures; all pretrained forward operators are injected mocks."""
import copy
from contextlib import contextmanager
import hashlib
import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest import mock

import gate
import matched_head
import physical_feature_bank as fb


@contextmanager
def no_model_runtime(*args,**kwargs):
    yield Path('/nonexistent-test-original-weights')


class FakeModel:
    tensor_count = 447_458_496
    feature_width = 1024
    calls = 0
    def forward_one(self, view, max_tokens):
        self.calls += 1
        return [float(i%5)/5 for i in range(self.feature_width)], 22


def synthetic_case():
    splits=['fit','fit','cal','cal','test','test']
    samples=[];cases=[]
    for i,split in enumerate(splits):
        state=f'Original public evidence passage {i}: a signed report declares support.'
        question=f'Does the original report support statement {i}?'
        joint={'state':state,'question':question,'options':fb.OPTIONS.copy()}
        id=f'case-{i}'
        digest=hashlib.sha256(state.encode()).hexdigest()
        h=gate.digest(joint)
        cases.append({'case_id':id,'group_id':f'doc-{i}',
            'family_id':f'family-{i}','split':split,
            'source_sha256':digest,'input_sha256':h,'token_count':22})
        samples.append({'case_id':id,'source_sha256':digest,'input_sha256':h,**joint})
    panel={'schema':gate.SCHEMA,'source_revision':'f'*40,
           'source_material_sha256':'e'*64,'purpose':'binary-support-research-only',
           'budget':{'max_tokens':128,'head_steps':40,'head_trainable_params':matched_head.PARAMS,
                     'head_seed':41,'head_optimizer':'sgd-lr-0.1','precision':'float32'},
           'cases':cases,'authority':'DENY_ALL',
           'production_promotion_permitted':False,'future_window_verified':False}
    manifest={'schema':fb.SCHEMA,'panel_sha256':gate.digest(panel),
              'source_revision':panel['source_revision'],
              'source_material_sha256':panel['source_material_sha256'],
              'cases':samples,'authority':'DENY_ALL','production_authorized':False}
    return panel,manifest


def receipt(model):
    repo,revision,_,_=gate.MODELS[model]
    weights='pytorch_model.bin' if model=='ettin400' else 'model.safetensors'
    return {'model':model,'repo':repo,'revision':revision,
            'selected_source_inventory':[
                {'filename':weights,'is_weight':True,
                 'source_identity_type':'lfs_sha256','source_identity':'a'*64},
                {'filename':'tokenizer.json','is_weight':False,
                 'source_identity_type':'git_blob_sha1','source_identity':'b'*40}]}


class OriginalBankSourceGuards(unittest.TestCase):
    def test_panel_inputs_exact_and_label_blind(self):
        p,m=synthetic_case();self.assertEqual(len(fb.manifest_views(p,m)),6)
        self.assertNotIn('target',repr(m).lower())

    def test_reject_test_label_anywhere_in_input(self):
        p,m=synthetic_case();m['cases'][4]['label']=1
        with self.assertRaises(gate.Denied):fb.manifest_views(p,m)

    def test_reject_model_output_label_or_surplus_case(self):
        p,m=synthetic_case();m['cases'][0]['gold']=True
        with self.assertRaises(gate.Denied):fb.manifest_views(p,m)
        p,m=synthetic_case();m['cases'].append(m['cases'][0])
        with self.assertRaises(gate.Denied):fb.manifest_views(p,m)

    def test_reject_change_to_state_question_options(self):
        for field,altered in [('state','tampered evidence'),
                              ('question','Was an unrelated event reported?'),
                              ('options',['supported','not_supported'])]:
            p,m=synthetic_case();m['cases'][0][field]=altered
            with self.subTest(field=field),self.assertRaises(gate.Denied):
                fb.manifest_views(p,m)

    def test_reject_forged_view_hash_if_panel_differs(self):
        p,m=synthetic_case();m['cases'][0]['input_sha256']='a'*64
        with self.assertRaises(gate.Denied):fb.manifest_views(p,m)

    def test_reject_relabelled_source_group_in_panel(self):
        p,m=synthetic_case();p['cases'][0]['group_id']=p['cases'][1]['group_id']
        p['cases'][0]['source_sha256']=p['cases'][1]['source_sha256']
        with self.assertRaises(gate.Denied):fb.manifest_views(p,m)

    def test_reject_missing_source_revision_and_wrong_authority(self):
        for change in ({'source_revision':'0'*40},{'authority':'PERMIT'},
                       {'production_authorized':True}):
            p,m=synthetic_case();m.update(change)
            with self.assertRaises(gate.Denied):fb.manifest_views(p,m)

    def test_reject_oversized_state_and_very_short_question(self):
        p,m=synthetic_case();m['cases'][0]['state']='z'*10000
        with self.assertRaises(gate.Denied):fb.manifest_views(p,m)
        p,m=synthetic_case();m['cases'][0]['question']='?'
        with self.assertRaises(gate.Denied):fb.manifest_views(p,m)

    def test_reject_other_models_before_touching_weight_loader(self):
        p,m=synthetic_case()
        with self.assertRaises(gate.Denied):fb.make_bank('openjev434',p,m,{},Path('/no-weights'))

    def test_private_original_feature_bank_for_two_synthetic_drivers(self):
        for model in ('ettin400','laya421'):
            p,m=synthetic_case()
            f=FakeModel()
            f.tensor_count=fb.PINNED_ORIGINAL_TENSOR_COUNTS[model]
            with mock.patch.object(fb.physical_forward,'checked_receipt',return_value={
                    'source_sha256_receipt':'c'*64}),\
                 mock.patch.object(fb.runtime_snapshot,'isolated_verified_runtime',no_model_runtime),\
                 mock.patch.object(fb,'_load_real_encoder',return_value=f):
                bank,cost=fb.make_bank(model,p,m,receipt(model),Path('/no-weights'))
            matched_head.validate_bank(p,bank)
            self.assertEqual(f.calls,len(p['cases']))
            self.assertEqual(cost['actual_encoder_forwards_observed'],6)
            self.assertEqual(bank['encoder_output_dimension'],1024)
            self.assertFalse(bank['production_authorized'])
            self.assertEqual(bank['rows'][0]['input_sha256'],p['cases'][0]['input_sha256'])
            self.assertNotIn('state',repr(bank))

    def test_fail_closed_before_real_model_import_when_source_review_fails(self):
        p,m=synthetic_case()
        with mock.patch.object(fb.physical_forward,'checked_receipt',side_effect=gate.Denied('wrong original model')):
            with self.assertRaises(gate.Denied):fb.make_bank('ettin400',p,m,receipt('ettin400'),Path('/none'))

    def test_writer_requires_create_new_destination(self):
        with TemporaryDirectory() as td:
            f=Path(td)/'bank.json';f.write_bytes(b'existing')
            with self.assertRaises(gate.Denied):fb._save_once(f,{'authority':'DENY_ALL'})
            self.assertEqual(f.read_bytes(),b'existing')
            n=Path(td)/'new.json';fb._save_once(n,{'authority':'DENY_ALL'})
            self.assertEqual(n.stat().st_mode & 0o777,0o600)

if __name__=='__main__':unittest.main()
