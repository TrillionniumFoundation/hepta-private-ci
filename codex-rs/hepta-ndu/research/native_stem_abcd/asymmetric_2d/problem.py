"""R18 asymmetric two-dimensional stochastic NDU; exact 16-case population.

Analytical quotient gradient/Hessian are derivatives of *actual* nested
positive-risk entropic utility. The forward parameters enter both stages.
"""
from __future__ import annotations
import numpy as np
from scipy.special import logsumexp
RHO=(.5,1.)
GAMMA=.9
NOISE=.1
KAPPA=.25
INITIALS=((0.,0.),(.1,.1),(-.1,-.1),(1.,1.),(-1.,-1.),(2.,-2.),(1.,-1.),(2.,2.))

def leaf(a,b,x,p0,e1,e2,shift=1.,biased=False):
    p1=p0^(e1==1)
    p2=p1^(e2==1)
    h1=a*x
    h2=b*h1+KAPPA*(a-b)**2+e2*NOISE
    return {'h1':h1,'h2':h2,'p0':p0,'p1':p1,'p2':p2,'x':x,'eps1':e1,'eps2':e2,
            'stage':p1/20.,'terminal':(h2-x-shift)**2+p2/50.}

def ce2(vals,rho):
    return float((logsumexp(rho*np.asarray(vals))-np.log(2))/rho)

def direct(theta,shift=1.,pplus=.5):
    if not 0<=pplus<=1 or shift not in (0.,1.):raise ValueError('law')
    a,b=np.asarray(theta,dtype=float)
    val=0.
    for x in (-1,1):
        for p0 in (0,1):
            stages=[]
            for e1 in (-1,1):
                branches=[leaf(a,b,x,p0,e1,e2,shift) for e2 in (-1,1)]
                stages.append(branches[0]['stage']+GAMMA*ce2([v['terminal'] for v in branches],RHO[branches[0]['p1']]))
            val+=(.5*(pplus if x==1 else 1-pplus))*GAMMA*ce2(stages,RHO[p0])
    return float(val+.25*(a*a+b*b))

def two_point(vals,grads,hessians,rho):
    z=rho*np.asarray(vals,dtype=float)
    soft=np.exp(z-logsumexp(z))
    value=float((logsumexp(z)-np.log(2))/rho)
    grads=np.asarray(grads,dtype=float)
    hes=np.asarray(hessians,dtype=float)
    g=soft@grads
    h=np.einsum('i,ijk->jk',soft,hes)
    diff=grads-g[None,:]
    h+=rho*np.einsum('i,ij,ik->jk',soft,diff,diff)
    return value,g,h

def population(t,d,shift=1.,pplus=.5):
    """C(t,d), gradient, Hessian of both conditional entropic layers."""
    if shift not in (0.,1.) or not 0<=pplus<=1:raise ValueError('law')
    total=0.;grad=np.zeros(2);H=np.zeros((2,2))
    for x in (-1,1):
        v=np.array([x,1.]);outerH=2*np.outer(v,v)
        for p0 in (0,1):
            vals=[];gs=[];hs=[]
            for e1 in (-1,1):
                p1=p0^(e1==1)
                vv=[];vg=[];vh=[]
                for e2 in (-1,1):
                    p2=p1^(e2==1)
                    z=x*(t-1)+d-shift+e2*NOISE
                    vv.append(z*z+p2/50.)
                    vg.append(2*z*v)
                    vh.append(outerH)
                V,g,h=two_point(vv,vg,vh,RHO[p1])
                vals.append(p1/20.+GAMMA*V)
                gs.append(GAMMA*g)
                hs.append(GAMMA*h)
            V,g,h=two_point(vals,gs,hs,RHO[p0])
            w=(pplus if x==1 else 1-pplus)/2
            total+=GAMMA*w*V;grad+=GAMMA*w*g;H+=GAMMA*w*h
    return float(total),grad,H

def objective(theta,shift=1.,pplus=.5):
    a,b=np.asarray(theta,dtype=float)
    t=a*b; d=KAPPA*(a-b)**2
    C,g,h=population(t,d,shift,pplus)
    jac=np.array([[b,a],[2*KAPPA*(a-b),-2*KAPPA*(a-b)]])
    HT=np.array([[0.,1.],[1.,0.]])
    HD=2*KAPPA*np.array([[1.,-1.],[-1.,1.]])
    value=C+(a*a+b*b)/4
    gradient=jac.T@g+.5*np.array([a,b])
    H=jac.T@h@jac+g[0]*HT+g[1]*HD+np.eye(2)*.5
    return float(value),gradient,H

def quotient(theta,shift=1.):
    a,b=theta
    t=a*b;d=(a-b)**2/4
    C,g,h=population(t,d,shift)
    return C+t/2+d,g+np.array([.5,1.]),h
