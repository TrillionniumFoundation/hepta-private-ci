import json
import shutil
import tempfile
import unittest
from pathlib import Path
from paired_result_audit import audit
from paired_trial_replay import run


class AuditorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp=tempfile.TemporaryDirectory()
        cls.src=Path(cls.temp.name)
        run(cls.src,train_count=128,future_count=32)

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def sandbox(self):
        d=tempfile.TemporaryDirectory()
        shutil.copytree(self.src,Path(d.name)/'session')
        return d,Path(d.name)/'session'

    def test_success_recomputes_both_windows(self):
        r=audit(self.src)
        self.assertEqual(r['future_cases_recomputed'],64)
        self.assertEqual(r['future_windows_checked'],2)
        self.assertFalse(r['p3_qualified'])

    def test_report_promotion_fails(self):
        d,p=self.sandbox()
        try:
            name=p/'report.json';x=json.loads(name.read_text());x['p3_qualified']=True
            name.write_text(json.dumps(x))
            with self.assertRaises(ValueError):audit(p)
        finally:d.cleanup()

    def test_changed_eval_receipt_fails(self):
        d,p=self.sandbox()
        try:
            name=p/'future_1.score.json';x=json.loads(name.read_text())
            x['arms']['learned_critic']['expected_mean']+=0.1
            name.write_text(json.dumps(x))
            with self.assertRaises(ValueError):audit(p)
        finally:d.cleanup()

    def test_source_file_tamper_fails(self):
        d,p=self.sandbox()
        try:
            name=p/'future_2.json';x=json.loads(name.read_text())
            x[0]['prior'][0]='1/3';name.write_text(json.dumps(x))
            with self.assertRaises(ValueError):audit(p)
        finally:d.cleanup()

    def test_missing_window_fails(self):
        d,p=self.sandbox()
        try:
            (p/'future_2.score.json').unlink()
            with self.assertRaises(FileNotFoundError):audit(p)
        finally:d.cleanup()

if __name__=='__main__':unittest.main()
