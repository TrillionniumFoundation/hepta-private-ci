"""He--Xiong (2012) equations (8), (9), (12), and (A7), float64.

Source: https://www.princeton.edu/~wxiong/papers/rollover.pdf
Notation follows the paper. All rates and maturities use the same time unit.
This module implements the financial model, not the simplified HCSN neuron.
"""

from dataclasses import dataclass
import math

import numpy as np
from scipy.special import ndtr, log_ndtr

if __package__:
    from .hx_precision import precision_boundary_equity
    from .admissibility import require_admissible_boundary
else:
    from hx_precision import precision_boundary_equity
    from admissibility import require_admissible_boundary


@dataclass(frozen=True)
class Parameters:
    r: float = .08
    delta: float = .02
    sigma: float = .23
    alpha: float = .6
    tax: float = .27
    liquidity: float = .01  # xi*k; only their product is identified here.
    maturity: float = 1.
    coupon: float = 6.39
    principal: float = 61.68

    def __post_init__(self):
        values = tuple(vars(self).values())
        if not np.all(np.isfinite(values)):
            raise ValueError("All parameters must be finite")
        if min(self.r, self.delta, self.sigma, self.maturity) <= 0:
            raise ValueError("r, delta, sigma and maturity must be positive")
        if self.liquidity < 0 or min(self.coupon, self.principal) < 0:
            raise ValueError("liquidity, coupon and principal must be nonnegative")
        if self.coupon + self.principal == 0:
            raise ValueError("A positive debt liability is required")
        if not (0 <= self.alpha <= 1 and 0 <= self.tax <= 1):
            raise ValueError("alpha and tax must lie in [0,1]")


def exp_cdf(exponent, argument):
    """exp(exponent)*Phi(argument), avoiding overflow times underflow."""
    return np.exp(np.asarray(exponent) + log_ndtr(argument))


def exp_phi(exponent, argument):
    return np.exp(np.asarray(exponent)-.5*np.asarray(argument)**2)/math.sqrt(2*math.pi)


def cdf_interval(lo, hi):
    """Phi(hi)-Phi(lo) with a survival-tail branch."""
    lo, hi = np.broadcast_arrays(lo, hi)
    return np.where(lo > 0, ndtr(-lo)-ndtr(-hi), ndtr(hi)-ndtr(lo))


def exp_cdf_interval(exponent, lo, hi):
    """exp(exponent)*(Phi(hi)-Phi(lo)), including extreme tails."""
    lo, hi = np.broadcast_arrays(lo, hi)
    log_big = np.where(lo > 0, log_ndtr(-lo), log_ndtr(hi))
    log_small = np.where(lo > 0, log_ndtr(-hi), log_ndtr(lo))
    return np.exp(exponent+log_big)*(-np.expm1(log_small-log_big))


