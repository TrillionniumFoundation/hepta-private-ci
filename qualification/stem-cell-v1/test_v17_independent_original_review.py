"""V17 independently implemented audit contracts; fake fixtures are NOT model runs."""
import copy
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import v17_independent_original_review as v
import v17_source_focusing as g
from test_v17_source_focusing import Toy

class FakeTokenizer:
    def encode(self,x):return [101,123,456]
    def decode(self,ids):return 'zz' if ids==[5,6] else 'changed'


def fixture():
    toy=Toy();plan=toy.build();tok=FakeTokenizer();start=[];raw={}
    for rid,entry in sorted(plan['requests'].items()):
        token_ids=tok.encode(entry['prompt'])
        start.append({'request_id':rid,'plan_sha256':g.digest(plan),'input_ids_sha256':g.digest(token_ids),'input_tokens':len(token_ids)})
        raw[rid]={'case_id':entry['case_id'],'arm':entry['arm'],'source_ids':entry['source_ids'],
                  'answer_text':'zz','answer_sha256':g.htext('zz'),'output_ids':[5,6],
                  'input_tokens':len(token_ids),'output_tokens':2,'cpu_seconds':0.1}
    output={'schema':v.SCHEMA+'.original-physical-answers','plan_sha256':g.digest(plan),
            'model_sha256':v.READER_SHA,'tokenizer_sha256':v.TOKEN_SHA,'model_forwards':3*64,
            'requests':64,'raw_answers':raw,'independently_human_reviewed':False,
            'official_HF_parity':False,'reference_reader_executed':False,'production_authorized':False}
    return toy,plan,output,start,tok


