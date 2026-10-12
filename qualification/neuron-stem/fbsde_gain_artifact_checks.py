"""Mutate copies of complete evidence after an actual run. Never skip silently."""
import json
import os
from pathlib import Path
import shutil
import tempfile
import unittest
from fbsde_gain_audit import audit


class GainArtifactChecks(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp=tempfile.TemporaryDirectory();cls.root=Path(cls.temp.name)/'study'
        shutil.copytree(os.environ['HEPTA_GAIN_ARTIFACT'],cls.root)
        cls.source=Path(os.environ['HEPTA_GAIN_SOURCE'])
    @classmethod
    def tearDownClass(cls):cls.temp.cleanup()
    def reject(self,name,mutate,pattern):
        path=self.root/(name+'.json');raw=path.read_bytes()
        try:
            value=json.loads(raw);mutate(value);path.write_text(json.dumps(value))
            with self.assertRaisesRegex(ValueError,pattern):audit(self.root,self.source)
        finally:path.write_bytes(raw)
    def test_weight_magnitude_cannot_be_fabricated(self):
        self.reject('policy',lambda x:x['fits']['signed_gain_v2'].__setitem__('weight_sum',288.),'weight or label')
    def test_test_data_cannot_select_the_threshold(self):
        self.reject('policy',lambda x:x['selectors']['signed_gain_v2'].__setitem__('selected',.1),'threshold')
    def test_changed_source_text_rejects(self):
        self.reject('inputs',lambda x:x[0]['events'].__setitem__(0,'A new task.'),'input inventory')
    def test_fake_policy_score_rejects(self):
        self.reject('signed_selected',lambda x:x[0]['route'].__setitem__('score',.1),'gain route')
    def test_fake_total_cpu_rejects(self):
        self.reject('results',lambda x:x['summary']['test']['no_checks'].__setitem__('cpu_ns',0),'cost totals')
    def test_dropping_failed_or_difficult_case_rejects(self):
        self.reject('no_checks',lambda x:x.pop(),'ordered arm')


if __name__=='__main__':unittest.main()
