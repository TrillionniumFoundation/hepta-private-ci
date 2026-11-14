"""Independent backward finite-maturity financial bond PDE (research-only).

Brownian first-hit quadrature, HX Eq.(8)/(12)/(A7), and either equity
obstacle solver are NOT used. The *time-to-maturity* log-asset bond PDE is

  partial_tau B = sigma^2/2 partial_yy B + (r-delta-sigma^2/2)
                  partial_y B - q B + coupon/T,

with q=r+shock_intensity*sale_fraction, absorption B(0,tau)=recovery*b/T,
terminal B(y,0)=principal/T for strictly positive y, and far boundary
B(L,tau) = coupon/(T*q) + exp(-q*tau)*(principal/T-coupon/(T*q)).

At the incompatible (y=0,tau=0) corner, *default wins*; approaching
from y>0 at tau=0 instead gives principal. This genuine corner
incompatibility must not be smoothed or treated as numeric precision loss.

Positive-jump-rate spatial discretization + backward Euler in maturity.
No continuum/roundoff/tail certificate or claim of unique HX equilibrium.
"""

from dataclasses import dataclass
import math


class UnresolvedBondPDE(ValueError):
    """Refuse invalid domain, spatial truncation or nonpositive M-matrix."""


@dataclass(frozen=True)
class BondPDESolution:
    barrier: float
    log_upper: float
    duration: float
    nodes: int
    time_steps: int
    values: tuple[float, ...]
    max_time_residual: float
    minimum_pivot: float
    drift_rate: float
    left_jump_rate: float
    right_jump_rate: float
    corner_contract: str = 'default wins at asset=barrier, tau=0'
    tail_contract: str = 'exact zero-default finite-maturity bond at right grid edge'

    def at(self, asset: float) -> float:
        if (type(asset) not in (int,float) or not math.isfinite(asset)
                or asset<self.barrier or
                asset>self.barrier*math.exp(self.log_upper)):
            raise UnresolvedBondPDE('asset outside finite PDE grid')
        y=math.log(asset/self.barrier)
        z=y*(self.nodes-1)/self.log_upper
        i=min(int(z),self.nodes-2)
        frac=max(0.0,min(1.0,z-i))
        return (1-frac)*self.values[i]+frac*self.values[i+1]


def solve_bond_pde(p, barrier: float, *, duration: float | None = None,
                   log_upper: float=5., nodes: int=401,
                   time_steps: int=1200) -> BondPDESolution:
    """M-matrix backward Euler for one fixed default barrier / debt cashflow.

    Input float64 and a fully specified spatial/time grid; upper-tail error
    is NOT rigorously bounded. Comparisons to an independent physical-time
    quadrature reference must vary both log_upper and mesh/time resolution.
    """
    fields=('rate','payout','volatility','maturity','principal','coupon',
            'tax_shield','recovery','shock_intensity','sale_fraction')
    try:
        vals={k:getattr(p,k) for k in fields}
    except (TypeError,AttributeError) as e:
        raise UnresolvedBondPDE('incomplete financial parameter set') from e
    if any(type(x) not in (float,int) or not math.isfinite(x) for x in vals.values()):
        raise UnresolvedBondPDE('nonfinite financial parameters')
    if not (p.rate>0 and p.payout>=0 and p.volatility>0 and p.maturity>0
            and p.principal>0 and p.coupon>=0 and p.shock_intensity>=0
            and 0<=p.tax_shield<=1 and 0<=p.recovery<=1
            and 0<=p.sale_fraction<=1):
        raise UnresolvedBondPDE('invalid financial structural domain')
    if duration is None:
        duration=p.maturity
    if not (type(duration) in (int,float) and math.isfinite(duration)
            and 0<=duration<=p.maturity and type(barrier) in (int,float)
            and math.isfinite(barrier) and barrier>0
            and type(log_upper) in (int,float) and math.isfinite(log_upper)
            and 1<=log_upper<=12
            and type(nodes) is int and 33<=nodes<=5001
            and type(time_steps) is int and 1<=time_steps<=20000
            and nodes*time_steps<=10_000_000):
        raise UnresolvedBondPDE('invalid finite-grid duration or budget')
    if not math.isfinite(barrier*math.exp(log_upper)):
        raise UnresolvedBondPDE('nonrepresentable upper asset')

    h=log_upper/(nodes-1)
    drift=p.rate-p.payout-.5*p.volatility**2
    diffusion=.5*(p.volatility/h)**2
    ql=diffusion-drift/(2*h)
    qr=diffusion+drift/(2*h)
    if min(ql,qr)<0:
        ql=diffusion+max(0.,-drift)/h
        qr=diffusion+max(0.,drift)/h
    q=p.rate+p.shock_intensity*p.sale_fraction
    if not all(math.isfinite(z) and z>0 for z in (ql,qr,q)):
        raise UnresolvedBondPDE('nonfinite discount or generator rates')
    coupon=p.coupon/p.maturity
    par=p.principal/p.maturity
    recovery=p.recovery*barrier/p.maturity
    base=coupon/q
    def far(t):
        return base+math.exp(-q*t)*(par-base)
    if duration==0:
        return BondPDESolution(barrier,log_upper,0.,nodes,time_steps,
                               (recovery,)+tuple([par]*(nodes-1)),0.,1.,drift,ql,qr)
    dt=duration/time_steps
    if dt<=0 or not math.isfinite(dt):
        raise UnresolvedBondPDE('unresolved time step')

    # Factor the constant tri-diagonal M-matrix once; do not use HX formulas.
    # Each right-hand-side changes as we integrate from maturity to present.
    n=nodes-2
    diag=1+dt*(q+ql+qr)
    lower=-dt*ql
    upper=-dt*qr
    reduced=[0.]*n; pivots=[0.]*n
    pivot=diag
    min_pivot=pivot
    for i in range(n):
        if i:
            pivot=diag-lower*reduced[i-1]
        if not (math.isfinite(pivot) and pivot>0):
            raise UnresolvedBondPDE('nonpositive M-matrix pivot')
        min_pivot=min(min_pivot,pivot)
        pivots[i]=pivot
        reduced[i]=(upper/pivot if i<n-1 else 0.)

    prev=[par]*nodes
    prev[0]=recovery
    worst=0.
    for step in range(1,time_steps+1):
        tt=step*dt
        target_far=far(tt)
        previous=prev
        rhs=[previous[i+1]+dt*coupon for i in range(n)]
        rhs[0]+=dt*ql*recovery
        rhs[-1]+=dt*qr*target_far
        forward=[0.]*n
        for i in range(n):
            forward[i]=(rhs[i]-(lower*forward[i-1] if i else 0.))/pivots[i]
        interior=[0.]*n
        interior[-1]=forward[-1]
        for i in range(n-2,-1,-1):
            interior[i]=forward[i]-reduced[i]*interior[i+1]
        curr=[recovery]+interior+[target_far]
        if not all(math.isfinite(v) for v in curr):
            raise UnresolvedBondPDE('nonfinite backward PDE solution')
        # Discrete residual is a consistency check for Thomas solve only.
        for i in range(1,nodes-1):
            defect=(curr[i]-previous[i])/dt - (
                ql*curr[i-1]+qr*curr[i+1]-(ql+qr+q)*curr[i]+coupon)
            worst=max(worst,abs(defect))
        prev=curr
    return BondPDESolution(barrier,log_upper,duration,nodes,time_steps,
                           tuple(prev),worst,min_pivot,drift,ql,qr)
