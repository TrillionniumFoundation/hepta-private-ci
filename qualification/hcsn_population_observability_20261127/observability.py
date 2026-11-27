"""Recoverability of future event probabilities from finite population messages.

Standalone Python 3 with NumPy/SciPy. Run with OPENBLAS_NUM_THREADS=1.
The He–Xiong Eq. (11) resolvent is evaluated by scalar quadrature. The boundary
comes from the nonexplosion condition and E_x(0)=0, independent of Eq. (12) code.
"""
import argparse
import json
from math import exp, log, sqrt
from pathlib import Path
import warnings
import numpy as np
from scipy.integrate import quad
from scipy.linalg import qr
from scipy.optimize import linprog, OptimizeWarning
from scipy.special import ndtr, log_ndtr

X=np.array([.025,.075,.125,.18,.235,.30,.46,.70])
R,DELTA,SIGMA,TAX,ALPHA,C,P=.08,.02,.23,.27,.6,6.39,61.68
Q=.09; D=SIGMA**2/2; MU=R-DELTA-D
ETA=(-MU+sqrt(MU**2+4*D*R))/(2*D)
GAMMA=(MU+sqrt(MU**2+4*D*R))/(2*D)
def hit(x,h):
    x=np.asarray(x);std=SIGMA*sqrt(h)
    return ndtr((-x-MU*h)/std)+np.exp(-MU*x/D+log_ndtr((-x+MU*h)/std))
def disc_hit(x,h):
    x=np.asarray(x);std=SIGMA*sqrt(h);chi=sqrt(MU**2+2*Q*SIGMA**2)
    return (np.exp((-MU+chi)*x/SIGMA**2+log_ndtr((-x-chi*h)/std))+
            np.exp((-MU-chi)*x/SIGMA**2+log_ndtr((-x+chi*h)/std)))
def boundary(principal=P):
    incl=lambda f: quad(lambda y:exp(-ETA*y)*f(y),0,np.inf,epsabs=1e-12)[0]
    c0=C/Q+exp(-Q)*(principal-C/Q)
    return (((1-TAX)*C+principal-c0)/ETA+exp(-Q)*(principal-C/Q)*incl(lambda y:hit(y,1))+
            (C/Q)*incl(lambda y:disc_hit(y,1)))/(DELTA/(ETA-1)+ALPHA*incl(lambda y:disc_hit(y,1)))
def price(x,principal=P):
    b=boundary(principal)
    def loss(y):return exp(-Q)*(principal-C/Q)*hit(y,1)+(C/Q-ALPHA*b)*disc_hit(y,1)
    no_default=C/Q+exp(-Q)*(principal-C/Q)
    def cash(y):return DELTA*b*exp(y)-(1-TAX)*C+no_default-loss(y)-principal
    def single(t):
        return -quad(lambda y:(exp(ETA*(t-y))-exp(-GAMMA*(t-y)))*cash(y),0,t,epsabs=1e-11)[0]/(D*(ETA+GAMMA))
    return np.array([single(t) for t in x]),loss(x)
def rank_sv(A):
    n=A/np.linalg.norm(A,axis=1)[:,None];sv=np.linalg.svd(n,compute_uv=False)
    return int((sv>1e-12*sv[0]).sum()),sv.tolist()
