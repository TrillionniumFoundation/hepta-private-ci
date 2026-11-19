"""R14 two-step nonzero-risk forward/backward discrete-control problem."""
from fractions import Fraction as Q
from itertools import product
import numpy as np
from scipy.special import logsumexp

XS=tuple(Q(i,2) for i in (-2,-1,0,1,2))
PS=(0,1)
EPS=(-1,1)
GAMMA=Q(9,10)
DELTA1=Q(1,5)
DELTA2=Q(1,10)
RHO=(Q(1,2),Q(1))


def phi(x):return (x*x,x*x*x)


def leaves(a,b,x,p0,e1):
    p1=p0^(e1==1)
    h1=x+a*x*x+b*x*x*x+e1*DELTA1
    t1=x*x+x**4/2
    gain=1+e1*x/10
    e1gap=h1-t1
    loss1=e1gap*e1gap+Q(p1,20)
    out=[]
    for e2 in EPS:
        p2=p1^(e2==1)
        h2=gain*h1+e2*DELTA2
        t2=gain*t1+x/8
        gap=h2-t2
        loss2=gap*gap+Q(p2,25)
        jac=tuple(2*gap*gain*v for v in phi(x))
        out.append((loss2,jac,p2))
    jac1=tuple(2*e1gap*v for v in phi(x))
    return loss1,jac1,p1,out


def _ce_cost(c,rho):
    z=float(rho)*np.array([float(v) for v in c])
    return float((logsumexp(z)-np.log(2))/float(rho))


def _weights(c,rho):
    z=float(rho)*np.array([float(v) for v in c])
    return np.exp(z-logsumexp(z))


def evaluate(theta):
    a,b=map(float,theta)
    out=0.; grad=np.zeros(2)
    for x,p0 in product(XS,PS):
        y=[];g=[]
        for e1 in EPS:
            loss1,der1,p1,last=leaves(a,b,float(x),p0,e1)
            r=float(RHO[p1]); cc=_ce_cost([t[0] for t in last],r)
            w2=_weights([t[0] for t in last],r)
            d1=np.array(der1,dtype=float)+float(GAMMA)*sum(float(w)*np.array(t[1],dtype=float) for w,t in zip(w2,last))
            y.append(float(loss1)+float(GAMMA)*cc)
            g.append(d1)
        w1=_weights(y,float(RHO[p0])); out+=float(GAMMA)*_ce_cost(y,float(RHO[p0]))/10
        grad+=float(GAMMA)*sum(float(w)*v for w,v in zip(w1,g))/10
    return out,grad


def risk_neutral(theta):
    return evaluate_with_risk(theta,0.)


def evaluate_with_risk(theta,risk=0.):
    # controls for risk perturbation, not part of exact rational certificate
    a,b=map(float,theta); cost=0.; grad=np.zeros(2)
    for x,p0 in product(XS,PS):
        y=[]; grads=[]
        for e1 in EPS:
            loss1,d1,p1,last=leaves(a,b,float(x),p0,e1)
            yy=[float(v[0]) for v in last]
            c=np.mean(yy) if risk==0 else _ce_cost(yy,float(RHO[p1])*risk)
            ww=np.array([.5,.5]) if risk==0 else _weights(yy,float(RHO[p1])*risk)
            y.append(float(loss1)+float(GAMMA)*c)
            grads.append(np.array(d1,dtype=float)+float(GAMMA)*sum(float(w)*np.array(v[1],dtype=float) for w,v in zip(ww,last)))
        w1=np.array([.5,.5]) if risk==0 else _weights(y,float(RHO[p0])*risk)
        cost+=float(GAMMA)*(np.mean(y) if risk==0 else _ce_cost(y,float(RHO[p0])*risk))/10
        grad+=float(GAMMA)*sum(float(w)*v for w,v in zip(w1,grads))/10
    return cost,grad

if __name__=='__main__':
    from scipy.optimize import minimize
    for risk in (0.,1.):
        f=lambda t:evaluate_with_risk(t,risk)
        sol=minimize(lambda t:f(t),[1.3,-1.4],jac=True,method='BFGS',options={'gtol':1e-12})
        print(risk,sol.x,sol.fun,np.max(abs(f(sol.x)[1])),sol.success,sol.message)
