"""Rehash mutated evidence before auditing; hashes alone cannot establish the claims."""
import hashlib
import json
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from fbsde_identification_audit import audit


class ArtifactTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        for src in SOURCE.glob('*.json'):shutil.copy2(src,self.root/src.name)
    def tearDown(self):self.temp.cleanup()
    def edit(self,name,fn):
        path=self.root/(name+'.json');data=json.loads(path.read_bytes());fn(data);path.write_text(json.dumps(data))
        if name=='outputs':
            self.edit('retention',lambda r:r['stream'].update(file_sha256=hashlib.sha256(path.read_bytes()).hexdigest()))
    def test_original(self):self.assertEqual(audit(self.root)['outputs_recomputed'],924)
    def test_optimistic_four_query_ceiling_rejects(self):
        self.edit('preparation',lambda r:r['optimal'][4].update(identified_mass=33))
        with self.assertRaises(ValueError):audit(self.root)
    def test_changed_compiled_identity_rejects(self):
        self.edit('preparation',lambda r:r['optimal'][5].update(policy_sha256='1'*64))
        with self.assertRaisesRegex(ValueError,'identity'):audit(self.root)
    def test_erased_paid_experiment_rejects(self):
        self.edit('outputs',lambda rs:next(r for r in rs if r['result']['records'])['result']['records'].pop())
        with self.assertRaises(ValueError):audit(self.root)
    def test_reset_budget_mid_session_rejects(self):
        def change(rows):
            r=next(r for r in rows if len(r['result']['records'])>1)['result']['records'][1]
            r['request']['remaining']=r['request']['declared_budget']
            from four_gate_common import digest
            r['receipt']['request_sha256']=digest(r['request'])
        self.edit('outputs',change)
        with self.assertRaises(ValueError):audit(self.root)
    def test_exporting_ambiguous_support_rejects(self):
        self.edit('outputs',lambda rows:next(r for r in rows if not r['result']['identified'])['result'].update(identified=True))
        with self.assertRaises(ValueError):audit(self.root)
    def test_semantic_certificate_rejects(self):
        self.edit('outputs',lambda rows:rows[0]['result'].update(semantic_certificate=True))
        with self.assertRaises(ValueError):audit(self.root)
    def test_fabricated_total_cost_rejects(self):
        self.edit('results',lambda r:r['summary']['5:optimal'].update(controller_cpu_ns=0))
        with self.assertRaises(ValueError):audit(self.root)
    def test_trimmed_denominator_rejects(self):
        self.edit('outputs',lambda rows:rows.pop())
        with self.assertRaises(ValueError):audit(self.root)

if __name__=='__main__':
    SOURCE=Path(sys.argv.pop());unittest.main()
