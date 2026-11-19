"""No-network fixture and mutation qualification; DOES NOT represent HotpotQA scores."""
import copy
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import v15_hotpot_source as source
import v15_evidence_proposer as proposer
import v15_hotpot_review as reviewer


def fake(n=8):
    rows=[]
    for i in range(n):
        rows.append(dict(_id=f'fake-human-style-{i:02}',
            question='Which city housed the painter after the academy hired the artist?',
            answer='Loma', type='bridge' if i%2 else 'comparison',
            level=['easy','medium','hard'][i%3],
            context=[['The painter', [
                    'The academy hired the artist in the regional museum.',
                    'The painter lived for years in Loma.',
                    'The gallery held unrelated records.']],
                     ['Regional museum', [
                    'The painter had worked at the Regional museum.',
                    'This institution opened in Loma.']],
                     ['The cliffs', ['Visitors remember a distant scenic overlook.',
                                    'Few archives mention the landscape.']]],
            supporting_facts=[['The painter',1],['Regional museum',1]]))
    return rows


class V15Small(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp=tempfile.TemporaryDirectory()
        cls.root=Path(cls.tmp.name)
        cls.raw=cls.root/'source.json'
        cls.raw.write_text(json.dumps(fake(),ensure_ascii=True))
        sha=hashlib.sha256(cls.raw.read_bytes()).hexdigest()
        with patch.object(source,'N_EXPECTED',8), patch.object(source,'SOURCE_SHA256',sha):
            cls.owner=source.source_owner(cls.raw,cls.root/'original')
        cls.pub=cls.root/'original'/'public.json'
        cls.own=cls.root/'original'/'manifest.json'
        cls.gold=cls.root/'original'/'hidden-restricted.json'
        with patch.object(proposer,'N_EXPECTED',8):
            cls.plan=proposer.plan(cls.pub,cls.own,cls.root/'plan.json')
            cls.seal=proposer.propose(cls.pub,cls.own,cls.root/'plan.json',cls.root/'sealed.json')
        with patch.object(reviewer,'N_EXPECTED',8):
            cls.rev=reviewer.audit(cls.pub,cls.own,cls.gold,cls.root/'plan.json',
                                  cls.root/'sealed.json',cls.root/'review.json')

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_first_party_data_and_gold_separated(self):
        self.assertEqual(len(source.load(self.pub)),8)
        self.assertFalse(any('supporting_facts' in row or 'answer' in row for row in source.load(self.pub)))
        self.assertEqual(len(source.load(self.gold)),8)
        self.assertEqual(self.owner['authority'],'DENY_ALL')
        self.assertFalse(self.owner['source_time_prospective'])

    def test_full_frozen_controls_and_two_equal_budgets(self):
        self.assertEqual(self.seal['completed_questions'],8)
        self.assertFalse(self.seal['actual_answer_generation'])
        for row in self.seal['proposals'].values():
            self.assertEqual(set(row),set(proposer.ARMS))
            for arm in proposer.ARMS:
                self.assertEqual(len(row[arm]['2']),2)
                self.assertEqual(len(row[arm]['5']),5)
        self.assertEqual(len(self.rev['summary']),8)
        self.assertEqual(self.rev['reviewed_questions'],8)
        self.assertFalse(self.rev['evaluate_answers'])
        self.assertEqual(self.rev['authority'],'DENY_ALL')

    def test_zero_pretrained_and_unsupported_claims(self):
        self.assertEqual(self.seal['optimizer_updates'],0)
        self.assertEqual(self.seal['pretrained_calls'],0)
        self.assertTrue(self.rev['answer_string_presence_not_generated_answer'])

    def test_tokenized_link_title_spans_case_insensitive(self):
        self.assertTrue(proposer.contains_title('The REGIONAL museum has moved','Regional museum'))
        self.assertFalse(proposer.contains_title('The birthplace of Air', 'chair'))
        self.assertEqual(proposer.tokens('Who was known as The Silver Knight?'),['known','silver','knight'])

    def test_scrambled_graph_does_not_mutate_public(self):
        rows=source.load(self.pub)
        frozen=source.digest(rows)
        p,_=proposer.predict_one(rows[0])
        self.assertEqual(source.digest(rows),frozen)
        self.assertEqual(set(p),set(proposer.ARMS))

    def test_prediction_repeat_same_input_same_result(self):
        public=source.load(self.pub)
        self.assertEqual(proposer.predict_one(public[0]),proposer.predict_one(public[0]))

    def test_conflicting_source_or_hidden_digest_refused(self):
        owner=source.load(self.own)
        owner['hidden_sha256']='0'*64
        with tempfile.TemporaryDirectory() as p:
            broken=Path(p)/'owner.json'; broken.write_text(json.dumps(owner))
            with patch.object(reviewer,'N_EXPECTED',8),self.assertRaises(ValueError):
                reviewer.audit(self.pub,broken,self.gold,self.root/'plan.json',self.root/'sealed.json',Path(p)/'out.json')

    def test_forged_support_id_and_resealed_probabilities_refused(self):
        sealed=copy.deepcopy(self.seal)
        cid=next(iter(sealed['proposals']))
        sealed['proposals'][cid]['bm25']['2'][0]=['forged article',111]
        sealed['proposal_sha256']=source.digest(sealed['proposals'])
        with tempfile.TemporaryDirectory() as p:
            broken=Path(p)/'sealed.json'; broken.write_text(json.dumps(sealed))
            with patch.object(reviewer,'N_EXPECTED',8),self.assertRaises(ValueError):
                reviewer.audit(self.pub,self.own,self.gold,self.root/'plan.json',broken,Path(p)/'out.json')

    def test_changed_top_k_or_duplicate_is_denied(self):
        for mode in ('short','duplicate'):
            sealed=copy.deepcopy(self.seal);cid=next(iter(sealed['proposals']))
            selection=sealed['proposals'][cid]['bm25']['5']
            if mode=='short':selection.pop()
            else: selection[4]=selection[0]
            sealed['proposal_sha256']=source.digest(sealed['proposals'])
            with tempfile.TemporaryDirectory() as p:
                broken=Path(p)/'sealed.json'; broken.write_text(json.dumps(sealed))
                with patch.object(reviewer,'N_EXPECTED',8),self.assertRaises(ValueError):
                    reviewer.audit(self.pub,self.own,self.gold,self.root/'plan.json',broken,Path(p)/'out.json')

    def test_label_leak_into_public_is_denied(self):
        row=source.load(self.pub)[0];row['answer']='Loma'
        with self.assertRaises(ValueError):proposer.predict_one(row)

    def test_original_checksum_tamper_prevents_source_owner(self):
        with tempfile.TemporaryDirectory() as p:
            with patch.object(source,'N_EXPECTED',8), patch.object(source,'SOURCE_SHA256','0'*64):
                with self.assertRaises(ValueError):source.source_owner(self.raw,Path(p)/'cannot-create')

    def test_source_golden_integrity_negative(self):
        raw=fake()
        raw[0]['supporting_facts']=[['MISSING',0]]
        with self.assertRaises(ValueError):source.convert(raw,exact_count=8)
        raw=fake();raw[0]['context'][0][0]=raw[0]['context'][1][0]
        with self.assertRaises(ValueError):source.convert(raw,exact_count=8)

    def test_stdlib_inference_under_python_S(self):
        s=("import v15_hotpot_source,v15_evidence_proposer,v15_hotpot_review,sys; "
           "assert not any(x in sys.modules for x in ('torch','safetensors','transformers')); "
           "assert callable(v15_evidence_proposer.predict_one)")
        r=subprocess.run([sys.executable,'-S','-c',s],cwd=Path(__file__).parent,
             env={**os.environ,'PYTHONPATH':str(Path(__file__).parent)},capture_output=True,text=True,check=False)
        self.assertEqual(r.returncode,0,r.stdout+r.stderr)


if __name__=='__main__': unittest.main()
