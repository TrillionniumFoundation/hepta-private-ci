"""Hermetic safety/functional controls. Real original material tested separately."""
from __future__ import annotations
import copy
import json
import math
import os
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch

import g6_coverage_source as source
import g6_coverage_model as model
import g6_independent_review as reviewer


def fake_packet():
    roots=[]
    for name in sorted(source.TRAIN + source.HELD):
        train=name in source.TRAIN
        documents=[]
        for i in range(256 if train else 320):
            text=f'Speaker: synthetic story with id {name} {i} about fruit.'
            documents.append({'id':f'D1:{i}', 'text':text,'text_sha':source.sha(text.encode())})
        questions=[]
        for i in range(24):
            text=f'What fruit is documented by {name} at position {i}?'
            row={'id':f'q{i}','text':text,'text_sha':source.sha(text.encode())}
            if train:row['train_support']=[f'D1:{i}']
            questions.append(row)
        roots.append({'root':name,'split':'TRAIN' if train else 'HELD',
                      'docs':documents,'questions':questions})
    packet={'schema':source.SCHEMA,'original_sha':source.CHECKSUMS['locomo.json'],
            'model_sha':source.CHECKSUMS['encoder/model.safetensors'],
            'original_g5_packet_digest':source.sha(b'original-g5-plan-fixture'),
            'train_documents_per_root':256,'candidate_documents':'all_held_original_dialogues',
            'questions_per_root':24,'rerank_shortlist':64,'roots':roots,
            'research_only':True,'production_authorized':False,'disposition':'HOLD_NO_GO'}
    packet['digest']=source.sha(source.DOMAIN+source.canonical(packet))
    return packet


