"""Risk inverse, sequential sufficient statistics and likelihood training of the same neuronal readout."""
import argparse
import gzip
import json
import os
from pathlib import Path
import sys
import time

import numpy as np
from scipy.optimize import brentq,minimize
from scipy.special import ndtr,expit
import torch

sys.path.insert(0,str(Path(__file__).parents[1]/'neurons'))
from spikes import current_bank,REGIONS

class Risk:
    def __init__(self,core):
        sys.path.insert(0,str(core.resolve()))
        from he_xiong import Published
        p=Published();self.k=.28*p.bp*p.p.P0/p.B0;self.mu=p.mu;self.sigma=p.p.sigma;self.t=.25
    def prob(self,z):
        x=np.maximum(.18-np.log1p(self.k*np.tanh(z)),0)
        s=self.sigma*np.sqrt(self.t)
        return np.minimum(1.,ndtr((-x-self.mu*self.t)/s)+np.exp(-2*self.mu*x/self.sigma**2)*ndtr((-x+self.mu*self.t)/s))
    def torch_prob(self,z):
        x=(.18-torch.log1p(self.k*z.tanh())).clamp_min(0)
        s=self.sigma*np.sqrt(self.t)
        return torch.special.ndtr((-x-self.mu*self.t)/s)+(-2*self.mu*x/self.sigma**2).exp()*torch.special.ndtr((-x+self.mu*self.t)/s)
    def inverse(self,p,errors):
        lo,hi=self.prob(-25.),self.prob(25.)
        if not lo<p<hi:
            errors.append(float(p));return -12. if p<=lo else 12.
        return brentq(lambda z:self.prob(z)-p,-25.,25.,xtol=1e-13)

def nll(p,y):
    p=np.clip(p,1e-10,1-1e-10);f=y.mean(axis=1)
    return -(f*np.log(p)+(1-f)*np.log1p(-p))

def batch(X,z,w0,r):
    A=r*np.eye(len(w0))+X.T@X
    return np.linalg.solve(A,r*w0+X.T@z)
def recursive(X,z,w0,r,rotation=None,transport=True,last_only=False):
    w=w0.copy();P=np.eye(len(w))/r
    half=len(X)//2
    for t,(h,s) in enumerate(zip(X,z)):
        if rotation is not None and t>=half:
            if transport and t==half:
                P=rotation.T@P@rotation;w=rotation.T@w
            h=h@rotation
        if last_only:
            w+=h*((s-h@w)/(h@h))
        else:
            ph=P@h;g=ph/(1+h@ph)
            w+=g*(s-h@w)
            P-=np.outer(g,ph)
    return w
def mle(X,y,w0,r,law,logistic):
    x=torch.tensor(X,dtype=torch.float64);z=torch.tensor(y.mean(1),dtype=torch.float64);prior=x.new_tensor(w0)
    def objective(w):
        w=torch.tensor(w,dtype=torch.float64,requires_grad=True)
        h=x@w;p=torch.sigmoid(h) if logistic else law.torch_prob(h)
        p=p.clamp(1e-10,1-1e-10);value=-(z*p.log()+(1-z)*torch.log1p(-p)).mean()+.5*r*(w-prior).square().sum()
        grad,=torch.autograd.grad(value,w);return value.item(),grad.detach().numpy()
    q=minimize(objective,w0,jac=True,method='L-BFGS-B',options={'maxiter':350,'ftol':1e-13,'gtol':1e-9})
    return q.x,dict(iterations=int(q.nit),converged=bool(q.success),status=str(q.message))
