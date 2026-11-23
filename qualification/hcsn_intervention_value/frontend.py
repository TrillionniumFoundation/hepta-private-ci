"""Frozen binary instrument frontend with a clean audio channel and four paid-channel ablations."""
import hashlib
import json
from pathlib import Path

import numpy as np
from scipy.special import expit

SLOTS = ('piano','guitar')
RIDGE = .25
METHODS = ('handwritten_visual','trained_visual','imagenet_visual','imagenet_fusion')


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def load_raw(path):
    with np.load(path,allow_pickle=False) as z:
        s = {k:z[k] for k in ('audio','visual','dt','label','group','recording','query_id','start_seconds','split')}
    y=s['label']
    n=len(y)
    if (not n or set(np.unique(y))-set(range(2)) or not np.all(s['dt']==.48)
            or s['audio'].shape[:2]!=(n,6) or s['visual'].shape[:2]!=(n,6)
            or s['dt'].shape!=(n,6) or len(set(s['query_id']))!=n
            or any(not np.isfinite(s[k]).all() for k in ('audio','visual'))):
        raise ValueError('invalid frozen descriptors')
    return s


def subset(s,ids):
    return {k:v[ids] for k,v in s.items()}


def concatenate(a,b):
    return {k:np.concatenate([a[k],b[k]]) for k in a}


def class_source_weights(data):
    y,g=data['label'],data['group']
    w=np.zeros(len(y))
    for label in (0,1):
        groups=np.unique(g[y==label])
        if not len(groups):
            raise ValueError('two class groups required')
        for group in groups:
            take=(y==label)&(g==group)
            w[take]=.5/(len(groups)*take.sum())
    return w


def train_model(data,channel):
    h=data[channel]
    n,t,width=h.shape
    w=np.repeat(class_source_weights(data)/t,t)
    obs=h.reshape(n*t,width)
    center=w@obs
    scale=np.sqrt(w@(obs-center)**2).clip(1.e-6)
    z=((obs-center)/scale).clip(-8,8)
    z=np.column_stack([z,np.ones(len(z))])
    y=np.repeat(2.*data['label']-1.,t)
    penalty=np.diag(np.r_[np.full(width,RIDGE),0.0])
    linear=np.linalg.solve((z.T*w)@z+penalty,z.T@(w*y))
    return dict(center=center.tolist(),scale=scale.tolist(),linear=linear.tolist())


def classify(model,h):
    z=((h-np.asarray(model['center']))/np.asarray(model['scale'])).clip(-8,8)
    beta=np.asarray(model['linear'])
    p=expit(2*(z@beta[:-1]+beta[-1]))
    return np.stack((1-p,p),axis=-1),z


def gallery_model(gallery,channel):
    m=train_model(gallery,channel)
    _,z=classify(m,gallery[channel])
    centers=[]
    for k in (0,1):
        per_group=[z[(gallery['label']==k)&(gallery['group']==g)].mean(axis=0)
                   for g in np.unique(gallery['group'][gallery['label']==k])]
        centers.append(np.mean(per_group,axis=0).tolist())
    return dict(center=m['center'],scale=m['scale'],gallery=centers)


def by_gallery(m,h):
    z=((h-np.asarray(m['center']))/np.asarray(m['scale'])).clip(-8,8)
    # Compare a prefix against references of the same duration.
    d=((z[:,:,None,:]-np.swapaxes(np.asarray(m['gallery']),0,1)[None,:,:,:])**2).mean(-1)
    p=expit(d[:,:,0]-d[:,:,1])
    return np.stack((1-p,p),axis=-1)


def render(s,fit,ref,semantic=None):
    free,z=classify(fit['audio'],s['audio'])
    visual,_=classify(fit['visual'],s['visual'])
    gallery_audio=by_gallery(ref['audio'],s['audio'])
    paid={'handwritten_visual':by_gallery(ref['visual'],s['visual']),'trained_visual':visual}
    if semantic is not None:
        if (semantic.shape!=free.shape or not np.isfinite(semantic).all()
                or np.min(semantic)<0 or np.max(semantic)>1 or not np.allclose(semantic.sum(-1),1)):
            raise ValueError('invalid prepaid semantic features')
        paid['imagenet_visual']=semantic
        paid['imagenet_fusion']=.75*semantic+.25*free
    # Deterministic orthonormal projection of 8 acoustic descriptors. Class posteriors, trend,
    # gallery agreement and the clock are observable without buying the camera stream.
    mat=np.random.default_rng(420111).normal(size=(z.shape[-1],8))
    proj=np.linalg.qr(mat,mode='reduced')[0]
    prob=free[:,:,1]
    diff=np.diff(prob,axis=1,prepend=prob[:,:1])
    clock=s['dt'].cumsum(axis=1)-s['dt'][:,:1]
    x=np.concatenate([z@proj,np.stack([prob,abs(2*prob-1),diff,gallery_audio[:,:,1],clock],axis=-1)],axis=-1)
    common=dict(x=x,scores=free,dt=s['dt'],target=s['label'],source=s['recording'].astype(str),
                group=s['group'].astype(str),query_id=s['query_id'].astype(str),gallery_audio=gallery_audio,
                split=s['split'].astype(str))
    return common,paid


def semantic_array(path,raw):
    with np.load(path,allow_pickle=False) as z:
        names=z['query_id'].astype(str).tolist()
        if len(set(names))!=len(names) or set(names)!=set(raw['query_id'].astype(str)):
            raise ValueError('unpaired semantic extraction')
        order={n:i for i,n in enumerate(names)}
        return z['probability'][[order[str(n)] for n in raw['query_id']]]


def models(s):
    return {c:train_model(s,c) for c in ('audio','visual')}


def build(gallery,train,others,semantic):
    ref={c:gallery_model(gallery,c) for c in ('audio','visual')}
    combined=concatenate(gallery,train)
    final=models(combined)
    output={}
    parts=[]
    groups=train['group']
    for g in np.unique(groups):
        idx=np.where(groups==g)[0]
        training=concatenate(gallery,subset(train,groups!=g))
        if g in training['group'] or set(train['recording'][idx])&set(training['recording']):
            raise ValueError('recording leaks into training fold')
        sm=semantic['train'][idx] if 'train' in semantic else None
        c,p=render(subset(train,idx),models(training),ref,sm)
        parts.append((idx,c,p))
    order=np.argsort(np.concatenate([x[0] for x in parts]))
    output['train']=tuple({k:np.concatenate([part[j][k] for part in parts])[order]
                          for k in parts[0][j]} for j in (1,2))
    for name,raw in others.items():
        output[name]=render(raw,final,ref,semantic.get(name))
    return output,dict(final=final,reference=ref,slots=SLOTS,ridge=RIDGE)


def candidate(rendered,which):
    common,paid=rendered
    return {**common,'read_scores':paid[which]}


def dump(path,value):
    with Path(path).open('x') as stream:
        json.dump(value,stream,sort_keys=True,allow_nan=False,indent=2)
        stream.write('\n')
