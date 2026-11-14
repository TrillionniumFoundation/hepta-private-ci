import json
import unittest
from pathlib import Path
from verify import qualify, REQUIRED

class GateTests(unittest.TestCase):
    def setUp(self):
        self.manifest = json.loads((Path(__file__).parent / 'qualification.json').read_text())
    def test_current_manifest_fails_closed(self):
        ok, problems = qualify(self.manifest)
        self.assertFalse(ok)
        self.assertEqual(len(problems), sum(map(len, REQUIRED.values())))
    def test_missing_phase_fails(self):
        del self.manifest['phases']['P4']
        ok, problems = qualify(self.manifest)
        self.assertFalse(ok)
        self.assertTrue(any('exactly' in p for p in problems))
    def test_queued_ci_not_pass(self):
        self.manifest['phases']['P0']['exact_head_ci']={'status':'QUEUED','evidence_url':'https://example.org','source_sha':'a'*40}
        self.assertFalse(qualify(self.manifest)[0])
    def test_self_attestation_does_not_pass(self):
        self.manifest['phases']['P0']['exact_head_ci']={'status':'PASS','attestation':'self','evidence_url':'https://example.org','source_sha':'a'*40,'study_status':'exact_head_ci'}
        self.assertTrue(any('independent' in p for p in qualify(self.manifest)[1]))
    def test_complete_forged_structural_fixture_rejected(self):
        for phase, criteria in REQUIRED.items():
            for criterion in criteria:
                self.manifest['phases'][phase][criterion]={'status':'PASS','attestation':'independent-verified','evidence_url':'https://example.org/receipt','source_sha':'a'*40,'study_status':'prospective_replication'}
        self.assertFalse(qualify(self.manifest)[0])
        self.assertTrue(any("UNVERIFIED_TRUST" in p for p in qualify(self.manifest)[1]))

if __name__ == '__main__':
    unittest.main()
