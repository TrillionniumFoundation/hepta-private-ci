import hashlib
import io
import sys
import time
import zipfile
from pathlib import Path

import numpy as np
from sklearn.datasets import load_svmlight_file

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'hcsn_independent_audiomnist_20261127'))
from receiver import Cell

WIDTH=8
SEEDS=(2021,4411,6709)
RUNGS=(1,3,8,24)
ARMS=('forward','bp','hybrid_bp','frozen','raw','fourier')
EXPECTED='91e8f466f202e7a093d657673ce47311c3e90416f7df3057966058961c351fe4'


def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def read_batches(path,numbers):
    if sha(path)!=EXPECTED:raise ValueError('unexpected UCI archive identity')
    xs=[];ys=[];bs=[];ids=[]
    with zipfile.ZipFile(path) as z:
        for b in numbers:
            x,y=load_svmlight_file(io.BytesIO(z.read(f'Dataset/batch{b}.dat')),n_features=128,zero_based=False)
            x=x.toarray();xs.append(x);ys.append(y.astype(int)-1);bs.extend([b]*len(y))
            ids.extend(hashlib.sha256(row.tobytes()).hexdigest() for row in x)
    return np.concatenate(xs),np.concatenate(ys),np.array(bs),np.array(ids)


def prep(x,p):
    return np.clip((np.sign(x)*np.log1p(np.abs(x))-p['mean'])/p['sd'],-6,6).reshape(-1,4,32)


def parent(x,seed,law):
    rng=np.random.default_rng(seed)
    log=np.sign(x)*np.log1p(abs(x))
    p={'mean':log.mean(0),'sd':np.maximum(log.std(0),1.e-6),
       'w1':rng.normal(0,1/np.sqrt(32),(32,WIDTH)),
       'w2':rng.normal(0,1/np.sqrt(WIDTH),(WIDTH,WIDTH)),
       'w3':rng.normal(0,.025,(4*WIDTH*4+1,6))}
    ids=rng.choice(len(x),min(512,len(x)),False)
    t=prep(x[ids],p);h1=law.run(t@p['w1'])[0][...,0]
    p['m1']=h1.mean((0,1));p['s1']=np.maximum(h1.std((0,1)),1e-4)
    t=(h1-p['m1'])/p['s1']
    h=law.run(t@p['w2'])[0].reshape(len(t),-1)
    p['mh']=h.mean(0);p['sh']=np.maximum(h.std(0),1e-4)
    return p


def clone(p):return {k:v.copy() for k,v in p.items()}


def hidden(t,p,law,grad=False):
    n=len(t);h1,a=law.run(t@p['w1'],grad)
    source=(h1[...,0]-p['m1'])/p['s1']
    h2,b=law.run(source@p['w2'],grad)
    h=np.column_stack(((h2.reshape(n,-1)-p['mh'])/p['sh'],np.ones(n)))
    return h,source,a,b


def predict(t,p,law):
    return hidden(t,p,law)[0]@p['w3']


def gradient(t,target,p,law):
    h,k,a,b=hidden(t,p,law,True)
    dz=2*(h@p['w3']-target)/target.size
    g3=h.T@dz
    dh=(dz@p['w3'][:-1].T/p['sh']).reshape(len(t),4,WIDTH,4)
    du2=law.reverse(dh,b)
    g2=k.reshape(-1,WIDTH).T@du2.reshape(-1,WIDTH)
    du1=du2@p['w2'].T/p['s1']
    dh1=np.zeros_like(dh);dh1[...,0]=du1
    ds=law.reverse(dh1,a)
    g1=t.reshape(-1,32).T@ds.reshape(-1,WIDTH)
    return [g1,g2,g3]


def ridge(h,target,lam):
    v=h.T@h/len(h);reg=np.eye(len(v));reg[-1,-1]=0
    return np.linalg.solve(v+(lam*np.trace(v)/max(len(v)-1,1)+1e-8)*reg+1e-11*np.eye(len(v)),h.T@target/len(h))


def macro(z,y,b):
    pred=z.argmax(1)
    return float(np.mean([np.mean([np.mean(pred[(b==bi)&(y==ci)]==ci) for ci in np.unique(y[b==bi])]) for bi in np.unique(b)]))


def raw_features(t,arm,model):
    x=t.reshape(len(t),-1)
    if arm=='fourier':x=np.sqrt(2.)*np.cos(x@model['rff_w']/float(model['width_scale'])+model['rff_b'])
    return np.column_stack((x,np.ones(len(x))))

FP_ARMS=('fp_hcsn','fp_relu8','fp_relu32','fp_flat32','fp_shuffle')


def fp_activation(x,w,physical,law):
    z=x@w
    return law.run(z)[0] if physical else np.maximum(z,0)


def fp_readout_features(t,p,arm,law):
    physical=arm in ('fp_hcsn','fp_shuffle')
    a=t.reshape(len(t),1,-1) if arm=='fp_flat32' else t
    h=fp_activation(a,p['w1'],physical,law)
    if physical:h=h[...,0]
    a=(h-p['m1'])/p['s1']
    h=fp_activation(a,p['w2'],physical,law).reshape(len(t),-1)
    return np.column_stack(((h-p['mh'])/p['sh'],np.ones(len(t))))
