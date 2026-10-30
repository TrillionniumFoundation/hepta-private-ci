"""Local independent numerical tests plus optional integration with HX reference."""
import math
import unittest

from .obstacle import solve_frozen_obstacle, audit_candidate, financial_cashflow


class ObstacleTests(unittest.TestCase):
    def test_exact_perpetual_abandonment_and_grid_refinement(self):
        # Unrelated closed-form Feynman--Kac stopping problem, not HX.
        r, payout, sigma, fixed = .08, .03, .25, 2.5
        mu = r-payout-.5*sigma*sigma
        gamma = (mu+math.hypot(mu, math.sqrt(2*r)*sigma))/(sigma*sigma)
        b = fixed/r * gamma/(gamma+1)
        def exact(v):
            return 0. if v <= b else v-fixed/r + b/gamma*(b/v)**gamma
        def grid(nodes):
            high = b*math.exp(5)
            return solve_frozen_obstacle(scale=b, log_min=-3, log_max=5,
                         nodes=nodes, rate=r, log_drift=mu, volatility=sigma,
                         cashflow=lambda v:payout*v-fixed,
                         upper_value=high-fixed/r)
        coarse, fine = grid(129), grid(513)
        for g in (coarse, fine):
            self.assertGreaterEqual(min(g.values), -1e-12)
            self.assertLess(g.max_complementarity_residual, 1e-8)
            self.assertLess(g.policy_iterations, 200)
            self.assertLess(abs(g.last_zero_asset-b)/b, .12 if g is coarse else .035)
        self.assertLess(abs(fine.at(2*b)-exact(2*b)), .5*abs(coarse.at(2*b)-exact(2*b)))
        self.assertLess(abs(fine.at(2*b)-exact(2*b)), .015)

    def test_independent_all_policies_on_upwind_mesh(self):
        # Independently enumerate all 2**7 finite policies, rather than
        # trusting the active-set/Howard implementation for an upwind case.
        from itertools import product
        import numpy as np
        n, drift, sigma, rate = 9, -.45, .2, .2
        low, high, scale = -2., 2., 1.
        upper_value = 1.
        cash = lambda v: .1*v-.3
        g=solve_frozen_obstacle(scale=scale, log_min=low, log_max=high,
               nodes=n,rate=rate,log_drift=drift,volatility=sigma,
               cashflow=cash,upper_value=upper_value)
        h=(high-low)/(n-1)
        d=.5*sigma*sigma/(h*h)
        # Upwind positive jump rates, derived independently.
        left=d+abs(drift)/h
        right=d
        all_values=[]
        for bits in product((False,True),repeat=n-2):
            mat=np.eye(n)
            rhs=np.zeros(n)
            rhs[-1]=upper_value
            for i,cont in enumerate(bits,1):
                if cont:
                    mat[i,i]=rate+left+right
                    mat[i,i-1]=-left
                    mat[i,i+1]=-right
                    rhs[i]=cash(g.assets[i])
            all_values.append(np.linalg.solve(mat,rhs))
        optimum=np.max(np.array(all_values),axis=0)
        self.assertLess(np.max(np.abs(optimum-np.array(g.values))),1e-11)
        self.assertLess(g.max_complementarity_residual,1e-8)

    def test_rejection_and_finite_domain_guards(self):
        f=lambda x:x-3
        kwargs=dict(scale=2,log_min=-2,log_max=2,nodes=65,
                    rate=.07,log_drift=0,volatility=.3,
                    cashflow=f,upper_value=4)
        with self.assertRaises(ValueError):
            solve_frozen_obstacle(**(kwargs | {'nodes':8}))
        with self.assertRaises(ValueError):
            solve_frozen_obstacle(**(kwargs | {'upper_value':float('nan')}))
        with self.assertRaises(ValueError):
            solve_frozen_obstacle(**(kwargs | {'cashflow':lambda _:float('nan')}))
        grid=solve_frozen_obstacle(**kwargs)
        with self.assertRaises(ValueError):
            grid.at(1e-30)
        self.assertLess(grid.max_complementarity_residual,1e-8)

    def test_hx_negative_equity_is_not_admitted(self):
        from .hx import HX, boundary, equity_closed
        bad=HX(sale_fraction=.2)
        b=boundary(bad)
        result=audit_candidate(bad,b)
        self.assertTrue(result.status.startswith('REJECT_'))
        self.assertFalse(result.certified)
        self.assertLess(equity_closed(bad,b*1.01,b), 0)
        self.assertGreater(result.boundary_cashflow, 0)
        self.assertAlmostEqual(result.boundary_cashflow,
                               financial_cashflow(bad,b,b), places=10)
        nominal=HX()
        normal_result=audit_candidate(nominal,boundary(nominal))
        self.assertFalse(normal_result.certified)
        self.assertEqual(normal_result.status,'LOCAL_NECESSARY_ONLY')

    def test_frozen_hx_bond_obstacle_and_independent_grid(self):
        from .hx import HX, boundary, equity_closed
        p=HX()
        b=boundary(p)
        def grid(n):
            hi=math.exp(5)*b
            const=(1-p.tax_shield)*p.coupon+p.per_bond_principal-(p.per_bond_coupon/p.q+math.exp(-p.q*p.maturity)*(p.per_bond_principal-p.per_bond_coupon/p.q))
            return solve_frozen_obstacle(scale=b,log_min=-3,log_max=5,
                    nodes=n,rate=p.rate,log_drift=p.rate-p.payout-.5*p.volatility**2,
                    volatility=p.volatility,
                    cashflow=lambda v:financial_cashflow(p,v,b),
                    upper_value=hi-const/p.rate)
        g1, g2=grid(129),grid(513)
        target=equity_closed(p,2*b,b)
        self.assertLess(g2.max_complementarity_residual,1e-7)
        self.assertLess(abs(g2.at(2*b)-target),abs(g1.at(2*b)-target))
        self.assertLess(abs(g2.at(2*b)-target),.05)
        # Numerical obstacle is diagnostic with frozen bond price, and not
        # a self-consistent revaluation of the rollover market.
        bad=HX(sale_fraction=.2)
        bb=boundary(bad)
        high=math.exp(5)*bb
        const=(1-bad.tax_shield)*bad.coupon+bad.per_bond_principal-(bad.per_bond_coupon/bad.q+math.exp(-bad.q*bad.maturity)*(bad.per_bond_principal-bad.per_bond_coupon/bad.q))
        g=solve_frozen_obstacle(scale=bb,log_min=-3,log_max=5,nodes=257,
                rate=bad.rate,log_drift=bad.rate-bad.payout-.5*bad.volatility**2,
                volatility=bad.volatility,
                cashflow=lambda v:financial_cashflow(bad,v,bb),
                upper_value=high-const/bad.rate)
        self.assertGreaterEqual(g.at(bb*1.01),0)
        self.assertGreater(g.at(bb*1.01),equity_closed(bad,bb*1.01,bb))


if __name__=='__main__':
    unittest.main()
