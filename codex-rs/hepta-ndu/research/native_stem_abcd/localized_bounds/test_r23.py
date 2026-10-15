import unittest
from fractions import Fraction as F
from r23 import bound
import centered as c
class ProofTests(unittest.TestCase):
 def test_weakly_dominates_old_box(self):
  for n in (2,3,4):
   for z in (F(0),F(1,2),F(-1,2)):
    box=tuple((z-F(1,4),z+F(1,4)) for _ in range(n))
    self.assertGreaterEqual(bound(box),c.hybrid_lower(box))
 def test_pointwise_covered(self):
  for n in (2,3,4):
   for z in (F(-1),F(0),F(1)):
    box=tuple((z-F(1,4),z+F(1,4)) for _ in range(n))
    point=tuple((z,z) for _ in range(n))
    self.assertLessEqual(bound(box),c.old.cost_bounds(point)[0])
 def test_exact_split_coverage(self):
  box=((F(-1),F(2)),(F(-3),F(4)),(F(0),F(2)))
  k,l,r=c.old.bisect(box)
  self.assertEqual(l[k][1],r[k][0]);self.assertEqual(l[k][0],box[k][0]);self.assertEqual(r[k][1],box[k][1])
 def test_historical_gate_unchanged(self):
  self.assertEqual(c.old.NODE_CAP,4000);self.assertEqual(c.old.TARGET,F(1,100))
if __name__=='__main__':unittest.main(verbosity=2)
