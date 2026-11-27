"""Rational fixed-point outward intervals for log/exp: no floats in the proof."""
from fractions import Fraction as Q
from dataclasses import dataclass

SCALE=2**160

def down(q):
    q=Q(q);return Q((q.numerator*SCALE)//q.denominator,SCALE)
def up(q):
    q=Q(q);return Q(-((-q.numerator*SCALE)//q.denominator),SCALE)

@dataclass(frozen=True)
class I:
    lo:Q
    hi:Q
    def __init__(self,lo,hi=None):
        lo=Q(lo);hi=lo if hi is None else Q(hi)
        if lo>hi:raise ValueError('invalid interval')
        object.__setattr__(self,'lo',down(lo))
        object.__setattr__(self,'hi',up(hi))
    @staticmethod
    def into(x):return x if isinstance(x,I) else I(x)
    def __add__(self,y):
        y=I.into(y);return I(self.lo+y.lo,self.hi+y.hi)
    __radd__=__add__
    def __neg__(self):return I(-self.hi,-self.lo)
    def __sub__(self,y):return self+-I.into(y)
    def __rsub__(self,y):return I.into(y)+-self
    def __mul__(self,y):
        y=I.into(y);p=[a*b for a in (self.lo,self.hi) for b in (y.lo,y.hi)]
        return I(min(p),max(p))
    __rmul__=__mul__
    def __truediv__(self,y):
        y=I.into(y)
        if y.lo<=0<=y.hi:raise ZeroDivisionError('interval includes zero')
        return self*I(Q(1,y.hi),Q(1,y.lo))
    def __rtruediv__(self,y):return I.into(y)/self
    def __pow__(self,n):
        if not isinstance(n,int) or n<0:raise ValueError('nonnegative integer power')
        o=I(1);a=self
        while n:
            if n&1:o=o*a
            n//=2
            if n:a=a*a
        return o
    def width(self):return self.hi-self.lo
    def max_abs(self):return max(abs(self.lo),abs(self.hi))


def exp_nonnegative(x,n=30):
    x=Q(x)
    if x<0:raise ValueError('positive only')
    k=0;y=x
    while y>Q(1,2):y/=2;k+=1
    arg=I(y)
    term=I(1);total=I(1)
    for j in range(1,n+1):
        term=term*arg/j
        total=total+term
    upcoming=term*arg/(n+1)
    # Positive geometric tail after n: ratios no larger than y/(n+2).
    tail=up(upcoming.hi/(1-y/Q(n+2)))
    result=I(total.lo,total.hi+tail)
    for _ in range(k):result=result*result
    return result

def exp_exact(x,n=30):
    x=Q(x)
    return exp_nonnegative(x,n) if x>=0 else I(1)/exp_nonnegative(-x,n)

def expi(x):
    x=I.into(x)
    a=exp_exact(x.lo);b=exp_exact(x.hi)
    return I(a.lo,b.hi)


def log_mantissa(m,n=36):
    m=Q(m)
    if not 1<=m<=2:raise ValueError('mantissa outside [1,2]')
    t=I((m-1)/(m+1))
    total=I(0);u=t; t2=t*t
    for j in range(n):
        total+=u*Q(2,2*j+1)
        u=u*t2
    # u approx t^(2n+1); tail terms denominator >=2n+1
    tail=up((u.hi*Q(2,2*n+1))/(1-t2.hi))
    return I(total.lo,total.hi+tail)

LOG2=log_mantissa(2)

def log_exact(v):
    v=Q(v)
    if v<=0:raise ValueError('log nonpositive')
    k=0; u=v
    while u>2:u/=2;k+=1
    while u<1:u*=2;k-=1
    return log_mantissa(u)+k*LOG2

def logi(x):
    x=I.into(x)
    if x.lo<=0:raise ValueError('log of nonpositive interval')
    lo=log_exact(x.lo);hi=log_exact(x.hi)
    return I(lo.lo,hi.hi)


def ce(values,rho):
    if len(values)!=2 or Q(rho)<=0:raise ValueError('binary nonzero-risk only')
    probs=[expi(Q(rho)*I.into(v)) for v in values]
    partition=(probs[0]+probs[1])/2
    result=logi(partition)/Q(rho)
    return result


def softmax(values,rho):
    # Stable, rational interval probability from differences.
    z=Q(rho)*(I.into(values[1])-I.into(values[0]))
    e=expi(z)
    p=I(1)/(I(1)+e)
    return p,I(1)-p

if __name__=='__main__':
    for x in (Q(-3),Q(0),Q(1,2),Q(7,3)):
        e=exp_exact(x);print('exp',str(x),float(e.lo),float(e.hi),float(e.width()))
    for x in (Q(1,2),Q(1),Q(2),Q(17,5),Q(13)):
        y=log_exact(x);print('log',str(x),float(y.lo),float(y.hi),float(y.width()))
