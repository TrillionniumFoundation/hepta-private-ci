"""Matched-likelihood analytic readout training and reverse-mode timing on recorded spikes."""
import argparse
import json
from pathlib import Path
import time
import numpy as np
from scipy.optimize import minimize
from scipy.special import ndtr
import torch
from recorded import Risk,current_bank,mle,nll,REGIONS

def link(z,law):
    t=np.tanh(z);margin=.18-np.log1p(law.k*t);x=margin.clip(0)
    s=law.sigma*np.sqrt(law.t);k=2*law.mu/law.sigma**2
    a=(-x-law.mu*law.t)/s;b=(-x+law.mu*law.t)/s;mirror=np.exp(-k*x)
    raw=ndtr(a)+mirror*ndtr(b);p=raw.clip(1e-10,1-1e-10)
    pdf=lambda y:np.exp(-.5*y*y)/np.sqrt(2*np.pi)
    fx=-pdf(a)/s-mirror*(k*ndtr(b)+pdf(b)/s)
    slope=np.where((margin>0)&(raw>1e-10)&(raw<1-1e-10),fx*(-law.k*(1-t*t)/(1+law.k*t)),0.)
    return p,slope
def score(X,y,w,w0,r,law,with_fisher=False):
    p,g=link(X@w,law);bern=p*(1-p);diff=w-w0
    value=float(np.mean(-y*np.log(p)-(1-y)*np.log1p(-p))+.5*r*(diff@diff))
    grad=X.T@((p-y)*g/bern)/len(X)+r*diff
    if not with_fisher:return value,grad
    info=X.T@(X*(g*g/bern)[:,None])/len(X)+r*np.eye(len(w))
    return value,grad,info
def analytic(X,y,w0,r,law,diagonal=False):
    if not diagonal:
        res=minimize(lambda w:score(X,y,w,w0,r,law),w0,jac=True,method='L-BFGS-B',options={'maxiter':350,'ftol':1e-13,'gtol':1e-9})
        return res.x,dict(iterations=int(res.nit),converged=bool(res.success))
    w=w0.copy();steps=0
    for iteration in range(180):
        value,g,info=score(X,y,w,w0,r,law,True)
        if np.max(np.abs(g))<3e-9:break
        change=np.linalg.solve(info,-g);inner=g@change;t=1.
        while t>=2**-37:
            proposed=w+t*change
            nv=score(X,y,proposed,w0,r,law)[0]
            if nv<=value+1e-4*t*inner+1e-15:break
            t*=.5
        if t<2**-37:break
        w=proposed;steps+=1
    final=score(X,y,w,w0,r,law)
    return w,dict(iterations=steps,converged=bool(np.max(abs(final[1]))<2e-7))
def main(data,core,out):
    torch.set_num_threads(1);law=Risk(core);methods=['manual_lbfgs','torch_lbfgs','fisher'];rates=[1e-5,.001,.03]
    results={};rng=np.random.default_rng(7261)
    for site in 'ABC':
        with np.load(data/(site+'.npz')) as z:
            x=current_bank(z['currents']);x=np.column_stack([np.ones(len(x)),x]);y=z['y'].astype('float64')
        X=x[REGIONS['train']];Y=y[REGIONS['train']];target=Y.mean(1)
        w0=np.zeros(x.shape[1]);w0[0]=law.inverse(float(target.mean()),[])
        maxd=0.
        for j in range(9):
            w=w0+rng.normal(0,.035,len(w0));v=rng.normal(size=len(w0));v/=np.linalg.norm(v);ep=3e-6
            f=lambda z:score(X,target,z,w0,.001,law)
            finite=(f(w+ep*v)[0]-f(w-ep*v)[0])/(2*ep)
            maxd=max(maxd,abs(f(w)[1]@v-finite))
        hist={m:[] for m in methods};all_fits={};cold_scores={}
        for j in range(8):
            for m in methods[j%3:]+methods[:j%3]:
                tic=time.perf_counter();cpu=time.process_time();opts=[]
                for r in rates:
                    if m=='torch_lbfgs':w,meta=mle(X,Y,w0,r,law,False)
                    else:w,meta=analytic(X,target,w0,r,law,m=='fisher')
                    testp=law.prob(x[REGIONS['dev']]@w);v=float(nll(testp,y[REGIONS['dev']]).mean())
                    opts.append(dict(ridge=r,weights=w.tolist(),dev_nll=v,**meta))
                took=dict(wall_s=time.perf_counter()-tic,cpu_s=time.process_time()-cpu)
                if j>0:hist[m].append(took)
                if j==0:all_fits[m]=opts
                else:assert max(abs(a['dev_nll']-b['dev_nll']) for a,b in zip(opts,all_fits[m]))<1e-10
        chosen={m:min(opts,key=lambda z:z['dev_nll']) for m,opts in all_fits.items()}
        ref=law.prob(x[REGIONS['cold']]@np.array(chosen['torch_lbfgs']['weights']))
        for m,rec in chosen.items():
            pp=law.prob(x[REGIONS['cold']]@np.array(rec['weights']))
            cold_scores[m]=dict(nll=float(nll(pp,y[REGIONS['cold']]).mean()),ridge=rec['ridge'],
                                all_prob_max_abs_vs_bp=float(np.max(abs(pp-ref))),
                                median_wall=np.median([v['wall_s'] for v in hist[m]]),median_cpu=np.median([v['cpu_s'] for v in hist[m]]))
        results[site]=dict(max_directional_gradient_error=maxd,holdout=cold_scores,all_fits=all_fits,times=hist,
                           fit_setup='external features and label bins ready; includes three ridge solves and dev scoring; excludes common measured-current preparation')
        print(site,[(m,z['nll'],z['all_prob_max_abs_vs_bp'],z['median_wall']) for m,z in cold_scores.items()],flush=True)
    out.write_text(json.dumps(results,indent=2,allow_nan=False)+'\n')
if __name__=='__main__':
    p=argparse.ArgumentParser()
    for n in ('data','core','out'):p.add_argument('--'+n,type=Path,required=True)
    a=p.parse_args();main(a.data,a.core,a.out)
