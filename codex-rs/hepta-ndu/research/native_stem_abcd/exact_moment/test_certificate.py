from fractions import Fraction as F
import unittest
from certificate import moment,score,ccscore,certificate
class Tests(unittest.TestCase):
 def test_moments(self):self.assertEqual((moment(6),moment(8)),(F(1,7),F(1,9)))
 def test_exact_optimum(self):
  for t in (F(0),F(1),F(4,3),F(2)):
   self.assertEqual(score(t)-score(F(9,7)),F(1,10)*(t-F(9,7))**2)
 def test_misleading_coarse(self):self.assertLess(ccscore(F(4,3)),ccscore(F(9,7)))
 def test_exact_gap(self):self.assertEqual(certificate()["rigorous_excess"],"1/4410")
 def test_bad_moment(self):
  with self.assertRaises(ValueError):moment(-1)
if __name__=="__main__":unittest.main()
