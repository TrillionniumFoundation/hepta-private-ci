"""Blind E21 research tests: scores and original human labels NEVER in this job."""
from __future__ import annotations
import copy
import os
from pathlib import Path
from unittest import TestCase, main
from unittest.mock import patch
import e21_whole_question as e


class OnlyModelInputs(TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source=os.environ.get('HEPTA_E21_SOURCE')
        cls.folds=[os.environ.get(f'HEPTA_E21_FOLD_{i}') for i in range(4)]
        if not cls.source or any(not x for x in cls.folds):
            raise ValueError('all exact true model predecessor ZIPs mandatory; no synthetic fallback')
        cls.blind=e.load_blind_source(cls.source,cls.folds)

    def test_actual_identity_census(self):
        x=self.blind
        self.assertEqual((x['source_group_count'],x['question_count'],x['candidate_count']),(4,8,33))
        self.assertEqual(sum(bool(r['original_v1_candidate']) for r in x['rows']),8)

    def test_genuine_models_only_and_no_label_truth(self):
        self.assertFalse(self.blind['held_human_labels_opened'])
        self.assertFalse(self.blind['production_accepted'])
        for r in self.blind['rows']:
            self.assertEqual(set(r['probs']),set(e.ALL))
            self.assertNotIn('label',r)

    def test_original_only_same_question_no_query(self):
        by={}
        for r in self.blind['rows']:
            by.setdefault((r['source_group'],r['question_slot']),set()).add(r['probs']['no_query'])
        self.assertEqual(len(by),8)
        self.assertTrue(all(len(v)==1 for v in by.values()))

    def test_missing_or_mixed_fold_fails(self):
        with self.assertRaises(ValueError):e.load_blind_source(self.source,self.folds[:-1])
        bad=self.folds[:];bad[3]=bad[0]
        with self.assertRaises(ValueError):e.load_blind_source(self.source,bad)

    def test_original_human_score_members_never_accessed(self):
        opened=[]
        class NoScoreZip(e.ZipFile):
            def read(self,name,*args,**kwargs):
                opened.append(name)
                if 'scores' in name or 'labels' in name:
                    raise AssertionError('blind process attempted to access held human labels or scores')
                return super().read(name,*args,**kwargs)
        with patch.object(e,'ZipFile',NoScoreZip):
            self.assertEqual(len(e.load_blind_source(self.source,self.folds)['rows']),33)
        self.assertTrue(opened)

    def test_blind_outputs_do_not_hold_human_truth(self):
        self.assertFalse(any('human_truth' in r or 'label' in r for r in self.blind['rows']))
        self.assertEqual(self.blind['real_pretrained_forwards_new'],0)

    def test_blind_numerical_source_values_typed(self):
        self.assertTrue(all(all(type(v) is float and 0<v<1 for v in r['probs'].values())
                            for r in self.blind['rows']))

    def test_blind_prod_flags_frozen(self):
        self.assertEqual(self.blind['authority'],'DENY_ALL')
        self.assertEqual(self.blind['e15_head'],e.E15_HEAD)

if __name__=='__main__':main()
