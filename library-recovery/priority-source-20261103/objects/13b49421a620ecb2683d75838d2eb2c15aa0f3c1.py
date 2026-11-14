"""P0 separate constant-cost smooth-pasting stopping problem.

NOT original He–Xiong rollover debt/equity model; allows exact PDE/boundary
regression and independent finite differences for a simplified obstacle.
"""
from __future__ import annotations
import math
from dataclasses import dataclass
from mpmath import mp

@dataclass(frozen=True)
class SimpleStopping:
    r:float
    payout:float
    sigma:float
    cost:float

    def validate(self):
        if not all(math.isfinite(v) and v>0 for v in
                   (self.r,self.payout,self.sigma,self.cost)):
            raise ValueError('r,payout,sigma,cost must be positive finite')


def _params(p):
    p.validate()
    r,d,s,k=[mp.mpf(repr(v)) for v in (p.r,p.payout,p.sigma,p.cost)]
    nu=r-d-s*s/2
    rad=mp.sqrt(nu*nu+2*r*s*s)
    # Cancellation-safe positive root when nu<0.
    gamma=(nu+rad)/(s*s) if nu>=0 else 2*r/(rad-nu)
    b=gamma*k/(r*(1+gamma))
    return r,d,s,k,gamma,b


def evaluate(p:SimpleStopping,ratio:float,dps=90):
    if not math.isfinite(ratio) or ratio<1:
        raise ValueError('ratio must be finite and >=1')
    if not 40<=dps<=200:
        raise ValueError('invalid precision')
    with mp.workdps(dps):
        r,d,s,k,g,b=_params(p)
        z=mp.mpf(repr(ratio))
        # Re-express in log-domain with expm1 near z=1 to avoid cancellation.
        w=mp.log(z)
        C=mp.expm1(w)+mp.expm1(-g*w)/g
        if abs(w)<mp.mpf('0.0001'):
            # sum_{k>=2} [(1+(-1)^k*g^(k-1))*w^k/k!]
            C=mp.nsum(lambda n: (1+(-1)**n*g**(n-1))*w**n/mp.factorial(n), [2,25])
        Q=mp.exp(-g*w)
        E=b*C
        EV=1-Q/z
        EVV=(g+1)*Q/(b*z*z)
        V=b*z
        residual=(r-d)*V*EV + s*s*V*V*EVV/2+d*V-k-r*E
        return {'gamma':mp.nstr(g,dps-10),'boundary':mp.nstr(b,dps-10),
                'equity':mp.nstr(E,dps-10),
                'discounted_hit':mp.nstr(Q,dps-10),
                'd_equity_d_asset':mp.nstr(EV,dps-10),
                'd2_equity_d_asset2':mp.nstr(EVV,dps-10),
                'pde_residual':mp.nstr(residual,22),
                'right_boundary_derivative_C':'0.0',
                'right_boundary_derivative_Q':mp.nstr(-g,22),
                'model':'simplified_constant_cost_obstacle_NOT_full_HX'}


def derivative_check(p:SimpleStopping,ratio:float,dps=80):
    if not math.isfinite(ratio) or ratio<=1:
        raise ValueError('strictly interior ratio only')
    with mp.workdps(dps):
        r,d,s,k,g,b=_params(p)
        z=mp.mpf(repr(ratio))
        V=b*z
        f=lambda vv:vv-k/r+(b/g)*(b/vv)**g
        d1=mp.diff(f,V)
        d2=mp.diff(f,V,2)
        analytic_d1=1-(b/V)**(g+1)
        analytic_d2=(g+1)*(b/V)**g*b/(V*V)
        return {'first_derivative_error':mp.nstr(abs(d1-analytic_d1),22),
                'second_derivative_error':mp.nstr(abs(d2-analytic_d2),22)}
