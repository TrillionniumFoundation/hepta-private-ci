"""Synthetic V19 contract tests. No pretrained Reader or publisher truth.

Private original-model numerical tests are separately executed offline.
"""
import unittest
from v19_windowed_witness import window_span,build
from v19_independent_original_review import source_span_independent,original_prompt_independent

class WindowSourceContracts(unittest.TestCase):
    def setUp(self):
        self.text='Alice met Bob. Carol moved to Oregon. Bob drove to Portland. They met again later. Finally they left.'
        self.question='Where did Bob drive Portland?' 
    def test_source_uses_original_bytes(self):
        for radius in (1,2):
            chunk,(a,b),n=window_span(self.question,self.text,radius)
            self.assertEqual(chunk,self.text[a:b])
            self.assertIn('Bob drove',chunk)
            self.assertEqual(n,5)
    def test_independent_source_window_matches(self):
        for radius in (1,2):
            p=window_span(self.question,self.text,radius)
            q=source_span_independent(self.question,self.text,radius)
            self.assertEqual(p[:2],q)
    def test_one_window_is_less_than_full(self):
        chunk,span,n=window_span(self.question,self.text,1)
        self.assertLess(len(chunk),len(self.text))
    def test_two_window_is_full(self):
        chunk,span,n=window_span(self.question,self.text,2)
        self.assertEqual(chunk,self.text)
    def test_reject_non_numeric_radius(self):
        for x in ('1',0,3,True,False,-1,None):
            with self.subTest(x=x),self.assertRaises(ValueError):window_span(self.question,self.text,x)
    def test_reject_empty_inputs(self):
        for q,d in (('',self.text),(self.question,''),(None,self.text),(self.question,None)):
            with self.subTest(q=q,d=d),self.assertRaises(ValueError):window_span(q,d,1)
    def test_reject_oversized_source(self):
        with self.assertRaises(ValueError):window_span(self.question,'abc.'*800,1)
    def test_punctuation_word_boundary(self):
        q='Where was the key?' 
        t='Notebook. The key was inside a cupboard! Empty drawer. Last room.'
        for rad in (1,2):
            self.assertEqual(window_span(q,t,rad)[:2],source_span_independent(q,t,rad))
    def test_early_sentence(self):
        self.assertEqual(window_span('Alice?',self.text,1)[:2],source_span_independent('Alice?',self.text,1))
    def test_late_sentence(self):
        self.assertEqual(window_span('finally?',self.text,1)[:2],source_span_independent('finally?',self.text,1))
    def test_single_sentence_full_length(self):
        self.assertEqual(window_span('cat','A cat sleeps.',1)[0],'A cat sleeps.')
    def test_no_stem_selection_possible(self):
        with self.assertRaises(Exception):build({}, {}, {}, {}, {})
    def test_prompt_and_evidence_source_ids(self):
        s=original_prompt_independent('Where?', ['a','b','c'], {'a':'First.','b':'Second.','c':'Third.'})
        self.assertEqual(s.count('[E1]'),2)
        self.assertEqual(s.count('[E2]'),2)
        self.assertEqual(s.count('[E3]'),2) # instruction plus one delivered E3
    def test_reject_duplicate_source(self):
        with self.assertRaises(ValueError):original_prompt_independent('Why?', ['a','a','c'], {'a':'A','c':'C'})
    def test_invalid_sentence_not_spurious(self):
        for text in ('   ','\n\n'):
            with self.assertRaises(ValueError):window_span('which?',text,2)
if __name__=='__main__':unittest.main()
