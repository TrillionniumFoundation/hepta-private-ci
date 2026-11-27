"""Reduced two-regime continuation and discounted first-hit operators.

Log-asset diffusion, observable exogenous regime, lower absorbing decision boundary.
Equity is the supremum of an integral of a running benefit minus an operating cost.
"""
from dataclasses import dataclass
import numpy as np
from scipy.optimize import least_squares

@dataclass(frozen=True)
class Model:
    r:float=.08
    payout:float=.02
    sigma:float=.23
    cheap:float=.04
    dear:float=.08
    up:float=.12
    down:float=.16
    discount:float=.09

    def __post_init__(self):
        if min(self.r,self.payout,self.sigma,self.cheap,self.up,self.down,self.discount)<=0 or self.dear<=self.cheap:
            raise ValueError('expected positive coefficients and dear > cheap')

    def exponents(self,q):
        mu=self.r-self.payout-self.sigma**2/2
        a=(mu**2+2*self.sigma**2*q)**.5
        return np.array([(-mu+a)/self.sigma**2,(-mu-a)/self.sigma**2])

    def uncoupled(self):
        n=self.exponents(self.r)[1]
        return n/(n-1)*np.array([self.cheap,self.dear])/self.r

def equation_matrix(p):
    return np.array([[p.r+p.up,-p.up],[-p.down,p.r+p.down]])

class Continuation:
    def __init__(self,p=Model()):
        self.p=p
        self.c=np.linalg.solve(equation_matrix(p),[p.cheap,p.dear])
        self.mode=np.array([p.up,-p.down])/(p.up+p.down)
        self.middle_n=p.exponents(p.r+p.up)
        self.upper_n=np.array([p.exponents(p.r)[1],p.exponents(p.r+p.up+p.down)[1]])
        self.mid_slope=p.payout/(p.payout+p.up)
        self.mid_cost=p.cheap/(p.r+p.up)
        b=p.uncoupled()
        def residual(logs):
            b0=np.exp(logs[0]);b1=b0*(1+np.exp(logs[1]))
            return self.match(b0,b1)
        sol=least_squares(residual,[np.log(b[0]),np.log(b[1]/b[0]-1)],max_nfev=700,xtol=1e-14,ftol=1e-14,gtol=1e-14)
        self.b0=np.exp(sol.x[0]);self.b1=self.b0*(1+np.exp(sol.x[1]))
        if not sol.success or np.linalg.norm(sol.fun,np.inf)>5e-10:
            raise ArithmeticError(('boundary residual',sol.message,sol.fun))
        self.middle,self.upper=self.coefficients(self.b0,self.b1)

    def coefficients(self,b0,b1):
        n=self.middle_n
        m=self.upper_n
        z=self.mode[1]
        # Value / log-derivative at the cheap and dear stopping points.
        mid=np.linalg.solve([[1,1],n],[self.mid_cost-self.mid_slope*b0,-self.mid_slope*b0])
        high=np.linalg.solve([[1,z],[m[0],z*m[1]]],[self.c[1]-b1,-b1])
        return mid,high

    def match(self,b0,b1):
        mid,high=self.coefficients(b0,b1)
        at=mid*(b1/b0)**self.middle_n
        common=self.mode[0]*high[1]
        return np.array([self.mid_slope*b1-self.mid_cost+at.sum()-(b1-self.c[0]+high[0]+common),
                         self.mid_slope*b1+at@self.middle_n-(b1+high[0]*self.upper_n[0]+common*self.upper_n[1])])

    def values(self,asset,order=0):
        if order not in (0,1,2):raise ValueError('expected log derivative order 0, 1 or 2')
        v=np.atleast_1d(np.asarray(asset,dtype=float))
        if np.any(v<=0):raise ValueError('positive asset required')
        y=np.zeros((len(v),2))
        mid=(v>self.b0)&(v<self.b1);high=v>=self.b1
        n=self.middle_n
        if mid.any():
            y[mid,0]=self.mid_slope*v[mid]-(self.mid_cost if order==0 else 0)+(v[mid,None]/self.b0)**n@(self.middle*n**order)
        if high.any():
            n=self.upper_n
            a=(v[high,None]/self.b1)**n*(self.upper*n**order)
            y[high]=v[high,None]-(self.c if order==0 else 0)+a[:,0,None]+a[:,1,None]*self.mode
        return y

class FirstHit:
    """Discounted transform of hitting under the already selected coupled stopping rule."""
    def __init__(self,cont, event="all"):
        rewards={"all":(1.,1.), "switch":(0.,0.), "cheap":(1.,0.), "dear":(0.,1.)}
        if event not in rewards:raise ValueError("unknown first-hit mark")
        self.on_stop=np.array(rewards[event]); switch_reward=1. if event=="switch" else self.on_stop[1]
        self.e=cont;p=cont.p
        q=p.discount
        self.mid=p.exponents(q+p.up)
        self.high=np.array([p.exponents(q)[1],p.exponents(q+p.up+p.down)[1]])
        self.constant=p.up*switch_reward/(p.up+q)
        z=(cont.b1/cont.b0)**self.mid
        matrix=np.array([[1,1,0,0],[0,0,1,cont.mode[1]],
                         [*z,-1,-cont.mode[0]],[*(z*self.mid),-self.high[0],-cont.mode[0]*self.high[1]]])
        self.coeff=np.linalg.solve(matrix,[self.on_stop[0]-self.constant,self.on_stop[1],-self.constant,0])

    def values(self,asset,order=0):
        if order not in (0,1,2):raise ValueError('expected log derivative order 0, 1 or 2')
        v=np.atleast_1d(np.asarray(asset,dtype=float))
        if np.any(v<=0):raise ValueError('positive asset required')
        a=self.e
        y=np.broadcast_to(self.on_stop,(len(v),2)).copy() if order==0 else np.zeros((len(v),2))
        mid=(v>a.b0)&(v<a.b1);high=v>=a.b1
        if mid.any():
            y[mid,0]=(self.constant if order==0 else 0)+(v[mid,None]/a.b0)**self.mid@(self.coeff[:2]*self.mid**order)
        if high.any():
            s=(v[high,None]/a.b1)**self.high*(self.coeff[2:]*self.high**order)
            y[high]=s[:,0,None]+s[:,1,None]*a.mode
        return y

if __name__=='__main__':
    model=Continuation()
    print('uncoupled',model.p.uncoupled(),'coupled',model.b0,model.b1,'residual',model.match(model.b0,model.b1))
    print(model.values([model.b0,model.b1,1.,1.5]), FirstHit(model).values([model.b0,model.b1,1.,1.5]))
