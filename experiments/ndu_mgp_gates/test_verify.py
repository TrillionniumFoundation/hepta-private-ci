import json,unittest
from pathlib import Path
from verify import REQUIRED, qualify
class GateTests(unittest.TestCase):
 def setUp(self): self.data=json.loads((Path(__file__).parent/"qualification.json").read_text())
 def test_all_real_gates_blocked(self):
  self.assertEqual(len(qualify(self.data)),sum(map(len,REQUIRED.values())))
 def test_missing_phase_rejected(self):
  del self.data["phases"]["P4"];self.assertTrue(qualify(self.data))
 def test_queued_is_not_success(self):
  self.data["phases"]["P0"]["exact_head_ci"]={"status":"QUEUED"};self.assertTrue(qualify(self.data))
 def test_self_scored_pass_rejected(self):
  self.data["phases"]["P0"]["exact_head_ci"]={"status":"PASS","attestation":"self","evidence_url":"https://example.org","source_sha":"a"*40,"study_status":"exact_head_ci"}
  self.assertTrue(any("independent" in x for x in qualify(self.data)))
 def test_all_syntactically_pass_receipts_cannot_mint_trust(self):
  # A malicious or erroneous manifest with fake HTTPS URLs and SHA values
  # must remain unqualified even if every declared field looks acceptable.
  for p,names in REQUIRED.items():
   for n in names:self.data["phases"][p][n]={"status":"PASS","attestation":"independent-verified","evidence_url":"https://example.org/fake","source_sha":"a"*40,"study_status":"prospective_replication"}
  self.assertEqual(qualify(self.data),["UNVERIFIED_TRUST: shape-only metadata cannot establish external acceptance"])
if __name__=="__main__": unittest.main()
