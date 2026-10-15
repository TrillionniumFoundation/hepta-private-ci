"""R20: 2-step positive-risk NDU; signed parameter coupling, no convex-quotient oracle."""
from pathlib import Path
import sys
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'asymmetric_2d'))
from problem import population, INITIALS
from scipy.special import logsumexp
RHO=(.5,1.)
GAMMA=.9
ETA=1/25
LAMBDA=1/8
METHODS=('adam','bfgs','lbfgs','trust-exact')

def q(v, coefficient):return coefficient*v/(1+v*v)
def dq(v, coefficient):return coefficient*(1-v*v)/(1+v*v)**2
def ddq(v, coefficient):return coefficient*2*v*(v*v-3)/(1+v*v)**3

def forward(theta,extra):
    a,b=theta
    v=a-b
    return a*b, v*v/4+q(a,ETA)+q(v,LAMBDA if extra else 0)

def full(theta,extra):
    a,b=np.asarray(theta,dtype=np.float64)
    v=a-b
    t,d=forward((a,b),extra)
    value,g,H=population(t,d,shift=1.,pplus=.5)
    lam=LAMBDA if extra else 0
    grad_v = v/2+dq(v,lam)
    hv = .5+ddq(v,lam)
    jac=np.array([[b,a],[grad_v+dq(a,ETA),-grad_v]])
    Ht=np.array([[0.,1.],[1.,0.]])
    Hd=np.array([[hv+ddq(a,ETA),-hv],[-hv,hv]])
    cost=value+(a*a+b*b)/4
    grad=jac.T@g+np.array([a,b])/2
    hess=jac.T@H@jac+g[0]*Ht+g[1]*Hd+np.eye(2)*.5
    return float(cost),grad,hess

def leaves(theta,extra):
    a,b=theta
    t,d=forward(theta,extra)
    rows=[]
    for x in (-1,1):
      for p0 in (0,1):
       for e1 in (-1,1):
        p1=p0^(e1==1)
        for e2 in (-1,1):
         p2=p1^(e2==1)
         H1=a*x
         H2=t*x+d+e2/10
         rows.append([x,p0,e1,e2,p1,p2,H1,H2,p1/20,(H2-x-1)**2+p2/50])
    return np.asarray(rows,dtype=np.float64)

def independent_full(theta,extra):
    table=leaves(theta,extra)
    result=0.
    for x in (-1,1):
      for p0 in (0,1):
       vals=[]
       for e1 in (-1,1):
        branch=table[(table[:,0]==x)&(table[:,1]==p0)&(table[:,2]==e1)]
        rho=RHO[int(branch[0,4])]
        y=branch[:,9]
        values=np.logaddexp(rho*y[0],rho*y[1])/rho-np.log(2)/rho
        vals.append(branch[0,8]+GAMMA*values)
       rho=RHO[p0]
       result+=GAMMA/4*(np.logaddexp(rho*vals[0],rho*vals[1])-np.log(2))/rho
    a,b=theta
    return float(result+(a*a+b*b)/4)
