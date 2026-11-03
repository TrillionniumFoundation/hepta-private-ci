"""Negative controls for actual archived-answer audit; no model inference."""
from copy import deepcopy
import unittest
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
import verify_memorycell_qwen_38224780900 as v

O = Path('/mnt/data/event-inputs-20261010.zip')
R = Path('/mnt/data/strong-rag-qwen-38224780900.zip')
V = Path('/mnt/data/strong-rag-independent-replay-38224780900.zip')

class ActualArchiveTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.original=v.read_pinned_zip(O, 'original')
        cls.reader=v.read_pinned_zip(R, 'reader')
        cls.docs={x['identity']:x for x in v.strict_json(cls.original['plan/source-view.json'])}
        cls.case=v.strict_json(cls.original['plan/plan.json'])['cases'][0]
        cls.labels={x['id']:x for x in v.strict_json(cls.original['observations/labels.json'])}
        cls.journal=[v.strict_json(x) for x in cls.reader['evaluation/raw-answers.jsonl'].splitlines()]
        cls.scored=v.strict_json(cls.reader['evaluation/scored-answers.json'])
        cls.identity=v.strict_json(cls.reader['inventory.json'])['inventory_digest']

    def record(self):
        i=next(i for i,r in enumerate(self.journal) if r['question_id']==self.case['query']['identity'] and r['arm']=='organized')
        return deepcopy(self.journal[i]),deepcopy(self.scored[i])

    def verify(self,a,b):
        return v.validate_answer_row(a,b,self.case,self.labels[self.case['query']['identity']],self.docs,self.identity)

    def test_correct_real_archived_answer_verifies(self):
        a,b=self.record()
        self.assertTrue(self.verify(a,b)['correct'])

    def test_changed_original_answer_rejected(self):
        a,b=self.record();a['answer'] += ' invented';
        with self.assertRaises(ValueError):self.verify(a,b)

    def test_changed_delivered_original_source_rejected(self):
        a,b=self.record();a['receipt']['delivered_evidence'][0]['excerpt']+=' forged';b['receipt']['delivered_evidence'][0]['excerpt']+=' forged'
        with self.assertRaises(ValueError):self.verify(a,b)

    def test_changed_reader_identity_rejected(self):
        a,b=self.record();a['receipt']['reader_identity']='0'*64;b['receipt']['reader_identity']='0'*64
        with self.assertRaises(ValueError):self.verify(a,b)

    def test_changed_citation_source_rejected(self):
        a,b=self.record();a['citation_audit']['request']['sources'][0]['excerpt']='fabricated';b['citation_audit']['request']['sources'][0]['excerpt']='fabricated'
        with self.assertRaises(ValueError):self.verify(a,b)

    def test_independent_complete_census_and_no_go(self):
        receipt=v.audit(O,R,V)
        self.assertEqual(receipt['original_answer_rows'],{'calibration':40,'evaluation':72})
        self.assertEqual(receipt['calibration']['selected_k'],1)
        self.assertFalse(receipt['calibration']['loo_stable'])
        self.assertEqual(receipt['evaluation']['by_arm']['organized']['correct'],8)
        self.assertEqual(receipt['evaluation']['by_arm']['organized']['correct_with_all_declared_sources_cited'],4)
        self.assertFalse(receipt['production_accepted'])

if __name__=='__main__':unittest.main()
