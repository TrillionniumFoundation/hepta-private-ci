"""Label-blind grouping with fail-closed source and seal identities."""
import copy
import unittest
from multirc_factorial_review import review_factorial
from next_round_matrix import _digest
from multirc_query_factorial import SCHEMA


def original():
    rows=[]
    for group in ('A','B'):
        for slot in (0,1):
            rows.append(dict(source_group=group,question_slot=slot,task_id=f'{group}{slot}',
                abs_change_question_only=0.0001 if group=='A' else 0.2,
                abs_change_answer_only=0.0002 if group=='A' else 0.3,
                abs_change_question_and_answer=.3))
    r=dict(schema=SCHEMA,question_count=4,passage_count=2,records=rows)
    r['factorial_id']=_digest(r)
    return r

class FactorialReviewTests(unittest.TestCase):
    def run_review(self,r=None,**kwargs):
        r=original() if r is None else r
        return review_factorial(r,expected_factorial_id=r['factorial_id'],**kwargs)
    def test_individual_passage_diagnosis_not_new_accuracy(self):
        out=self.run_review()
        self.assertEqual(out['double_insensitive_question_count'],2)
        self.assertEqual(out['passage_count'],2)
        self.assertEqual(out['question_count'],4)
        self.assertIsNone(out['answer_accuracy'])
        self.assertFalse(out['question_understanding_established'])
    def test_seal_tamper_or_missing_question_rejected(self):
        r=original(); r['records'][0]['abs_change_answer_only']=0.9
        with self.assertRaises(ValueError):self.run_review(r)
        r=original();r['records'].pop();r['factorial_id']=_digest({k:v for k,v in r.items() if k!='factorial_id'})
        with self.assertRaises(ValueError):self.run_review(r)
    def test_duplicate_source_slot_rejected_even_if_resealed(self):
        r=original();r['records'][1]['question_slot']=0
        r['factorial_id']=_digest({k:v for k,v in r.items() if k!='factorial_id'})
        with self.assertRaises(ValueError):self.run_review(r)
    def test_invalid_epsilon_rejected(self):
        for val in (True,float('nan'),float('inf'),-1,.2):
            with self.subTest(value=val),self.assertRaises(ValueError):self.run_review(epsilon=val)
