import unittest
import tempfile
import pathlib
import hashlib
import json
from teacher_study import emit
from teacher_study_evaluator import evaluate

class SeparateTeacherScorerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp=tempfile.TemporaryDirectory()
        cls.root=pathlib.Path(cls.temp.name)
        cls.future=cls.root/'future.json';cls.seal=cls.root/'seal.json'
        emit(str(cls.future),str(cls.seal))
        cls.fh=hashlib.sha256(cls.future.read_bytes()).hexdigest()
        cls.sh=hashlib.sha256(cls.seal.read_bytes()).hexdigest()
    @classmethod
    def tearDownClass(cls):cls.temp.cleanup()
    def test_independent_frozen_sha_scoring(self):
        result=evaluate(str(self.future),self.fh,str(self.seal),self.sh)
        self.assertEqual(result['synthetic_future_cases'],160)
        self.assertGreater(result['teacher_agreement_by_arm']['learned_gate'],.9)
        self.assertFalse(result['external_natural_task_utility'])
    def test_separate_future_label_absence(self):
        rows=json.loads(self.future.read_text())
        self.assertTrue(all('label' not in row for row in rows))
    def test_sha_mismatch_fails_closed(self):
        with self.assertRaises(ValueError):evaluate(str(self.future),'0'*64,str(self.seal),self.sh)
    def test_create_only_prevents_overwrite(self):
        with self.assertRaises(FileExistsError):emit(str(self.future),str(self.seal))

if __name__=='__main__':unittest.main()
