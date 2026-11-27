"""Shared SHD data, nonlinear free-boundary features, ridge and validation."""
import hashlib
import json
import resource
import time
from pathlib import Path

import numpy as np
from scipy.linalg import solve
from scipy.special import softmax

SEEDS = (137, 251, 389)
PEN = (.0003, .003, .03)
TEMPS = (.5, 1, 2, 4, 8, 16)
WIDTH = 16
START = (time.perf_counter(), time.process_time())


def sha(path):
    with Path(path).open('rb') as f:
        return hashlib.file_digest(f, 'sha256').hexdigest()


def record(path, obj):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(obj, indent=2, allow_nan=False)+'\n')


def usage():
    return dict(wall_s=time.perf_counter()-START[0], cpu_s=time.process_time()-START[1],
                peak_rss_kib=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)


def trdata(root, mode):
    x = np.load(root/'x_train.npy')
    y = np.load(root/'labels_train.npy')
    people = np.load(root/'people_train.npy')
    dev = np.load(root/'devmask.npy')
    retain = y<10 if mode == 'english' else np.ones_like(dev)
    permitted = retain & ~dev
    center = x[permitted].mean((0,1),dtype=np.float64).astype('f4')
    scale = x[permitted].std((0,1),dtype=np.float64).clip(1e-4).astype('f4')
    x = (x-center)/scale
    return (x[permitted],y[permitted],people[permitted]), (x[retain & dev],y[retain & dev],people[retain & dev]), center, scale


def indices(scores, y, people, scale=1.):
    probs=softmax(scores.astype('f8')*scale,axis=1)
    pred=probs.argmax(1)
    correct=(pred==y)
    row_brier=np.sum(probs*probs,axis=1)-2*probs[np.arange(len(y)),y]+1
    return dict(acc=float(correct.mean()), speaker_acc=float(np.mean([correct[people==k].mean() for k in np.unique(people)])),
                brier=float(row_brier.mean()))


def calibrate(scores,y,people):
    found=[(indices(scores,y,people,t),t) for t in TEMPS]
    return min(found,key=lambda a:(a[0]["brier"],a[1]))


def better(current, candidate):
    a=candidate['dev']
    return current is None or (a['speaker_acc'],-a['brier']) > (current['dev']['speaker_acc'],-current['dev']['brier'])


def numpy_gate(drive,table,kind):
    if kind=='smooth':
        return np.tanh(drive[...,None]*table['smooth_k'])*table['smooth_amp']
    lut=table['lut']
    v=np.clip((drive+12.)*((len(lut)-1)/24.),0.,len(lut)-1.)
    lower=v.astype(np.int32)
    upper=np.minimum(lower+1,len(lut)-1)
    return lut[lower]+(v-lower)[...,None].astype('f4')*(lut[upper]-lut[lower])


def gate_features(x,w,b,table,kind='physical'):
    y=numpy_gate(x@w+b,table,kind)
    return y.reshape(x.shape[0],x.shape[1],2*w.shape[-1])


def pool(h):
    return h.reshape(len(h),6,2,-1).mean(2).reshape(len(h),-1)


def features(x, state, table):
    if state['kind'].item()=='ridge':
        return x.reshape(len(x),-1)
    h=gate_features(x,state['w1'],state['b1'],table,state['kind'].item())
    return pool(gate_features(h,state['w2'],state['b2'],table,state['kind'].item()))


def sufficient(f,y,ncls):
    z=f.astype('f8')
    mean=z.mean(0)
    z-=mean
    target=np.eye(ncls)[y]
    target_mean=target.mean(0)
    target-=target_mean
    var=z.T@z/len(f)
    return var,z.T@target/len(f),mean,target_mean


def ridge(stats,pen):
    var,cov,mean,tmean=stats
    a=var.copy()
    a.flat[::len(a)+1]+=pen
    w=solve(a,cov,assume_a='pos',check_finite=False)
    b=tmean-mean@w
    return w.astype('f4'),b.astype('f4')


def score_batches(x,state,table):
    return np.concatenate([features(x[i:i+192],state,table)@state['head']+state['head_bias'] for i in range(0,len(x),192)])
