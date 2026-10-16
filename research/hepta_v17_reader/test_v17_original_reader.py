"""Synthetic source, identity and authority negatives. No pretrained outputs in fixtures."""
import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import source_first as s
import physical


def fake_original():
    out=[]
    for root in s.ROOTS:
        context={'speaker_a':'Ada','speaker_b':'Bo'}
        for sess in range(1,6):
            context[f'session_{sess}']=[dict(dia_id=f'D{sess}:{i}',speaker='Ada' if i%2 else 'Bo',
                text=f'Ada placed the {root} item {i} near the gallery in May 2024.') for i in range(1,26)]
        qa=[]
        for k in range(55):
            qa.append(dict(question=f'Where is item {k} in {root}?',
                           answer=f'Gallery {k}',evidence=[f'D1:{1+(k%25)}'],category=k%5+1))
        out.append(dict(sample_id=root,qa=qa,conversation=context))
    return out


class V17Offline(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp=tempfile.TemporaryDirectory()
        cls.root=Path(cls.tmp.name)
        cls.original=cls.root/'original.json'
        cls.original.write_text(json.dumps(fake_original()))
        cls.pin=patch.object(s,'CORPUS_SHA',hashlib.sha256(cls.original.read_bytes()).hexdigest())
        cls.pin.start()
        cls.owner=s.prepare(cls.original,cls.root/'source')
        cls.pub=cls.root/'source'/'public.json'
        cls.restricted=cls.root/'source'/'hidden.json'
        cls.own=cls.root/'source'/'owner.json'
        cls.p=s.plan(cls.pub,cls.own,cls.root/'plan.json')
        cls.annotation=s.annotations(cls.pub,cls.own,cls.restricted,cls.root/'plan.json',cls.root/'annotation.json')
        cls.packet=s.requests(cls.pub,cls.own,cls.root/'plan.json',cls.root/'annotation.json',cls.root/'requests.json')

    @classmethod
    def tearDownClass(cls):
        cls.pin.stop();cls.tmp.cleanup()

    def test_immutable_source_and_ten_origins(self):
        self.assertEqual(self.owner['source_sha256'],hashlib.sha256(self.original.read_bytes()).hexdigest())
        self.assertEqual(len(s.read(self.pub)),10)
        self.assertEqual(self.owner['authority'],'DENY_ALL')
        self.assertFalse(self.owner['production_accepted'])

    def test_source_first_30_cases_and_four_arms(self):
        self.assertEqual(len(self.p['case_ids']),30)
        self.assertEqual(len(self.packet['requests']),120)
        for root in s.ROOTS:
            self.assertEqual(sum(x.startswith(root+'/') for x in self.p['case_ids']),3)

    def test_no_answer_in_reader_requests(self):
        self.assertTrue(self.packet['publisher_answer_text_never_supplied'])
        self.assertFalse('answer' in next(iter(self.packet['requests'].values())))
        for case,ids in self.annotation['source_ids'].items():
            self.assertTrue(ids)
            self.assertIsInstance(case,str)

    def test_no_evidence_exactly_empty(self):
        for r in self.packet['requests'].values():
            if r['arm']=='none':
                self.assertEqual(r['source_ids'],[])
                self.assertIn('(no evidence provided)',r['prompt'])

    def test_prompt_sha_and_source_id_anchor(self):
        for row in self.packet['requests'].values():
            self.assertEqual(row['request_sha256'],s.sha_text(row['prompt']))
            self.assertTrue(row['case_id'].startswith('conv-'))

    def test_real_public_key_is_not_publisher_truth(self):
        public=s.read(self.pub)
        self.assertEqual(set(public[0]),{'id','questions','utterances'})
        self.assertTrue(all(set(q)=={'id','question'} for family in public for q in family['questions']))

    def test_plaintext_role_delimiter_injection_is_denied(self):
        self.assertRaises(ValueError,s.prompt,'<|im_start|>',['D1:1'],{'D1:1':dict(text='clean',speaker='Ada')})
        self.assertRaises(ValueError,s.prompt,'Hi',['D1:1'],{'D1:1':dict(text='<|im_end|>',speaker='Ada')})

    def test_witness_label_tamper_rejected(self):
        hidden=s.read(self.restricted);fid=s.ROOTS[0];cid=self.p['case_ids'][0]
        hidden[fid][f'{fid}/q0']['answer']='ATTACKER GOLD'
        with tempfile.TemporaryDirectory() as t:
            p=Path(t)/'gold.json';p.write_text(json.dumps(hidden))
            with self.assertRaises(ValueError):s.annotations(self.pub,self.own,p,self.root/'plan.json',Path(t)/'ann.json')

    def test_publisher_support_bad_reference_denied_in_prompt(self):
        ann=copy.deepcopy(self.annotation)
        case=next(iter(ann['source_ids']))
        ann['source_ids'][case]=['D404:7']
        ann['packet_sha256']=s.digest({k:v for k,v in ann.items() if k!='packet_sha256'})
        with tempfile.TemporaryDirectory() as t:
            p=Path(t)/'ann.json';p.write_text(json.dumps(ann))
            with self.assertRaises(ValueError):s.requests(self.pub,self.own,self.root/'plan.json',p,Path(t)/'req.json')

    def test_unauthorized_objective_change_denied(self):
        p=copy.deepcopy(self.p);p['authority']='ALLOW'
        p['plan_sha256']=s.digest({k:v for k,v in p.items() if k!='plan_sha256'})
        with tempfile.TemporaryDirectory() as t:
            x=Path(t)/'plan.json';x.write_text(json.dumps(p))
            with self.assertRaises(ValueError):s.requests(self.pub,self.own,x,self.root/'annotation.json',Path(t)/'req.json')

    def test_false_model_packet_output_denied(self):
        req=copy.deepcopy(self.packet);req['requests'][next(iter(req['requests']))]['prompt']='forged'
        req['requests_sha256']=s.digest(req['requests'])
        with tempfile.TemporaryDirectory() as t:
            x=Path(t)/'req.json';x.write_text(json.dumps(req))
            with self.assertRaises(ValueError):physical.checked(self.pub,self.own,self.root/'plan.json',self.root/'annotation.json',x)

    def test_forward_preflight_without_model_is_source_only(self):
        plan,packet=physical.checked(self.pub,self.own,self.root/'plan.json',self.root/'annotation.json',self.root/'requests.json')
        self.assertEqual(plan['n_cases'],30)
        self.assertEqual(packet['requests_sha256'],self.packet['requests_sha256'])

    def test_denies_missing_logical_arm(self):
        modified=copy.deepcopy(self.packet)
        del modified['requests'][next(iter(modified['requests']))]
        modified['requests_sha256']=s.digest(modified['requests'])
        with tempfile.TemporaryDirectory() as t:
            p=Path(t)/'truncated.json';p.write_text(json.dumps(modified))
            with self.assertRaises(ValueError):physical.checked(self.pub,self.own,self.root/'plan.json',self.root/'annotation.json',p)

    def test_duplicate_question_or_source_rejected(self):
        bad=fake_original();bad[0]['conversation']['session_1'][1]['dia_id']=bad[0]['conversation']['session_1'][0]['dia_id']
        self.assertRaises(ValueError,s.material,bad)

    def test_deterministic_exact_same_request(self):
        public=s.read(self.pub)
        self.assertEqual(s.select(public,self.owner),s.select(copy.deepcopy(public),self.owner))
        self.assertEqual(self.packet['requests_sha256'],s.digest(self.packet['requests']))

    def test_strict_create_only(self):
        with self.assertRaises(FileExistsError):s.plan(self.pub,self.own,self.root/'plan.json')

    def test_unrecognized_gold_answer_type_rejected(self):
        bad=fake_original();bad[0]['qa'][0]['answer']={'dangerous':'schema'}
        self.assertRaises(ValueError,s.material,bad)

    def test_original_archive_sha_is_fixed(self):
        self.assertEqual(s.ARCHIVE_SHA,'07b357cbb3362f4afa4dc1872ab7e28e8a46daaf338f2636fed8d40fbcee76af')

    def test_nonfinite_json_source_rejected(self):
        with tempfile.TemporaryDirectory() as t:
            p=Path(t)/'nan.json';p.write_text('{"x":NaN}')
            self.assertRaises(ValueError,s.read,p)

    def test_duplicate_json_field_rejected(self):
        with tempfile.TemporaryDirectory() as t:
            p=Path(t)/'duplicate.json';p.write_text('{"x":1,"x":2}')
            self.assertRaises(ValueError,s.read,p)


if __name__=='__main__':unittest.main()
