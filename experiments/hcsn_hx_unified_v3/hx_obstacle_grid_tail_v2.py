"""Independent, finite-domain HX equity obstacle *diagnostic* (research only).

The model uses HX's financial cash-flow contract, but DOES NOT invoke its
published Eq.(8)/(12)/(A7), analytic free boundary or Green resolvent.
A fixed candidate default level b determines the debt cash flow. On a log
asset grid y=log(A/b), it solves
    max{(L-r)V + delta*A + B(A;b,T) - C, -V}=0,
where C=(1-tax)*coupon + principal/T, B is reconstructed by numerically
integrating the Brownian first-hit *density* rather than the HX bond formula.
This is a fixed-b obstacle audit; it is NOT a jointly solved self-consistent
financial equilibrium, continuum certificate or production kernel.
"""

from dataclasses import dataclass
import math
import warnings

from scipy.integrate import quad, IntegrationWarning


class UnresolvedObstacle(ValueError):
    """Fail closed on unsupported, ill-conditioned, or unconverged regimes."""


@dataclass(frozen=True)
class ObstacleGrid:
    candidate_boundary: float
    log_upper: float
    nodes: int
    values: tuple[float, ...]
    stop: tuple[bool, ...]
    max_bellman_residual: float
    iterations: int
    last_stop_asset: float | None
    max_bond_quadrature_error: float
    tail_assumption: str

    def at(self, asset: float) -> float:
        if not (math.isfinite(asset) and asset >= self.candidate_boundary
                and asset <= self.candidate_boundary*math.exp(self.log_upper)):
            raise UnresolvedObstacle('asset outside discrete grid')
        w=math.log(asset/self.candidate_boundary)*(self.nodes-1)/self.log_upper
        j=min(int(w),self.nodes-2)
        alpha=min(1.0,max(0.0,w-j))
        return (1-alpha)*self.values[j]+alpha*self.values[j+1]


def _validate(p, b: float, log_upper: float, nodes: int):
    fields=('rate','payout','volatility','maturity','principal','coupon',
            'tax_shield','recovery','shock_intensity','sale_fraction')
    try:
        d={k:getattr(p,k) for k in fields}
    except (AttributeError,TypeError) as e:
        raise UnresolvedObstacle('missing financial parameters') from e
    if any(type(v) not in (int,float) or not math.isfinite(v) for v in d.values()):
        raise UnresolvedObstacle('nonfinite financial parameters')
    if not (d['rate']>0 and d['payout']>0 and d['volatility']>0
            and d['maturity']>0 and d['principal']>0 and d['coupon']>=0
            and 0<=d['tax_shield']<=1 and 0<=d['recovery']<=1
            and d['shock_intensity']>=0 and 0<=d['sale_fraction']<=1):
        raise UnresolvedObstacle('unsupported financial domain, including payout=0')
    if not (type(b) in (int,float) and math.isfinite(b) and b>0
            and type(log_upper) in (int,float) and math.isfinite(log_upper)
            and .5<=log_upper<=6.0 and type(nodes) is int
            and 33<=nodes<=4001 and nodes%2==1):
        raise UnresolvedObstacle('invalid candidate boundary or grid')
    h=log_upper/(nodes-1)
    if not (math.isfinite(b*math.exp(log_upper)) and math.isfinite(h)):
        raise UnresolvedObstacle('unrepresentable asset range')
    return d


def bond_from_first_hit(p, asset: float, b: float,
                        *, epsabs: float=2e-10) -> tuple[float,float]:
    """Independent Brownian first-hit density quadrature for a fixed b.

    Change variable t = (log(A/b)/(sigma*u))^2. The density measure is
       sqrt(2/pi)*exp(-(u+a*log(A/b)/u)^2/2) du.
    Integrate *both* survival and discounted hitting; no Eq.(8) or CDF.
    Return price and worst reported absolute quadrature error, not a rigorous
    interval enclosure. Near-discontinuous boundary values are deliberately
    checked by the caller rather than smoothed or clamped.
    """
    rate=p.rate; sigma=p.volatility; T=p.maturity
    if not all(math.isfinite(z) for z in (asset,b,epsabs)) or asset<=0 or b<=0 or epsabs<=0:
        raise UnresolvedObstacle('invalid bond state')
    q=rate+p.shock_intensity*p.sale_fraction
    base=p.coupon/T/q
    principal=p.principal/T
    recovery=p.recovery*b/T
    if asset<=b:
        return recovery,0.0
    v=math.log(asset/b)
    mu=rate-p.payout-.5*sigma*sigma
    a=mu/(sigma*sigma)
    lower=v/(sigma*math.sqrt(T))
    k=(v/sigma)**2
    def density(u):
        if u<=0: return 0.0
        return math.sqrt(2/math.pi)*math.exp(-.5*(u+a*v/u)**2)
    def discounted(u):
        return density(u)*math.exp(-q*k/(u*u)) if u>0 else 0.0
    try:
        with warnings.catch_warnings():
            warnings.simplefilter('error', IntegrationWarning)
            F,ef=quad(density,lower,math.inf,epsabs=epsabs,epsrel=1e-10,limit=220)
            G,eg=quad(discounted,lower,math.inf,epsabs=epsabs,epsrel=1e-10,limit=220)
    except (OverflowError,ValueError,IntegrationWarning) as e:
        raise UnresolvedObstacle('unresolved first-hit integration') from e
    if not (math.isfinite(F) and math.isfinite(G) and -1e-9<=G<=F+1e-9
            and F<=1+1e-9 and max(ef,eg)<1e-7):
        raise UnresolvedObstacle('invalid first-hit probabilities/quadrature')
    price=(base+math.exp(-q*T)*(principal-base)*(1-F)+(recovery-base)*G)
    if not math.isfinite(price):
        raise UnresolvedObstacle('nonfinite bond price')
    return price,max(ef,eg)


