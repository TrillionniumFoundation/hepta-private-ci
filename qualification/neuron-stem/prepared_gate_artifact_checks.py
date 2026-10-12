"""Mutation contracts for a complete measured study; originals remain untouched."""
import json
import os
from pathlib import Path
import shutil
import tempfile
import unittest
from fbsde_prepared_gate_audit import audit


class PreparedArtifactTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.original=Path(os.environ.get('HEPTA_PREPARED_EVIDENCE','prepared-gate-study'))
        cls.source=Path(os.environ.get('HEPTA_OUTCOME_EVIDENCE','outcome-study'))
        if not (cls.original/'results.json').exists():raise ValueError('complete prepared study required')
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)/'copy';shutil.copytree(self.original,self.root)
    def change(self,name,fn):
        p=self.root/(name+'.json');r=json.loads(p.read_text());fn(r);p.write_text(json.dumps(r))
    def test_complete_current_result(self):
        self.assertEqual(audit(self.root,self.source)['audited_calls'],30240)
    def test_changed_decision_digest_rejects(self):
        self.change('calls',lambda r:r[0].__setitem__('semantic_sha256','f'*64))
        with self.assertRaisesRegex(ValueError,'changed action'):audit(self.root,self.source)
    def test_removed_execution_rejects(self):
        self.change('calls',lambda r:r.pop())
        with self.assertRaisesRegex(ValueError,'inventory'):audit(self.root,self.source)
    def test_reordered_fastest_repetition_rejects(self):
        self.change('calls',lambda r:r.reverse())
        with self.assertRaisesRegex(ValueError,'inventory'):audit(self.root,self.source)
    def test_altered_preparation_identity_rejects(self):
        self.change('preparation',lambda r:r[0].__setitem__('identity','f'*64))
        with self.assertRaisesRegex(ValueError,'provenance'):audit(self.root,self.source)
    def test_fabricated_speedup_rejects(self):
        self.change('results',lambda r:r['summary']['outcome_outcome'].__setitem__('prepared_cpu_reduction_fraction',.99999))
        with self.assertRaisesRegex(ValueError,'cost reduction'):audit(self.root,self.source)

if __name__=='__main__':unittest.main()
