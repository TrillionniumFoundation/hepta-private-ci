import mpmath as mp
from fractions import Fraction as Q
from itertools import product
from problem import XS,PS,EPS,GAMMA,RHO,leaves
mp.mp.dps=65

def mpf(q):
    
    if isinstance(q,mp.mpf):return q
    q=Q(q);return mp.mpf(q.numerator)/q.denominator

def calc(a,b):
    cost=mp.mpf(0);g=[mp.mpf(0),mp.mpf(0)]
    for x,p0 in product(XS,PS):
        y=[];grad=[]
        for e1 in EPS:
            xx=mpf(x); ph=(xx**2,xx**3);p1=p0^(e1==1)
            h1=xx+a*ph[0]+b*ph[1]+e1/mp.mpf(5)
            t1=xx**2+xx**4/2
            gap1=h1-t1
            v=gap1**2+p1/mp.mpf(20)
            d1=[2*gap1*p for p in ph]
            gain=1+e1*xx/10
            lv=[]
            for e2 in EPS:
                p2=p1^(e2==1)
                h2=gain*h1+e2/mp.mpf(10)
                t2=gain*t1+xx/8
                gap2=h2-t2
                lv.append((gap2**2+p2/mp.mpf(25),[2*gap2*gain*u for u in ph],p2))
            vals=[t[0] for t in lv]
            rho=mpf(RHO[p1]);t=[mp.exp(rho*v) for v in vals];tot=sum(t)
            s=[z/tot for z in t]
            Y=mpf(v)+mpf(GAMMA)*mp.log(tot/2)/rho
            gy=[mpf(d1[j])+mpf(GAMMA)*sum(s[k]*mpf(lv[k][1][j]) for k in range(2)) for j in range(2)]
            y.append(Y);grad.append(gy)
        rho=mpf(RHO[p0]);w=[mp.exp(rho*v) for v in y];su=sum(w);w=[v/su for v in w]
        cost+=mpf(GAMMA)*mp.log(su/2)/rho/10
        for j in range(2):g[j]+=mpf(GAMMA)*sum(w[k]*grad[k][j] for k in range(2))/10
    return cost,g

def high_precision_root():
    f=lambda a,b:calc(a,b)[1]
    return mp.findroot(f,(mp.mpf('1.47'),mp.mpf('-1.0')),tol=mp.mpf('1e-58'))

if __name__=='__main__':
    r=high_precision_root()
    print('ROOT',mp.nstr(r[0],65),mp.nstr(r[1],65))
    print('COST',mp.nstr(calc(r[0],r[1])[0],55))
