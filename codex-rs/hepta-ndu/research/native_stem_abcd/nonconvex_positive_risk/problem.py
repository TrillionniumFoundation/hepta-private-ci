"""Numerical R16 two-step preference-switching, positive-entropic-risk model.

No reference optimum is used in objective/gradient/optimizer. All 8 nested
noise/preference branches and two X-atom states are exact finite-law sums.
"""
import numpy as np
from scipy.special import logsumexp
G=.9
RISKS=(.5,1.)


def loss_tree(a,b,x,p0,e1,e2):
    p1=p0 ^ (e1==1)
    p2=p1 ^ (e2==1)
    h1=a*x
    h2=b*h1+e2/10
    terminal=(h2-x)**2+p2/50
    stage=p1/20
    return dict(h1=h1,h2=h2,p1=p1,p2=p2,terminal=terminal,stage=stage)


def ce_costs(t,x,p0):
    # Separate explicit tree formula, no cosh simplification.
    stage=[]
    for e1 in (-1,1):
        branch=[loss_tree(1,t,x,p0,e1,e2) for e2 in (-1,1)]
        risk=RISKS[branch[0]['p1']]
        ce=logsumexp(np.array([v['terminal'] for v in branch])*risk)/risk-np.log(2)/risk
        stage.append(branch[0]['stage']+G*ce)
    risk0=RISKS[p0]
    return G*(logsumexp(risk0*np.asarray(stage))/risk0-np.log(2)/risk0)


def C(t):
    return sum(ce_costs(float(t),x,p) for x in (-1,1) for p in (0,1))/4


def c_derivatives(t):
    """Analytic nested entropic adjoint + Hessian in quotient parameter t=ab."""
    u=float(t)-1
    val=grad=hess=0.
    for x in (-1,1):
        y=np.array([RISKS[p]*(u*x/5+(1-2*p)/100) for p in (0,1)])
        lp=np.array([np.logaddexp(yv,-yv)-np.log(2.) for yv in y])
        A=np.array([p/20+G*(u*u+.02+lp[p]/RISKS[p]) for p in (0,1)])
        Ap=G*np.array([2*u+x/5*np.tanh(yv) for yv in y])
        App=G*np.array([2+RISKS[p]*(x/5)**2/(np.cosh(y[p])**2) for p in (0,1)])
        for p0 in (0,1):
            logits=RISKS[p0]*A
            w=np.exp(logits-logsumexp(logits))
            c=G*(logsumexp(logits)-np.log(2))/RISKS[p0]
            v=w@Ap
            curv=w@App+RISKS[p0]*(w@(Ap*Ap)-v*v)
            val+=c/4;grad+=G*v/4;hess+=G*curv/4
    return val,grad,hess


def objective(theta):
    a,b=np.asarray(theta,dtype=float)
    return C(a*b)+(a*a+b*b)/4


def derivative(theta):
    a,b=np.asarray(theta,dtype=float)
    _,c,c2=c_derivatives(a*b)
    grad=np.array([c*b+a/2,c*a+b/2])
    hess=np.array([[.5+c2*b*b,c+c2*a*b],[c+c2*a*b,.5+c2*a*a]])
    return grad,hess


def populations_agree(theta):
    a,b=theta
    exact=sum(ce_costs(a*b,x,p) for x in (-1,1) for p in (0,1))/4
    return objective(theta),float(exact)+(a*a+b*b)/4
