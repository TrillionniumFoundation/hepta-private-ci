"""He--Xiong (Journal of Finance 2012) reference, not a neuron activation.

Equations (8), (12), (A5), and (A7) of doi:10.1111/j.1540-6261.2012.01721.x.
This is a research precision reference, not a differentiable/production kernel.
The risk-neutral financial state must NOT be confused with a neural membrane state.
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
    def z(self):
        return math.sqrt(self.a**2+2*self.rate/self.volatility**2)

    @property
    def zhat(self):
        return math.sqrt(self.a**2+2*self.q/self.volatility**2)

    @property
    def eta(self):
        return self.z-self.a

    @property
    def gamma(self):
        return self.z+self.a

    @property
    def per_bond_coupon(self):
        return self.coupon/self.maturity

    @property
    def per_bond_principal(self):
        return self.principal/self.maturity


def _exp_cdf(exponent: float, argument: float) -> float:
    """Evaluate exp(exponent) Phi(argument) without avoidable overflow."""
    log_value = exponent + float(log_ndtr(argument))
    if log_value < -745:
        return 0.0
    if log_value > 709:
        raise OverflowError('HX normal-tail combination outside finite f64 domain')
    return math.exp(log_value)


def _b_and_B(p: HX, t: float):
    """The auxiliary b(t), B(t) of HX (12); t is a, -a, +/-zhat."""
    z,a,m,sigma = p.z,p.a,p.maturity,p.volatility
    denom=z+t
    u=sigma*math.sqrt(m)
    if abs(denom) < .01 * max(1,abs(z),abs(t)):
        # The B(-zhat) coalescent limit is removable. Integrate the
        # derivative of its analytic numerator to avoid subtractive loss.
        nodes=(-math.sqrt(.6),0.0,math.sqrt(.6))
        weights=(5/18,4/9,5/18)
        B=0.0
        for node,w in zip(nodes,weights):
            t0=-z+(t+z)*(node+1)/2
            dens=math.exp(.5*(z*z-t0*t0)*u*u)
            derivative=(u*math.exp(-.5*(t0*u)**2)/math.sqrt(2*math.pi)
                        +t0*u*u*dens*float(ndtr(-z*u)))
            B+=w*derivative
        return math.nan,B
    # For the formula in (12), the exponential combinations are nontrivial;
    # keep both independently rather than silently dropping a tiny term.
    b=(math.exp(-p.q*m)*float(ndtr(t*u))
       -math.exp(-p.hazard*m)*float(ndtr(-z*u)))/denom
    B=(float(ndtr(t*u))
       -_exp_cdf(.5*(z*z-t*t)*u*u,-z*u))/denom
    return b,B


def boundary(p: HX) -> float:
    """HX endogenous financial default asset boundary, published equation (12).

    Reports no *positive* smooth-pasting boundary instead of coercing to zero.
    Uses delta/(eta-1)=(sigma^2/2)*(gamma+1) to include delta=0.
    """
    b1,_=_b_and_B(p,-p.a)
    b2,_=_b_and_B(p,p.a)
    _,B1=_b_and_B(p,-p.zhat)
    _,B2=_b_and_B(p,p.zhat)
    Bsum=B1+B2
    off=p.per_bond_principal-p.per_bond_coupon/p.q
    top=((1-p.tax_shield)*p.coupon+(-math.expm1(-p.q*p.maturity))*off)/p.eta
    top+=off*(b1+b2)+p.per_bond_coupon/p.q*Bsum
    # Stable identity, even payout -> 0.
    bottom=.5*p.volatility**2*(p.gamma+1)+p.recovery/p.maturity*Bsum
    if bottom <= 0 or not math.isfinite(bottom):
        raise ValueError('HX smooth-pasting denominator not positive')
    asset_boundary=top/bottom
    if asset_boundary <= 0 or not math.isfinite(asset_boundary):
        raise ValueError('No finite positive HX endogenous default boundary in this regime')
    return asset_boundary


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
    v=math.log(asset/b)
    u=p.volatility*math.sqrt(tau)
    h1=(-v-p.a*u*u)/u
    h2=(-v+p.a*u*u)/u
    q1=(-v-p.zhat*u*u)/u
    q2=(-v+p.zhat*u*u)/u
    F=float(ndtr(h1))+_exp_cdf(-2*p.a*v,h2)
    G=_exp_cdf((-p.a+p.zhat)*v,q1)+_exp_cdf((-p.a-p.zhat)*v,q2)
    base=p.per_bond_coupon/p.q
    return base+math.exp(-p.q*tau)*(p.per_bond_principal-base)*(1-F)+(recovery-base)*G


def _K(p: HX, v: float, y: float, beta: float) -> float:
    """Equation (A5): Laplace-inversion helper for equity."""
    u=p.volatility*math.sqrt(p.maturity)
    u2=u*u
    s=.5*((beta-p.a)**2-y*y)*u2
    # Signed terms are kept separately to preserve the paper's definition.
    return (_exp_cdf(-beta*v,y*u)
            -_exp_cdf(s-beta*v,(beta-p.a)*u)
            +_exp_cdf(s-beta*v,(-v+(beta-p.a)*u2)/u)
            -_exp_cdf(-(p.a+y)*v,(-v+y*u2)/u))


def _k(p: HX, v: float, y: float) -> float:
    """The k(v;a,y,-eta) term immediately below (A7)."""
    beta=-p.eta
    u=p.volatility*math.sqrt(p.maturity)
    u2=u*u
    s=.5*((beta-p.a)**2-y*y)*u2
    return (_exp_cdf(s-beta*v,(-v+(beta-p.a)*u2)/u)
            -_exp_cdf(-(p.a+y)*v,(-v+y*u2)/u))


def _K_y(p: HX, v: float, y: float, beta: float) -> float:
    u=p.volatility*math.sqrt(p.maturity)
    u2=u*u
    s=.5*((beta-p.a)**2-y*y)*u2
    h=(-v+(beta-p.a)*u2)/u
    j=(-v+y*u2)/u
    phi=lambda t: math.exp(-t*t/2)/math.sqrt(2*math.pi)
    return (math.exp(-beta*v)*u*phi(y*u)
            + y*u2*_exp_cdf(s-beta*v,(beta-p.a)*u)
            - y*u2*_exp_cdf(s-beta*v,h)
            + math.exp(-(p.a+y)*v)*(v*float(ndtr(j))-u*phi(j)))


def _k_y(p: HX, v: float, y: float) -> float:
    beta=-p.eta
    u=p.volatility*math.sqrt(p.maturity)
    u2=u*u
    s=.5*((beta-p.a)**2-y*y)*u2
    h=(-v+(beta-p.a)*u2)/u
    j=(-v+y*u2)/u
    phi=lambda t: math.exp(-t*t/2)/math.sqrt(2*math.pi)
    return (-y*u2*_exp_cdf(s-beta*v,h)
            + math.exp(-(p.a+y)*v)*(v*float(ndtr(j))-u*phi(j)))


def _A(p: HX, v: float, y: float) -> float:
    z=p.z
    if abs(z-y)<.01*max(z,1):
        # Remove the 0/0 at y=z by the fundamental theorem of calculus.
        # N(z)=K(z,gamma)+k(-z,-eta)=0 identically.  This 3-point
        # Gauss-Legendre integral is only of the *analytic derivative*,
        # not an approximation to the financial stochastic problem.
        nodes=(-math.sqrt(.6),0.0,math.sqrt(.6))
        weights=(5/18,4/9,5/18)
        d=0.0
        for node,w in zip(nodes,weights):
            t=z+(y-z)*(node+1)/2
            d+=w*(_K_y(p,v,t,p.gamma)-_k_y(p,v,-t))
        first=-d
    else:
        first=(_K(p,v,y,p.gamma)+_k(p,v,-y))/(z-y)
    return first+(_K(p,v,-y,p.gamma)+_k(p,v,y))/(z+y)


def equity_closed(p: HX, asset: float, asset_boundary: float | None = None) -> float:
    """Literal financial equity equation (A7), regular positive-hazard regime.

    The q=r coalescent limit uses the exact removable-singularity
    derivative, not an arbitrary epsilon or a different financial model.
    """
    b=boundary(p) if asset_boundary is None else asset_boundary
    if not (math.isfinite(asset) and math.isfinite(b) and asset>0 and b>0):
        raise ValueError('Invalid HX equity input')
    if asset<=b:
        return 0.0
    v=math.log(asset/b)
    z,s2=p.z,p.volatility**2
    off=p.per_bond_principal-p.per_bond_coupon/p.q
    cash=(1-p.tax_shield)*p.coupon+(-math.expm1(-p.q*p.maturity))*off
    return (asset - p.payout*b/(z*s2)*math.exp(-p.gamma*v)/(p.gamma+1)
            -cash/(z*s2)*(1/p.eta+(-math.expm1(-p.gamma*v))/p.gamma)
            +(math.exp(-p.q*p.maturity)*off*_A(p,v,p.a)
              -(p.recovery*b/p.maturity-p.per_bond_coupon/p.q)*_A(p,v,p.zhat))/(z*s2))


def equity_resolvent(p: HX, asset: float, asset_boundary: float | None = None,
                     *, epsabs: float = 1e-10) -> float:
    """Independent Feynman--Kac killed-diffusion resolvent for financial equity.

    This evaluates the *same* fixed-boundary cashflow as A7, using the bond
    Eq (8), a reflected Green density and adaptive integration. It is not a
    second closed form or a free-boundary optimizer. Scientific reference only.
    """
    from scipy.integrate import quad

    b=boundary(p) if asset_boundary is None else asset_boundary
    if not (math.isfinite(asset) and math.isfinite(b) and asset>0 and b>0):
        raise ValueError('Invalid HX equity input')
    if asset<=b:
        return 0.0
    x=math.log(asset/b)
    a,z=p.a,p.z
    const=(1-p.tax_shield)*p.coupon+p.per_bond_principal
    def integrand(y):
        # Normalized green kernel: exp(a(y-x))*(exp(-z*|x-y|)
        # -exp(-z*(x+y)))/(sigma^2*z).
        # exp form is nonnegative analytically, stable at y >> x.
        if y<x:
            density=math.exp((-a-z)*x+(a+z)*y)*(-math.expm1(-2*z*y))
        else:
            density=math.exp((a-z)*y+(-a+z)*x)*(-math.expm1(-2*z*x))
        # Multiply cashflow without forming exp(y) at large y.
        debt=bond_value(p,b*math.exp(y),p.maturity,b)
        return density*(p.payout*b*math.exp(y)+debt-const)/(p.volatility**2*z)
    # To avoid unbounded exp(y) under automated quadrature, use a finite cutoff
    # and explicitly bound the asymptotic tail in audits; for ordinary regimes
    # 50 log units are ample. No guarantee for arbitrarily tiny payout/discount.
    upper=max(50.0,x+25)
    left=quad(integrand,0,x,epsabs=epsabs,epsrel=2e-10,limit=250)[0]
    right=quad(integrand,x,upper,epsabs=epsabs,epsrel=2e-10,limit=250)[0]
    # Analytic tail: bond -> c/q and f -> payout*b*e^y + c/q - const.
    # For y>upper, y>=x, density=C*exp(-eta*y), and correction from
    # bond default tail is exponentially small in the audited range.
    # For delta=0, use the delta-down-to-zero (transversality) limit;
    # naive Feynman--Kac cash-flow integration loses the asset-value term.
    eta=p.eta
    C=math.exp((z-a)*x)*(-math.expm1(-2*z*x))/(p.volatility**2*z)
    # Stable identity: eta-1=2*delta/(sigma^2*(gamma+1)).
    eta_minus_one=2*p.payout/(p.volatility**2*(p.gamma+1))
    tail=C*(.5*p.volatility**2*(p.gamma+1)*b*math.exp(-eta_minus_one*upper))
    tail+=C*(p.per_bond_coupon/p.q-const)*math.exp(-eta*upper)/eta
    return left+right+tail


@dataclass(frozen=True)
class HXChannels:
    """Mechanism readout, *not* a causal attribution or a put-option payoff."""
    equity: float
    default_probability: float
    discounted_default_factor: float
    rollover_margin: float


def default_probability(p: HX, asset: float, tau: float, asset_boundary: float | None = None) -> float:
    """F(tau) of HX (9): probability of first hitting VB by maturity."""
    b=boundary(p) if asset_boundary is None else asset_boundary
    if not (math.isfinite(asset) and math.isfinite(tau) and math.isfinite(b)
            and b>0 and asset>0 and 0<=tau<=p.maturity):
        raise ValueError('Invalid first-passage input')
    if asset<=b:
        return 1.0
    if tau==0:
        return 0.0
    v=math.log(asset/b)
    u=p.volatility*math.sqrt(tau)
    result=float(ndtr((-v-p.a*u*u)/u))+_exp_cdf(-2*p.a*v,(-v+p.a*u*u)/u)
    return result


def discounted_default_factor(p: HX, asset: float, tau: float,
                              asset_boundary: float | None = None) -> float:
    """G(tau) of HX (8)-(9): E[e^(-q*T) 1{T<=tau}], not default probability."""
    b=boundary(p) if asset_boundary is None else asset_boundary
    if not (math.isfinite(asset) and math.isfinite(tau) and math.isfinite(b)
            and b>0 and asset>0 and 0<=tau<=p.maturity):
        raise ValueError('Invalid discounted first-passage input')
    if asset<=b:
        return 1.0
    if tau==0:
        return 0.0
    v=math.log(asset/b)
    u=p.volatility*math.sqrt(tau)
    return (_exp_cdf((-p.a+p.zhat)*v,(-v-p.zhat*u*u)/u)
            +_exp_cdf((-p.a-p.zhat)*v,(-v+p.zhat*u*u)/u))


def mechanism_channels(p: HX, asset: float, asset_boundary: float | None = None) -> HXChannels:
    """Named financial proxy channels for later matched experimental ablations."""
    b=boundary(p) if asset_boundary is None else asset_boundary
    d=bond_value(p,asset,p.maturity,b)
    return HXChannels(equity=equity_closed(p,asset,b),
                      default_probability=default_probability(p,asset,p.maturity,b),
                      discounted_default_factor=discounted_default_factor(p,asset,p.maturity,b),
                      rollover_margin=d-p.per_bond_principal)
