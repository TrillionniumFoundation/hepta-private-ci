"""Portable source-only regression checks when the original R21 ZIP is unavailable."""
import unittest,hashlib
from fractions import Fraction as F
import numpy as np
import core
class Portable(unittest.TestCase):
 def test_embedded_witness_tensor_hashes(self):
  for n,(name,hexes,h) in core.WITNESS_INFO.items():
   v=np.asarray([float.fromhex(s) for s in hexes.split('|')],dtype='<f8')
   self.assertEqual(len(v),n)
   self.assertEqual(hashlib.sha256(v.tobytes()).hexdigest(),h)
 def test_anchor_rounding(self):
  self.assertEqual(core.nearest_eighth(F(-7,20)),-F(3,8))
  self.assertEqual(core.nearest_eighth(F(15,16)),F(7,8))
 def test_fixed_original_residual_anchors(self):
  v=core.anchor_details()
  self.assertEqual(len(v),2)
  for _,res,anchor in v:self.assertLessEqual(abs(res-anchor),F(1,16))
 def test_new_lower_dominates_old(self):
  for n in (3,4):
   for x in (F(-1),F(0),F(1)):
    box=tuple((x-F(1,4),x+F(1,4)) for _ in range(n))
    self.assertGreaterEqual(core.anchored_lower(box),core.e.hybrid_lower(box))
 def test_pointwise_soundness(self):
  box=tuple((F(-1,2),F(1,2)) for _ in range(4))
  x=tuple((F(0),F(0)) for _ in range(4))
  self.assertLessEqual(core.anchored_lower(box),core.old.cost_bounds(x)[1])
 def test_fixed_gate(self):
  self.assertEqual(core.CAP,4000);self.assertEqual(core.THRESHOLD,F(1,100))
if __name__=='__main__':unittest.main(verbosity=2)
