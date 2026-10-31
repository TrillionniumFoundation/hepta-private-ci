"""Independent numerical and negative controls, not a task-quality experiment."""
import math
import random
import unittest
import torch
from .contextual_rank import (Refuse, setup, normalized_features, hit,
                              rank_receipt, inverse_time)

class TestContextualRank(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        torch.set_num_threads(1)

    def test_old_scale_and_time_blind_spot(self):
        for v,k in ((1.3,1.),(1.,.7),(2.,1.5)):
            a=normalized_features(math.log(v/k))
            for multiplier in (.1,.5,2.,30.):
                b=normalized_features(math.log((v*multiplier)/(k*multiplier)))
                for x,y in zip(a,b): self.assertAlmostEqual(x,y,delta=3e-15)
            self.assertEqual(a,normalized_features(math.log(v/k)))

    def test_mathematical_rank_three_not_independent_risk(self):
        rng=random.Random(1009)
        for _ in range(180):
            x=rng.uniform(.1,.7)
            k=rng.uniform(-2.,2.)
            T=rng.uniform(.4,12.)
            rec=rank_receipt(x,k,math.log(T))
            self.assertTrue(rec.mathematical_rank_three)
            self.assertGreater(rec.log_time_derivative,0.)
            self.assertFalse(rec.independent_risk_information)
            self.assertFalse(rec.p1_causal_quality_gain)
            self.assertFalse(rec.production_activation)

    def test_reflection_probability_derivative_matches_independent_density(self):
        rng=random.Random(1913)
        for _ in range(100):
            r,payout,sigma=rng.uniform(.012,.17),rng.uniform(.01,.14),rng.uniform(.075,.55)
            x,T=rng.uniform(.1,.7),rng.uniform(.2,8.)
            drift,_,ratio=setup(r,payout,sigma)
            m=x-math.log(ratio)
            time=torch.tensor(T,dtype=torch.float64,requires_grad=True)
            root=sigma*torch.sqrt(time)
            x1=(-m-drift*time)/root
            x2=(-m+drift*time)/root
            q=torch.exp(torch.logaddexp(torch.special.log_ndtr(x1),
                        -2*drift*m/(sigma*sigma)+torch.special.log_ndtr(x2)))
            dp=torch.autograd.grad(q,time)[0].item()
            p,f=hit(x,T,r=r,payout=payout,sigma=sigma)
            self.assertAlmostEqual(q.detach().item(),p,delta=1e-12)
            self.assertAlmostEqual(dp,f,delta=max(1e-11,1e-9*abs(f)))

    def test_full_rank_jacobian_and_triangular_determinant(self):
        drift,_,ratio=setup()
        for x,T in ((.15,.5),(.3,1.),(.5,2.),(.7,6.)):
            inputs=torch.tensor((x,1.,math.log(T)),dtype=torch.float64)
            def fn(y):
                a,scale,lt=y.unbind()
                m=a-math.log(ratio)
                t=torch.exp(lt)
                den=.2*torch.sqrt(t)
                h=torch.exp(torch.logaddexp(
                      torch.special.log_ndtr((-m-drift*t)/den),
                      -2*drift*m/(.2*.2)+torch.special.log_ndtr((-m+drift*t)/den)))
                return torch.stack((m,scale,h))
            J=torch.autograd.functional.jacobian(fn,inputs)
            self.assertGreater(float(torch.linalg.svdvals(J)[-1]),1e-7)
            self.assertAlmostEqual(float(torch.linalg.det(J)),
                                   rank_receipt(x,1.,math.log(T)).log_time_derivative,
                                   delta=1e-10)

    def test_horizon_invertible_no_new_information(self):
        for x,T in ((.12,.5),(.25,1.),(.4,4.),(.7,10.),(.25,15.)):
            self.assertAlmostEqual(inverse_time(x,hit(x,T)[0]),T,delta=max(1e-8,T*1e-8))

    def test_f64_saturation_refuses_numerical_rank(self):
        num=0
        for x,T in ((.4,1e-5),(.4,1e-3),(.1,100.),(.2,100.)):
            if not rank_receipt(x,0.,math.log(T)).f64_conditioning_accepted:
                num+=1
        self.assertGreaterEqual(num,2)

    def test_stopped_region_no_full_rank(self):
        for x in (-2.,-1.,-.5):
            p=rank_receipt(x,0.,0.)
            if normalized_features(x)[2]<=0:
                self.assertFalse(p.mathematical_rank_three)
                self.assertEqual(p.log_time_derivative,0.)

    def test_refuse_invalid_domain(self):
        for bad in (float('nan'),float('inf'),float('-inf')):
            with self.assertRaises(Refuse):hit(bad,1.)
        for bad in (0.,-1.,101.):
            with self.assertRaises(Refuse):hit(.3,bad)
        for bad in (0.,1.,float('nan')):
            with self.assertRaises(Refuse):inverse_time(.3,bad)
        with self.assertRaises(Refuse):rank_receipt(.3,0.,-16.)

if __name__=='__main__':unittest.main()
