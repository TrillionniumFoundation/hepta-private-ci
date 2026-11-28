"""Closed-form He–Xiong equity and credit operators from the killed diffusion resolvent."""
from dataclasses import dataclass
import math
from scipy.special import log_ndtr, ndtr


@dataclass(frozen=True)
class Contract:
    r: float = .08
    payout: float = .02
    sigma: float = .23
    tax: float = .27
    recovery: float = .60
    coupon: float = 6.39
    principal: float = 61.68
    maturity: float = 1.
    premium: float = .01


def phi(z):
    return math.exp(-.5*z*z)/math.sqrt(2*math.pi)


def gaussian_tail_integral(k,a,width):
    """Integral from 0 to infinity of exp(-k*y) Phi((a-y)/width) dy."""
    z=a/width
    if k==0.:
        return a*ndtr(z)+width*phi(z)
    # exp(logPhi(z)) - exp(-k*a+.5*(k*w)^2+logPhi(z-k*w)).
    log_a=float(log_ndtr(z))
    displacement=-k*a+.5*(k*width)**2+float(log_ndtr(z-k*width))-log_a
    if abs(k)*max(1.,abs(a),width)<2e-6:
        moment0 = a*ndtr(z)+width*phi(z)
        moment1 = .5*((a*a+width**2)*ndtr(z)+a*width*phi(z))
        return moment0-k*moment1
    if displacement<=0:
        return -math.exp(log_a)*math.expm1(displacement)/k
    return math.exp(log_a+displacement)*math.expm1(-displacement)/k


def exp_integral(k,lower,upper):
    if upper==math.inf:
        if k<=0:raise ValueError("nonintegrable exponential")
        return math.exp(-k*lower)/k
    if k==0:return upper-lower
    return math.exp(-k*lower)*(-math.expm1(-k*(upper-lower)))/k


class Prices:
    def __init__(self,p):
        if p.r<=0 or p.payout<=0 or p.sigma<=0 or p.maturity<=0 or p.premium<0:
            raise ValueError("requires positive r, payout, sigma, maturity and nonnegative premium")
        self.p=p
        self.q=p.r+p.premium
        self.var=p.sigma**2
        self.mu=p.r-p.payout-.5*self.var
        self.width=p.sigma*math.sqrt(p.maturity)
        self.speed=math.hypot(self.mu,p.sigma*math.sqrt(2*p.r))
        self.eta=2*p.r/(self.speed+self.mu)
        self.gamma=(self.speed+self.mu)/self.var
        self.par=p.principal/p.maturity
        self.c=p.coupon/p.maturity
        self.A=math.exp(-self.q*p.maturity)*(self.par-self.c/self.q)
        i_f=self.hit_integral(0.,self.eta,0.,math.inf)
        i_g=self.hit_integral(self.q,self.eta,0.,math.inf)
        denom=p.payout/(self.eta-1)+p.recovery*i_g/p.maturity
        numer=((1-p.tax)*p.coupon+self.par-self.c/self.q)/self.eta-self.A*(1/self.eta-i_f)+(self.c/self.q)*i_g
        self.boundary=numer/denom

    def terms(self,q):
        lam=math.hypot(self.mu,self.p.sigma*math.sqrt(2*q))
        return ((self.mu+lam)/self.var,lam*self.p.maturity),((self.mu-lam)/self.var,-lam*self.p.maturity)

    def hit(self,x,q=0.):
        if x<=0:return 1.
        return sum(math.exp(-b*x+float(log_ndtr((a-x)/self.width))) for b,a in self.terms(q))

    def hit_integral(self,q,k,lower,upper):
        total=0.
        for b,a in self.terms(q):
            m=k+b
            low=math.exp(-m*lower)*gaussian_tail_integral(m,a-lower,self.width)
            high=0. if upper==math.inf else math.exp(-m*upper)*gaussian_tail_integral(m,a-upper,self.width)
            total+=low-high
        return total

    def bond(self,x):
        return self.c/self.q+self.A*(1-self.hit(x))+(self.p.recovery*self.boundary/self.p.maturity-self.c/self.q)*self.hit(x,self.q)

    def credit_loss(self,x):
        return self.c/self.q+self.A-self.bond(x)

    def cash_integral(self,k,low,hi):
        p=self.p
        constant=-(1-p.tax)*p.coupon+self.c/self.q+self.A-self.par
        return (p.payout*self.boundary*exp_integral(k-1,low,hi)
                + constant*exp_integral(k,low,hi)-self.A*self.hit_integral(0.,k,low,hi)
                +(p.recovery*self.boundary/p.maturity-self.c/self.q)*self.hit_integral(self.q,k,low,hi))

    def equity(self,x):
        if x<=0:return 0.
        # The reflected image's full cash moment is zero at the endogenous barrier.
        return (math.exp(-self.gamma*x)*self.cash_integral(-self.gamma,0.,x)
                +math.exp(self.eta*x)*self.cash_integral(self.eta,x,math.inf))/self.speed
