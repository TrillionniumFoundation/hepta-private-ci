import itertools
import unittest
import numpy as np
from control import Command
from sampling import Allocation,allocate


class AllocationTests(unittest.TestCase):
    def test_exact_complete_command_lattice(self):
        commands=[Command(*v) for v in itertools.product(range(4),range(3),range(3))]
        result=allocate(commands)
        self.assertEqual(result.population,36)
        self.assertEqual(len(result.indices),24)
        self.assertEqual(result.gradient_weight,2/3)
        self.assertIn(0,result.indices)
        self.assertTrue(all(any(x==0 for x in commands[i].values) for i in result.indices))

    def test_all_keep_retained_and_no_stratum_switch(self):
        result=allocate([Command(0,0,0),Command(3,2,2),Command(1,0,2)])
        self.assertEqual(result,Allocation(3,(0,2)))
        self.assertEqual(allocate([Command(0,0,0)]).gradient_weight,1)

    def test_all_constant_objective_has_no_informative_batch(self):
        with self.assertRaises(ValueError):allocate([Command(1,1,1),Command(3,2,2)])

    def test_invalid_allocations_and_types_reject(self):
        for population,indices in ((True,(0,)),(2,(1,0)),(2,(0,0)),(2,(2,)),(2,())):
            with self.assertRaises(ValueError):Allocation(population,indices)
        with self.assertRaises(ValueError):allocate([(0,0,0)])

    def test_weighted_mean_gradient_matches_original(self):
        gradients=np.asarray([[1.,-2.],[0.,0.],[2.,1.],[0.,0.]])
        active=gradients[[0,2]];fraction=.5
        np.testing.assert_allclose(gradients.mean(0),fraction*active.mean(0),rtol=0,atol=1e-15)
        self.assertFalse(np.array_equal(gradients.mean(0),active.mean(0)))

    def test_covariance_reduction_identity(self):
        gradients=np.asarray([[1.,-2.],[0.,0.],[2.,1.],[0.,0.]])
        active=gradients[[0,2]];fraction=.5
        def covariance(rows):
            centered=rows-rows.mean(0)
            return centered.T@centered/len(rows)
        difference=covariance(gradients)-covariance(fraction*active)
        expected=fraction*(1-fraction)*(active.T@active/len(active))
        np.testing.assert_allclose(difference,expected,rtol=0,atol=1e-15)
        self.assertGreaterEqual(np.linalg.eigvalsh(difference).min(),-1e-15)

    def test_scale_is_not_an_adam_update_identity(self):
        # Same mean gradient is not the mean of nonlinear adaptive updates.
        values=np.asarray([-1.,3.]);epsilon=.1
        update=lambda g:g/(np.abs(g)+epsilon)
        self.assertGreater(abs(update(values).mean()-update(values.mean())),.1)

if __name__=='__main__':unittest.main()
