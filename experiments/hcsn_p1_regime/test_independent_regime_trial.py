"""Local targeted P1 experiment-contract tests; none establishes efficacy."""
import math
import unittest
import numpy as np
import torch
from .independent_regime_trial import (ANCHOR, Refuse, _perpetual,
    exact_signflip_p, features, first_hit, make_data, make_model,
    parameter_count, train, warmup_runtime)

class P1Contract(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        torch.set_num_threads(1)
        warmup_runtime()

    def test_both_arms_same_context_and_shape(self):
        obs,y=make_data(504,80)
        a=features(obs,'ordinary'); b=features(obs,'call_put_margin_risk')
        self.assertEqual(a.shape,b.shape)
        self.assertEqual(a.shape,(80,7))
        self.assertTrue(np.array_equal(a[:,4:],b[:,4:]))
        self.assertEqual(parameter_count(),sum(p.numel() for p in make_model().parameters()))
        self.assertEqual(set(y.tolist()),{0,1})

    def test_signed_slope_and_anchor_value_all_contexts(self):
        for z in (0,1):
            for t in (.7,1.,1.7,2.4,3.7):
                for arm in ('ordinary','call_put_margin_risk'):
                    a=np.array([[ANCHOR,0.,math.log(t),z]],dtype=float)
                    eps=1e-5
                    plus=a.copy(); minus=a.copy(); plus[0,0]+=eps; minus[0,0]-=eps
                    self.assertTrue(np.allclose(features(a,arm)[0,:4],ANCHOR,rtol=0,atol=1e-6))
                    grad=(features(plus,arm)[0,:4].astype(float)-features(minus,arm)[0,:4].astype(float))/(2*eps)
                    self.assertTrue(np.allclose(grad,np.ones(4),rtol=0,atol=.006), (z,t,arm,grad))

    def test_normalized_common_scale_invariance_and_parity(self):
        for z in (.22,.46):
            m=np.array([.2,.35,.6]); s=np.full(3,z)
            c,p,dc,dp=_perpetual(m,s)
            # Call minus Put equals V/K -1, with contextual ratio from beta.
            nu=.02-.5*z*z; beta=(math.hypot(nu,math.sqrt(.1*z*z))+nu)/(z*z) if nu>=0 else .1/(math.hypot(nu,math.sqrt(.1*z*z))-nu)
            ratio=beta/(1+beta)
            self.assertTrue(np.allclose(c-p,ratio*np.exp(m)-1,atol=1e-12))
            self.assertTrue((dp<0).all())
            for abs_k in (.01,1.,200.):
                self.assertTrue(np.allclose(c,p+(ratio*np.exp(m)-1)))

    def test_finite_firsthit_derivative(self):
        for z in (.22,.46):
            for t in (.7,1.,2.7,3.7):
                m=np.array([.15,.35,.8]); tt=np.full(3,t); sig=np.full(3,z)
                p,d=first_hit(m,tt,sig)
                e=1e-5
                pd=(first_hit(m+e,tt,sig)[0]-first_hit(m-e,tt,sig)[0])/(2*e)
                self.assertTrue((d<0).all())
                self.assertTrue(np.allclose(d,pd,atol=3e-9,rtol=3e-7))
                self.assertTrue(np.all((0<=p)&(p<=1)))

    def test_markov_regime_replay_and_ood_shift(self):
        obs,y=make_data(902,1000)
        ob2,y2=make_data(902,1000)
        self.assertTrue(np.array_equal(obs,ob2))
        self.assertTrue(np.array_equal(y,y2))
        ood,_=make_data(902,1000,ood=True)
        self.assertTrue(np.all(ood[:,2]>math.log(2.4)-1e-12))
        self.assertTrue(set(obs[:,3])=={0,1})
        # Absolute scale was generated independently and has no label effect.
        aa=obs.copy();aa[:,1]+=0.1
        for arm in ('ordinary','call_put_margin_risk'):
            self.assertTrue(np.array_equal(features(aa,arm)[:,:4],features(obs,arm)[:,:4]))

    def test_invalid_and_nonfinite_fail_closed(self):
        obs,_=make_data(22,9)
        for col,bad in ((0,0.),(1,9.),(2,float('nan')),(3,.2)):
            a=obs.copy();a[0,col]=bad
            with self.assertRaises(Refuse):features(a,'ordinary')
        with self.assertRaises(Refuse):features(obs,'unknown')
        with self.assertRaises(Refuse):make_data(-1,0)
        with self.assertRaises(Refuse):train(1,'ordinary',obs,np.zeros(9),budget_seconds=0.)

    def test_exact_signflip_test_retains_negative(self):
        self.assertEqual(exact_signflip_p([1.]*8),2/256)
        self.assertEqual(exact_signflip_p([1.,-1.,1.,-1.]),1.)
        with self.assertRaises(Refuse):exact_signflip_p([1.])

    def test_cpu_smoke_not_a_scientific_run(self):
        obs,y=make_data(20,128)
        for arm in ('ordinary','call_put_margin_risk'):
            model,receipt=train(51,arm,obs,y,budget_seconds=.10)
            self.assertGreaterEqual(receipt['training_and_feature_cpu_seconds'],.10)
            self.assertEqual(receipt['parameters'],609)
            self.assertGreater(receipt['updates'],0)

if __name__=='__main__':unittest.main()
