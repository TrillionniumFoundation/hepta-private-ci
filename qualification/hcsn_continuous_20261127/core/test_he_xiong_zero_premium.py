"""Independent smooth-fit/Green checks for Published's coincident discount roots."""
from dataclasses import replace
import math
import unittest

import numpy as np
import torch

from he_xiong import Law, Published


def reference(p, principal, margins):
    """Build the boundary from the integrated equity ODE, then solve its IVP."""
    var = p.sigma**2
    mu = p.r - p.payout - var/2
    eta = (math.sqrt(mu**2 + 2*p.r*var) - mu) / var
    q = p.r+p.premium
    c, par = p.C/p.m, principal/p.m

    def passage(x, discount):
        speed = math.hypot(mu, p.sigma*math.sqrt(2*discount))
        width = p.sigma*math.sqrt(p.m)
        def phi(z):
            return .5*math.erfc(-z/math.sqrt(2))
        return (math.exp((speed-mu)*x/var)*phi((-x-speed*p.m)/width)
                + math.exp((-speed-mu)*x/var)*phi((-x+speed*p.m)/width))

    def integ(discount):
        # The growing integration domain ends at least 14 Gaussian widths
        # past the drift shift, where the first-hit integral tail is negligible
        # for the declared contracts. Integrate the constant terms analytically.
        end = 14*p.sigma*math.sqrt(p.m) + abs(mu)*p.m + 1
        nodes, weights = np.polynomial.legendre.leggauss(64)
        xs = (nodes+1)*end/2
        return end/2*sum(w*math.exp(-eta*x)*passage(x,discount) for x,w in zip(xs,weights))

    fd, gd = integ(0.), integ(q)
    adj = math.exp(-q*p.m)*(par-c/q)
    b = (((1-p.tax)*p.C + par - c/q)/eta-adj*(1/eta-fd)+c/q*gd
         ) / (p.payout/(eta-1)+p.alpha/p.m*gd)

    def equation(x,y):
        bond = c/q + adj*(1-passage(x,0)) + (p.alpha*b/p.m-c/q)*passage(x,q)
        income = p.payout*b*math.exp(x) - (1-p.tax)*p.C + bond-par
        return y[1], 2/var*(p.r*y[0]-mu*y[1]-income)

    # Integrate over successive live margins with a classical RK4 step. This
    # reference has no dependency on the closed-form boundary or A7 basis.
    value = np.zeros(2)
    output = []
    start = 0.
    for target in margins:
        steps = max(1,math.ceil((target-start)/.001))
        h = (target-start)/steps
        for j in range(steps):
            x = start+j*h
            k1 = np.asarray(equation(x,value))
            k2 = np.asarray(equation(x+h/2,value+h*k1/2))
            k3 = np.asarray(equation(x+h/2,value+h*k2/2))
            k4 = np.asarray(equation(x+h,value+h*k3))
            value = value+h*(k1+2*k2+2*k3+k4)/6
        output.append(value.copy())
        start = target
    return b,np.stack(output,axis=1)


class PublishedZeroPremium(unittest.TestCase):
    def compare(self, p, principal):
        law = Published(p)
        margins = [0.,.004,.18,.42,.85]
        x = torch.tensor(margins,dtype=torch.float64,requires_grad=True)
        debt = torch.full_like(x,principal,requires_grad=True)
        value = law.equity(x,debt)
        dx, dp = torch.autograd.grad(value.sum(),(x,debt))
        expected_b, (expected_v, expected_x) = reference(p,principal,margins)
        _, (plus, _) = reference(p,principal+1,margins)
        # Equity is affine in the nominal principal at fixed log margin.
        self.assertLess(abs(law.boundary(principal)-expected_b), 5e-9)
        for actual, expected in [(value,expected_v),(dx,expected_x),(dp,plus-expected_v)]:
            torch.testing.assert_close(actual.detach(),torch.as_tensor(expected),
                                       rtol=2e-8,atol=1.5e-8)

    def test_zero_and_nonzero_contracts(self):
        for premium in (0.,1e-16,1e-12,1e-8,1e-5,.01,.04):
            with self.subTest(premium=premium):
                self.compare(Law(premium=premium),61.68)

    def test_alternative_law_and_principal(self):
        for premium in (0.,1e-11,.005):
            with self.subTest(premium=premium):
                p = Law(r=.06,payout=.022,sigma=.31,m=2.,premium=premium)
                self.compare(p,49.)

    def test_switch_matches_independent_solution_on_both_sides(self):
        p = Law()
        a=(p.r-p.payout-.5*p.sigma**2)/p.sigma**2
        z=math.sqrt(a*a+2*p.r/p.sigma**2)
        switch = .5*p.sigma**2*((z+1e-4*max(1,z))**2-z*z)
        for scale in (.999,1.001):
            with self.subTest(scale=scale):
                self.compare(replace(p,premium=switch*scale),72.)

    def test_absorbed_extension_and_cuda_free_backward(self):
        law = Published(Law(premium=0.))
        x = torch.tensor([-.1,0.,.18],dtype=torch.float64,requires_grad=True)
        p = torch.full_like(x,61.68,requires_grad=True)
        equity,risk = law.values(x,p)
        torch.testing.assert_close(equity[:2],torch.zeros_like(equity[:2]))
        torch.testing.assert_close(risk[:2],torch.ones_like(risk[:2]))
        gx,gp = torch.autograd.grad((equity+risk).sum(),(x,p))
        self.assertTrue(torch.isfinite(gx).all() and torch.isfinite(gp).all())
        self.assertGreater(abs(gx[-1].item()),1.)
        self.assertNotEqual(gp[-1].item(),0.)


if __name__ == "__main__":
    unittest.main()
