"""R15 nonlinear-in-parameter two-step entropic forward Stem.

Population: R14 original finite five-point law, fully enumerated 40 terminal
branches. New second-step state has a nonaffine learned-weight response.
"""
from fractions import Fraction as Q
from itertools import product
from math import sin, cos
import numpy as np
from scipy.special import logsumexp

XS=tuple(Q(i,2) for i in (-2,-1,0,1,2))
PS=(0,1)
EPS=(-1,1)
RHO=(Q(1,2),Q(1))
GAMMA=Q(9,10)
KAPPA=Q(1,100)
BOX=(Q(-2),Q(2))


def branch(a,b,x,p0,e1,e2,kappa=KAPPA,oscillatory=False):
    """Returns rational stage losses, gradients, Hessians for fixed noise path."""
    p1=p0^(e1==1)
    p2=p1^(e2==1)
    phi=(x*x,x*x*x)
    t1=x*x+x**4/2
    h1=x+a*phi[0]+b*phi[1]+Q(e1,5)
    z=h1-t1
    gain=1+Q(e1)*x/10
    # Second state evolves NONLINEARLY in shared learned weights.
    if oscillatory:
        # Separate UNcertified nonconvex stress arm; no impact on strict theorem.
        nonlinear=sin(4*float(z))
        d_nonlin=4*cos(4*float(z))
        d2_nonlin=-16*sin(4*float(z))
    else:
        nonlinear=kappa*z*z
        d_nonlin=2*kappa*z
        d2_nonlin=2*kappa
    h2=gain*h1+nonlinear+Q(e2,10)
    t2=gain*t1+x/8
    d2=h2-t2
    l1=z*z+Q(p1,20)
    l2=d2*d2+Q(p2,25)
    c2=gain+d_nonlin
    q2=2*(c2*c2+d2_nonlin*d2)
    g1=tuple(2*z*v for v in phi)
    g2=tuple(2*d2*c2*v for v in phi)
    h1mat=tuple(tuple(2*v*w for w in phi) for v in phi)
    h2mat=tuple(tuple(q2*v*w for w in phi) for v in phi)
    return dict(z=z,gain=gain,gap2=d2,p1=p1,p2=p2,l1=l1,l2=l2,
                g1=g1,g2=g2,h1mat=h1mat,h2mat=h2mat,c2=c2,q2=q2)


def ce_details(children,rho):
    vals=np.array([v[0] for v in children],dtype=float)
    grads=np.array([v[1] for v in children],dtype=float)
    hesses=np.array([v[2] for v in children],dtype=float)
    logits=float(rho)*vals
    weights=np.exp(logits-logsumexp(logits))
    val=(logsumexp(logits)-np.log(2))/float(rho)
    grad=np.einsum('i,ij->j',weights,grads)
    hess=np.einsum('i,ijk->jk',weights,hesses)
    centered=grads-grad
    hess+=float(rho)*np.einsum('i,ij,ik->jk',weights,centered,centered)
    return float(val),grad,hess


def population(theta,kappa=KAPPA,oscillatory=False):
    a,b=map(float,theta)
    kappa=float(kappa)
    value=0.;grad=np.zeros(2);hess=np.zeros((2,2))
    for x,p0 in product(XS,PS):
        step1=[]
        for e1 in EPS:
            d=[branch(a,b,float(x),p0,e1,e2,kappa,oscillatory) for e2 in EPS]
            ce,ce_g,ce_h=ce_details([(r['l2'],r['g2'],r['h2mat']) for r in d],RHO[d[0]['p1']])
            r=d[0]
            step1.append((float(r['l1'])+float(GAMMA)*ce,
                          np.array(r['g1'],float)+float(GAMMA)*ce_g,
                          np.array(r['h1mat'],float)+float(GAMMA)*ce_h))
        ce,ce_g,ce_h=ce_details(step1,RHO[p0])
        value+=float(GAMMA)*ce/10
        grad+=float(GAMMA)*ce_g/10
        hess+=float(GAMMA)*ce_h/10
    return value,grad,hess


def stage_values(theta,x,p0,kappa=KAPPA,oscillatory=False):
    a,b=map(float,theta)
    candidates=[]
    for e1 in EPS:
        branch_pair=[branch(a,b,float(x),p0,e1,e2,float(kappa),oscillatory) for e2 in EPS]
        terminal_cost=[float(r['l2']) for r in branch_pair]
        p1=branch_pair[0]['p1']; r=float(RHO[p1])
        ce=(logsumexp(np.array(terminal_cost)*r)-np.log(2))/r
        candidates.append(float(branch_pair[0]['l1'])+float(GAMMA)*ce)
    r=float(RHO[p0]);outer=(logsumexp(np.array(candidates)*r)-np.log(2))/r
    return float(GAMMA)*outer


def population_direct(theta,kappa=KAPPA,oscillatory=False):
    return sum(stage_values(theta,x,p0,kappa,oscillatory) for x,p0 in product(XS,PS))/10


def certified_leaf_hessian_lower(kappa=KAPPA):
    """Conservative rational domain-wide pointwise bound, NO numerical sampling.

    |z|<=67/10, 9/10<=gain<=11/10,
    d2=gain*z+k*z^2+eps2/10-x/8.
    Terminal Hessian prefactor q2=2[(gain+2kz)^2+2k*d2].
    Works only for positive k satisfying gain>=2k*67/10.
    """
    k=Q(kappa)
    if k<=0:raise ValueError('positive nonlinear coefficient required')
    zmax=Q(67,10)
    leading=Q(9,10)-2*k*zmax
    if leading<0:raise ValueError('domain-wide simple lower bound unavailable')
    gapupper=Q(11,10)*zmax+k*zmax*zmax+Q(1,10)+Q(1,8)
    qmin=2*(leading*leading-2*k*gapupper)
    if qmin<=0:raise ValueError('terminal convexity not proven')
    return qmin


if __name__=='__main__':
    print('leaf prefactor guaranteed >=',certified_leaf_hessian_lower())
    for k in (.01,.1,.3,1.):
        theta=np.array([1.48,-1.])
        print(k,population(theta,k)[0],np.linalg.eigvalsh(population(theta,k)[2]))
