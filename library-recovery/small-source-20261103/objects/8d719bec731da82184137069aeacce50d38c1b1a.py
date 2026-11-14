"""Local-only temporary subset of upstream HX, NOT for publication.
Copied reference boundary/bond & independent Feynman-Kac equity; this file
exists only to exercise the new isolated module before GitHub integration.
"""
from dataclasses import dataclass
import math
from scipy.special import ndtr, log_ndtr
from scipy.integrate import quad

@dataclass(frozen=True)
class HX:
    rate:float=.05; payout:float=.03; volatility:float=.25
    maturity:float=2.; principal:float=60.; coupon:float=4.
    tax_shield:float=.25; recovery:float=.6; shock_intensity:float=1.; sale_fraction:float=.015
    @property
    def hazard(self): return self.shock_intensity*self.sale_fraction
    @property
    def q(self): return self.rate+self.hazard
    @property
    def a(self): return (self.rate-self.payout-.5*self.volatility**2)/(self.volatility**2)
    @property
    def z(self): return math.sqrt(self.a**2+2*self.rate/self.volatility**2)
    @property
    def zhat(self): return math.sqrt(self.a**2+2*self.q/self.volatility**2)
    @property
    def eta(self): return self.z-self.a
    @property
    def gamma(self): return self.z+self.a
    @property
    def per_bond_coupon(self): return self.coupon/self.maturity
    @property
    def per_bond_principal(self): return self.principal/self.maturity

def _exp_cdf(exponent,argument):
    val=exponent+float(log_ndtr(argument))
    return math.exp(val) if val > -745 else 0.

def _b_and_B(p,t):
    z,a,m,sigma=p.z,p.a,p.maturity,p.volatility
    denom=z+t
    u=sigma*math.sqrt(m)
    if abs(denom)<.01*max(1,abs(z),abs(t)):
        nodes=(-math.sqrt(.6),0.,math.sqrt(.6))
        weights=(5/18,4/9,5/18)
        B=0.
        for node,w in zip(nodes,weights):
            t0=-z+(t+z)*(node+1)/2
            dens=math.exp(.5*(z*z-t0*t0)*u*u)
            der=(u*math.exp(-.5*(t0*u)**2)/math.sqrt(2*math.pi)+t0*u*u*dens*float(ndtr(-z*u)))
            B+=w*der
        return math.nan,B
    b=(math.exp(-p.q*m)*float(ndtr(t*u))-math.exp(-p.hazard*m)*float(ndtr(-z*u)))/denom
    B=(float(ndtr(t*u))-_exp_cdf(.5*(z*z-t*t)*u*u,-z*u))/denom
    return b,B

def boundary(p):
    b1,_=_b_and_B(p,-p.a); b2,_=_b_and_B(p,p.a)
    _,B1=_b_and_B(p,-p.zhat); _,B2=_b_and_B(p,p.zhat)
    Bsum=B1+B2
    off=p.per_bond_principal-p.per_bond_coupon/p.q
    top=((1-p.tax_shield)*p.coupon+(-math.expm1(-p.q*p.maturity))*off)/p.eta
    top+=off*(b1+b2)+p.per_bond_coupon/p.q*Bsum
    bottom=.5*p.volatility**2*(p.gamma+1)+p.recovery/p.maturity*Bsum
    return top/bottom

def bond_value(p,asset,tau,asset_boundary=None):
    b=boundary(p) if asset_boundary is None else asset_boundary
    recovery=p.recovery*b/p.maturity
    if asset<=b: return recovery
    if tau==0: return p.per_bond_principal
    v=math.log(asset/b);u=p.volatility*math.sqrt(tau)
    h1=(-v-p.a*u*u)/u; h2=(-v+p.a*u*u)/u
    q1=(-v-p.zhat*u*u)/u;q2=(-v+p.zhat*u*u)/u
    F=float(ndtr(h1))+_exp_cdf(-2*p.a*v,h2)
    G=_exp_cdf((-p.a+p.zhat)*v,q1)+_exp_cdf((-p.a-p.zhat)*v,q2)
    base=p.per_bond_coupon/p.q
    return base+math.exp(-p.q*tau)*(p.per_bond_principal-base)*(1-F)+(recovery-base)*G

def equity_closed(p,asset,asset_boundary=None):
    # Temporarily use upstream equivalent independent Feynman-Kac resolvent.
    b=boundary(p) if asset_boundary is None else asset_boundary
    if asset<=b: return 0.
    x=math.log(asset/b);a,z=p.a,p.z
    const=(1-p.tax_shield)*p.coupon+p.per_bond_principal
    def integrand(y):
        if y<x: density=math.exp((-a-z)*x+(a+z)*y)*(-math.expm1(-2*z*y))
        else: density=math.exp((a-z)*y+(-a+z)*x)*(-math.expm1(-2*z*x))
        debt=bond_value(p,b*math.exp(y),p.maturity,b)
        return density*(p.payout*b*math.exp(y)+debt-const)/(p.volatility**2*z)
    upper=max(50.,x+25)
    left=quad(integrand,0,x,epsabs=1e-10,epsrel=2e-10,limit=250)[0]
    right=quad(integrand,x,upper,epsabs=1e-10,epsrel=2e-10,limit=250)[0]
    eta=p.eta
    C=math.exp((z-a)*x)*(-math.expm1(-2*z*x))/(p.volatility**2*z)
    eta_minus_one=2*p.payout/(p.volatility**2*(p.gamma+1))
    tail=C*(.5*p.volatility**2*(p.gamma+1)*b*math.exp(-eta_minus_one*upper))
    tail+=C*(p.per_bond_coupon/p.q-const)*math.exp(-eta*upper)/eta
    return left+right+tail