def minimax(A,target,epsilon):
    # Bounded noisy measurements after per-row max normalization. The mass-sum row is exact.
    a=A/np.max(abs(A),axis=1)[:,None];m,n=a.shape;k=m-1
    obj=np.r_[np.zeros(m),1.,np.full(k,epsilon)]
    ff=np.c_[np.zeros(k),np.eye(k)]
    lhs=np.vstack((np.c_[a.T,-np.ones(n),np.zeros((n,k))],np.c_[-a.T,-np.ones(n),np.zeros((n,k))],
                   np.c_[ff,np.zeros(k),-np.eye(k)],np.c_[-ff,np.zeros(k),-np.eye(k)]))
    kw=dict(method="highs",options={"threads":1,"primal_feasibility_tolerance":1e-9,"dual_feasibility_tolerance":1e-9})
    with warnings.catch_warnings():
        warnings.simplefilter("ignore",OptimizeWarning)
        p=linprog(obj,A_ub=lhs,b_ub=np.r_[target,-target,np.zeros(2*k)],bounds=[(None,None)]*m+[(0,None)]*(1+k),**kw)
        aa=np.c_[a[1:],-a[1:]]
        d=linprog(np.r_[-target,target],A_ub=np.vstack((aa,-aa)),b_ub=np.full(2*k,2*epsilon),
                  A_eq=[np.r_[np.ones(n),np.zeros(n)],np.r_[np.zeros(n),np.ones(n)]],b_eq=[1,1],bounds=(0,None),**kw)
    if not(p.success and d.success):raise ArithmeticError((p.message,d.message))
    actual=max(abs(target-a.T@p.x[:m]))+epsilon*abs(p.x[1:m]).sum()
    assert abs(actual+d.fun/2)<2e-7
    return {"primal":float(actual),"dual_half_diameter":float(-d.fun/2)}
def analyze():
    e,l=price(X);ones=np.ones(len(X))
    q=hit(X,.25);h=hit(X,.5)-q
    witnesses=[]
    for a in (np.stack((ones,e,l)),np.stack((ones,e,l,q)),np.stack((ones,e,l,q,hit(X,1)))):
        normalized=a/np.linalg.norm(a,axis=1)[:,None]
        _,sv,v=np.linalg.svd(normalized,full_matrices=True);b=v[len(sv):].T
        direction=b@(b.T@h);step=.99/len(X)/max(abs(direction))
        hi=1/len(X)+step*direction;lo=1/len(X)-step*direction
        assert min(hi.min(),lo.min())>0 and max(abs(a@(hi-lo)))<2e-12
        witnesses.append(dict(observed=a.shape[0],high=hi.tolist(),low=lo.tolist(),
              max_observed_divergence=float(max(abs(a@(hi-lo)))),future_hit_gap=float((hi-lo)@h)))
    base=np.stack((ones,e,l,q));s=base/np.linalg.norm(base,axis=1)[:,None]
    _,sv,v=np.linalg.svd(s,full_matrices=True);null=v[len(sv):].T
    bank_times=np.array([.08,.125,.2,.35,.5,.75,1.,1.5,2.,3.]);bank=np.stack([hit(X,t) for t in bank_times])
    residual=(bank/np.linalg.norm(bank,axis=1)[:,None])@null
    chosen=bank_times[qr(residual.T,pivoting=True)[2][:len(X)-len(base)]]
    targets=[.10,.16,.42,.65,.9,1.25,1.75,2.5];augmented=[]
    for i in range(len(chosen)+1):
        a=np.vstack([base]+[hit(X,t) for t in chosen[:i]]);noise={}
        for eps in (0.,1e-4,1e-3,1e-2):
            scores={str(t):minimax(a,hit(X,t),eps) for t in targets}
            noise[str(eps)]=dict(worst=max(p["primal"] for p in scores.values()),horizons=scores)
        augmented.append(dict(probes=chosen[:i].tolist(),rank_and_singular_values=rank_sv(a),noise=noise))
    return dict(reference_boundary=boundary(),margin_grid=X.tolist(),nominal_equity=e.tolist(),nominal_loss=l.tolist(),
                witnesses=witnesses,base_rank=rank_sv(base),joint_rank=rank_sv(np.vstack((base,bank))),
                augmentation=augmented,heldout_horizons=targets,
                scope="Known finite support, piecewise frozen diffusion, arbitrary positive probability mixtures. Deterministic minimax recovery, not a learned task score.")
if __name__=="__main__":
    ap=argparse.ArgumentParser();ap.add_argument("output",type=Path);args=ap.parse_args()
    args.output.write_text(json.dumps(analyze(),indent=2)+"\n")
