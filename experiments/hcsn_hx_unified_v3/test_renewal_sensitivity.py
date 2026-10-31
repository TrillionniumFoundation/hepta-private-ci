"""Independent checks of local analytic derivatives, not P0 global admission."""
from dataclasses import replace
import math
import random
import unittest

import mpmath as mp

from .stopping import Stop, regenerative_boundary
from .renewal_sensitivity import regenerative_boundary_sensitivity


def mp_boundary(p):
    """Independent 90-dps Lambert-W boundary; no parent f64 roots used."""
    with mp.workdps(90):
        mu = mp.mpf(repr(p.drift))
        sigma = mp.mpf(repr(p.diffusion))
        rho = mp.mpf(repr(p.discount))
        K = mp.mpf(repr(p.cost))
        r = mp.mpf(repr(p.reset))
        tau = mp.mpf(repr(p.refractory))
        k = 2*rho/(mu+mp.sqrt(mu*mu+2*rho*sigma*sigma)) if mu>=0 else \
            (-mu+mp.sqrt(mu*mu+2*rho*sigma*sigma))/(sigma*sigma)
        h = k*(K-r)+rho*tau
        t = 1+mp.lambertw(-mp.exp(-h-1), 0)
        return K+t/k


def mp_derivative(p, field, scale=mp.mpf('1e-23')):
    """Independent high-precision *central* differences, not implicit code."""
    with mp.workdps(90):
        kwargs={key:mp.mpf(repr(value)) for key,value in vars(p).items()}
        def exact(args):
            mu,sigma,rho,K,r,tau=(args[x] for x in ('drift','diffusion','discount','cost','reset','refractory'))
            k = 2*rho/(mu+mp.sqrt(mu*mu+2*rho*sigma*sigma)) if mu>=0 else \
                (-mu+mp.sqrt(mu*mu+2*rho*sigma*sigma))/(sigma*sigma)
            h=k*(K-r)+rho*tau
            return K+(1+mp.lambertw(-mp.exp(-h-1), 0))/k
        plus=dict(kwargs); minus=dict(kwargs)
        plus[field]+=scale; minus[field]-=scale
        return (exact(plus)-exact(minus))/(2*scale)


class BoundarySensitivityTests(unittest.TestCase):
    PARAMS=('drift','diffusion','discount','cost','reset','refractory')

    def test_fixed_witness_vs_independent_high_precision(self):
        cases=[Stop(.1,.4,.1,1.,0.,.3), Stop(-.3,1.,.01,.4,-1.,1.),
               Stop(.5,.05,1.,1.,0.,0.), Stop(0.,.6,.5,1.,0.,2.),
               Stop(.01, .8, .05, .5, .35, .01)]
        for p in cases:
            result=regenerative_boundary_sensitivity(p)
            self.assertAlmostEqual(result.boundary,float(mp_boundary(p)),delta=1e-10*(1+abs(result.boundary)))
            for key in self.PARAMS:
                oracle=float(mp_derivative(p,key))
                observed=getattr(result,key)
                with self.subTest(p=p,key=key):
                    self.assertLess(abs(oracle-observed),3e-8*(1+abs(oracle)),(oracle,observed))

    def test_seeded_128_randomized_high_precision_directions(self):
        rng=random.Random(2026103101)
        admitted = 0
        refused = 0
        for n in range(128):
            p=Stop(drift=rng.uniform(-.6,.6),diffusion=rng.uniform(.12,1.5),
                   discount=rng.uniform(.015,1.1), cost=rng.uniform(.4,4),
                   reset=0., refractory=rng.uniform(.0,2.))
            p=replace(p,reset=p.cost-rng.uniform(.15,3.))
            try:
                result=regenerative_boundary_sensitivity(p)
            except ArithmeticError:
                refused += 1
                continue
            admitted += 1
            key=self.PARAMS[n % 6]
            oracle=float(mp_derivative(p,key))
            error=abs(getattr(result,key)-oracle)
            self.assertLess(error,5e-8*(1+abs(oracle)),(n,p,key,error,oracle))
        # These are finite-domain *refusals*, not passes or certified proofs.
        self.assertEqual((admitted, refused), (121, 7))

    def test_f64_differentiation_matches_high_precision_reference(self):
        p=Stop(.1,.4,.1,1.,0.,.3)
        result=regenerative_boundary_sensitivity(p)
        for key in self.PARAMS:
            base=getattr(p,key)
            step=1e-5*max(1.,abs(base))
            if key=='refractory' and base==0:
                continue
            a=replace(p,**{key:base-step})
            b=replace(p,**{key:base+step})
            approx=(regenerative_boundary(b)-regenerative_boundary(a))/(2*step)
            self.assertAlmostEqual(approx,getattr(result,key),delta=3e-6*(1+abs(approx)))

    def test_signs_and_analytic_conditions(self):
        for p in (Stop(.1,.4,.1,1.,0.,.3),Stop(-.3,1.,.01,.4,-1.,1.)):
            res=regenerative_boundary_sensitivity(p)
            self.assertGreater(res.cost,0)
            self.assertLess(res.reset,0)
            self.assertGreaterEqual(res.refractory,0)
            self.assertGreater(res.renewal_t,0)
            self.assertGreater(res.discount_factor,0)
            self.assertLess(res.discount_factor,1)
            self.assertLess(abs(res.renewal_t+res.discount_factor-1),1e-14)

    def test_ill_conditioned_f64_boundary_fails_closed(self):
        # The optimal boundary can be too near K to be represented with a
        # stable f64 sensitivity, even when the Stop parameters are finite.
        p=Stop(0.,1.,1e-18,1.,math.nextafter(1.,0.),0.)
        with self.assertRaises((ArithmeticError,ValueError)):
            regenerative_boundary_sensitivity(p)

    def test_no_projection_onto_prohibited_parameter_domain(self):
        with self.assertRaises(ValueError):
            Stop(.1,0.,.1,1.,0.,0.)
        with self.assertRaises(ValueError):
            Stop(.1,.3,.1,1.,1.,0.)
        with self.assertRaises(ValueError):
            Stop(.1,.3,-.1,1.,0.,0.)


if __name__=='__main__':
    unittest.main()
