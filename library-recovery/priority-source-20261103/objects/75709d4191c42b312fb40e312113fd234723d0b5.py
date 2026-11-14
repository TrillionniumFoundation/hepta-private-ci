"""P0 independent *full rollover-coupled* He-Xiong (2012) Eq (8)/(11) solver.

Finite-difference free-boundary solver with FPT bond price, not closed-form A7.
Intended to cross-check actual upstream HX code once its exact source is present.
Uses finite v=log(V/B) truncation and second order grid approximation; not an
all-parameter proof, not certified error intervals, not a regenerative QVI.
Source: He & Xiong (2012), Journal of Finance pp.399-401, Eq (8),(11),(12).
"""
from __future__ import annotations
from dataclasses import dataclass
import math
import numpy as np
from scipy.special import log_ndtr
from scipy.sparse import diags
from scipy.sparse.linalg import spsolve

@dataclass(frozen=True)
class HXCoupled:
    rate:float=.08
    payout:float=.03
    volatility:float=.25
    maturity:float=2.0
    shock_intensity:float=.1
    sale_fraction:float=.2
    recovery_fraction:float=.6
    tax_shield:float=.27
    total_coupon:float=.08
    total_principal:float=1.0

    def validate(self):
        scalars=vars(self)
        if any(not math.isfinite(x) for x in scalars.values()):
            raise ValueError('nonfinite parameter')
        positive=('rate','payout','volatility','maturity','total_principal')
        if any(scalars[k]<=0 for k in positive):
            raise ValueError('zero/negative HX positive parameter')
        if any(scalars[k]<0 for k in ('shock_intensity','sale_fraction','total_coupon')):
            raise ValueError('invalid negative HX parameter')
        if not 0<=self.recovery_fraction<=1 or not 0<=self.tax_shield<1:
            raise ValueError('HX fractions out of legal domain')
        if self.sale_fraction>1:
            raise ValueError('sale fraction cannot exceed 1')

    @property
    def discount(self):return self.rate+self.shock_intensity*self.sale_fraction


def _exp_cdf(log_multiplier,arg):
    with np.errstate(over='ignore',under='ignore',invalid='raise'):
        value=np.exp(np.asarray(log_multiplier)+log_ndtr(np.asarray(arg)))
    if not np.all(np.isfinite(value)):
        raise ArithmeticError('unresolved exponential Gaussian tail')
    return value


def first_hit_factors(p,v,tau=None):
    p.validate()
    v=np.asarray(v,dtype=np.float64)
    if not np.all(np.isfinite(v)) or np.any(v<0):raise ValueError('negative log distance')
    t=p.maturity if tau is None else tau
    if not math.isfinite(t) or t<0:raise ValueError('invalid horizon')
    if t==0:return np.where(v==0,1.,0.),np.where(v==0,1.,0.)
    sig=p.volatility
    mu=p.rate-p.payout-.5*sig*sig
    q=p.discount
    z=math.sqrt(mu*mu+2*q*sig*sig)/(sig*sig)
    a=mu/(sig*sig)
    u=sig*math.sqrt(t)
    F=_exp_cdf(0.,(-v-mu*t)/u)+_exp_cdf(-2*a*v,(-v+mu*t)/u)
    G=(_exp_cdf((-a+z)*v,(-v-z*sig*sig*t)/u)+
       _exp_cdf((-a-z)*v,(-v+z*sig*sig*t)/u))
    # The stable physical envelope must be checked before any use in a price.
    # Naive F-G may be numerically unresolved for near-boundary tiny horizons.
    F=np.where(v==0,1.0,F)
    G=np.where(v==0,1.0,G)
    if np.any((F<0)|(G<0)|(F>1)|(G>1)|(G>F)):
        raise ArithmeticError('f64 FPT factors violate exact physical order')
    # Even when F=G numerically, they may differ in exact mathematics.
    # This solver is only a moderate-domain independent reference.
    return F,G


