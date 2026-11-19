"""Independent NumPy convex scenario-tree reference with a global tangent bound.

No Torch/model/adjoint imports. One adapted action per tree node, box-constrained.
A feasible point supplies an upper bound; convex first-order support over the
box supplies a lower bound even if the optimizer has not converged.
"""
import numpy as np
from scipy.optimize import minimize


def build(p,state,mode):
    from problem import target_np
    n=2**p.horizon-1;d=2*n;count=2*n+1
    offsets=[None]*count;maps=[None]*count;modes=[0]*count
    offsets[0]=state[:2];maps[0]=np.zeros((2,d));modes[0]=mode
    selectors=[]
    for i in range(n):
        E=np.zeros((2,d));E[:,2*i:2*i+2]=np.eye(2);selectors.append(E)
        for j in (0,1):
            child=2*i+1+j
            offsets[child]=p.A@offsets[i]+(2*j-1)*p.noise[modes[i]]
            maps[child]=p.A@maps[i]+p.B@E;modes[child]=j
    target=target_np(state[None,2:],p)[0]
    return offsets,maps,modes,selectors,target


def evaluate(u,p,tree,hessian=True):
    offsets,maps,modes,selectors,target=tree;n=len(selectors);d=len(u)
    vals=[None]*(2*n+1);grads=[None]*len(vals);hess=[None]*len(vals)
    for i in reversed(range(len(vals))):
        h=offsets[i]+maps[i]@u;H=maps[i];m=modes[i]
        if i>=n:
            E=p.readouts@H;z=p.readouts@(h-target);a=p.weights[m]
            vals[i]=float(np.sum(a*(.5*z*z+.25*p.quartic*z**4)))
            grads[i]=E.T@(a*(z+p.quartic*z**3))
            if hessian:hess[i]=E.T@((a*(1+3*p.quartic*z*z))[:,None]*E)
        else:
            S=selectors[i];v=S@u;rc=p.action_cost[m]
            local=.5*p.state_cost*h@h+.5*rc*v@v
            gl=p.state_cost*H.T@h+rc*S.T@v
            vv=np.array([vals[2*i+1],vals[2*i+2]]);gg=np.array([grads[2*i+1],grads[2*i+2]])
            if p.eta:
                logs=np.log(p.branch[m])+p.eta*vv;mx=max(logs);ex=np.exp(logs-mx);wt=ex/ex.sum()
                ce=(mx+np.log(ex.sum()))/p.eta
            else:wt=p.branch[m];ce=wt@vv
            avg=wt@gg;vals[i]=local+p.gamma*ce;grads[i]=gl+p.gamma*avg
            if hessian:
                hh=wt[0]*hess[2*i+1]+wt[1]*hess[2*i+2]
                dev=gg-avg
                hh=hh+p.eta*(dev.T@(wt[:,None]*dev))
                hess[i]=p.state_cost*H.T@H+rc*S.T@S+p.gamma*hh
    return vals[0],grads[0],hess[0]


def solve(p,state,mode):
    tree=build(p,state,mode);d=2*(2**p.horizon-1);calls=0
    def fg(u):
        nonlocal calls
        calls+=1;f,g,_=evaluate(u,p,tree,False);return f,g
    result=minimize(fg,np.zeros(d),method='L-BFGS-B',jac=True,bounds=[(-p.bound,p.bound)]*d,
                    options=dict(maxiter=1500,ftol=1e-15,gtol=1e-10,maxls=40))
    u=result.x.copy()
    # Independent damped Newton polishing in action coordinates. All work paid.
    for _ in range(15):
        val,g,H=evaluate(u,p,tree,True);calls+=1
        if np.max(np.abs(g))<2e-11:break
        direction=-np.linalg.solve(H,g)
        step=1.;accepted=False
        for _ in range(30):
            candidate=np.clip(u+step*direction,-p.bound,p.bound)
            f,_,_=evaluate(candidate,p,tree,False);calls+=1
            if f<=val+1e-4*g@(candidate-u):u=candidate;accepted=True;break
            step*=.5
        if not accepted:break
    val,g,H=evaluate(u,p,tree,True);calls+=1
    gap=float(g@u+p.bound*np.abs(g).sum())
    # Exact real-arithmetic convex support formula; evaluated FP64, not interval certified.
    return dict(upper=val,lower=val-gap,gap_bound=gap,actions=u,
                gradient_inf=float(np.max(np.abs(g))),hessian_min=float(np.linalg.eigvalsh(H).min()),
                evaluations=calls,optimizer_success=bool(result.success),interval_certified=False)
