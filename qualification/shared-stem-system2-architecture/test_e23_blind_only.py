"""No human labels or scored source archives touched in this pre-seal run."""
from __future__ import annotations

import os
from pathlib import Path
import unittest
from unittest.mock import patch
from zipfile import ZipFile
from e22_e16_question_gate import blind_e22, ALL
from e21_whole_question import once


def original_inputs():
    def path(k):
        value=os.environ.get(k)
        if not value or not Path(value).is_file():
            raise RuntimeError(f'original archived source mandatory: {k}')
        return value
    return path('HEPTA_E23_ORIGINAL'),[path(f'HEPTA_E23_E15_FOLD_{i}') for i in range(4)],\
           [path(f'HEPTA_E23_E16_FOLD_{i}') for i in range(4)]


class LabelBlind(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source,cls.e15,cls.e16=original_inputs()
        cls.data=blind_e22(cls.source,cls.e15,cls.e16)

    def test_01_only_original_prelabel_and_frozen_fold_members_are_read(self):
        reads=[];method=ZipFile.read
        def remember(obj,name,*args,**kwargs):
            reads.append(name)
            return method(obj,name,*args,**kwargs)
        with patch.object(ZipFile,'read',remember):
            blind_e22(self.source,self.e15,self.e16)
        self.assertNotIn('multirc-native-candidate-scores/scores.json',reads)
        self.assertTrue(all('human' not in x.lower() and 'owner-only' not in x.lower() for x in reads))

    def test_02_all_33_and_eight_arms_are_original_complete(self):
        self.assertEqual((self.data['source_passages'],self.data['questions'],self.data['candidates']),(4,8,33))
        self.assertEqual(len({r['task_id'] for r in self.data['rows']}),33)
        self.assertTrue(all(set(r['probs'])==set(ALL) for r in self.data['rows']))

    def test_03_no_original_human_score_access_before_prediction_seal(self):
        self.assertIs(self.data['human_labels_opened'],False)
        self.assertEqual(self.data['new_pretrained_forwards'],0)
        self.assertEqual(self.data['authority'],'DENY_ALL')

    def test_04_frozen_full_original_model_source_deterministic(self):
        self.assertEqual(self.data,blind_e22(self.source,self.e15,self.e16))

    def test_05_create_only_predictions(self):
        from tempfile import TemporaryDirectory
        with TemporaryDirectory() as d:
            path=str(Path(d)/'blind.json')
            once(path,self.data)
            with self.assertRaises(FileExistsError):once(path,self.data)

if __name__=='__main__':unittest.main()
