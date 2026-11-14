"""Independent fixed-financial-barrier HX *debt* PDE candidate, research only.

Finite-maturity financial bond, log-distance y=log(A/b)>0:
    B_tau = 0.5*sigma**2 B_yy + (r-delta-sigma**2/2) B_y
            - q B + coupon / T.

This implementation does not import the analytic bond Eq.(8), HX Eq.(12)/
(A7), a financial Green resolvent, nor an earlier debt PDE implementation.
It uses two backward-Euler half-steps (Rannacher damping) for the incompatible
terminal/default corner, then positivity-guarded Crank-Nicolson. A numerical
PDE residual and comparisons on bounded grids are NOT continuum/rounding
certificates or proof of a coupled financial equilibrium.
"""
from dataclasses import dataclass
import math

class UnresolvedRannacher(ValueError):
    """Fail closed on unsupported grid, parameters, M-matrix or work budget."""

@dataclass(frozen=True)
class RannacherBondGrid:
    barrier: float
    log_upper: float
    duration: float
    nodes: int
    time_steps: int
    values: tuple[float, ...]
    minimum_pivot: float
    max_step_residual: float
    grid_step: float
    positivity_proved_for_discrete_weights: bool
    method: str = '2 half-step backward Euler; remainder Crank-Nicolson'
    terminal_corner: str = 'default wins at y=0,tau=0; principal at y>0,tau=0'
    upper_boundary: str = 'no-default finite-maturity bond, NOT true far-field enclosure'
    scientific_gate_closed: bool = False
    production_activation: bool = False

    def at(self, asset:float)->float:
        if (type(asset) not in (int,float) or not math.isfinite(asset)
                or asset<self.barrier or asset>self.barrier*math.exp(self.log_upper)):
            raise UnresolvedRannacher('asset outside discrete financial domain')
        z=math.log(asset/self.barrier)/self.grid_step
        j=min(int(z),self.nodes-2)
        a=max(0.,min(1.,z-j))
        return (1-a)*self.values[j]+a*self.values[j+1]


def solve_bond_rannacher(p,barrier:float,*,duration:float|None=None,
                         log_upper:float=3.6,nodes:int=201,
                         time_steps:int=500)->RannacherBondGrid:
    fields=('rate','payout','volatility','maturity','principal','coupon',
            'tax_shield','recovery','shock_intensity','sale_fraction')
    try:
        vals=tuple(getattr(p,k) for k in fields)
    except (TypeError,AttributeError) as exc:
        raise UnresolvedRannacher('missing financial parameters') from exc
    if (any(type(x) not in (int,float) or not math.isfinite(x) for x in vals)
            or p.rate<=0 or p.payout<0 or p.volatility<=0 or p.maturity<=0
            or p.principal<=0 or p.coupon<0 or p.shock_intensity<0
            or not 0<=p.tax_shield<=1 or not 0<=p.recovery<=1
            or not 0<=p.sale_fraction<=1):
        raise UnresolvedRannacher('invalid financial parameter domain')
    if duration is None:
        duration=p.maturity
    if not (type(duration) in (int,float) and math.isfinite(duration)
            and 0<=duration<=p.maturity and type(barrier) in (int,float)
            and math.isfinite(barrier) and barrier>0
            and type(log_upper) in (int,float) and math.isfinite(log_upper)
            and 1<=log_upper<=12 and type(nodes) is int
            and 33<=nodes<=5001 and type(time_steps) is int
            and 1<=time_steps<=20000 and nodes*time_steps<=10_000_000
            and math.isfinite(barrier*math.exp(log_upper))):
        raise UnresolvedRannacher('invalid finite mesh, horizon or work budget')
    h=log_upper/(nodes-1)
    drift=p.rate-p.payout-.5*p.volatility*p.volatility
    diff=.5*(p.volatility/h)**2
    ql=diff-drift/(2*h)
    qr=diff+drift/(2*h)
    if min(ql,qr)<0:
        ql=diff+max(0.,-drift)/h
        qr=diff+max(0.,drift)/h
    q=p.rate+p.shock_intensity*p.sale_fraction
    gen=q+ql+qr
    if not all(math.isfinite(z) and z>0 for z in (h,ql,qr,q,gen)):
        raise UnresolvedRannacher('nonpositive jump/discount rate')
    coupon=p.coupon/p.maturity
    principal=p.principal/p.maturity
    recovery=p.recovery*barrier/p.maturity
    base=coupon/q
    far=lambda t:base+math.exp(-q*t)*(principal-base)
    if duration==0:
        return RannacherBondGrid(barrier,log_upper,0.,nodes,time_steps,
            (recovery,)+tuple([principal]*(nodes-1)),1.,0.,h,True)
    dt=duration/time_steps
    # CN right-hand weights must be nonnegative; otherwise refuse instead of
    # quietly claiming monotonicity/maximum principle on an inadmissible mesh.
    if dt*gen/2>1:
        raise UnresolvedRannacher('CN positivity CFL violated: increase time_steps')
    n=nodes-2
    def factor(fraction):
        ell=-fraction*ql; upp=-fraction*qr; dia=1+fraction*gen
        cs=[0.]*n;pivots=[0.]*n
        minimum=dia
        for i in range(n):
            pivot=dia-(ell*cs[i-1] if i else 0.)
            if not math.isfinite(pivot) or pivot<=0:
                raise UnresolvedRannacher('nonpositive M-matrix elimination pivot')
            pivots[i]=pivot
            minimum=min(minimum,pivot)
            cs[i]=upp/pivot if i<n-1 else 0.
        return ell,upp,pivots,cs,minimum
    be=factor(.5*dt)
    cn=factor(.5*dt)
    # Same left-hand matrix (I-.5*dt*G) in BE half-steps and CN full steps.
    worst=0.
    def step(previous,now,half_be):
        nonlocal worst
        ell,upp,pivots,cs,_=be if half_be else cn
        frac=.5*dt
        left=recovery;right=far(now)
        rhs=[0.]*n
        for j in range(n):
            i=j+1
            if half_be:
                val=previous[i]+frac*coupon
            else:
                val=((1-frac*gen)*previous[i]+frac*(ql*previous[i-1]
                      +qr*previous[i+1])+dt*coupon)
            if i==1: val+=frac*ql*left
            if i==nodes-2: val+=frac*qr*right
            rhs[j]=val
        f=[0.]*n
        for j in range(n):
            f[j]=(rhs[j]-(ell*f[j-1] if j else 0.))/pivots[j]
        v=[0.]*n
        v[-1]=f[-1]
        for j in range(n-2,-1,-1):
            v[j]=f[j]-cs[j]*v[j+1]
        current=[left]+v+[right]
        if not all(math.isfinite(z) for z in current):
            raise UnresolvedRannacher('nonfinite numerical debt state')
        for j in range(n):
            i=j+1
            defect=((1+frac*gen)*current[i]
                    -frac*ql*(current[i-1] if i>1 else 0.)
                    -frac*qr*(current[i+1] if i<nodes-2 else 0.)-rhs[j])
            worst=max(worst,abs(defect))
        return current
    prev=[recovery]+[principal]*(nodes-1)
    # Step to dt/2, then dt. The incompatible maturity/default corner remains
    # explicit: its discontinuity is damped, not altered into a fake match.
    prev=step(prev,dt/2,True)
    prev=step(prev,dt,True)
    for k in range(2,time_steps+1):
        prev=step(prev,k*dt,False)
    return RannacherBondGrid(barrier,log_upper,duration,nodes,time_steps,
        tuple(prev),min(be[4],cn[4]),worst,h,True)