def _thomas(lower,diag,upper,rhs):
    n=len(diag)
    c=[0.0]*n; y=[0.0]*n
    for i in range(n):
        z=diag[i]-(lower[i]*c[i-1] if i else 0.0)
        if not (math.isfinite(z) and z>0):
            raise UnresolvedObstacle('nonpositive M-matrix pivot')
        c[i]=upper[i]/z
        y[i]=(rhs[i]-(lower[i]*y[i-1] if i else 0.0))/z
    for i in range(n-2,-1,-1):
        y[i]-=c[i]*y[i+1]
    if not all(math.isfinite(v) for v in y):
        raise UnresolvedObstacle('nonfinite obstacle value')
    return y


def solve_fixed_boundary_obstacle(p, candidate_boundary: float, *,
                                  log_upper: float=3.6, nodes: int=301,
                                  max_iterations: int=100) -> ObstacleGrid:
    """Monotone finite difference policy iteration, stop payoff precisely 0.

    Bottom is V(0)=0 (default). At top, a NO-DEFAULT asymptotic tail is
    imposed; finite-domain/mesh/domain sensitivity MUST be audited separately.
    """
    d=_validate(p,candidate_boundary,log_upper,nodes)
    if type(max_iterations) is not int or not 1<=max_iterations<=1000:
        raise UnresolvedObstacle('invalid iteration budget')
    b=candidate_boundary; h=log_upper/(nodes-1)
    drift=d['rate']-d['payout']-.5*d['volatility']**2
    diff=.5*(d['volatility']/h)**2
    ql=diff-drift/(2*h); qr=diff+drift/(2*h)
    if min(ql,qr)<0:
        ql=diff+max(0.,-drift)/h
        qr=diff+max(0.,drift)/h
    q=d['rate']+ql+qr
    if not all(math.isfinite(z) and z>0 for z in (ql,qr,q)):
        raise UnresolvedObstacle('unresolved generator rates')
    const=(1-d['tax_shield'])*d['coupon']+d['principal']/d['maturity']
    bond_discount=d['rate']+d['shock_intensity']*d['sale_fraction']
    bond_coupon_base=d['coupon']/d['maturity']/bond_discount
    bond_par=d['principal']/d['maturity']
    # At zero default probability, the surviving maturity-T bond still pays
    # its principal: B(infty)=c/q+exp(-q*T)*(par-c/q), not merely c/q.
    debt_far=bond_coupon_base+math.exp(-bond_discount*d['maturity'])*(bond_par-bond_coupon_base)
    top=b*math.exp(log_upper)+(debt_far-const)/d['rate']
    if not math.isfinite(top) or top<=0:
        raise UnresolvedObstacle('no valid positive far-field Dirichlet value')
    cash=[0.0]*nodes
    worst_quad=0.0
    for i in range(1,nodes-1):
        asset=b*math.exp(i*h)
        debt,err=bond_from_first_hit(p,asset,b)
        worst_quad=max(worst_quad,err)
        cash[i]=d['payout']*asset+debt-const
    policy=[False]*nodes  # False=continue; True=exercise/STOP
    policy[0]=True
    values=None
    for iteration in range(1,max_iterations+1):
        sub=[0.0]*nodes; diag=[1.0]*nodes; sup=[0.0]*nodes
        rhs=[0.0]*nodes; rhs[-1]=top
        for i in range(1,nodes-1):
            if not policy[i]:
                sub[i]=-ql; diag[i]=q; sup[i]=-qr; rhs[i]=cash[i]
        values=_thomas(sub,diag,sup,rhs)
        changed=False
        for i in range(1,nodes-1):
            continuation=(ql*values[i-1]+qr*values[i+1]+cash[i])/q
            # Use a fixed tie policy for stability; ties remain STOP.
            choose_stop=continuation<=1e-12*(1+abs(continuation))
            if choose_stop!=policy[i]:
                policy[i]=choose_stop; changed=True
        if not changed:
            break
    else:
        raise UnresolvedObstacle('obstacle policy iteration did not converge')
    residual=max(abs(values[i]-max(0.,(ql*values[i-1]+qr*values[i+1]+cash[i])/q))
                 for i in range(1,nodes-1))
    if residual>1e-7*(1+max(abs(z) for z in values)) or min(values)<-1e-8:
        raise UnresolvedObstacle('finite grid complementarity violated')
    stops=[i for i in range(1,nodes-1) if policy[i]]
    last=b*math.exp(max(stops)*h) if stops else None
    return ObstacleGrid(b,log_upper,nodes,tuple(values),tuple(policy),residual,
                        iteration,last,worst_quad,
                        'finite-maturity no-default bond, payout>0, finite log-domain')
