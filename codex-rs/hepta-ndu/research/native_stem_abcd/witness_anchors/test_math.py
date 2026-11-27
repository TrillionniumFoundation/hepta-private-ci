"""R25 math tests, requiring mounted original R21 archive for archival checks."""
import unittest
from fractions import Fraction as F
import core
class TestCertificate(unittest.TestCase):
 def test_archive_hash(self):
  self.assertEqual(core.sha('/mnt/data/hepta_native_ndu_four_weight_round21_20261015.zip'),core.ARCHIVE_SHA)
 def test_hex_index(self):
  self.assertEqual(core.sha('/mnt/data/ndu_round21_evidence/WEIGHTS_HEX.csv'),core.INDEX_SHA)
 def test_witness_exact_bytes(self):
  data=core.verify_provenance('/mnt/data/hepta_native_ndu_four_weight_round21_20261015.zip','/mnt/data/ndu_round21_evidence/WEIGHTS_HEX.csv','/mnt/data/ndu_round24/source/WITNESS_INPUT.csv')
  self.assertEqual(set(data),{3,4});self.assertEqual(len(data[4]),4)
 def test_nearest_eighth(self):
  self.assertEqual(core.nearest_eighth(F(-7,20)),-F(3,8))
  self.assertEqual(core.nearest_eighth(F(1,16)),0)
  self.assertEqual(core.nearest_eighth(F(-1,16)),0)
  self.assertEqual(core.nearest_eighth(F(15,16)),F(7,8))
 def test_fixed_anchor_identity(self):
  a=core.anchor_details()
  self.assertEqual(tuple(x[0] for x in a),(-1,1))
  self.assertNotEqual(a[0][2],a[1][2])
  for _,z,t in a:self.assertLessEqual(abs(z-t),F(1,16))
 def test_candidate_census(self):
  data=core.verify_provenance('/mnt/data/hepta_native_ndu_four_weight_round21_20261015.zip','/mnt/data/ndu_round21_evidence/WEIGHTS_HEX.csv','/mnt/data/ndu_round24/source/WITNESS_INPUT.csv')
  for row in core.cert_candidates(data):self.assertLess(F(row['upper']),F(9,4))
 def test_anchored_dominates_original(self):
  for n in (3,4):
   for z in (F(-1),F(0),F(1,3)):
    box=tuple((z-F(1,4),z+F(1,4)) for _ in range(n))
    self.assertGreaterEqual(core.anchored_lower(box),core.e.hybrid_lower(box))
 def test_pointwise_valid(self):
  for n in (3,4):
   for z in (F(-1),F(0),F(1)):
    box=tuple((z-F(1,4),z+F(1,4)) for _ in range(n))
    pt=tuple((z,z) for _ in range(n))
    self.assertLessEqual(core.anchored_lower(box),core.old.cost_bounds(pt)[1])
 def test_old_three_candidate_mathematically_ineligible(self):
  data=core.verify_provenance('/mnt/data/hepta_native_ndu_four_weight_round21_20261015.zip','/mnt/data/ndu_round21_evidence/WEIGHTS_HEX.csv','/mnt/data/ndu_round24/source/WITNESS_INPUT.csv')
  old=tuple(F(v) for v in core.old.CANDIDATES[3])
  self.assertGreater(core.old.cost_bounds(core.interval(old))[0]-core.old.cost_bounds(core.interval(data[3]))[1],F(1,100))
 def test_gate_and_schedule_unchanged(self):
  self.assertEqual(core.CAP,4000);self.assertEqual(core.THRESHOLD,F(1,100));self.assertEqual(len(core.TRIALS),3)
if __name__=='__main__':unittest.main(verbosity=2)
