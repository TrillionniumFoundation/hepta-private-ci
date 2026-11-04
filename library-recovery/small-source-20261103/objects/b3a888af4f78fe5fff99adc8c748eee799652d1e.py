"""Literal numerical f64 F/G slice from HX reference, for isolated regression.
Not a full-repository checkout; exact production scope must be reviewed remotely.
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

def original_pair(p: HX, asset: float, tau: float, b: float):
    v=math.log(asset/b)
    u=p.volatility*math.sqrt(tau)
    F=float(ndtr((-v-p.a*u*u)/u))+_exp_cdf(-2*p.a*v,(-v+p.a*u*u)/u)
    G=(_exp_cdf((-p.a+p.zhat)*v,(-v-p.zhat*u*u)/u)
       +_exp_cdf((-p.a-p.zhat)*v,(-v+p.zhat*u*u)/u))
    return F,G

def checked_pair(p: HX, asset: float, tau: float, b: float):
    F,G=original_pair(p,asset,tau,b)
    if not (math.isfinite(F) and math.isfinite(G) and 0.0 <= G <= F <= 1.0):
        raise ArithmeticError('HX first-passage F/G ordering unresolved in f64')
    return F,G

def bond_value(p: HX, asset: float, tau: float, asset_boundary: float | None = None) -> float:
    b = asset_boundary
    if b is None:
        raise ValueError('Slice explicitly requires boundary')
    if not (math.isfinite(asset) and math.isfinite(tau) and math.isfinite(b)
            and b>0 and asset>0 and 0<=tau<=p.maturity):
        raise ValueError('Invalid bond (asset, maturity, boundary)')
    recovery=p.recovery*b/p.maturity
    if asset<=b:
        return recovery
    if tau==0:
        return p.per_bond_principal
    F,G=checked_pair(p,asset,tau,b)
    base=p.per_bond_coupon/p.q
    return base+math.exp(-p.q*tau)*(p.per_bond_principal-base)*(1-F)+(recovery-base)*G

def default_probability(p: HX, asset: float, tau: float, asset_boundary: float | None = None) -> float:
    b=asset_boundary
    if b is None:
        raise ValueError('Slice explicitly requires boundary')
    if not (math.isfinite(asset) and math.isfinite(tau) and math.isfinite(b)
            and b>0 and asset>0 and 0<=tau<=p.maturity):
        raise ValueError('Invalid first-passage input')
    if asset<=b:
        return 1.0
    if tau==0:
        return 0.0
    return checked_pair(p,asset,tau,b)[0]

def discounted_default_factor(p: HX, asset: float, tau: float,
                              asset_boundary: float | None = None) -> float:
    b=asset_boundary
    if b is None:
        raise ValueError('Slice explicitly requires boundary')
    if not (math.isfinite(asset) and math.isfinite(tau) and math.isfinite(b)
            and b>0 and asset>0 and 0<=tau<=p.maturity):
        raise ValueError('Invalid discounted first-passage input')
    if asset<=b:
        return 1.0
    if tau==0:
        return 0.0
    return checked_pair(p,asset,tau,b)[1]
