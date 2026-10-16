"""V18 synthetic review-ticket contracts; no reviewer or model success."""
import copy
import unittest
from test_v18_factorial_contract import data
from v18_factorial_original_reader import htext
from v18_blind_review_tickets import build

class BlindReviewContracts(unittest.TestCase):
    def setUp(self):
        self.plan,self.outputs,_,self.v17,self.old,_=data()
        for rid,row in self.v17['requests'].items():
            row['prompt']='old synthetic prompt for '+rid
            self.old['raw_answers'][rid]['answer_sha256']=htext('abc')
        self.old['plan_sha256']=self._digest_old()
    def _digest_old(self):
        from v18_factorial_original_reader import digest
        return digest(self.v17)
    def test_fully_sealed_no_reviews(self):
        from v18_factorial_original_reader import digest
        self.plan['v17_plan_sha256']=digest(self.v17)
        self.outputs['plan_sha256']=digest(self.plan)
        t,o=build(self.plan,self.v17,self.outputs,self.old,b'P'*32)
        self.assertEqual(len(t['tickets']),128)
        self.assertEqual(t['human_opinions_received'],0)
        self.assertNotIn('intervention_arm',t['tickets'][0])
        self.assertTrue(o['not_for_reviewers'])
    def test_weak_secret_rejected(self):
        with self.assertRaises(ValueError):build(self.plan,self.v17,self.outputs,self.old,b'bad')
    def test_missing_original_rejected(self):
        self.outputs['requests']=57
        with self.assertRaises(ValueError):build(self.plan,self.v17,self.outputs,self.old,b'P'*32)
    def test_foreign_source_rejected(self):
        self.old['raw_answers'][next(iter(self.old['raw_answers']))]['source_ids']=['other']
        with self.assertRaises(ValueError):build(self.plan,self.v17,self.outputs,self.old,b'P'*32)

if __name__=='__main__':unittest.main()
