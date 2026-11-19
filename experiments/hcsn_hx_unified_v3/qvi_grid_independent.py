"""Independent finite-state discretization of the *scalar* regenerative QVI.

For dX=mu dt+sigma dW, firing at x earns x-K, resets to r<K
and enforces a fixed dead-time tau. The infinite-horizon discounted QVI is
  max{ (L-rho)V, x-K+exp(-rho*tau)*V(r)-V(x) } = 0.

This policy-iteration oracle NEVER imports the Lambert-W/Brent optimal
boundary, its value formula, or the existing analytic scalar QVI. The
finite interval has a zero lower Dirichlet boundary and an assumed-FIRE
upper boundary; mesh/truncation errors are NOT certified continuum bounds.
"""

from dataclasses import dataclass
import math


class UnresolvedGrid(ValueError):
    """Refuse invalid finite-domain, noncontractive or unresolved calculations."""


@dataclass(frozen=True)
class GridResult:
    lower: float
    upper: float
    nodes: int
    values: tuple[float, ...]
    firing: tuple[bool, ...]
    threshold: float
    reset_value: float
    bellman_residual: float
    policy_iterations: int
    grid_step: float
    lower_rate: float
    upper_rate: float

    def at(self, state: float) -> float:
        if not (math.isfinite(state) and self.lower <= state <= self.upper):
            raise UnresolvedGrid('state outside discrete domain')
        u = (state - self.lower) / self.grid_step
        j = min(int(u), self.nodes - 2)
        w = max(0.0, min(1.0, u-j))
        return self.values[j]*(1-w) + self.values[j+1]*w


def _solve_pair(sub: list[float], diag: list[float], sup: list[float],
                rhs_a: list[float], rhs_b: list[float]):
    """Independent shared-factor Thomas solve of two M-matrix systems."""
    n = len(diag)
    cs = [0.0]*n
    da = [0.0]*n
    db = [0.0]*n
    for i in range(n):
        pivot = diag[i] - (sub[i]*cs[i-1] if i else 0.0)
        if not math.isfinite(pivot) or pivot <= 0:
            raise UnresolvedGrid('nonpositive M-matrix elimination pivot')
        cs[i] = sup[i]/pivot
        da[i] = (rhs_a[i]-(sub[i]*da[i-1] if i else 0.0))/pivot
        db[i] = (rhs_b[i]-(sub[i]*db[i-1] if i else 0.0))/pivot
    for i in range(n-2, -1, -1):
        da[i] -= cs[i]*da[i+1]
        db[i] -= cs[i]*db[i+1]
    if not all(math.isfinite(x) for x in da+db):
        raise UnresolvedGrid('nonfinite policy evaluation')
    return da, db


