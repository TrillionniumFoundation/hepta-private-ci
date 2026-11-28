"""An interval-verified uniform error lower bound for every bilinear price surrogate."""
import json
import math
from pathlib import Path
from mpmath import iv

iv.dps=75
def N(x):return iv.mpf(x)
def phi(x):
    # Integrate the Taylor polynomial of exp(-z^2/2) from 0 to x. Since
    # z^2/2 >= 0, its exponential Lagrange remainder is bounded by the first
    # omitted power divided by its factorial, including when x is negative.
    y=x;term=x
    for n in range(1,131):
        term*=(-x*x)*(2*n-1)/(2*n*(2*n+1));y+=term
    n=131
    rem=abs(term*x*x*(2*n-1)/(2*n*(2*n+1))).b
    return N('.5')+(y+N([-1,1])*rem)/iv.sqrt(2*iv.pi)


class Price:
    def __init__(self,u):
        self.sig=N('.23');self.mu=N('.03355');self.D=self.sig**2/2
        self.r=N('.08');self.delta=N('.02');self.q=N('.09');self.alpha=N('.6')
        self.P=N('61.68')*(1+N('.28')*u);self.C=N('6.39');self.cp=self.C/self.q
        self.A=iv.exp(-self.q)*(self.P-self.cp)
        self.speed=iv.sqrt(self.mu**2+4*self.D*self.r)
        self.eta=2*self.r/(self.speed+self.mu);self.gamma=(self.speed+self.mu)/(2*self.D)
        f=self.hmoment(N(0),self.eta,N(0),None);g=self.hmoment(self.q,self.eta,N(0),None)
        den=self.delta/(self.eta-1)+self.alpha*g
        self.B=((1-N('.27'))*self.C+self.P-self.cp)/self.eta-self.A*(1/self.eta-f)+self.cp*g
        self.B/=den
    def pairs(self,d):
        l=iv.sqrt(self.mu**2+4*self.D*d)
        return ((self.mu+l)/(2*self.D),l),((self.mu-l)/(2*self.D),-l)
    def hit(self,d,x):
        return sum(iv.exp(-b*x)*phi((m-x)/self.sig) for b,m in self.pairs(d))
    def hmoment(self,d,k,lo,hi):
        out=N(0)
        for b,m in self.pairs(d):
            z=k+b
            def tail(x):
                h=(m-x)/self.sig
                return iv.exp(-z*x)*(phi(h)-iv.exp(-z*(m-x)+(z*self.sig)**2/2)*phi(h-z*self.sig))/z
            out+=tail(lo) if hi is None else tail(lo)-tail(hi)
        return out
    def cash(self,k,lo,hi):
        def moment(z):
            return (iv.exp(-z*lo)-(N(0) if hi is None else iv.exp(-z*hi)))/z
        return (self.delta*self.B*moment(k-1)+(-(1-N('.27'))*self.C+self.cp+self.A-self.P)*moment(k)
                -self.A*self.hmoment(N(0),k,lo,hi)+(self.alpha*self.B-self.cp)*self.hmoment(self.q,k,lo,hi))
    def eqloss(self,x):
        e=(iv.exp(-self.gamma*x)*self.cash(-self.gamma,N(0),x)+iv.exp(self.eta*x)*self.cash(self.eta,x,None))/self.speed
        loss=self.A*self.hit(N(0),x)-(self.alpha*self.B-self.cp)*self.hit(self.q,x)
        return e,loss

def enclosure(x):
    return [math.nextafter(float(x.a),-math.inf),math.nextafter(float(x.b),math.inf)]
def run():
    base=Price(N(0));E=base.eqloss(N('.8'))[0];L=base.eqloss(N('.02'))[1];rows={}
    for u in (0,1):
        p=Price(N(u));vals=[]
        for x in map(N,('.02','.41','.80')):
            e,l=p.eqloss(x);vals.append(u+e/E-l/L)
        second=vals[0]-2*vals[1]+vals[2];lb=abs(second)/4
        if not lb>N('.17'):raise ArithmeticError('Separation not verified')
        rows[str(u)]=dict(values=list(map(enclosure,vals)),second_difference=enclosure(second),
                          unavoidable_uniform_error_lower_bound=enclosure(lb))
    return dict(margin=['.02','.41','.80'],op='outward-rounded 75-decimal mpmath.iv',
             normal_cdf_taylor_terms=131,normal_cdf_remainder='first integrated omitted power',rows=rows)
if __name__=='__main__':
    (Path(__file__).with_name('separation.json')).write_text(json.dumps(run(),indent=2)+'\n')
