import math, unittest
import numpy as np
from analyze import aps_scores,fit_temperature,threshold,probabilities,set_metrics,nll_rows,wilson
class Tests(unittest.TestCase):
 def test_order_statistic(self):
  self.assertEqual(threshold(np.arange(160))[0],144);self.assertEqual(threshold(np.arange(160))[1],145)
 def test_small_calibration_infinity(self):self.assertTrue(math.isinf(threshold([.2],.1)[0]))
 def test_bad_scores(self):
  for x in [[],[float('nan')],[[1,2]]]:
   with self.assertRaises(ValueError):threshold(x)
 def test_aps_hand(self):
  np.testing.assert_allclose(aps_scores(np.array([[.5,.3,.2]]),np.array([.4])),[[.3,.68,.92]])
 def test_aps_ties_label_order(self):
  np.testing.assert_allclose(aps_scores(np.array([[.5,.5]]),np.array([0.])),[[.5,1.]])
 def test_aps_bad_uniform(self):
  with self.assertRaises(ValueError):aps_scores([[.5,.5]],[1.])
 def test_temperature_invariance_and_objective(self):
  a=np.array([[4.,1.],[3.,0.],[2.,1.],[1.,4.]]);y=np.array([0,1,0,1]);t=fit_temperature(a,y)
  self.assertGreater(t['T'],0);self.assertLessEqual(t['tuned_tune_nll'],t['raw_tune_nll']);np.testing.assert_array_equal(a.argmax(1),(a/t['T']).argmax(1))
 def test_confident_wrong_temperature_boundary_record(self):
  t=fit_temperature(np.array([[10.,0.],[0.,10.]]),np.array([1,0]));self.assertTrue(t['boundary']);self.assertAlmostEqual(t['log_T'],5)
 def test_nll_stable(self):self.assertTrue(np.isfinite(nll_rows(np.array([[1000.,-1000.]]),np.array([1]))[0]))
 def test_zero_acceptance(self):
  x=set_metrics(np.ones((4,4),dtype=bool),np.arange(4));self.assertIsNone(x['singleton_error']);self.assertIsNone(x['singleton_error_wilson95'])
 def test_singleton_error_not_coverage(self):
  x=set_metrics(np.array([[1,0,0,0],[0,0,1,0],[1,1,1,1],[1,1,1,1]],dtype=bool),np.arange(4));self.assertEqual(x['coverage'],.75);self.assertEqual(x['singleton_error'],.5)
 def test_wilson_zero(self):self.assertGreater(wilson(0,10)[1],0);self.assertIsNone(wilson(0,0))
if __name__=='__main__':unittest.main()
