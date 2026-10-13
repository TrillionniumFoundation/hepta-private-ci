"""Rehashed mutations must not convert stale or unobserved results into success."""
import hashlib
import json
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from four_gate_common import digest
from fbsde_lifecycle_audit import audit


class ArtifactTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        for p in SOURCE.glob('*.json'):shutil.copy2(p,self.root/p.name)
    def tearDown(self):self.temp.cleanup()
    def mutate(self,fn):
        p=self.root/'outputs.json';rows=json.loads(p.read_bytes());fn(rows)
        for row in rows:
            prior=None
            for i,e in enumerate(row['ledger']):
                e['sequence']=i;e['previous']=digest(prior) if prior is not None else None;prior=e
        p.write_text(json.dumps(rows))
        r=self.root/'retention.json';record=json.loads(r.read_bytes());record['stream']['file_sha256']=hashlib.sha256(p.read_bytes()).hexdigest();r.write_text(json.dumps(record))
    def test_original(self):self.assertEqual(audit(self.root)['target_requests'],3960)
    def test_rehashed_stale_finish(self):
        def edit(rows):
            e=next(e for r in rows for e in r['ledger'] if e['event']=='finish' and e['revision']>0)
            e['revision']=0
        self.mutate(edit)
        with self.assertRaises(ValueError):audit(self.root)
    def test_erased_retirement(self):
        def edit(rows):
            r=next(r for r in rows if any(e['event']=='retire' for e in r['ledger']))
            r['ledger']=[e for e in r['ledger'] if e['event']!='retire']
        self.mutate(edit)
        with self.assertRaises(ValueError):audit(self.root)
    def test_erased_paid_observation(self):
        self.mutate(lambda rs:next(r for r in rs if r['source_calls'])['source_calls'].pop())
        with self.assertRaises(ValueError):audit(self.root)
    def test_recovery_budget_refill(self):
        def edit(rows):
            c=next(c for r in rows for c in r['source_calls'] if c['request'].get('purpose')=='relearn' and c['request']['sequence']>0)
            c['request']['remaining']=5;c['receipt']['request_sha256']=digest(c['request'])
        self.mutate(edit)
        with self.assertRaises(ValueError):audit(self.root)
    def test_reused_old_initial_certificate(self):
        self.mutate(lambda rows:next(r for r in rows if r['initial'] is not None)['initial']['snapshot']['effects'].__setitem__(0,5))
        with self.assertRaises(ValueError):audit(self.root)
    def test_removed_refusals(self):
        self.mutate(lambda rows:rows.pop())
        with self.assertRaises(ValueError):audit(self.root)
    def test_wrong_answer_relabelled(self):
        self.mutate(lambda rows:rows[0]['outputs'][0].update(value=[2,2,2]))
        with self.assertRaises(ValueError):audit(self.root)
    def test_fabricated_total_cpu(self):
        p=self.root/'results.json';r=json.loads(p.read_bytes());next(iter(r['summary'].values()))['cpu_ns']=0;p.write_text(json.dumps(r))
        with self.assertRaises(ValueError):audit(self.root)

if __name__=='__main__':SOURCE=Path(sys.argv.pop());unittest.main()
