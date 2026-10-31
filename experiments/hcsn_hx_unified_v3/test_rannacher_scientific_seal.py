"""Scientific facts require a stable identity while timings stay descriptive."""
from copy import deepcopy
import base64
import gzip
from pathlib import Path
import json
import unittest
from .rannacher_scientific_seal import audit_panel,InvalidRannacherEvidence

class SealTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # The frozen test payload is also generated from this fixed script and
        # shipped with the research PR as a SHA256 manifest + reproducible run.
        path=Path(__file__).resolve().parent/'RANNACHER_DEBT_PANEL_20261031.json.gz.b64'
        cls.panel=json.loads(gzip.decompress(base64.b64decode(path.read_text())).decode())

    def test_stable_science_under_timing_variation(self):
        base=audit_panel(self.panel)
        changed=deepcopy(self.panel)
        for row in changed['observations']:
            row['cpu_cn_s_single_sample']*=2
            row['cpu_be_s_single_sample']*=3
        self.assertEqual(audit_panel(changed),base)
        self.assertEqual(base['strict_selected_nodes'],6)

    def test_changes_to_science_change_seal(self):
        base=audit_panel(self.panel)
        changed=deepcopy(self.panel)
        changed['observations'][0]['max_error_be_vs_eq8']+=1e-6
        self.assertNotEqual(base['sha256_scientific_payload'],audit_panel(changed)['sha256_scientific_payload'])

    def test_refuse_forged_certificates_and_missing_rows(self):
        for edit in ('delete','claim_all_nodes','alter_interval','duplicate'):
            changed=deepcopy(self.panel)
            if edit=='delete': changed['observations'].pop()
            if edit=='claim_all_nodes': changed['observations'][0]['pointwise_certificate']['all_node_financial_error_certified']=True
            if edit=='alter_interval': changed['observations'][0]['pointwise_certificate']['rannacher_error_upper']='1000'
            if edit=='duplicate': changed['observations'][1]=changed['observations'][0]
            with self.subTest(edit=edit),self.assertRaises(InvalidRannacherEvidence):
                audit_panel(changed)

if __name__=='__main__':
    unittest.main()
