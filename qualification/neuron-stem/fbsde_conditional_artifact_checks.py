"""Rehashed complete-record mutations; run with a completed study directory."""
import hashlib
import json
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from four_gate_common import canonical
from fbsde_conditional_audit import audit

ROOT=None


class ArtifactTests(unittest.TestCase):
    def mutate(self, fn):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)/'study';shutil.copytree(ROOT,root);fn(root)
            streams=json.loads((root/'streams.json').read_text());payload=0
            for arm,meta in streams.items():
                raw=(root/(arm+'.json')).read_bytes();rows=json.loads(raw)
                size=sum(len(canonical(r)) for r in rows);payload+=size
                meta.update(file_sha256=hashlib.sha256(raw).hexdigest(),rows=len(rows),serialized_payload_bytes=size)
            (root/'streams.json').write_text(json.dumps(streams))
            result=json.loads((root/'results.json').read_text());result['record_payload_bytes']=payload
            (root/'results.json').write_text(json.dumps(result))
            with self.assertRaises(ValueError):audit(root)

    def edit(self,root,fn,arm='conditional_two'):
        p=root/(arm+'.json');rows=json.loads(p.read_text());fn(rows);p.write_text(json.dumps(rows))

    def test_false_identified_program(self):
        self.mutate(lambda p:self.edit(p,lambda r:r[54]['decisions'][-1]['posterior'].update(program_set_identified=True)))
    def test_true_predecessor_cannot_be_smuggled_in_receipt(self):
        self.mutate(lambda p:self.edit(p,lambda r:r[54]['checks'][0]['receipt'].update(predecessor=[0,1,2])))
    def test_altered_selected_observation(self):
        self.mutate(lambda p:self.edit(p,lambda r:r[54]['checks'][0]['receipt'].update(effect=[0,1,2])))
    def test_failed_or_refused_cases_remain_in_denominator(self):
        self.mutate(lambda p:self.edit(p,lambda r:r.pop(216)))
    def test_no_replayed_observation_erasure(self):
        self.mutate(lambda p:self.edit(p,lambda r:r[54]['decisions'][-1].update(known=[])))
    def test_fabricated_total_cost(self):
        self.mutate(lambda p:self.edit(p,lambda r:r[54].update(cpu_ns=0)))
    def test_no_semantic_certificate_from_support(self):
        self.mutate(lambda p:self.edit(p,lambda r:r[54].update(semantic_certificate=True)))

if __name__=='__main__':
    ROOT=Path(sys.argv.pop());unittest.main()
