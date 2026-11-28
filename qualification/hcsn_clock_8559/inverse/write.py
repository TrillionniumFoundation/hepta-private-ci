"""Exact affordable local target writing vs numerical local inversion and same-site full reverse optimization."""
import argparse
import json
import time
from pathlib import Path
import numpy as np
import torch
from scipy.optimize import least_squares
from scipy.special import expit,logit
from identify import Basis,LO,HI

def latent_input(x,s):return np.stack([logit((x-LO)/(HI-LO)),np.arctanh(s/.30)],1)
def state(X,W):
    raw=X@W;return LO+(HI-LO)*expit(raw[:,0]),.30*np.tanh(raw[:,1])
def observable(law,x,s):
    return np.stack([law.equity_loss(x,s)[:,0],law.hit(x,.25)],1)
def forms(law,X,W):return observable(law,*state(X,W))
def norm(v):return np.max(np.abs(v),axis=0).tolist()
def solve(seed,law):
    rng=np.random.default_rng(seed);d=32
    X=rng.normal(size=(16,d));K=rng.normal(size=(12,d));Z=rng.normal(size=(128,d))
    W0=rng.normal(0,.14,(d,2));desired_x=rng.uniform(.055,.30,len(X));desired_s=rng.uniform(-.2,.2,len(X))
    targets=observable(law,desired_x,desired_s)
    oldK=forms(law,K,W0);oldZ=forms(law,Z,W0);rows=[]
    for method in ('direct_inverse','local_nonlinear_inverse','reverse_lbfgs'):
        initial=time.perf_counter();cpu=time.process_time()
        _,sv,vh=np.linalg.svd(K,full_matrices=True);Q=vh[len(sv):].T
        H=X@Q
        if method!='reverse_lbfgs':
            if method=='direct_inverse':
                x,s,valid=law.from_equity_hit(targets[:,0],targets[:,1],.25);assert valid.all()
                solves=1
            else:
                x,s=state(X,W0);solves=0
                for i,target in enumerate(targets):
                    def f(v):return (observable(law,v[:1],v[1:])[0]-target)
                    fit=least_squares(f,[x[i],s[i]],bounds=([LO,-.3],[HI,.3]),ftol=1e-14,xtol=1e-14,gtol=1e-14,max_nfev=150)
                    x[i],s[i]=fit.x;solves+=fit.nfev
            raw=latent_input(x,s);coeff=np.linalg.lstsq(H,raw-X@W0,rcond=None)[0]
            W=W0+Q@coeff
        else:
            X0=torch.tensor(X);Q0=torch.tensor(Q);Winit=torch.tensor(W0);goal=torch.tensor(targets)
            D=torch.zeros((Q.shape[1],2),dtype=torch.float64,requires_grad=True)
            opt=torch.optim.LBFGS([D],lr=1.,max_iter=350,max_eval=500,tolerance_grad=1e-12,
                                  tolerance_change=1.e-16,line_search_fn='strong_wolfe',history_size=50)
            calls=0
            def closure():
                nonlocal calls
                calls+=1;opt.zero_grad()
                raw=X0@(Winit+Q0@D);x=LO+(HI-LO)*raw[:,0].sigmoid();s=.30*raw[:,1].tanh()
                e,_=law.price_torch(x,s);f=law.law.passage(x,.25)
                z=torch.stack([e,f],1);loss=((z-goal)**2).mean();loss.backward();return loss
            opt.step(closure);W=W0+Q@D.detach().numpy();solves=calls
        new=forms(law,X,W);unchanged=forms(law,K,W);newZ=forms(law,Z,W)
        err=norm(new-targets);ret=norm(unchanged-oldK);off=np.sqrt(np.mean((newZ-oldZ)**2,axis=0)).tolist()
        rows.append(dict(seed=seed,method=method,wall_s=time.perf_counter()-initial,cpu_s=time.process_time()-cpu,
             target_max=err,protected_max=ret,unprotected_rms=off,gate=bool(max(err)<=1e-6 and max(ret)<=1e-9),
             numerical_evaluations=solves,weight_update_rank=int(np.linalg.matrix_rank(W-W0)),update_frobenius=float(np.linalg.norm(W-W0)),
             achieved_weights=W.tolist()))
    return rows
def main(out):
    torch.set_num_threads(1);t=time.perf_counter();law=Basis();setup=time.perf_counter()-t;rows=[]
    for seed in (137,311,557,677,991):
        rows+=solve(seed,law)
        out.write_text(json.dumps(dict(shared_analytic_setup_wall_s=setup,rows=rows),indent=1)+'\n')
        print(seed,[(r['method'],r['gate'],r['target_max'],round(r['cpu_s'],4)) for r in rows[-3:]],flush=True)
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('out',type=Path);a=p.parse_args();main(a.out)