class HXBoundaryCandidate:
    """Unverified Eq.(12)/A7 candidate, retained for formula and failure audits.

    Smooth pasting alone does not imply nonnegative equity. Neural consumers
    should use HXModel, which rejects an inadmissible local boundary.
    """

    def __init__(self, params=Parameters()):
        self.p = params
        self.s2 = params.sigma**2
        self.R = params.r + params.liquidity
        self.a = (params.r-params.delta-.5*self.s2)/self.s2
        self.z = math.sqrt(self.a*self.a+2*params.r/self.s2)
        self.zt = math.sqrt(self.a*self.a+2*self.R/self.s2)
        # Rationalized roots avoid catastrophic subtraction.
        self.eta = 2*params.r/(self.s2*(self.z+self.a)) if self.a >= 0 else self.z-self.a
        self.gamma = 2*params.r/(self.s2*self.eta)
        self.s = params.sigma*math.sqrt(params.maturity)
        self.c = params.coupon/params.maturity
        self.principal_unit = params.principal/params.maturity
        self.q = self.principal_unit-self.c/self.R
        self.discount = math.exp(-self.R*params.maturity)
        self.constant_cost = (1-params.tax)*params.coupon-math.expm1(-self.R*params.maturity)*self.q
        gx, gw = np.polynomial.legendre.leggauss(8)
        self._nodes, self._weights = (gx+1)/2, gw/2
        self.boundary = self.default_boundary()
        self.high_precision = params.maturity < 1e-4
        if self.high_precision:
            self.boundary, _ = precision_boundary_equity(params, [])

    def _B_derivative_numerator(self, y):
        q = .5*(self.z-y)*(self.z+y)*self.s*self.s
        return self.s*exp_phi(0, y*self.s)+y*self.s*self.s*exp_cdf(q, -self.z*self.s)

    def B_aux(self, y):
        """Paper Eq.(12) B(y), including its removable limit at y=-z."""
        denominator = self.z+y
        if abs(denominator) < 1e-3*(1+self.z):
            ys = -self.z+self._nodes*denominator
            return float(self._weights @ self._B_derivative_numerator(ys))
        q = .5*(self.z-y)*(self.z+y)*self.s*self.s
        return float((ndtr(y*self.s)-exp_cdf(q, -self.z*self.s))/denominator)

    def default_boundary(self):
        """Paper Eq.(12), algebraically stabilized but not root-fitted."""
        bs = self.discount*(self.B_aux(-self.a)+self.B_aux(self.a))
        big_bs = self.B_aux(-self.zt)+self.B_aux(self.zt)
        numerator = self.constant_cost/self.eta+self.q*bs+(self.c/self.R)*big_bs
        # delta/(eta-1) = .5*sigma^2*(gamma+1), including delta->0+.
        denominator = .5*self.s2*(self.gamma+1)+self.p.alpha/self.p.maturity*big_bs
        result = numerator/denominator
        if not np.isfinite(result) or result <= 0:
            raise ValueError("Parameters do not give a positive finite default boundary")
        return result

    def first_hit(self, x, horizon, rate=None):
        """Eq.(9): F=P(tau_b<=t), G=E[exp(-rate*tau_b) 1(tau_b<=t)].

        x=log(V/b)>=0. At the corner x=t=0, immediate default has priority.
        """
        x = np.asarray(x, dtype=float)
        if np.any(x < 0) or horizon < 0:
            raise ValueError("Continuation distance and horizon must be nonnegative")
        if horizon == 0:
            f = np.where(x == 0, 1., 0.)
            return f, f.copy()
        rate = self.R if rate is None else rate
        if rate < 0:
            raise ValueError("Discount rate must be nonnegative")
        s = self.p.sigma*math.sqrt(horizon)
        zt = math.sqrt(self.a*self.a+2*rate/self.s2)
        f = ndtr(-x/s-self.a*s)+exp_cdf(-2*self.a*x, -x/s+self.a*s)
        g = exp_cdf((-self.a+zt)*x, -x/s-zt*s)+exp_cdf((-self.a-zt)*x, -x/s+zt*s)
        return f, g

    def debt(self, x, horizon=None, boundary=None):
        """Paper Eq.(8), value of one debt unit, x=log(V/b)."""
        horizon = self.p.maturity if horizon is None else horizon
        boundary = self.boundary if boundary is None else boundary
        f, g = self.first_hit(x, horizon)
        discount = math.exp(-self.R*horizon)
        return self.c/self.R+discount*self.q*(1-f)+(self.p.alpha*boundary/self.p.maturity-self.c/self.R)*g

    def debt_decay(self, x, boundary):
        """Debt minus its x->infinity limit, without large-value subtraction."""
        f, g = self.first_hit(x, self.p.maturity)
        return -self.discount*self.q*f+(self.p.alpha*boundary/self.p.maturity-self.c/self.R)*g

    def _A_numerator(self, v, y, derivative=False):
        """K(v;a,y,gamma)+k(v;a,-y,-eta) from A7/A5, or d/dy."""
        gamma, eta, z, a, s = self.gamma, self.eta, self.z, self.a, self.s
        q = .5*(z*z-y*y)*s*s
        first = np.exp(-gamma*v)*ndtr(y*s)
        common = -exp_cdf_interval(q-gamma*v, z*s-v/s, z*s)
        common += exp_cdf(q+eta*v, -v/s-z*s)
        pos = exp_cdf(-(a+y)*v, -v/s+y*s)
        neg = exp_cdf(-(a-y)*v, -v/s-y*s)
        if not derivative:
            return first+common-pos-neg
        return (s*exp_phi(-gamma*v, y*s)-y*s*s*common
                +v*pos-s*exp_phi(-(a+y)*v, -v/s+y*s)
                -v*neg+s*exp_phi(-(a-y)*v, -v/s-y*s))

    def A_aux(self, v, y):
        """A7 A(y); evaluate removable divided differences by derivative integration.

        In the tiny near-singular interval, 8-point Gauss evaluation of the
        fundamental-theorem identity avoids subtracting two nearly equal values.
        At y=z this is the exact l'Hopital limit, not a liquidity floor.
        """
        v = np.asarray(v, dtype=float)
        result = np.zeros_like(v)
        for u in (y, -y):
            denominator = self.z-u
            if abs(denominator) < 1e-5*(1+self.z):
                for node, weight in zip(self._nodes, self._weights):
                    at = self.z-node*denominator
                    result -= weight*self._A_numerator(v, at, derivative=True)
            else:
                result += self._A_numerator(v, u)/denominator
        return result

    def equity_raw(self, x):
        """Literal A7 (using stabilized equivalent K/k combinations), no clipping."""
        x = np.asarray(x, dtype=float)
        if np.any(x < 0):
            raise ValueError("A7 is a continuation-region formula: x>=0")
        b, p = self.boundary, self.p
        decay = np.exp(-self.gamma*x)
        result = b*np.exp(x)-p.delta*b/(self.z*self.s2)*decay/(self.gamma+1)
        result -= self.constant_cost/(self.z*self.s2)*(1/self.eta-np.expm1(-self.gamma*x)/self.gamma)
        result += (self.discount*self.q*self.A_aux(x, self.a)
                   -(p.alpha*b/p.maturity-self.c/self.R)*self.A_aux(x, self.zt))/(self.z*self.s2)
        return result

    def net_cashflow(self, x, boundary=None):
        b = self.boundary if boundary is None else boundary
        return self.p.delta*b*np.exp(x)-self.constant_cost+self.debt_decay(x, b)

    def boundary_taylor(self):
        """E_xx(0), E_xxx(0), E_xxxx(0) from the ODE and analytic debt derivatives."""
        p, b, a, zt, s = self.p, self.boundary, self.a, self.zt, self.s
        f1 = -2*exp_phi(0, a*s)/s-2*a*ndtr(a*s)
        g1 = (-a+zt)*ndtr(-zt*s)+(-a-zt)*ndtr(zt*s)-2*exp_phi(0, zt*s)/s
        f2 = -2*a*f1
        g2 = 2*self.R/self.s2-2*a*g1
        recovery = p.alpha*b/p.maturity-self.c/self.R
        flow0 = p.delta*b-(1-p.tax)*p.coupon+p.alpha*b/p.maturity-self.principal_unit
        flow1 = p.delta*b-self.discount*self.q*f1+recovery*g1
        flow2 = p.delta*b-self.discount*self.q*f2+recovery*g2
        e2 = -2*flow0/self.s2
        e3 = -2*a*e2-2*flow1/self.s2
        e4 = -2*a*e3+2*p.r/self.s2*e2-2*flow2/self.s2
        return e2, e3, e4

    def equity(self, x):
        """A7 with a controlled fourth-order Taylor branch near the double zero.

        Raw A7 remains available for auditing. This branch prevents subtraction
        noise dominating values of order x^2. It is a local numerical evaluation
        approximation; its overlap error is reported by the validation suite.
        """
        x = np.asarray(x, dtype=float)
        if np.any(x < 0):
            raise ValueError("Continuation distance must be nonnegative")
        if self.high_precision:
            _, values = precision_boundary_equity(self.p, x.ravel(), digits=60)
            result = np.asarray(values).reshape(x.shape)
            return np.where(x == 0, 0., result)
        threshold = min(1e-4, 1e-3*self.s)
        result = np.zeros_like(x)
        far = x >= threshold
        result[far] = self.equity_raw(x[far])
        e2, e3, e4 = self.boundary_taylor()
        near = x[~far]
        result[~far] = near**2*(e2/2+near*(e3/6+near*e4/24))
        return result


class HXModel(HXBoundaryCandidate):
    """Full formulas with a necessary local limited-liability admission check."""

    def __init__(self, params=Parameters()):
        super().__init__(params)
        require_admissible_boundary(params, self.boundary)
