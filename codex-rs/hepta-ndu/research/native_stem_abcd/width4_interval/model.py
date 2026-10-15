"""R21: same known 2-step entropic law, widths 2/3/4 true coupled forward weights.

Full 16-leaf objective and exact analytic first and second parameter derivatives.
No optimum, certificate or training data enters these calculations.
"""
import numpy as np
from scipy.special import logsumexp

RISKS=(.5,1.); GAMMA=.9; ETA=.04; KAPPA=.125
METHODS=('adam','bfgs','lbfgs','trust-exact','ad-trust-exact')
INITIALS=((0.,0.),(.1,.1),(-.1,-.1),(1.,1.),(-1.,-1.),(2.,-2.),(1.,-1.),(2.,2.))

def q(v,k):return k*v/(1+v*v)
def dq(v,k):return k*(1-v*v)/(1+v*v)**2
def ddq(v,k):return k*2*v*(v*v-3)/(1+v*v)**3

def forward(theta,x,e1,e2):
    """2 weights: R20 signed control. 3: eps1 forward cell. 4: quadratic mixing."""
    a,b=float(theta[0]),float(theta[1]);c=float(theta[2]) if len(theta)>2 else 0.
    d=float(theta[3]) if len(theta)>3 else 0.
    h1=a*x+c
    v=a-b
    h2=b*h1+d*h1*h1/4+v*v/4+q(a,ETA)+q(v,KAPPA)+e2/10
    return h1,h2

def leaf_table(theta):
    rows=[]
    for x in (-1,1):
      for p0 in (0,1):
       for e1 in (-1,1):
        p1=p0^(e1==1)
        for e2 in (-1,1):
         p2=p1^(e2==1)
         h1,h2=forward(theta,x,e1,e2)
         rows.append([x,p0,e1,e2,p1,p2,h1,h2,p1/20,(h2-x-1)**2+p2/50])
    return np.asarray(rows,dtype=np.float64)

def softmax(values,rho):
    z=rho*np.asarray(values)
    return np.exp(z-logsumexp(z))

def full(theta):
    theta=np.asarray(theta,dtype=np.float64);n=len(theta)
    if n not in (2,3,4):raise ValueError('width should be 2,3,4')
    a,b=theta[:2];c=theta[2] if n>2 else 0.;d=theta[3] if n>3 else 0.
    v=a-b
    ea=np.zeros(n);eb=np.zeros(n);ea[0]=1.;eb[1]=1.
    ec=np.zeros(n);ed=np.zeros(n)
    if n>2:ec[2]=1.
    if n>3:ed[3]=1.
    dv=ea-eb
    result=0.;gradient=np.zeros(n);hessian=np.zeros((n,n))
    for x in (-1,1):
      for p0 in (0,1):
       outer=[];outer_g=[];outer_H=[]
       for e1 in (-1,1):
        p1=p0^(e1==1)
        h1=a*x+c
        u=x*ea+ec
        z=b*h1+d*h1*h1/4+v*v/4+q(a,ETA)+q(v,KAPPA)
        dh=(b+d*h1/2)*u+h1*eb+(h1*h1/4)*ed+v*dv/2+dq(a,ETA)*ea+dq(v,KAPPA)*dv
        hh=(np.outer(eb,u)+np.outer(u,eb)+d/2*np.outer(u,u)
            +h1/2*(np.outer(ed,u)+np.outer(u,ed))
            +(.5+ddq(v,KAPPA))*np.outer(dv,dv)+ddq(a,ETA)*np.outer(ea,ea))
        leaves=[];gs=[];hs=[]
        for e2 in (-1,1):
         p2=p1^(e2==1)
         err=z+e2/10-x-1
         leaves.append(err*err+p2/50)
         gs.append(2*err*dh)
         hs.append(2*np.outer(dh,dh)+2*err*hh)
        rho=RISKS[p1];w=softmax(leaves,rho)
        ce=logsumexp(rho*np.asarray(leaves))/rho-np.log(2)/rho
        mg=sum(w[i]*gs[i] for i in range(2))
        cov=sum(w[i]*np.outer(gs[i],gs[i]) for i in range(2))-np.outer(mg,mg)
        outer.append(p1/20+GAMMA*ce)
        outer_g.append(GAMMA*mg)
        outer_H.append(GAMMA*(sum(w[i]*hs[i] for i in range(2))+rho*cov))
       rho=RISKS[p0];w=softmax(outer,rho)
       result+=GAMMA*(logsumexp(rho*np.asarray(outer))/rho-np.log(2)/rho)/4
       mg=sum(w[i]*outer_g[i] for i in range(2))
       cov=sum(w[i]*np.outer(outer_g[i],outer_g[i]) for i in range(2))-np.outer(mg,mg)
       gradient+=GAMMA*mg/4
       hessian+=GAMMA*(sum(w[i]*outer_H[i] for i in range(2))+rho*cov)/4
    result+=theta@theta/4;gradient+=theta/2;hessian+=np.eye(n)/2
    return float(result),gradient,hessian

def independent_full(theta):
    """Independent evaluator builds all sixteen explicit branches (no analytic derivatives)."""
    table=leaf_table(theta)
    cost=0.
    for x in (-1,1):
     for p0 in (0,1):
      stages=[]
      for e1 in (-1,1):
       records=table[(table[:,0]==x)&(table[:,1]==p0)&(table[:,2]==e1)]
       r=RISKS[int(records[0,4])]
       leaves=records[:,9]
       stages.append(float(records[0,8])+(logsumexp(r*leaves)-np.log(2))/r*GAMMA)
      r=RISKS[p0]
      cost+=GAMMA/4*(logsumexp(r*np.asarray(stages))-np.log(2))/r
    z=np.asarray(theta,dtype=float)
    return float(cost+z@z/4)