def solve_regenerative_grid(*, drift: float, diffusion: float, discount: float,
                            cost: float, reset: float, refractory: float,
                            lower: float, upper: float, nodes: int,
                            max_iterations: int = 100) -> GridResult:
    """Monotone finite-state Howard policy iteration with endogenous V(reset).

    Continuation row: (rho+q-+q+)V_i=q-V_(i-1)+q+V_(i+1).
    FIRE row: V_i=(x_i-K)+D V(reset), with D=exp(-rho*tau).
    For a fixed policy solve V=a+b V(reset), then interpolate at reset
    and solve the scalar consistency equation V(reset)=a_r/(1-b_r).
    No analytic optimal threshold or reference value enters this calculation.
    """
    floats = (drift,diffusion,discount,cost,reset,refractory,lower,upper)
    if (any(type(x) not in (float,int) or not math.isfinite(x) for x in floats)
            or diffusion <= 0 or discount <= 0 or reset >= cost
            or refractory < 0 or lower >= reset or reset >= upper
            or upper <= cost or not (type(nodes) is int and 9 <= nodes <= 20001)
            or type(max_iterations) is not int or not 1 <= max_iterations <= 10000):
        raise UnresolvedGrid('invalid finite regenerative QVI domain')
    h = (upper-lower)/(nodes-1)
    if not math.isfinite(h) or h <= 0:
        raise UnresolvedGrid('degenerate mesh')
    # Positive-rate upwinding when centered Markov off-diagonals would be negative.
    diff_rate = 0.5*(diffusion/h)**2
    ql = diff_rate-drift/(2*h)
    qr = diff_rate+drift/(2*h)
    if min(ql,qr) < 0:
        ql = diff_rate+max(0.0,-drift)/h
        qr = diff_rate+max(0.0,drift)/h
    if not all(math.isfinite(z) for z in (ql,qr,discount+ql+qr)):
        raise UnresolvedGrid('nonfinite generator rates')
    q = discount+ql+qr
    delay = math.exp(-discount*refractory)
    # Two-element convex interpolation for V(reset): no nearest-node shortcut.
    z = (reset-lower)/h
    ri = min(int(z), nodes-2)
    rw = max(0.0, min(1.0,z-ri))
    policy = [False]*nodes
    policy[-1] = True  # caller's upper-FIRE assumption
    last_values = None
    for iteration in range(1,max_iterations+1):
        sub=[0.0]*nodes; diag=[1.0]*nodes; sup=[0.0]*nodes
        ra=[0.0]*nodes; rb=[0.0]*nodes
        for i in range(1,nodes):
            if policy[i]:
                ra[i] = (lower+h*i)-cost
                rb[i] = delay
            else:
                sub[i],diag[i],sup[i] = -ql,q,-qr
        a,b = _solve_pair(sub,diag,sup,ra,rb)
        ar = (1-rw)*a[ri]+rw*a[ri+1]
        br = (1-rw)*b[ri]+rw*b[ri+1]
        denom = 1-br
        if not (math.isfinite(denom) and denom > 1e-14):
            raise UnresolvedGrid('unresolved endogenous reset contraction')
        vr=ar/denom
        vals=[ai+bi*vr for ai,bi in zip(a,b)]
        if not math.isfinite(vr) or any(not math.isfinite(v) for v in vals):
            raise UnresolvedGrid('nonfinite QVI value')
        changed = False
        residual = 0.0
        for i in range(1,nodes-1):
            continuation=(ql*vals[i-1]+qr*vals[i+1])/q
            fire=(lower+h*i)-cost+delay*vr
            residual=max(residual,abs(vals[i]-max(continuation,fire)))
            advantage = fire-continuation
            tol=1e-12*(1+abs(fire)+abs(continuation))
            choose=policy[i] if abs(advantage)<=tol else advantage>0
            if choose != policy[i]:
                policy[i]=choose
                changed=True
        if not changed:
            last_values=vals
            break
    if last_values is None:
        raise UnresolvedGrid('Howard iteration did not stabilize')
    # The scalar upper-threshold policy must have one contiguous FIRE region.
    fires = [i for i in range(1,nodes) if policy[i]]
    if not fires or fires != list(range(fires[0],nodes)):
        raise UnresolvedGrid('nonthreshold or disconnected grid policy')
    first=fires[0]
    if first<=1 or first>=nodes-1:
        raise UnresolvedGrid('free boundary not resolved inside mesh')
    # Independently interpolate the zero of discrete FIRE-continuation advantage.
    def margin(i: int) -> float:
        fire=lower+h*i-cost+delay*vr
        hold=(ql*last_values[i-1]+qr*last_values[i+1])/q
        return fire-hold
    lo,hi=margin(first-1),margin(first)
    if lo > 2e-9*(1+abs(vr)) or hi < -2e-9*(1+abs(vr)):
        raise UnresolvedGrid('no discrete obstacle crossing')
    frac=-lo/(hi-lo) if hi != lo else .5
    threshold=lower+h*(first-1+max(0.,min(1.,frac)))
    if not math.isfinite(threshold) or not lower<threshold<upper:
        raise UnresolvedGrid('unresolved grid threshold')
    return GridResult(lower,upper,nodes,tuple(last_values),tuple(policy),
                      threshold,vr,residual,iteration,h,ql,qr)
