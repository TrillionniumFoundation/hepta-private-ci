"""Outward-rounded interval arithmetic and interval first derivatives for the three roots."""
import json
import math
from pathlib import Path

from mpmath import iv

from halfline import Stationary

iv.dps=80


def cdf(x):
    # Integrate the Taylor polynomial of exp(-s^2/2) on 0..x. Lagrange's
    # remainder is bounded for every real x by the magnitude of the next term.
    x=iv.mpf(x)
    term=x
    total=x
    last=110
    for n in range(1,last+1):
        term*=(-x*x)*(2*n-1)/(2*n*(2*n+1))
        total+=term
    n=last+1
    error=abs(term*x*x*(2*n-1)/(2*n*(2*n+1))).b
    rem=iv.mpf([-1,1])*error
    return iv.mpf('.5')+(total+rem)/iv.sqrt(2*iv.pi)


class Dual:
    def __init__(self,v,d=0):
        self.v=iv.mpf(v)
        self.d=iv.mpf(d)
    @staticmethod
    def asdual(v):
        return v if isinstance(v,Dual) else Dual(v)
    def __add__(self,other):
        t=self.asdual(other)
        return Dual(self.v+t.v,self.d+t.d)
    __radd__=__add__
    def __neg__(self):return Dual(-self.v,-self.d)
    def __sub__(self,other):return self+(-self.asdual(other))
    def __rsub__(self,other):return self.asdual(other)-self
    def __mul__(self,other):
        t=self.asdual(other)
        return Dual(self.v*t.v,self.d*t.v+self.v*t.d)
    __rmul__=__mul__
    def __truediv__(self,other):
        t=self.asdual(other)
        if 0 in t.v:
            raise ZeroDivisionError("enclosure meets zero")
        q=self.v/t.v
        return Dual(q,(self.d-q*t.d)/t.v)
    def __rtruediv__(self,other):return self.asdual(other)/self


class Rigorous:
    number=staticmethod(Dual)
    is_zero=staticmethod(lambda t: bool(Dual.asdual(t).v==0))
    sqrt2pi=staticmethod(lambda:Dual(iv.sqrt(2*iv.pi)))
    @staticmethod
    def exp(v):
        t=Dual.asdual(v)
        x=iv.exp(t.v)
        return Dual(x,x*t.d)
    @staticmethod
    def sqrt(v):
        t=Dual.asdual(v)
        x=iv.sqrt(t.v)
        return Dual(x,t.d/(2*x))
    @staticmethod
    def phi(v):
        t=Dual.asdual(v)
        return Dual(cdf(t.v),iv.exp(-t.v*t.v/2)/iv.sqrt(2*iv.pi)*t.d)
    @staticmethod
    def tanh(v):
        t=Dual.asdual(v)
        k=iv.exp(-2*t.v)
        return Dual((1-k)/(1+k),4*k/((1+k)*(1+k))*t.d)


def enclosing_numbers(x):
    return [math.nextafter(float(x.a),-math.inf),math.nextafter(float(x.b),math.inf)]


def run():
    source=Stationary(Rigorous)
    brackets=[(".036790156067",".036790156070"),(".142875032261",".142875032264"),
              (".311545393218",".311545393223")]
    roots=[]
    for lo,hi in brackets:
        f_lo=source.stationary(Dual(lo))[0].v
        f_hi=source.stationary(Dual(hi))[0].v
        f,j,e,l,mean=source.stationary(Dual(iv.mpf([lo,hi]),1))
        if not ((f_lo<0 and f_hi>0) or (f_lo>0 and f_hi<0)):
            raise ArithmeticError("bracket sign not decided")
        if 0 in f.d or e.v.a<=0 or l.v.a<=0:
            raise ArithmeticError("slope or price positivity not decided")
        roots.append(dict(inward_drift=[lo,hi],left=enclosing_numbers(f_lo),right=enclosing_numbers(f_hi),
                          slope=enclosing_numbers(f.d),rate=enclosing_numbers(j.v),
                          E_over20=enclosing_numbers(e.v),L_over20=enclosing_numbers(l.v),
                          conditional_mean=enclosing_numbers(mean.v)))
    return dict(interval_digits=iv.dps,normal_cdf_expansion_degree=110,drive="-.8",equity_gain=".6",
                loss_gain="4.1",sigma=".23",reset=".30",refractory=".25",at_least_distinct_roots=3,roots=roots)


if __name__=="__main__":
    result=run()
    Path(__file__).with_name("enclosures.json").write_text(json.dumps(result,indent=2)+"\n")
    print(result)
