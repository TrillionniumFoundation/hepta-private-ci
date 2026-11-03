"""Reconstructed HX relevant-function subset from PR #4462 with proposed patch.
This local test harness is NOT the full remote source. The submitted PR edits
remote source directly and retains its unrelated functions byte-for-byte.
"""
from dataclasses import dataclass
import math
from scipy.special import log_ndtr, ndtr

@dataclass(frozen=True)
class HX:
    rate: float = .05
    payout: float = .03
    volatility: float = .25
    maturity: float = 2.0
    principal: float = 60.0
    coupon: float = 4.0
    tax_shield: float = .25
    recovery: float = .6
    shock_intensity: float = 1.0
    sale_fraction: float = .015

    def __post_init__(self):
        vals = tuple(vars(self).values())
        if not all(math.isfinite(v) for v in vals):
            raise ValueError('All HX parameters must be finite')
        if not (self.rate > 0 and self.payout >= 0 and self.volatility > 0
                and self.maturity > 0 and self.principal > 0 and self.coupon >= 0
                and 0 <= self.tax_shield <= 1 and 0 <= self.recovery <= 1
                and self.shock_intensity >= 0 and 0 <= self.sale_fraction <= 1):
            raise ValueError('Invalid HX structural parameter domain')

    @property
    def hazard(self):
        return self.shock_intensity * self.sale_fraction

    @property
    def q(self):
        return self.rate + self.hazard

    @property
    def a(self):
        s2 = self.volatility ** 2
        return (self.rate-self.payout-.5*s2)/s2

    @property
    def zhat(self):
        return math.sqrt(self.a**2+2*self.q/self.volatility**2)

    @property
    def per_bond_coupon(self):
        return self.coupon/self.maturity

    @property
    def per_bond_principal(self):
        return self.principal/self.maturity


def _exp_cdf(exponent: float, argument: float) -> float:
    log_value = exponent + float(log_ndtr(argument))
    if log_value < -745:
        return 0.0
    if log_value > 709:
        raise OverflowError('HX normal-tail combination outside finite f64 domain')
    return math.exp(log_value)


def _log_asset_ratio(asset: float, asset_boundary: float) -> float:
    ratio = asset / asset_boundary
    if math.isfinite(ratio):
        return math.log(ratio)
    v = math.log(asset) - math.log(asset_boundary)
    if not math.isfinite(v):
        raise ArithmeticError('HX log asset/boundary ratio unresolved in f64')
    return v


def _first_passage_factors(p: HX, v: float, tau: float) -> tuple[float, float]:
    u=p.volatility*math.sqrt(tau)
    a,zhat=p.a,p.zhat
    if (not all(math.isfinite(t) for t in (v,u,a,zhat))
            or v<0 or u<=0):
        raise ArithmeticError('HX first-passage scaled state unresolved in f64')
    u2=u*u
    h1=(-v-a*u2)/u
    h2=(-v+a*u2)/u
    q1=(-v-zhat*u2)/u
    q2=(-v+zhat*u2)/u
    F=float(ndtr(h1))+_exp_cdf(-2*a*v,h2)
    G=(_exp_cdf((-a+zhat)*v,q1)
       +_exp_cdf((-a-zhat)*v,q2))
    if not (math.isfinite(F) and math.isfinite(G) and 0<=G<=F<=1):
        raise ArithmeticError('HX F/G first-passage ordering unresolved in f64')
    return F,G


def boundary(p):
    raise RuntimeError('boundary() not present in this reconstructed local subset')


def bond_value(p: HX, asset: float, tau: float, asset_boundary: float | None = None) -> float:
    """Finite-maturity defaultable bond, published equation (8), including endpoints."""
    b=boundary(p) if asset_boundary is None else asset_boundary
    if not (math.isfinite(asset) and math.isfinite(tau) and math.isfinite(b)
            and b>0 and asset>0 and 0<=tau<=p.maturity):
        raise ValueError('Invalid bond (asset, maturity, boundary)')
    recovery=p.recovery*b/p.maturity
    if asset<=b:
        return recovery
    if tau==0:
        return p.per_bond_principal
    F,G=_first_passage_factors(p,_log_asset_ratio(asset,b),tau)
    qt=p.q*tau
    # For tiny discount products even exp(-qt) < 1 loses significant
    # figures when the coupon/q terms cancel. No-hit cashflows have a
    # stable exmp1 expression. Any nonzero first-hit factor needs the
    # numerically unresolved F-G stopped duration: explicitly refuse.
    # The 2**-26 f64 danger band is conservative, not certified.
    if p.per_bond_coupon>0 and qt<2.0**-26:
        if F!=0.0 or G!=0.0:
            raise ArithmeticError('HX stopped coupon unresolved at small discount product')
        lost=-math.expm1(-qt)
        annuity=tau if qt==0.0 else tau*(lost/qt)
        try:
            value=math.fsum((p.per_bond_principal,
                             -p.per_bond_principal*lost,
                             p.per_bond_coupon*annuity))
        except (OverflowError,ValueError) as exc:
            raise ArithmeticError('HX stopped coupon cashflow unresolved in f64') from exc
        if not math.isfinite(value):
            raise ArithmeticError('HX stopped coupon cashflow unresolved in f64')
        return value
    base=p.per_bond_coupon/p.q
    return base+math.exp(-p.q*tau)*(p.per_bond_principal-base)*(1-F)+(recovery-base)*G
