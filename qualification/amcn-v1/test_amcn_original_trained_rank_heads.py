"""Research-only CPU physical scalar rank-Head controls and tamper refusals.

Synthetic fixtures here are explicitly NOT source/model task success. An
independent optional original-source material test requires local pinned data.
"""
from __future__ import annotations
from copy import deepcopy
from hashlib import sha256
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import numpy as np
import torch
from safetensors.torch import save_file

import amcn_original_trained_rank_heads as e


def q(case_id='conv-26:0',family='conv-26',split='train',question='When was it?'):
    return {'case_id':case_id,'family':family,'split':split,'question':question,
            'question_sha256':sha256(question.encode()).hexdigest()}


def ranking():
    b=[f'D1:{i}' for i in range(1,17)]
    d=[f'D1:{i}' for i in range(9,25)]
    return {'ranked_source_ids':{'bm25':b,'dense_original_minilm':d,
                                 'bm25_dense_half':b,'rrf_60':b}}


class RankHeadContracts(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        torch.set_num_threads(1)

    def test_query_type_from_question_only(self):
        self.assertEqual(e.typename('When did they visit?'),'episodic')
        self.assertEqual(e.typename('How long ago?'),'episodic')
        self.assertEqual(e.typename('What hobbies were mentioned?'),'semantic')

    def test_original_top16_is_unmodified_frozen_control(self):
        ids,x,mask=e.candidates(q(),ranking())
        self.assertEqual(len(ids),24)
        self.assertEqual(int(mask.sum()),24)
        self.assertEqual(ids[:16],ranking()['ranked_source_ids']['bm25'])
        self.assertEqual(x.shape,(32,3))
        self.assertEqual(list(x[0]),[1.,0.,0.])
        self.assertEqual(float(x[8,2]),1.)
        self.assertTrue(np.all(x[24:]==0))

    def test_nonadmitted_label_identity_fails(self):
        for s in ('D0:evil','../bad','D:7','D7:0x123'):
            with self.assertRaises(ValueError):e.normalize_source(s)
        self.assertEqual(e.normalize_source('D7:00012'),'D7:12')

    def test_no_original_publisher_field_in_feature_input(self):
        cases=[(q(),ranking())]
        x=e.build_features(cases)
        self.assertNotIn('y',x[0])
        self.assertNotIn('publisher_support',str(x))

    def test_training_labels_only_cause_train_row_labels(self):
        rows=[(q(),ranking()),(q('conv-50:1','conv-50','retrospective_heldout_b'),ranking())]
        train_labels={'conv-26:0':{'publisher_support':['D1:9']}}
        out=e.build_features(rows,train_labels)
        self.assertEqual(float(out[0]['y'].sum()),1.)
        self.assertEqual(int(out[0]['train_has_positive_in_union']),1)
        self.assertNotIn('y',out[1])

    def test_real_cpu_adamw_update_and_equal_work(self):
        rng=np.random.default_rng(7)
        rows=[]
        for i in range(36):
            f=rng.uniform(0,1,size=(32,3)).astype(np.float32)
            support=np.zeros(32,dtype=np.float32)
            support[(i*5)%24]=1.
            rows.append({'family':f'root{i%6}','x':f,'y':support,
                         'mask':np.array([True]*24+[False]*8),
                         'memory_type':e.TYPES[i%2]})
        h,r=e.train_model(rows,kind='semantic',seed=12,steps=12,batch_size=7)
        self.assertEqual(r['trained_parameter_count'],3)
        self.assertEqual(r['steps'],12)
        self.assertEqual(r['minibatch_examples'],84)
        self.assertNotEqual(r['learned_fp32_weights'],[1.,0.,0.])
        h2,r2=e.train_model(rows,kind='semantic',seed=12,steps=12,batch_size=7)
        self.assertEqual(r['learned_fp32_weights'],r2['learned_fp32_weights'])
        other,wrong=e.train_model(rows,kind='semantic',seed=12,steps=12,
                                  batch_size=7,permute_labels=True)
        self.assertNotEqual(r['learned_fp32_weights'],wrong['learned_fp32_weights'])
        self.assertEqual(r['minibatch_examples'],wrong['minibatch_examples'])

    def test_original_weak_census_is_read_only(self):
        self.assertEqual(e.SOURCE_SHA,'ac5f95085e5b223f81e888236e2c162f1ef45a3d1f52ad3e903fde48a629a633')
        self.assertEqual(e.RANK_SHA,'25bd9754e1da4ee5ddf620e7f3c734f06650568278c6aab51916d55046baef99')
        self.assertEqual(e.GOLD_SHA,'758d951c2fb296c3ba23ef539e3f243fb8464d52ed0d42c8d0981943ac907a06')
        self.assertEqual(e.TYPES,('episodic','semantic'))
        self.assertEqual(len(e.BANKS),3)

    def test_invalid_source_frozen_rank_fails_closed(self):
        bad=ranking()
        bad['ranked_source_ids']['bm25'][0]='D99:99'
        with self.assertRaises(ValueError):
            with patch.object(e,'pinned',side_effect=[
                {'publisher_targets_not_included':True,'production_accepted':False,
                 'cases':[q()], 'source_families':{'conv-26':[{'id':f'D1:{j}'} for j in range(1,25)]}},
                {'training_or_publisher_gold_accessed':False,
                 'real_original_pretrained_forward':True,
                 'official_hf_tokenizer_model_parity_proven':False,
                 'case_predictions':[{'case_id':'conv-26:0','family':'conv-26',
                   'split':'train','question_sha256':q()['question_sha256'],
                   'ranked_source_ids':bad}]}]):
                e.load_source_and_rank('ignored',e.SOURCE_SHA,'ignored',e.RANK_SHA)

    def test_create_only_and_external_hash_pins(self):
        with tempfile.TemporaryDirectory() as d:
            f=Path(d)/'file.json'
            sha=e.write_new(f,{'x':1})
            self.assertEqual(e.pinned(f,sha),{'x':1})
            with self.assertRaisesRegex(ValueError,'overwrite'):
                e.write_new(f,{'x':2})
            with self.assertRaisesRegex(ValueError,'SHA'):
                e.pinned(f,'f'*64)

    def test_duplicate_json_member_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            f=Path(d)/'bad.json';f.write_text('{"a":1,"a":2}')
            with self.assertRaisesRegex(ValueError,'duplicate JSON'):
                e.pinned(f,e.file_sha(f))

    def test_untrusted_head_tensor_sha_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            base=Path(d)
            entries={}
            for kind in e.TYPES:
                for bank in e.BANKS:
                    name=f'{bank}__{kind}'
                    f=base/(name+'.safetensors')
                    save_file({'weight':torch.tensor([[1.,0.,0.]])},str(f))
                    entries[name]={'file':f.name,'sha256':e.file_sha(f),
                                   'train_receipt':{'steps':3}}
            manifest={'schema':e.PROFILE+'.physically-trained-two-head-banks.v1',
                      'source_sha256':e.SOURCE_SHA,'rank_sha256':e.RANK_SHA,
                      'types':list(e.TYPES),'entries':entries,'production_accepted':False,
                      'real_physical_cpu_torch_adamw_training':True}
            sha=e.write_new(base/'manifest.json',manifest)
            h,m=e.physically_reload(base,sha,e.SOURCE_SHA,e.RANK_SHA)
            self.assertEqual(len(h),6)
            one=base/'typed_equal_budget__episodic.safetensors'
            with one.open('ab') as f:f.write(b'1')
            with self.assertRaisesRegex(ValueError,'tampered'):
                e.physically_reload(base,sha,e.SOURCE_SHA,e.RANK_SHA)

    @unittest.skipUnless(os.getenv('HEPTA_AMCN_ORIGINAL_RANK_ROOT'),
                         'original 1,986-case material required; synthetic-only hosted lane')
    def test_original_full_physical_predictions_match_reloaded_tensors(self):
        root=Path(os.environ['HEPTA_AMCN_ORIGINAL_RANK_ROOT'])
        bank=root/'physical_banks'
        source=root/'public-sources-only.json'
        ranked=root/'ten-family-real-original-minilm-rank.json'
        pred=root/'sealed_heldout_predictions_recounted.json'
        gold=root/'withheld-publisher-weak-labels.json'
        original=e.load_source_and_rank(source,e.SOURCE_SHA,ranked,e.RANK_SHA)
        labels=e.pinned(gold,e.GOLD_SHA)
        manifest=e.file_sha(bank/'manifest.json')
        observations=e.pinned(pred,e.file_sha(pred))
        self.assertEqual(e.verify_original_predictions(
            original,bank,manifest,observations['complete_predictions'],e.SOURCE_SHA,e.RANK_SHA),3316)
        self.assertEqual(len({r['family'] for c,r in original if c['split'].startswith('retrospective')}),2)


if __name__=='__main__':unittest.main()