class G6HermeticTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.packet=fake_packet()

    def test_explicit_held_label_absence(self):
        p=copy.deepcopy(self.packet)
        with patch.dict(source.CHECKSUMS,{'locomo.json':p['original_sha'],
                                           'encoder/model.safetensors':p['model_sha']}):
            source.validate(p)
            held=next(x for x in p['roots'] if x['split']=='HELD')
            self.assertTrue(all(set(q)=={'id','text','text_sha'} for q in held['questions']))

    def test_held_label_insertion_rejected_after_resigning(self):
        p=copy.deepcopy(self.packet)
        p['roots'][-1]['questions'][0]['evidence']=['D1:1']
        p['digest']=source.sha(source.DOMAIN+source.canonical({k:v for k,v in p.items() if k!='digest'}))
        with patch.dict(source.CHECKSUMS,{'locomo.json':p['original_sha'],
                                           'encoder/model.safetensors':p['model_sha']}):
            with self.assertRaisesRegex(ValueError,'HELD gold'):
                source.validate(p)

    def test_authority_forgery_rejected_after_resigning(self):
        p=copy.deepcopy(self.packet)
        p['production_authorized']=True
        p['digest']=source.sha(source.DOMAIN+source.canonical({k:v for k,v in p.items() if k!='digest'}))
        with self.assertRaises(ValueError):source.validate(p)

    def test_source_hash_mutation_rejected(self):
        p=copy.deepcopy(self.packet)
        p['roots'][2]['docs'][1]['text']='altered'
        p['digest']=source.sha(source.DOMAIN+source.canonical({k:v for k,v in p.items() if k!='digest'}))
        with patch.dict(source.CHECKSUMS,{'locomo.json':p['original_sha'],
                                           'encoder/model.safetensors':p['model_sha']}):
            with self.assertRaisesRegex(ValueError,'doc source identity'):
                source.validate(p)

    def test_missing_full_document_group_rejected(self):
        p=copy.deepcopy(self.packet)
        p['roots'][-1]['docs']=p['roots'][-1]['docs'][:256]
        p['digest']=source.sha(source.DOMAIN+source.canonical({k:v for k,v in p.items() if k!='digest'}))
        with patch.dict(source.CHECKSUMS,{'locomo.json':p['original_sha'],
                                           'encoder/model.safetensors':p['model_sha']}):
            with self.assertRaises(ValueError):source.validate(p)

    def test_model_ingress_gold_rejected_without_torch(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);(root/'locomo.json').write_text('fake raw answers')
            with self.assertRaisesRegex(ValueError,'held publisher'):
                model.run(root,self.packet)

    def test_canonical_source_parser_refuses_duplicate(self):
        with self.assertRaisesRegex(ValueError,'duplicate'):
            json.loads('{"x":1,"x":2}',object_pairs_hook=source.strict_pairs)

    def test_full_transcript_duplicate_dia_id_rejected(self):
        doc={'dia_id':'D1:4','speaker':'Alice','text':'hello there'}
        record={'conversation':{'session_1':[doc,doc]}}
        with self.assertRaisesRegex(ValueError,'duplicate source'):
            source.full_docs(record)

    def test_tie_break_is_source_id_in_bm25(self):
        docs=[{'id':'D1:3','text':'apples'},{'id':'D1:2','text':'apples'},
              {'id':'D1:1','text':'bananas'}]
        queries=[{'text':'apples'},{'text':'plums'}]
        ranked,work=model.bm25_all(docs,queries)
        self.assertEqual(work,6)
        self.assertEqual([docs[i]['id'] for i in ranked[0]][:2],['D1:2','D1:3'])
        self.assertEqual([docs[i]['id'] for i in ranked[1]],['D1:1','D1:2','D1:3'])

    def test_independent_bm25_matches_native(self):
        docs=[{'id':f'D1:{i}', 'text':'red apple '+('blue' if i%3==0 else 'orange')}
              for i in range(70)]
        qs=[{'text':'red apple blue'},{'text':'orange blue unknown'},{'text':'nonexistent'}]
        a,_=model.bm25_all(docs,qs)
        b=reviewer.independent_bm25(docs,qs)
        self.assertEqual([[docs[i]['id'] for i in x] for x in a],b)

    def test_hash_seed_independence_cross_process(self):
        code=("import json;from g6_coverage_model import bm25_all;"
              "d=[{'id':str(i),'text':'apple banana '+str(i)} for i in range(70)];"
              "q=[{'text':'apple banana'}];"
              "print(json.dumps(bm25_all(d,q)[0][0]))")
        env=os.environ.copy()
        out=[]
        for seed in ('1','20'):
            env['PYTHONHASHSEED']=seed
            a=subprocess.check_output([sys.executable,'-S','-c',code],env=env,text=True,timeout=20)
            out.append(a)
        self.assertEqual(out[0],out[1])

    def test_reviewer_rejects_unknown_original(self):
        with self.assertRaisesRegex(ValueError,'publisher original'):
            reviewer.independent_rebuild(b'not a matching original source')

    def test_top64_partition_and_output_cardinality(self):
        base=list(range(100));short=base[:64]
        arm=model.merge_ranks(base,short,[float(i) for i in range(64)],
                              [float(-i) for i in range(64)],[0.0]*64)
        self.assertEqual(set(arm),set(source.SCORES))
        self.assertEqual(arm['bm25_full'],base)
        self.assertEqual(arm['rank8_64'],base)
        self.assertEqual(arm['sham_64'],base)
        for v in arm.values():
            self.assertEqual(len(v),100)
            self.assertEqual(set(v[:64]),set(short))
            self.assertEqual(v[64:],base[64:])

    def test_incompatible_shortlist_denied(self):
        with self.assertRaises(ValueError):
            model.merge_ranks(list(range(100)),list(range(1,65)),[0.]*64,[0.]*64,[0.]*64)

    def test_nonfinite_head_scores_denied(self):
        with self.assertRaises(ValueError):
            model.merge_ranks(list(range(100)),list(range(64)),[0.]*64,[float('nan')]*64,[0.]*64)

    def test_real_original_optional(self):
        raw=os.environ.get('HDSI_G6_ORIGINAL')
        packet=os.environ.get('HDSI_G6_SOURCE')
        preds=os.environ.get('HDSI_G6_PREDICTIONS')
        if not all([raw,packet,preds]):
            self.skipTest('original SHA-pinned pretrained/scored source material not supplied')
        res=reviewer.independently_score(Path(raw).read_bytes(),
                json.loads(Path(packet).read_text()),json.loads(Path(preds).read_text()))
        self.assertEqual(res['denominator'],96)
        self.assertEqual(res['disposition'],'HOLD_NO_GO')
        self.assertTrue(res['model_free_independent_reconstruction'])


if __name__=='__main__':
    unittest.main()
