import itertools,unittest
import numpy as np
from direction_helpers import sample_direction_rows,displacement,norm_matched_parameters
class DirectionHelpersTests(unittest.TestCase):
    def test_fixed_partial_group_disjoint_sampler(self):
        names=[':'.join(map(str,g)) for g in itertools.islice(itertools.product(range(12),range(4),range(3),range(3)),130)];ids=[g for g in names for _ in range(6)];before=ids.copy()
        result=sample_direction_rows(ids,29103);self.assertEqual(result,sample_direction_rows(ids,29103));self.assertEqual(ids,before);gr,gf,sr,sf=result
        self.assertEqual((len(gr),len(sr),sum(gf),sum(sf)),(64,96,32,48));self.assertFalse({ids[i] for i in gr}&{ids[i] for i in sr})
        for rows,k in ((gr,4),(sr,6)):
            groups={ids[i] for i in rows};self.assertEqual(len(groups),8)
            for group in groups:
                members=[i for i in rows if ids[i]==group];self.assertEqual(len(set(members)),k);self.assertEqual(len(members),2*k);self.assertIn(sum(int(v)!=0 for v in group.split(':')[1:]),(1,2))
        for bad,seed in ((ids[:-1],29103),(ids,True),(ids,1),(['x']*780,29103)):
            with self.assertRaises(ValueError):sample_direction_rows(bad,seed)
    def test_equal_norm_no_enlargement_and_input_immutability(self):
        base={'x':np.array([1.,2.]),'y':np.array([3.])};updated={'x':np.array([4.,6.]),'y':np.array([3.])};before={k:v.copy() for k,v in base.items()};delta,norm=displacement(base,updated);self.assertEqual(norm,5.)
        result,scale=norm_matched_parameters(base,delta,2.5);self.assertEqual(scale,.5);np.testing.assert_array_equal(result['x'],[2.5,4.]);self.assertAlmostEqual(displacement(base,result)[1],2.5)
        for k in base:np.testing.assert_array_equal(base[k],before[k]);self.assertFalse(np.shares_memory(result[k],base[k]))
        with self.assertRaises(ValueError):displacement(base,base)
        with self.assertRaises(ValueError):norm_matched_parameters(base,delta,6.)
        with self.assertRaises(ValueError):norm_matched_parameters(base,delta,float('nan'))
        with self.assertRaises(ValueError):norm_matched_parameters(base,{'x':np.ones(3),'y':np.ones(1)},1.)
