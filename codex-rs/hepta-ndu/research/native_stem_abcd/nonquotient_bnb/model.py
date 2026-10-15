"""R19 genuine parameter-specific non-quotient forward path; known 16-leaf risk law."""
from __future__ import annotations
from pathlib import Path
import sys
import numpy as np
from scipy.special import logsumexp

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'asymmetric_2d'))
from problem import population, INITIALS, two_point

ETA = 1/25
METHODS = ('adam','bfgs','lbfgs','trust-exact')

def qfun(a,eta):
    return eta*a/(1+a*a)

def dq(a,eta):
    return eta*(1-a*a)/(1+a*a)**2

def ddq(a,eta):
    return eta*2*a*(a*a-3)/(1+a*a)**3

def components(a,b,eta):
    return a*b,(a-b)**2/4 + qfun(a,eta)

def full(theta, eta):
    a,b=np.asarray(theta,dtype=np.float64)
    t,u=components(a,b,eta)
    C,g,H=population(t,u,shift=1.,pplus=.5)
    dif=a-b
    jac=np.array([[b,a],[dif/2+dq(a,eta),-dif/2]])
    HT=np.array([[0.,1.],[1.,0.]])
    HU=np.array([[.5+ddq(a,eta),-.5],[-.5,.5]])
    cost=C+(a*a+b*b)/4
    grad=jac.T@g+np.array([a,b])/2
    hess=jac.T@H@jac+g[0]*HT+g[1]*HU+np.eye(2)*.5
    return float(cost),grad,hess

def leaves(theta,eta):
    a,b=theta
    data=[]
    for x in (-1,1):
        for p0 in (0,1):
            for e1 in (-1,1):
                p1=p0^(e1==1)
                for e2 in (-1,1):
                    p2=p1^(e2==1)
                    h1=a*x
                    h2=b*h1+(a-b)**2/4+e2/10+qfun(a,eta)
                    data.append([x,p0,e1,e2,h1,h2,p1,p2,p1/20,(h2-x-1)**2+p2/50])
    return np.array(data,dtype=np.float64)

def independent_direct(theta,eta):
    """Fresh full terminal enumeration, no population() or analytic derivatives."""
    leaf=leaves(theta,eta)
    out=0.
    for x in (-1,1):
        for p0 in (0,1):
            mid=[]
            for e1 in (-1,1):
                branch=leaf[(leaf[:,0]==x)&(leaf[:,1]==p0)&(leaf[:,2]==e1)]
                rho=.5 if branch[0,6]==0 else 1.
                term=branch[:,9]
                c2=np.logaddexp(rho*term[0],rho*term[1])/rho-np.log(2)/rho
                mid.append(branch[0,8]+.9*c2)
            rho=.5 if p0==0 else 1.
            outer=np.logaddexp(rho*mid[0],rho*mid[1])/rho-np.log(2)/rho
            out+=.9*outer/4
    a,b=theta
    return float(out+(a*a+b*b)/4)
