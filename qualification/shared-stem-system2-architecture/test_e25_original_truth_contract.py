"""Synthetic geometry/human-label fixtures solely for E25 scorer fault testing.

NO new pretrained forward and NO original new-six human task score in this file.
"""
from __future__ import annotations

from copy import deepcopy
from hashlib import sha256
import json
import os
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

from e25_fixed_policy_transfer import frozen,propose,source_json
from e25_independent_score import truth_from_parquet,review,independently_predictions
from test_e25_frozen_panel import synthetic_six,ORIGINAL,POLICY


def synthetic_parquet_and_slate():
    audit,source,slate,owner=synthetic_six()
    rows=[];labels={}
    for i,group in enumerate(slate['rows']):
        pid=i+900
        paragraph=f'Independent FAKE passage {i}; this is a TEST fixture'
        pd=sha256(json.dumps(paragraph,sort_keys=True,separators=(',',':')).encode()).hexdigest()
        sourceid=sha256(f'validation:passage:{pid}:{pd}'.encode()).hexdigest()[:32]
        previous=group['source_group']
        group['source_group']=sourceid;group['evidence']=paragraph
        for qid,q in enumerate(group['questions']):
            q['question']=f'SYNTHETIC question {i}-{qid}'
            for v,c in enumerate(q['candidates']):
                aid=v
                task=sha256(f'{sourceid}:q{qid}:a{aid}'.encode()).hexdigest()[:32]
                c['task_id']=task;c['candidate_id']=aid
                c['answer']=f'SYNTHETIC candidate {i}-{qid}-{v}'
                rows.append({'idx':{'paragraph':pid,'question':qid,'answer':aid},
                             'paragraph':paragraph,'question':q['question'],
                             'answer':c['answer'],'label':v})
                labels[task]=v
            q['original_task_id']=q['candidates'][0]['task_id']
        for j,rec in enumerate(audit['rows']):
            if rec['source_group']==previous:
                q=rec['question_slot'];v=rec['candidate_id']
                new=group['questions'][q]['candidates'][v]
                rec['source_group']=sourceid;rec['task_id']=new['task_id']
                for arm in audit['predictions']:
                    audit['predictions'][arm][j]['source_group']=sourceid
                    audit['predictions'][arm][j]['task_id']=new['task_id']
    source['new_source_groups']=[p['source_group'] for p in slate['rows']]
    source['eligible_unused_group_set_sha256']=sha256(
        json.dumps(sorted(source['new_source_groups']),separators=(',',':')).encode()).hexdigest()
    ownerlabels={'schema':'hepta.multirc.candidate-slate-owner-labels.v1',
                 'slate_id':slate['slate_id'],'external_observer_authenticated':False,
                 'labels':labels}
    return audit,source,slate,owner,rows,ownerlabels


class FakeArrow:
    def __init__(self,records):self.records=records
    def read_table(self,pathname,columns):
        if set(columns)!={'paragraph','question','answer','label','idx'}:
            raise ValueError('test source column change')
        return types.SimpleNamespace(to_pylist=lambda:deepcopy(self.records))


class TruthSeparationTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not Path(ORIGINAL).is_file():
            raise RuntimeError('genuine historic original ZIP required')
        cls.config=frozen(POLICY)

    def src(self,records):
        parent=types.ModuleType('pyarrow');parent.__path__=[]
        child=types.ModuleType('pyarrow.parquet')
        child.read_table=FakeArrow(records).read_table
        parent.parquet=child
        return {'pyarrow':parent,'pyarrow.parquet':child}

    def test_independently_reconstruct_all_synthetic_label_ids(self):
        audit,source,slate,owner,rows,labels=synthetic_parquet_and_slate()
        with tempfile.TemporaryDirectory() as td:
            p=Path(td)/'fake-test.parquet';p.write_bytes(b'FAKE SOURCE TEST ONLY')
            with patch.dict(sys.modules,self.src(rows)),patch('e25_independent_score.VAL_SHA',sha256(p.read_bytes()).hexdigest()):
                out=truth_from_parquet(str(p),slate,labels)
                self.assertEqual(out,labels['labels'])
                self.assertEqual(len(out),24)

    def test_scorer_rejects_changed_true_label_even_if_source_rehashed(self):
        audit,source,slate,owner,rows,labels=synthetic_parquet_and_slate()
        changed=deepcopy(rows);changed[0]['label']^=1
        with tempfile.TemporaryDirectory() as td:
            p=Path(td)/'fake-test.parquet';p.write_bytes(b'FAKE SOURCE TEST ONLY')
            with patch.dict(sys.modules,self.src(changed)),patch('e25_independent_score.VAL_SHA',sha256(p.read_bytes()).hexdigest()):
                with self.assertRaises(ValueError):truth_from_parquet(str(p),slate,labels)

    def test_missing_held_original_candidate_label_fails(self):
        audit,source,slate,owner,rows,labels=synthetic_parquet_and_slate()
        with tempfile.TemporaryDirectory() as td:
            p=Path(td)/'fake-test.parquet';p.write_bytes(b'FAKE SOURCE TEST ONLY')
            with patch.dict(sys.modules,self.src(rows[:-1])),patch('e25_independent_score.VAL_SHA',sha256(p.read_bytes()).hexdigest()):
                with self.assertRaises(ValueError):truth_from_parquet(str(p),slate,labels)

    def test_unlisted_real_candidate_in_selected_question_is_rejected(self):
        audit,source,slate,owner,rows,labels=synthetic_parquet_and_slate()
        more=deepcopy(rows)
        addition=deepcopy(rows[0])
        addition['idx']['answer']=2
        addition['answer']='EXTRA genuine candidate never included in proposed slate'
        addition['label']=1
        more.append(addition)
        with tempfile.TemporaryDirectory() as td:
            p=Path(td)/'fake-test.parquet';p.write_bytes(b'FAKE SOURCE TEST ONLY')
            with patch.dict(sys.modules,self.src(more)),patch('e25_independent_score.VAL_SHA',sha256(p.read_bytes()).hexdigest()):
                with self.assertRaisesRegex(ValueError,'omitted or duplicate genuine answer'):
                    truth_from_parquet(str(p),slate,labels)

    def test_independent_all_candidate_numeric_replay_on_synthetic_new_groups(self):
        audit,source,slate,owner,rows,labels=synthetic_parquet_and_slate()
        result=propose(audit,source,slate,owner,self.config,ORIGINAL)
        numeric=independently_predictions(audit,slate,self.config)
        for item in result['rows']:
            for name,prob in item['probabilities'].items():
                self.assertAlmostEqual(prob,numeric[item['task_id']][name],delta=1e-12)

    def test_full_original_human_scorer_contract_on_explicitly_FAKE_labels(self):
        audit,source,slate,owner,rows,labels=synthetic_parquet_and_slate()
        result=propose(audit,source,slate,owner,self.config,ORIGINAL)
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);p=root/'fake-test.parquet';p.write_bytes(b'FAKE SOURCE TEST ONLY')
            blind=root/'predictions.json';blind.write_text(json.dumps(result,sort_keys=True))
            aud=root/'audit.json';aud.write_text(json.dumps(audit,sort_keys=True))
            slate_p=root/'slate.json';slate_p.write_text(json.dumps(slate,sort_keys=True))
            owner_p=root/'owner.json';owner_p.write_text(json.dumps(labels,sort_keys=True))
            with patch.dict(sys.modules,self.src(rows)),patch('e25_independent_score.VAL_SHA',sha256(p.read_bytes()).hexdigest()):
                rec=review(str(blind),sha256(blind.read_bytes()).hexdigest(),
                  str(aud),str(slate_p),POLICY,str(owner_p),str(p))
                self.assertEqual(rec['new_holdout_passages'],6)
                self.assertEqual(rec['methods']['mean_pool_query_fused']['total_questions'],12)
                self.assertFalse(rec['production_accepted'])
                self.assertFalse(rec['statistical_superiority_established'])

    def test_held_human_score_denies_mismatched_prelabel_source_census(self):
        audit,source,slate,owner,rows,labels=synthetic_parquet_and_slate()
        result=propose(audit,source,slate,owner,self.config,ORIGINAL)
        result['eligible_unused_group_set_sha256']='0'*64
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);parquet=root/'fake-test.parquet'
            parquet.write_bytes(b'FAKE SOURCE TEST ONLY')
            def dump(name,value):
                path=root/name
                path.write_text(json.dumps(value,sort_keys=True))
                return path
            blind=dump('blind.json',result)
            stored_audit=dump('audit.json',audit)
            stored_slate=dump('slate.json',slate)
            owner_labels=dump('owner.json',labels)
            with patch.dict(sys.modules,self.src(rows)),patch(
                'e25_independent_score.VAL_SHA',sha256(parquet.read_bytes()).hexdigest()
            ):
                with self.assertRaisesRegex(ValueError,'physical source or authority'):
                    review(str(blind),sha256(blind.read_bytes()).hexdigest(),
                           str(stored_audit),str(stored_slate),POLICY,
                           str(owner_labels),str(parquet))

    def test_forged_blind_probability_rejected_by_independent_math(self):
        audit,source,slate,owner,rows,labels=synthetic_parquet_and_slate()
        result=propose(audit,source,slate,owner,self.config,ORIGINAL)
        result['rows'][0]['probabilities']['question_softworst_tau_001']+=.05
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);p=root/'fake-test.parquet';p.write_bytes(b'FAKE SOURCE TEST ONLY')
            blind=root/'predictions.json';blind.write_text(json.dumps(result,sort_keys=True))
            aud=root/'audit.json';aud.write_text(json.dumps(audit,sort_keys=True))
            slate_p=root/'slate.json';slate_p.write_text(json.dumps(slate,sort_keys=True))
            owner_p=root/'owner.json';owner_p.write_text(json.dumps(labels,sort_keys=True))
            with patch.dict(sys.modules,self.src(rows)),patch('e25_independent_score.VAL_SHA',sha256(p.read_bytes()).hexdigest()):
                with self.assertRaises(ValueError):review(str(blind),sha256(blind.read_bytes()).hexdigest(),
                  str(aud),str(slate_p),POLICY,str(owner_p),str(p))

if __name__=='__main__':unittest.main()
