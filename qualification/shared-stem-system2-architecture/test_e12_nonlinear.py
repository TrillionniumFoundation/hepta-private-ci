"""Adversarial math/provenance tests; never a natural reasoning claim."""
import unittest
from dataclasses import replace
from fractions import Fraction as F

from e12_nonlinear_cert import Law,State,Trace,solve,operator,rat,phi,_nearest_even
from e12_independent_audit import audit,reference,round_even

class NonlinearExactTest(unittest.TestCase):
    def test_six_preregistered_profiles_independently_verified(self):
        for n in (1,2,3):
            for a in ('0','1/3'):
                with self.subTest(depth=n,coupling=a):
                    law=Law(depth=n,a=a)
                    result=solve(law)
                    review=audit(law,result)
                    self.assertTrue(review.certified)
                    self.assertTrue(review.independent_iteration_replay)
                    self.assertEqual(review.authority,'DENY_ALL')
                    self.assertFalse(review.natural_task_improvement_proven)

    def test_nonzero_noise_two_distinct_futures(self):
        law=Law()
        result=solve(law)
        self.assertNotEqual(result.trace.states[1].x,result.trace.states[2].x)
        self.assertTrue(any(v!='0' for v in result.trace.z))

    def test_genuine_nonlinearity(self):
        self.assertEqual(phi(F(1,2)), F(2,5))
        self.assertEqual(phi(F(-1,2)), F(-2,5))
        law=Law(a='1/3',depth=1)
        self.assertNotEqual(operator(law,(F(0),)),operator(law,(F(1,4),)))

    def test_uncoupled_one_map_is_exact(self):
        law=Law(a='0',depth=3)
        n=2**law.depth-1
        zero=(F(0),)*n
        first=operator(law,zero)
        self.assertEqual(operator(law,first),first)
        self.assertEqual(law.values()['q'],0)
        self.assertEqual(audit(law,solve(law)).exact_residual!='0',True)

    def test_single_map_with_nonlinear_coupling_is_insufficient(self):
        law=Law(a='1/3',depth=3)
        zero=(F(0),)*7
        first=operator(law,zero)
        second=operator(law,first)
        one_map_bound=max(abs(v-w) for v,w in zip(first,second))/(1-law.values()['q'])
        self.assertGreater(one_map_bound,F(1,10000))
        self.assertLessEqual(F(solve(law).fixed_point_error_bound),F(1,10000))

    def test_global_contraction_adversarial_rational_pair(self):
        law=Law(depth=3,a='1/3')
        n=7
        a=(F(1,8),)*n
        b=(-F(1,8),)*n
        out_a=operator(law,a)
        out_b=operator(law,b)
        self.assertLessEqual(max(abs(v-w) for v,w in zip(out_a,out_b)),
                             law.values()['q']*F(1,4))

    def test_independent_prefix_map_matches_original(self):
        law=Law()
        inp=(F(1,16),)*7
        self.assertEqual(reference(law,inp)[2],operator(law,inp))

    def test_rounding_parity_and_ties_even(self):
        for f in (F(1,131072),F(3,131072),F(-3,131072),F(1,7),F(-19,21)):
            with self.subTest(f=f):
                self.assertEqual(_nearest_even(f,16),round_even(f,16))
        self.assertEqual(_nearest_even(F(1,131072),16),0)
        self.assertEqual(_nearest_even(F(3,131072),16),F(1,32768))

    def test_changed_forward_path_rejected(self):
        law=Law()
        result=solve(law)
        states=list(result.trace.states)
        states[1]=replace(states[1],x='5')
        with self.assertRaises(ValueError):
            audit(law,replace(result,trace=replace(result.trace,states=tuple(states))))

    def test_changed_backward_path_rejected(self):
        law=Law()
        result=solve(law)
        states=list(result.trace.states)
        states[0]=replace(states[0],y='0')
        with self.assertRaises(ValueError):
            audit(law,replace(result,trace=replace(result.trace,states=tuple(states))))

    def test_changed_terminal_leaf_rejected(self):
        law=Law()
        result=solve(law)
        states=list(result.trace.states)
        states[-1]=replace(states[-1],y='0')
        with self.assertRaises(ValueError):
            audit(law,replace(result,trace=replace(result.trace,states=tuple(states))))

    def test_forged_z_and_martingale_rejected(self):
        law=Law()
        result=solve(law)
        z=list(result.trace.z)
        z[0]='0'
        with self.assertRaises(ValueError):
            audit(law,replace(result,trace=replace(result.trace,z=tuple(z))))

    def test_missing_public_prefix_rejected(self):
        result=solve(Law())
        with self.assertRaises(ValueError):
            audit(Law(),replace(result,trace=replace(result.trace,
                                                      states=result.trace.states[:-1])))

    def test_fake_error_bound_rejected(self):
        r=solve(Law())
        for forged in ('0','1/9999'):
            with self.subTest(forged=forged),self.assertRaises(ValueError):
                audit(Law(),replace(r,fixed_point_error_bound=forged))

    def test_forged_iteration_rejected(self):
        r=solve(Law())
        with self.assertRaises(ValueError):
            audit(Law(),replace(r,evaluations=r.evaluations+1,rounded_steps=r.rounded_steps+1))

    def test_forged_precision_rejected(self):
        r=solve(Law())
        with self.assertRaises(ValueError):
            audit(Law(),replace(r,quantization_bits=14))

    def test_reject_promotion_fraud(self):
        r=solve(Law())
        for change in ({'production_accepted':True},
                       {'authority':'ALLOW'}, {'real_pretrained_forwards':1}):
            with self.subTest(change=change),self.assertRaises(ValueError):
                audit(Law(),replace(r,**change))

    def test_invalid_numbers_and_regions(self):
        for bad in ('NaN','inf','2/4','01','-0',"1.0",'1e2','9'*90):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                rat(bad)
        for law in (Law(depth=True),Law(depth=4),Law(sigma='0'),Law(s='0'),
                    Law(horizon='0'),Law(a='1',horizon='2',g='1',beta='1')):
            with self.subTest(law=law),self.assertRaises(ValueError):
                law.values()

    def test_no_unbounded_work_or_incompatible_trace(self):
        law=Law()
        for kwargs in ({'bits':True},{'max_calls':True},{'bits':5},{'max_calls':0},
                       {'tolerance':'0'},{'tolerance':'1/2'}):
            with self.subTest(kwargs=kwargs),self.assertRaises(ValueError):
                solve(law,**kwargs)
        with self.assertRaises(ValueError):
            solve(law,max_calls=1)
        with self.assertRaises(ValueError):
            operator(law,(F(0),))

if __name__=='__main__':
    unittest.main()
