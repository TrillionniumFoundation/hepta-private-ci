"""Numerical reference for batched differentiable quotes using first passage, quadrature and an IVP."""
import json
import math
from pathlib import Path
import sys

import numpy as np
from scipy.integrate import quad,solve_ivp

base=Path(__file__).resolve().parents[1]
sys.path.extend([str(base/"paper_check"),str(base/"paper")])
from hx_reference import hit


def solution(p,margins):
    r,delta,sigma,tax,alpha,C,P,T,premium=p
    q=r+premium
    mu=r-delta-.5*sigma**2
    eta=2*r/(math.hypot(mu,sigma*math.sqrt(2*r))+mu)
    c=C/T;par=P/T;A=math.exp(-q*T)*(par-c/q)
    def laplace(discount):
        return quad(lambda x:math.exp(-eta*x)*hit(x,T,mu,sigma,discount),0,np.inf,
                    epsabs=1e-13,epsrel=1e-12)[0]
    Fi,Gi=laplace(0),laplace(q)
    B=(((1-tax)*C+par-c/q)/eta-A*(1/eta-Fi)+c/q*Gi)/(delta/(eta-1)+alpha*Gi/T)
    def loss(x,F,G):
        return A*F+(c/q-alpha*B/T)*G
    def fun(x,y):
        debt=c/q+A-loss(x,hit(x,T,mu,sigma),hit(x,T,mu,sigma,q))
        cash=delta*B*math.exp(x)-(1-tax)*C+debt-par
        return y[1],2*(r*y[0]-mu*y[1]-cash)/sigma**2
    sol=solve_ivp(fun,(0,max(margins)+1e-8),(0.,0.),method="DOP853",rtol=2e-12,atol=1e-13,dense_output=True)
    if not sol.success:raise RuntimeError(sol.message)
    rows=[]
    for x in margins:
        F=hit(x,T,mu,sigma);G=hit(x,T,mu,sigma,q)
        rows.append([B,sol.sol(x)[0],loss(x,F,G),F,G])
    return np.array(rows)


def main():
    p0=np.array([.08,.02,.23,.27,.60,6.39,61.68,1.,.01])
    ps=[p0,p0.copy(),p0.copy()]
    ps[1][-1]=0
    ps[2][1]=ps[2][0]-.5*ps[2][2]**2
    rng=np.random.default_rng(251247)
    lo=[.04,.014,.17,.15,.4,5.0,49,.65,.001]
    hi=[.12,.039,.32,.33,.75,7.9,77,1.7,.055]
    ps.extend(rng.uniform(lo,hi) for _ in range(9))
    x=np.array([.015,.23,.7])
    data=[]
    for p in ps:
        y=solution(p,x)
        h=.00004
        margin=(solution(p,x-2*h)-8*solution(p,x-h)+8*solution(p,x+h)-solution(p,x+2*h))/(12*h)
        derivatives=[margin]
        for i in range(len(p)):
            scale=max(abs(p[i]),.04)
            h=scale*4e-4
            def at(offset):
                u=p.copy();u[i]+=offset*h
                return solution(u,x)
            if i==8 and p[i]==0:
                d=(-25*y+48*at(1)-36*at(2)+16*at(3)-3*at(4))/(12*h)
            else:
                d=(at(-2)-8*at(-1)+8*at(1)-at(2))/(12*h)
            derivatives.append(d)
        data.append(dict(contract=p.tolist(),margin=x.tolist(),values=y.tolist(),jacobian=np.stack(derivatives,-1).tolist()))
    path=Path(__file__).with_name("reference.json")
    path.write_text(json.dumps(dict(method="DOP853 + Gauss-Kronrod + fourth-order differences",cases=data))+"\n")

if __name__=="__main__":main()