def bond_price(p,v,boundary):
    p.validate()
    if not math.isfinite(boundary) or boundary<0:
        raise ValueError('invalid equity boundary')
    v=np.asarray(v,dtype=float)
    if np.any(v<0):raise ValueError('not in continuation domain')
    F,G=first_hit_factors(p,v)
    q=p.discount;m=p.maturity
    principal=p.total_principal/m
    coupon=p.total_coupon/m
    riskless=coupon/q
    return (riskless+math.exp(-q*m)*(principal-riskless)*(1-F)
            +(p.recovery_fraction*boundary/m-riskless)*G)


def _linear_equity(p,b,L,N):
    v=np.linspace(0.,L,N+1)
    h=L/N
    sig=p.volatility
    mu=p.rate-p.payout-.5*sig*sig
    D=sig*sig/2
    d=bond_price(p,v,b)
    principal=p.total_principal/p.maturity
    f=-(1-p.tax_shield)*p.total_coupon + d-principal
    # E=B*exp(v)+U, so D U'' + mu U' - r U + f = 0.
    # U(0)=-B; U(L)=f_infty/r. f_infty excludes default tails.
    q=p.discount; c=p.total_coupon/p.maturity
    riskless=c/q
    d_inf=riskless+math.exp(-q*p.maturity)*(principal-riskless)
    f_inf=-(1-p.tax_shield)*p.total_coupon+d_inf-principal
    left=-b;right=f_inf/p.rate
    lower=D/h**2-mu/(2*h)
    upper=D/h**2+mu/(2*h)
    diag=-2*D/h**2-p.rate
    A=diags([np.full(N-2,lower),np.full(N-1,diag),
             np.full(N-2,upper)],[-1,0,1],format='csc')
    rhs=-f[1:-1].copy()
    rhs[0]-=lower*left
    rhs[-1]-=upper*right
    inside=spsolve(A,rhs)
    u=np.r_[left,inside,right]
    # 2nd order one-sided derivative.
    du0=(-3*u[0]+4*u[1]-u[2])/(2*h)
    return v,u,b+du0


def solve_free_boundary(p:HXCoupled,N=800,L=10.):
    p.validate()
    if N<32 or N>100000 or not math.isfinite(L) or L<=2:
        raise ValueError('invalid finite-difference mesh')
    v0,u0,r0=_linear_equity(p,0.,L,N)
    v1,u1,r1=_linear_equity(p,1.,L,N)
    slope=r1-r0
    if not math.isfinite(slope) or abs(slope)<1e-12:
        raise ArithmeticError('degenerate/free-boundary residual slope')
    b=-r0/slope
    if not math.isfinite(b) or b<=0:
        raise ArithmeticError('no admissible positive HX free boundary')
    v,u,residual=_linear_equity(p,b,L,N)
    E=b*np.exp(v)+u
    # Finite grid can introduce tiny near-boundary E<0 numerical error;
    # require economically non-negative continuation with mesh slack.
    if np.min(E)<-1e-6*max(1.,b):
        raise ArithmeticError('equity positivity violated in continuation')
    if p.recovery_fraction*b>p.total_principal+1e-9:
        raise ArithmeticError('outside current research recovery<=principal screening policy')
    return {'boundary':float(b),'boundary_value_abs':float(abs(E[0])),
            'smooth_pasting_log_derivative_residual':float(abs(residual)),
            'min_equity':float(min(E)),'grid_points':N,'log_ceiling':L,
            'q':p.discount,
            'limit_treatment':'U(L)=far-field constant; numerical truncation',
            'original_HX_equity_A7_verified':False,
            'regenerative_QVI_solved':False}


def mesh_convergence(p=HXCoupled(),resolutions=(200,400,800,1600),L=10.):
    rows=[solve_free_boundary(p,N=n,L=L) for n in resolutions]
    boundaries=[r['boundary'] for r in rows]
    return {'rows':rows,
            'successive_boundary_deltas':[abs(y-x) for x,y in zip(boundaries,boundaries[1:])],
            'asymptotic_order_expected':2,
            'independent_analytic_A7_comparison':False}
