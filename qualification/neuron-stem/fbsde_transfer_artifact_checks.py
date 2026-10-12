"""Mutate complete output records; original evidence is never modified."""
import json
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from fbsde_transfer_audit import audit

ROOT=Path(sys.argv.pop()) if len(sys.argv)>1 and not sys.argv[-1].startswith('-') else Path('transfer-study')


class TransferArtifactTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)/'copy';shutil.copytree(ROOT,self.root)
    def change(self,name,edit):
        p=self.root/(name+'.json');v=json.loads(p.read_bytes());edit(v);p.write_text(json.dumps(v))
    def test_original(self):self.assertEqual(audit(self.root)['outputs_recomputed'],1584)
    def test_counterfeit_complete_rule_rejects(self):
        def edit(rows):
            row=next(r for r in rows if r['table_snapshot']);row['table_snapshot']['effects'][0]=(row['table_snapshot']['effects'][0]+1)%6
        self.change('outputs',edit)
        with self.assertRaisesRegex(ValueError,'exported rule'):audit(self.root)
    def test_unselected_or_erased_probe_rejects(self):
        def edit(rows):next(r for r in rows if r['result']['records'])['result']['records'].pop()
        self.change('outputs',edit)
        with self.assertRaises(ValueError):audit(self.root)
    def test_optimistic_identification_ceiling_rejects(self):
        self.change('identification-ceiling',lambda r:r['two_probe_identifiable_rules'].append(6))
        with self.assertRaisesRegex(ValueError,'ceiling'):audit(self.root)
    def test_budget_change_and_trimmed_denominator_reject(self):
        self.change('plan',lambda r:r.__setitem__('ordinary_checks',3))
        with self.assertRaisesRegex(ValueError,'design'):audit(self.root)
    def test_semantic_certificate_rejects(self):
        self.change('outputs',lambda r:r[0]['result'].__setitem__('semantic_certificate',True))
        with self.assertRaisesRegex(ValueError,'certificate'):audit(self.root)


if __name__=='__main__':unittest.main()
