"""Unmodified input, assignment, regularized readout and loss routines from retina.py.
Source SHA256 ab838d7038e476acf1ee376fff9f8417a7647b51d46b87fc682037761e1af547
"""
import hashlib
from pathlib import Path
import numpy as np
from scipy.optimize import minimize
from scipy.signal import lfilter
from scipy.special import expit


def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def make_trial(folder,idx):
    files=[folder/f'Spks{k}_rep{idx}.txt' for k in ('Pre','Post')]
    pre,post=[np.loadtxt(f) for f in files]
    assert np.allclose(pre,np.rint(pre)) and np.allclose(post,np.rint(post))
    pre=pre.astype(int);post=post.astype(int)
    assert (np.diff(pre)>=0).all() and (np.diff(post)>=0).all()
    pos=np.searchsorted(pre,post,side='right')-1
    ok=(pos>=0)&(post-pre[pos]<=2);outcomes=np.isin(np.arange(len(pre)),pos[ok])
    eligible=(pre>=5000)&(pre<=9997)
    stream=np.bincount(pre[(pre>=0)&(pre<10000)],minlength=10000)
    bank=[]
    for tau in (2,4,8,16,40,100):
        a=np.exp(-1/tau);bank.append(lfilter([1.],[1,-a],stream))
    return dict(id=idx,features=np.stack(bank,-1),indices=np.ascontiguousarray(pre[eligible],dtype=np.int32),y=outcomes[eligible],input_sha=[sha(f) for f in files])


def logistic(x,y,t,ridge):
    mean=x[t].mean(0);sd=x[t].std(0).clip(1e-8)
    z=np.column_stack([np.ones(len(x)),(x-mean)/sd]);a=z[t];b=y[t].astype(float)
    def fn(w):
        logits=a@w;r=w.copy();r[0]=0
        return np.mean(np.logaddexp(0,logits)-b*logits)+.5*ridge*(r@r),a.T@(expit(logits)-b)/len(b)+ridge*r
    w=np.zeros(z.shape[1]);w[0]=np.log(b.mean()/(1-b.mean()))
    sol=minimize(fn,w,jac=True,method='L-BFGS-B',options={'maxiter':300,'ftol':1e-12,'gtol':1e-8})
    return expit(z@sol.x).clip(1e-10,1-1e-10),dict(params=sol.x.tolist(),mean=mean.tolist(),sd=sd.tolist(),status=str(sol.message))


def bce(p,y):
    return -(y*np.log(p)+(1-y)*np.log1p(-p))
