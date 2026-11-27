"""Conservative far-field *bond* error budget from Brownian first hit.

Independent of HX Eq.(8), (12), (A7) and quadrature/PDE solvers.
It bounds |B(A,b,T)-B_no_default(T)|. It is NOT a bound on
the financial equity upper Dirichlet boundary: no such inference is allowed.
Mathematical probability envelope uses reflection principle and drift
comparison; binary64 erfc/exp are NOT outward-rounded interval arithmetic.
"""
from dataclasses import dataclass
import math

class UnresolvedFarTail(ValueError):
    pass

@dataclass(frozen=True)
class FarTail:
    asset: float
    boundary: float
    maturity: float
    no_default_bond: float
    hit_probability_envelope: float
    bond_error_budget: float
    bound_kind: str = "ANALYTIC_INEQUALITY_BINARY64_NOT_CERTIFIED_INTERVAL"
    equity_upper_error_budget: None = None
    scientific_admission: bool = False
    production_activation: bool = False

def far_field_bond_budget(p, *, asset: float, boundary: float, maturity: float) -> FarTail:
    names=("rate","payout","volatility","principal","coupon","recovery",
           "shock_intensity","sale_fraction")
    try:
        values={name:getattr(p,name) for name in names}
    except AttributeError as exc:
        raise UnresolvedFarTail("missing HX financial field") from exc
    if any(type(v) not in (float,int) or not math.isfinite(v) for v in values.values()):
        raise UnresolvedFarTail("nonfinite HX financial input")
    r=values["rate"]; delta=values["payout"]; sigma=values["volatility"]
    if not (r>0 and delta>=0 and sigma>0 and values["principal"]>0
            and values["coupon"]>=0 and 0<=values["recovery"]<=1
            and values["shock_intensity"]>=0 and 0<=values["sale_fraction"]<=1):
        raise UnresolvedFarTail("invalid HX financial domain")
    if (type(asset) not in (float,int) or type(boundary) not in (float,int)
            or type(maturity) not in (float,int)
            or not all(math.isfinite(z) for z in (asset,boundary,maturity))
            or asset<=boundary or boundary<=0 or maturity<=0):
        raise UnresolvedFarTail("invalid far-field geometry")
    q=r+values["shock_intensity"]*values["sale_fraction"]
    principal=values["principal"]/maturity
    coupon=values["coupon"]/maturity
    base=coupon/q
    discounted=math.exp(-q*maturity)
    no_default=base+discounted*(principal-base)
    recovery=values["recovery"]*boundary/maturity
    v=math.log(asset/boundary)
    mu=r-delta-.5*sigma*sigma
    # For Brownian Y_t=mu*t+sigma*W_t starting at v>0:
    # first-hit probability is <= min(1,2*Phi(-(v-|mu|*T)/(sigma*sqrt T)))
    # whenever v>|mu|*T. This uses pathwise drift domination
    # by -|mu| and reflection for zero-drift Brownian motion.
    distance=v-abs(mu)*maturity
    if distance<=0:
        probability=1.0
    else:
        z=distance/(sigma*math.sqrt(maturity))
        probability=min(1.,math.erfc(z/math.sqrt(2.)))
    # B - B_nd = -e^(-qT)(P-base)*F+(R-base)*G.
    # Both F and G are no larger than P(hit by T).
    magnitude=(abs(discounted*(principal-base))+abs(recovery-base))
    budget=magnitude*probability
    if not all(math.isfinite(z) for z in (probability,budget,no_default)):
        raise UnresolvedFarTail("nonfinite tail budget")
    return FarTail(float(asset),float(boundary),float(maturity),no_default,
                   probability,budget)
