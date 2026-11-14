"""Known-law two-step positive-risk NDU with a non-product forward channel.

P1 and P2 switch on independent Bernoulli branches. The forward recurrence is
H1=a*X, H2=b*H1 + kappa*(a-b)^2 + epsilon2*X/10. Risk is strictly positive.
There are exactly 16 elementary root-to-terminal configurations.
"""
from __future__ import annotations
import numpy as np
from scipy.special import logsumexp
GAMMA=.9
RISKS=(.5,1.)
KAPPA=.25


def leaf(a,b,x,p0,e1,e2,kappa=KAPPA,noise='correlated'):
    p1=p0 ^ (e1==1); p2=p1 ^ (e2==1)
    h1=a*x
    n=e2*(x if noise=='correlated' else 1.)/10
    h2=b*h1+kappa*(a-b)**2+n
    return dict(h1=float(h1),h2=float(h2),p0=int(p0),p1=int(p1),p2=int(p2),
                stage=float(p1/20),terminal=float((h2-x)**2+p2/50))


def ce2(v,rho):
    return float(np.logaddexp(rho*v[0],rho*v[1])/rho-np.log(2)/rho)


def branch_value(a,b,x,p0,kappa=KAPPA,noise='correlated'):
    outer=[]
    for e1 in (-1,1):
        end=[leaf(a,b,x,p0,e1,e2,kappa,noise) for e2 in (-1,1)]
        outer.append(end[0]['stage']+GAMMA*ce2([s['terminal'] for s in end],RISKS[end[0]['p1']]))
    return GAMMA*ce2(outer,RISKS[p0])


def direct(theta,kappa=KAPPA,noise='correlated',prob_plus=.5):
    a,b=np.asarray(theta,dtype=float)
    if noise not in ('correlated','uncorrelated') or not (0<=prob_plus<=1):
        raise ValueError('noise/probability')
    return sum((prob_plus if x==1 else 1-prob_plus)*.5*branch_value(a,b,x,p0,kappa,noise)
            for x in (-1,1) for p0 in (0,1)) +.25*(a*a+b*b)


def _two_point(values,gradients,hessians,rho):
    z=rho*np.asarray(values,dtype=float)
    weights=np.exp(z-logsumexp(z))
    value=float((logsumexp(z)-np.log(2))/rho)
    gradients=np.asarray(gradients,dtype=float)
    hessians=np.asarray(hessians,dtype=float)
    g=weights@gradients
    h=np.einsum('i,ijk->jk',weights,hessians)
    deviation=gradients-g[None,:]
    h=h+rho*np.einsum('i,ij,ik->jk',weights,deviation,deviation)
    return value,g,h


def population(t,d,noise='correlated',prob_plus=.5):
    """C(t,d) and exact analytical t,d gradient and Hessian of nested risk."""
    if noise not in ('correlated','uncorrelated') or not 0<=prob_plus<=1:raise ValueError('law')
    values=[]
    for x in (-1,1):
        for p0 in (0,1):
            outer_val=[];outer_g=[];outer_h=[]
            for e1 in (-1,1):
                p1=p0 ^ (e1==1)
                innerval=[];innerg=[];innerh=[]
                for e2 in (-1,1):
                    p2=p1 ^ (e2==1)
                    n=e2*(x if noise=='correlated' else 1)/10
                    z=x*(t-1)+d+n
                    v=z*z+p2/50
                    gr=2*z*np.array([x,1.])
                    hess=2*np.array([[1.,x],[x,1.]])
                    innerval.append(v);innerg.append(gr);innerh.append(hess)
                v,g,h=_two_point(innerval,innerg,innerh,RISKS[p1])
                outer_val.append(p1/20+GAMMA*v)
                outer_g.append(GAMMA*g);outer_h.append(GAMMA*h)
            v,g,h=_two_point(outer_val,outer_g,outer_h,RISKS[p0])
            w=(prob_plus if x==1 else 1-prob_plus)/2
            values.append((GAMMA*v*w,GAMMA*g*w,GAMMA*h*w))
    return (sum(v for v,g,h in values),
            sum((g for v,g,h in values),np.zeros(2)),
            sum((h for v,g,h in values),np.zeros((2,2))))


def objective(theta,kappa=KAPPA,noise='correlated',prob_plus=.5):
    a,b=np.asarray(theta,dtype=float)
    t=a*b;d=kappa*(a-b)**2
    c,g,h=population(t,d,noise,prob_plus)
    J=c+.25*(a*a+b*b)
    dt=np.array([b,a]);dd=2*kappa*(a-b)*np.array([1.,-1.])
    jac=np.array([dt,dd]); grad=jac.T@g+.5*np.array([a,b])
    HT=np.array([[0.,1.],[1.,0.]])
    HD=2*kappa*np.array([[1.,-1.],[-1.,1.]])
    H=jac.T@h@jac+g[0]*HT+g[1]*HD+.5*np.eye(2)
    return float(J),grad,H


def transfer(theta,kappa=KAPPA):
    return {'uncorrelated_noise':float(objective(theta,kappa,noise='uncorrelated')[0]),
            'biased_input':float(objective(theta,kappa,prob_plus=.7)[0]),
            'product_only':float(objective(theta,kappa=0)[0])}