class V17IndependentSourceAudit(unittest.TestCase):
    def test_valid_fixture_unverified(self):
        toy,plan,raw,starts,tok=fixture();out=v.audit(plan,toy.src,toy.parent,raw,starts,tok)
        self.assertEqual(out['exact_original_requests'],64)
        self.assertEqual(out['actual_model_forwards'],192)
        self.assertIsNone(out['human_semantic_correctness'])
        self.assertFalse(out['production_authorized'])
    def test_missing_answer(self):
        toy,plan,raw,starts,tok=fixture();raw['raw_answers'].pop(next(iter(raw['raw_answers'])))
        with self.assertRaises(ValueError):v.audit(plan,toy.src,toy.parent,raw,starts,tok)
    def test_missing_start(self):
        toy,plan,raw,starts,tok=fixture();starts.pop()
        with self.assertRaises(ValueError):v.audit(plan,toy.src,toy.parent,raw,starts,tok)
    def test_duplicate_start(self):
        toy,plan,raw,starts,tok=fixture();starts[0]=starts[1]
        with self.assertRaises(ValueError):v.audit(plan,toy.src,toy.parent,raw,starts,tok)
    def test_added_gold_in_plan(self):
        toy,plan,raw,starts,tok=fixture();plan['publisher_answer']='bad'
        with self.assertRaises(ValueError):v.audit(plan,toy.src,toy.parent,raw,starts,tok)
    def test_wrong_physical_lineage(self):
        toy,plan,raw,starts,tok=fixture();raw['model_sha256']='a'*64
        with self.assertRaises(ValueError):v.audit(plan,toy.src,toy.parent,raw,starts,tok)
    def test_forged_reference(self):
        toy,plan,raw,starts,tok=fixture();raw['reference_reader_executed']=True
        with self.assertRaises(ValueError):v.audit(plan,toy.src,toy.parent,raw,starts,tok)
    def test_wrong_forward_census(self):
        toy,plan,raw,starts,tok=fixture();raw['model_forwards']=191
        with self.assertRaises(ValueError):v.audit(plan,toy.src,toy.parent,raw,starts,tok)
    def test_answer_text_replaced(self):
        toy,plan,raw,starts,tok=fixture();rid=next(iter(raw['raw_answers']));raw['raw_answers'][rid]['answer_text']='forged'
        with self.assertRaises(ValueError):v.audit(plan,toy.src,toy.parent,raw,starts,tok)
    def test_answer_token_replaced(self):
        toy,plan,raw,starts,tok=fixture();rid=next(iter(raw['raw_answers']));raw['raw_answers'][rid]['output_ids']=[1,2]
        with self.assertRaises(ValueError):v.audit(plan,toy.src,toy.parent,raw,starts,tok)
    def test_input_token_substitution(self):
        toy,plan,raw,starts,tok=fixture();starts[0]['input_ids_sha256']='0'*64
        with self.assertRaises(ValueError):v.audit(plan,toy.src,toy.parent,raw,starts,tok)
    def test_semantic_false_claim(self):
        toy,plan,raw,starts,tok=fixture();raw['independently_human_reviewed']=True
        with self.assertRaises(ValueError):v.audit(plan,toy.src,toy.parent,raw,starts,tok)
    def test_original_model_numeric_profile_not_parity(self):
        toy,plan,raw,starts,tok=fixture();raw['official_HF_parity']=True
        with self.assertRaises(ValueError):v.audit(plan,toy.src,toy.parent,raw,starts,tok)
    def test_genuine_source_mutation(self):
        toy,plan,raw,starts,tok=fixture();toy.src['families']['conv-47']['passages'][0]['text']='shifted'
        with self.assertRaises(ValueError):v.audit(plan,toy.src,toy.parent,raw,starts,tok)
    def test_provenance_refs_still_null(self):
        toy,plan,raw,starts,tok=fixture()
        x=v.audit(plan,toy.src,toy.parent,raw,starts,tok)
        self.assertEqual(x['reference_reader_executed'],False)
        self.assertEqual(x['independent_future_calendar_windows'],0)
    def test_missing_label_owner_rejected(self):
        toy,plan,raw,starts,tok=fixture()
        with self.assertRaises(ValueError):v.audit(plan,toy.src,toy.parent,raw,starts,tok,original=[])
    def test_blind_seed_necessary(self):
        toy,plan,raw,starts,tok=fixture()
        with self.assertRaises(ValueError):v.blinded_review_packet(plan,toy.src,toy.parent,raw,{'plan_sha256':g.digest(toy.parent)},b'short')
    def test_blind_tickets_complete_and_no_labels(self):
        toy,plan,raw,starts,tok=fixture()
        base={'plan_sha256':g.digest(toy.parent),'raw_answers':{}}
        for c in toy.parent['cases']:
            wid=c['arms']['witness'].get('request_id')
            if wid is None:
                wid='parent-'+c['id']
                c['arms']['witness']['request_id']=wid
            base['raw_answers'][wid]={'answer_text':'zz'}
        base['plan_sha256']=g.digest(toy.parent)
        ticket,mapping=v.blinded_review_packet(plan,toy.src,toy.parent,raw,base,b'a'*32)
        self.assertEqual((len(ticket['tickets']),len(mapping)),(96,96))
        self.assertTrue(all('publisher_answer' not in str(x) for x in ticket['tickets']))
        self.assertFalse(ticket['human_verdicts_collected'])
        self.assertNotIn('arm',ticket['tickets'][0])
    def test_review_packet_focus_evidence_is_actual_span(self):
        toy,plan,raw,starts,tok=fixture()
        base={'plan_sha256':g.digest(toy.parent),'raw_answers':{}}
        for c in toy.parent['cases']:
            wid='parent-'+c['id'];c['arms']['witness']['request_id']=wid
            base['raw_answers'][wid]={'answer_text':'zz'}
        base['plan_sha256']=g.digest(toy.parent)
        packet,mapping=v.blinded_review_packet(plan,toy.src,toy.parent,raw,base,b'b'*32)
        by_ticket={p['ticket']:p for p in packet['tickets']}
        first=next(row for row in mapping if row['arm']=='formatted_focused')
        ticket=by_ticket[first['ticket']]
        orig_case=next(c for c in plan['cases'] if c['case_id']==first['case_id'])
        docs={p['id']:p['text'] for p in toy.src['families'][first['family']]['passages']}
        a,b=orig_case['focus_offsets']
        self.assertEqual(ticket['source_texts'][0],docs[orig_case['witness_id']][a:b])

if __name__=='__main__':unittest.main()
