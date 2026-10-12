"""Mutation checks of a complete saved family study; run after the study."""
import json
import hashlib
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from fbsde_effect_audit import audit
from four_gate_common import canonical

ROOT = None


class ArtifactTests(unittest.TestCase):
    def mutate(self,name,change):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)/'copy';shutil.copytree(ROOT,root)
            path=root/(name+'.json');value=json.loads(path.read_text());change(value)
            path.write_text(json.dumps(value))
            # Refresh consistency hashes: the semantic audit must still reject.
            streams=json.loads((root/'streams.json').read_text())
            if name in streams:
                streams[name].update(file_sha256=hashlib.sha256(path.read_bytes()).hexdigest(), rows=len(value),
                                     serialized_payload_bytes=sum(len(canonical(v)) for v in value))
                (root/'streams.json').write_text(json.dumps(streams))
                result=json.loads((root/'results.json').read_text())
                result['record_payload_bytes']=sum(s['serialized_payload_bytes'] for s in streams.values())
                (root/'results.json').write_text(json.dumps(result))
            with self.assertRaises((ValueError,IndexError)):audit(root)

    def test_fabricated_costs(self):
        self.mutate('results',lambda v:v['summary']['cycle']['expand_two'].__setitem__('cpu_ns',0))

    def test_no_prior_observations_erased_after_expansion(self):
        def change(rows):
            row=next(r for r in rows if r['revisions']);row['revisions'][0]['history_sha256']='0'*64
        self.mutate('expand_two',change)

    def test_no_check_budget_reset(self):
        def change(rows):
            row=next(r for r in rows if r['revisions']);row['revisions'][0]['remaining_checks']=2
        self.mutate('expand_two',change)

    def test_support_unanimity_not_global_semantic_certificate(self):
        self.mutate('permutation_two',lambda v:v[0].__setitem__('semantic_certificate',True))

    def test_source_revelation_cannot_be_relabelled(self):
        def change(rows):
            row=next(r for r in rows if r['checks']);row['checks'][0]['receipt']['effect']=[0,0,0]
        self.mutate('expand_two',change)

    def test_partial_outputs_not_a_complete_study(self):
        self.mutate('event_probe',lambda v:v.pop())


if __name__=='__main__':
    ROOT=Path(sys.argv.pop())
    unittest.main()
