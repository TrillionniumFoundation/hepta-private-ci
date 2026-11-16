"""Independent clustering-weight and strict gate boundary checks."""

import unittest
import numpy as np

from cell_field_statistics_audit_v6 import component_draws,paired_interval,numerical_gate


class StatisticalAuditTests(unittest.TestCase):
    def test_seed_pairing_precedes_cluster_weighting_and_higher_quantile(self):
        values=np.asarray([1.,3.,5.,7.,9.])
        paired=np.stack((values,values+1,values-1))
        inverse=np.asarray([0,0,1,2,3])
        samples=np.asarray([[0,1,2,3],[1,1,2,3],[0,0,2,3],[3,3,3,3]])
        result=paired_interval(paired,inverse,samples)
        self.assertEqual(result["difference"],5.)
        self.assertEqual(result["upper_bound"],9.)
        self.assertEqual(result["paired_seed_mean_differences"],[5.,6.,4.])
        self.assertEqual(result["source_components"],4)
        self.assertEqual(result["source_rows"],5)

    def test_stratum_draw_counts_preserve_component_not_row_population(self):
        names=np.asarray(["a","b","c","d","z","b"])
        strata=np.asarray([0,1,2,3,0,1])
        inverse,samples=component_draws(names,strata,np.random.default_rng(20261025),17)
        np.testing.assert_array_equal(inverse,[0,1,2,3,4,1])
        self.assertEqual(samples.shape,(17,5))
        self.assertTrue(np.isin(samples[:,:2],[0,4]).all())
        np.testing.assert_array_equal(samples[:,2:],np.tile([1,2,3],(17,1)))
        strata[-1]=0
        with self.assertRaisesRegex(ValueError,"crosses strata"):
            component_draws(names,strata,np.random.default_rng(0),17)

    def test_registered_strict_future_and_inclusive_retention_boundaries(self):
        self.assertFalse(numerical_gate("future",-.001))
        self.assertTrue(numerical_gate("future",np.nextafter(-.001,-np.inf)))
        self.assertTrue(numerical_gate("old",0.))
        self.assertFalse(numerical_gate("old",np.nextafter(0.,np.inf)))


if __name__=="__main__":
    unittest.main()