def record(data,core,out):
    torch.set_num_threads(1);law=Risk(core);results={};info={}
    for s in 'ABC':
        with np.load(data/(s+'.npz')) as z:
            ts=time.monotonic();X=current_bank(z['currents']);X=np.column_stack([np.ones(len(X)),X]);y=z['y'].astype(float)
            features_s=time.monotonic()-ts
        xt=X[REGIONS['train']];yt=y[REGIONS['train']];xd=X[REGIONS['dev']];yd=y[REGIONS['dev']]
        errors=[];p0=float(yt.mean());w0=np.zeros(X.shape[-1]);w0[0]=law.inverse(p0,errors)
        logw=np.zeros_like(w0);logw[0]=np.log(p0/(1-p0))
        pool={m:[] for m in ['batch_drive','last_only','risk_BP','logit_BP']}
        counts=yt.sum(1).astype(int);k=yt.shape[1];zs={};inverse_clock=time.monotonic()
        for beta in (.5,2.,8.,32.):
            uq=np.unique(counts);look={int(i):law.inverse(float((i+beta*p0)/(k+beta)),errors) for i in uq}
            zs[beta]=np.array([look[int(i)] for i in counts])
        inverse_s=time.monotonic()-inverse_clock
        def add(method,weight,par,clock,notes):
            p=expit(xd@weight) if method=='logit_BP' else law.prob(xd@weight)
            dev=float(nll(p,yd).mean());pool[method].append(dict(dev_nll=dev,weights=weight.tolist(),param=par,wall_s=time.monotonic()-clock,**notes))
        for beta,z in zs.items():
            for rate in (1e-5,.001,.03):
                clock=time.monotonic();w=batch(xt,z,w0,len(z)*rate);add('batch_drive',w,[beta,rate],clock,{})
            clock=time.monotonic();w=recursive(xt,z,w0,len(z),last_only=True);add('last_only',w,[beta],clock,{})
        for method,logistic in [('risk_BP',False),('logit_BP',True)]:
            for rate in (1e-5,.001,.03):
                clock=time.monotonic();w,details=mle(xt,yt,logw if logistic else w0,rate,law,logistic);add(method,w,[rate],clock,details)
        selected={k:min(opts,key=lambda x:x['dev_nll']) for k,opts in pool.items()}
        rbest=selected['batch_drive'];beta,rate=rbest['param'];reg=len(xt)*rate;targets=zs[beta]
        tic=time.monotonic();online=recursive(xt,targets,w0,reg);online_s=time.monotonic()-tic
        batch_weights=np.asarray(rbest['weights']);agreement=float(abs(online-batch_weights).max())
        d=len(w0);rng=np.random.default_rng(4801);R=np.eye(d);R[1:,1:]=np.linalg.qr(rng.standard_normal((d-1,d-1)))[0]
        eq=recursive(xt,targets,w0,reg,R,True);stale=recursive(xt,targets,w0,reg,R,False)
        rotated=R.T@batch_weights
        other={'recursive':online,'transported':R@eq,'stale_representation':R@stale}
        selected.update({k1:dict(weights=h.tolist(),param=rbest['param'],dev_nll=float(nll(law.prob(xd@h),yd).mean())) for k1,h in other.items()})
        assert agreement<1e-7 and np.max(abs(eq-rotated))<1e-7
        info[s]=dict(features_s=features_s,inverse_s=inverse_s,selected_recursive_s=online_s,train_mean=p0,
                     open_risk_limits=[law.prob(-25.),law.prob(25.)],clipped_targets=errors,
                     selected=selected,candidates=pool,online_vs_batch_weight_max=agreement,
                     transported_vs_batch_weight_max=float(np.max(abs(eq-rotated))),
                     stale_vs_batch_weight_max=float(np.max(abs(stale-rotated))),train_bins=len(xt),d=d)
        results[s]=(X[REGIONS['cold']],y[REGIONS['cold']])
    out.mkdir(exist_ok=True,parents=True)
    (out/'selection.json').write_text(json.dumps(info,indent=2,allow_nan=False)+'\n')
    answer={}
    for s,(X,y) in results.items():
        met={};probs={};loss={}
        for method,o in info[s]['selected'].items():
            w=np.array(o['weights']);p=expit(X@w) if method=='logit_BP' else law.prob(X@w);ll=nll(p,y)
            probs[method]=p;loss[method]=ll;met[method]={'nll':ll.mean(),'brier':np.square(y-p[:,None]).mean(),'mean_predicted':p.mean(),'actual_rate':y.mean()}
        group=np.arange(len(y))//250;n=np.bincount(group);G=len(n);take=np.random.default_rng(59207).integers(0,G,(4000,G))
        for name in met:
            z=np.bincount(group,weights=loss['recursive']-loss[name]);ci=z[take].sum(1)/n[take].sum(1)
            met[name]['recursive_minus_this_nll']=[(loss['recursive']-loss[name]).mean(),*np.quantile(ci,[.025,.975])]
        np.savez_compressed(out/(s+'-edit.npz'),y=y.astype(np.uint8),**probs)
        answer[s]=met
    (out/'heldout.json').write_text(json.dumps(answer,indent=2,allow_nan=False)+'\n')
    print([(s,v['recursive']['nll'],v['risk_BP']['nll'],v['logit_BP']['nll'],v['last_only']['nll']) for s,v in answer.items()])
if __name__=='__main__':
    p=argparse.ArgumentParser()
    for name in ('data','core','out'):p.add_argument('--'+name,type=Path,required=True)
    a=p.parse_args();record(a.data,a.core,a.out)
