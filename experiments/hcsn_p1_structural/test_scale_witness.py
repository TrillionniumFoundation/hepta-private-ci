"""Check structural repaired-coordinate identifiability, not learned efficacy."""
import math
import random
import unittest
import torch
try:
    from .dual_channel_structural_gate import channels,first_hit_probability,power_boundary
    from .scale_witness import scale_aware_features
except ImportError:
    from dual_channel_structural_gate import channels,first_hit_probability,power_boundary
    from scale_witness import scale_aware_features


class ScaleWitnessTests(unittest.TestCase):
    def test_second_singular_value_is_restored(self):
        rng=random.Random(8181)
        for _ in range(64):
            v0,k0=rng.uniform(.6,1.7),rng.uniform(.6,1.7)
            u=torch.tensor((v0,k0),dtype=torch.float64)
            def g(v):
                q=channels(v[0],v[1])
                return torch.stack((q.call_normalized,q.put_normalized,q.margin))
            def f(v):return scale_aware_features(v[0],v[1])
            before=torch.linalg.svdvals(torch.autograd.functional.jacobian(g,u))
            after=torch.linalg.svdvals(torch.autograd.functional.jacobian(f,u))
            self.assertLess(float(before[1]),1e-11)
            self.assertGreater(float(after[1]),.2)

    def test_equal_normalized_features_cannot_classify_scale_label(self):
        # Any deterministic model using only the first three channels sees
        # identical inputs for two states with distinct absolute resource.
        v0,k0=1.3,1.
        a=scale_aware_features(torch.tensor(.5*v0,dtype=torch.float64),torch.tensor(.5*k0,dtype=torch.float64))
        b=scale_aware_features(torch.tensor(2*v0,dtype=torch.float64),torch.tensor(2*k0,dtype=torch.float64))
        self.assertLess(float(torch.abs(a[:3]-b[:3]).max()),1e-12)
        self.assertAlmostEqual(float(b[3]-a[3]),math.log(4),delta=1e-12)

    def test_frozen_first_hit_probability_is_also_scale_blind(self):
        beta,ratio=power_boundary(.05,.03,.2)
        k0=1.
        v0=1.5
        t=2.1
        p0=first_hit_probability(v0,ratio*k0,t)
        for a in (.25,2.,16.,1000.):
            p=first_hit_probability(a*v0,ratio*a*k0,t)
            self.assertAlmostEqual(p,p0,delta=1e-13)


if __name__=='__main__':unittest.main()
