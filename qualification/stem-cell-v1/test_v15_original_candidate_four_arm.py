"""Source-contract and tampering regressions, never mistaken for neural inference."""
import copy
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
from hashlib import sha256

sys.path.insert(0,str(Path(__file__).parents[1]))
import v15_original_candidate_four_arm as v
import v15_original_private_recount as rev

class SourceContracts(unittest.TestCase):
    def setUp(self):
        self.docs={'a':'A proof is here','b':'Another record','c':'Additional independent source','w':'Critical source witness'}
        self.question='Who arrived first?'
    def test_empty_prompt_keeps_same_instruction(self):
        txt=v.prompt(self.question,[],self.docs)
        self.assertIn('unknown',txt)
        self.assertNotIn('[E1] A proof',txt)
    def test_annotated_witness_prompt_is_actual_distinct_input(self):
        a=v.prompt(self.question,['a','b','c'],self.docs)
        b=v.prompt(self.question,['w','a','b'],self.docs)
        c=v.prompt(self.question,['a','b'],self.docs)
        self.assertEqual(len({v.htext(x) for x in (a,b,c)}),3)
    def test_duplicate_evidence_rejected(self):
        with self.assertRaises(ValueError):v.prompt(self.question,['a','a'],self.docs)
    def test_missing_source_rejected(self):
        with self.assertRaises(ValueError):v.prompt(self.question,['forged'],self.docs)
    def test_not_allow_empty_question(self):
        with self.assertRaises(ValueError):v.prompt('',[],self.docs)
    def test_new_cannot_overwrite(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'x.json';v.save_new(p,{'status':1})
            with self.assertRaises(FileExistsError):v.save_new(p,{'status':2})
    def test_nonfinite_json_rejected(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'x.json';p.write_text('{"x":NaN}')
            with self.assertRaises(ValueError):v.load(p)
    def test_duplicate_json_rejected(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'x.json';p.write_text('{"x":1,"x":2}')
            with self.assertRaises(ValueError):v.load(p)
    def test_auditor_rejects_missing_starts(self):
        with patch.object(rev,'validate_answers',return_value=True):
            with self.assertRaises(ValueError):rev.recount({'requests':{'a':{}}},{},{},{'raw_answers':{}},[])
    def test_auditor_rejects_started_wrong_plan(self):
        p={'requests':{'a':{}},'cases':[]}
        packet={'raw_answers':{'a':{'input_tokens':1}}}
        line=json.dumps(dict(request_id='a',plan_sha256='b'*64,original_input_token_sha256='x',original_input_token_count=1))
        with patch.object(rev,'validate_answers',return_value=True):
            with self.assertRaises(ValueError):rev.recount(p,{},{},packet,[line])
    def test_auditor_rejects_false_forward_count(self):
        p={'requests':{'a':{}},'cases':[]}; rid='a'
        ans={'raw_answers':{'a':{'input_tokens':1,'token_ids':[5,6,2],'answer_text':'txt','answer_sha256':v.htext('txt')}},'model_forwards':0}
        line=json.dumps(dict(request_id=rid,plan_sha256=v.digest(p),original_input_token_sha256='x',original_input_token_count=1))
        with patch.object(rev,'validate_answers',return_value=True):
            with self.assertRaises(ValueError):rev.recount(p,{},{},ans,[line])

if __name__=='__main__':unittest.main()
