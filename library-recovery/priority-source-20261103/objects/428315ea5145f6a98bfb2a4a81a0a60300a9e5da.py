"""Independent P2 rate-switching / repeated-event reference stress.

The comparison is the finite two-state CTMC, not the actual neural HCSN
training model or the He--Xiong endogenous barrier process.
"""
import math
import random
import unittest
import numpy as np
from scipy.linalg import expm
from experiments.hcsn_distributional_v2.renewal_event_oracle import RenewalState, advance


def independent_piecewise(active, segments):
    """Independent 5D generator product: physical mass, count, killed mass."""
    row=np.array([active,1-active,0.,active,1-active],dtype=np.float64)
    for lam,gamma,dt in segments:
        Q=np.zeros((5,5),dtype=np.float64)
        Q[0,0],Q[0,1],Q[0,2]=-lam,lam,lam
        Q[1,0],Q[1,1]=gamma,-gamma
        Q[3,3]=-lam
        Q[4,3],Q[4,4]=gamma,-gamma
        row=row@expm(Q*dt)
    return row


class SegmentedRenewalTests(unittest.TestCase):
    def test_70_independent_three_segment_generators(self):
        rng=random.Random(2026103061)
        for _ in range(70):
            initial=rng.random()
            segments=[(rng.uniform(.2,6),rng.uniform(.2,6),rng.uniform(.005,.7))
                      for k in range(3)]
            state=RenewalState.initial(initial)
            for lam,gamma,dt in segments:
                state=advance(state,lam,gamma,dt)
            v=independent_piecewise(initial,segments)
            with self.subTest(init=initial):
                self.assertLess(abs(state.active-v[0]),3e-12)
                self.assertLess(abs(state.expected_count-v[2]),3e-12)
                self.assertLess(abs(state.no_fire_active-v[3]),3e-12)
                self.assertLess(abs(state.no_fire_refractory-v[4]),3e-12)
                self.assertLess(abs(state.ever_fired-(1-v[3]-v[4])),3e-12)
                self.assertGreaterEqual(state.expected_count,state.ever_fired)

    def test_two_step_constant_rate_semigroup(self):
        rng=random.Random(2026103062)
        for i in range(80):
            lam,gamma=rng.uniform(.1,4),rng.uniform(.1,4)
            a=rng.random()
            dt1,dt2=rng.uniform(.01,.3),rng.uniform(.01,.3)
            split=advance(advance(RenewalState.initial(a),lam,gamma,dt1),lam,gamma,dt2)
            direct=advance(RenewalState.initial(a),lam,gamma,dt1+dt2)
            for k in ('active','no_fire_active','no_fire_refractory',
                      'ever_fired','expected_count'):
                with self.subTest(i=i,k=k):
                    self.assertLess(abs(getattr(split,k)-getattr(direct,k)),3e-12)

    def test_first_event_probability_is_not_repeated_event_count(self):
        state=advance(RenewalState.initial(1.),7.,7.,2.)
        self.assertGreater(state.expected_count,5.)
        self.assertLessEqual(state.ever_fired,1.)
        self.assertGreater(state.expected_count,state.ever_fired+3.)

    def test_identical_prefix_and_different_suffix(self):
        init=RenewalState.initial(.61)
        p1=advance(init,.7,1.2,.31)
        p2=advance(init,.7,1.2,.31)
        self.assertEqual(p1,p2)
        q1=advance(p1,1.,2.,.55)
        q2=advance(p2,3.,1.,.55)
        self.assertNotEqual(q1.expected_count,q2.expected_count)
        self.assertGreater(q1.time,p1.time)

    def test_versioned_checkpoint_required(self):
        state=RenewalState(0.,.5,.5,.5,0.,0.,version=2)
        with self.assertRaises(ValueError):
            advance(state,1.,2.,.1)


if __name__=='__main__':
    unittest.main()
