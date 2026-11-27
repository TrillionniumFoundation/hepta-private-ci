"""Finite-belief Tree policy -> genuinely optimized State-Gated Cell Head.

TRAIN-only synthetic rational inputs, independently reproduced FUTURE teacher
labels after predictions are sealed. Same-feature cheap linear control retained.
This is NOT pretrained Stem learning, natural reasoning or learned stochastic NDU.
"""
from __future__ import annotations
import hashlib
import json
from dataclasses import dataclass
from fractions import Fraction as Q
from pathlib import Path

import numpy as np
from global_consistency import belief_tree

D,S,R,C=384,64,8,8
CLASS={'no_search':0,'search':1}


def _digest(item):
    return hashlib.sha256(json.dumps(item,sort_keys=True,separators=(',',':'),
                                     ensure_ascii=True,allow_nan=False).encode()).hexdigest()


def cases(split,seed,count):
    """Different denominators and exact integer seeds prevent train/future copies."""
    if split not in ('train','future') or type(count) is not int or not 2<=count<=1024:
        raise ValueError('bounded synthetic split')
    if type(seed) is not int or not 0<=seed<2**32:
        raise ValueError('bounded seed')
    rng=np.random.default_rng(seed)
    d=64 if split=='train' else 97
    cd=128 if split=='train' else 193
    out=[];seen=set()
    for i in range(count):
        while True:
            p=[str(Q(int(z),d)) for z in rng.integers(4,d-3,size=2)]
            cost=[str(Q(int(z),cd)) for z in rng.integers(1,cd//3,size=2)]
            k=_digest([p,cost])
            if k not in seen:
                seen.add(k);break
        out.append({'case_id':f'{split}-{i}', 'group_id':k,
                    'observed_at':i+1 if split=='train' else i+10000,
                    'split':split,'prior':p,'cost':cost})
    return tuple(out)


def _verify(rows,split):
    if not isinstance(rows,(list,tuple)) or not 1<=len(rows)<=1024:
        raise ValueError('bounded rows')
    ids=set();groups=set();inputs=set();times=[]
    for row in rows:
        if type(row) is not dict or set(row)!= {'case_id','group_id','observed_at','split','prior','cost'}:
            raise ValueError('source-only exact row required; no labels allowed')
        if row['split']!=split or type(row['case_id']) is not str or type(row['group_id']) is not str:
            raise ValueError('invalid identity/split')
        if type(row['observed_at']) is not int or row['observed_at']<=0:
            raise ValueError('event time')
        ids.add(row['case_id']);groups.add(row['group_id']);times.append(row['observed_at'])
        if not isinstance(row['prior'],list) or not isinstance(row['cost'],list) or len(row['prior'])!=2 or len(row['cost'])!=2:
            raise ValueError('two-bit problem only')
        if any(type(x) is not str or str(Q(x))!=x for x in row['prior']+row['cost']):
            raise ValueError('canonical rational input required')
        if any(not Q(0)<Q(p)<1 for p in row['prior']) or any(not Q(0)<=Q(c)<=1 for c in row['cost']):
            raise ValueError('bounded model belief/cost')
        true_id=_digest([row['prior'],row['cost']])
        if true_id!=row['group_id']:
            raise ValueError('source group digest inconsistent')
        inputs.add(true_id)
    if len(ids)!=len(rows) or len(groups)!=len(rows) or len(inputs)!=len(rows):
        raise ValueError('reused task case/group')
    if split=='train' and max(times)>=10000 or split=='future' and min(times)<10000:
        raise ValueError('invalid temporal split')
    return tuple(sorted(groups))


def labels(rows):
    """Synthetic exact-policy supervisor. NEVER call this on FUTURE in fitting."""
    return {r['case_id']:int(belief_tree(r['prior'],r['cost'])['action'].startswith('observe_')) for r in rows}


def tensors(rows):
    x=np.zeros((len(rows),D),dtype=np.float64)
    h=np.zeros((len(rows),S),dtype=np.float64)
    for i,r in enumerate(rows):
        p0,p1=[float(Q(k)) for k in r['prior']]
        c0,c1=[float(Q(k)) for k in r['cost']]
        x[i,:9]=(2*p0-1,2*p1-1,4*c0,4*c1,p0*p1,
                 abs(p0-.5),abs(p1-.5),p0+p1,1.)
        h[i,:4]=(c0,c1,p0,p1)
    return x,h


def initialize(seed):
    rng=np.random.default_rng(seed)
    def w(shape): return rng.normal(0,.02,size=shape)
    return dict(down=w((R,D)),gate=w((R,S)),gate_bias=np.zeros(R),
                up=np.zeros((D,R)),output=w((C,D)),output_bias=np.zeros(C))


def _forward(params,x,h):
    a=x@params['down'].T
    asig=1/(1+np.exp(-np.clip(a,-30,30)))
    z=a*asig
    g=1/(1+np.exp(-np.clip(h@params['gate'].T+params['gate_bias'],-30,30)))
    m=z*g
    v=x+m@params['up'].T
    logits=v@params['output'].T+params['output_bias']
    return logits,(a,asig,z,g,m,v)


def _grad(params,x,h,truth):
    logits,cache=_forward(params,x,h)
    logits=logits-logits.max(axis=1,keepdims=True)
    prob=np.exp(logits);prob/=prob.sum(axis=1,keepdims=True)
    loss=-np.log(prob[np.arange(len(truth)),truth]+1e-15).mean()
    dl=prob.copy();dl[np.arange(len(truth)),truth]-=1;dl/=len(truth)
    a,asig,z,g,m,v=cache
    grad={}
    grad['output']=dl.T@v
    grad['output_bias']=dl.sum(axis=0)
    dv=dl@params['output']
    grad['up']=dv.T@m
    dm=dv@params['up']
    dz=dm*g
    dg=dm*z
    da=dz*asig*(1+a*(1-asig))
    gb=dg*g*(1-g)
    grad['down']=da.T@x
    grad['gate']=gb.T@h
    grad['gate_bias']=gb.sum(axis=0)
    return loss,grad


def _params_digest(params):
    h=hashlib.sha256()
    for key in sorted(params):
        a=params[key]
        h.update(key.encode());h.update(str(a.shape).encode());h.update(np.asarray(a,dtype='<f8').tobytes())
    return h.hexdigest()


@dataclass(frozen=True)
class Candidate:
    weights: dict
    initial_digest: str
    trained_digest: str
    train_groups: tuple
    max_train_time: int
    training_cpu_ns: int
    steps: int
    observed_parameters_changed: int
    initial_weights: dict


def fit(train_rows,train_labels,*,seed=19,steps=300,batch=64,lr=.03):
    import time
    groups=_verify(train_rows,'train')
    if type(steps) is not int or not 1<=steps<=2000 or type(batch) is not int or not 1<=batch<=256 or type(lr) not in (float,int) or not 0<lr<=.05:
        raise ValueError('bounded update budget')
    if type(train_labels) is not dict or set(train_labels)!={r['case_id'] for r in train_rows} or any(type(v) is not int or v not in CLASS.values() for v in train_labels.values()):
        raise ValueError('complete train-only label inventory')
    x,h=tensors(train_rows)
    y=np.asarray([train_labels[r['case_id']] for r in train_rows],dtype=np.int64)
    p=initialize(seed)
    orig={k:v.copy() for k,v in p.items()}
    initial=_params_digest(orig)
    rng=np.random.default_rng(seed+3)
    av={k:np.zeros_like(v) for k,v in p.items()}
    sq={k:np.zeros_like(v) for k,v in p.items()}
    start=time.process_time_ns()
    for step in range(1,steps+1):
        idx=rng.choice(len(x),size=min(batch,len(x)),replace=False)
        loss,grads=_grad(p,x[idx],h[idx],y[idx])
        norm=np.sqrt(sum(np.sum(g*g) for g in grads.values()))
        scale=min(1.,1./max(float(norm),1e-12))
        for key in p:
            gg=grads[key]*scale
            av[key]=.9*av[key]+.1*gg
            sq[key]=.999*sq[key]+.001*(gg*gg)
            mh=av[key]/(1-.9**step)
            vh=sq[key]/(1-.999**step)
            p[key]-=lr*mh/(np.sqrt(vh)+1e-8)
        if not np.isfinite(loss) or any(not np.isfinite(a).all() for a in p.values()):
            raise ValueError('optimizer failure')
    cpu=time.process_time_ns()-start
    changed=sum(np.count_nonzero(p[k]!=orig[k]) for k in p)
    if changed<100 or _params_digest(p)==initial:
        raise ValueError('no actual learned Head update')
    return Candidate(p,initial,_params_digest(p),groups,max(r['observed_at'] for r in train_rows),cpu,steps,int(changed),orig)


def predict(candidate,future_rows):
    if type(candidate) is not Candidate or _params_digest(candidate.weights)!=candidate.trained_digest:
        raise ValueError('trained model drift')
    groups=_verify(future_rows,'future')
    if set(groups)&set(candidate.train_groups):
        raise ValueError('train/future source group overlap')
    if min(r['observed_at'] for r in future_rows)<=candidate.max_train_time:
        raise ValueError('future window is not later')
    x,h=tensors(future_rows)
    logits,_=_forward(candidate.weights,x,h)
    predicted=np.argmax(logits,axis=1)
    result={
        'schema':'hepta.ndu-stem.exact-teacher-shadow-seal.v1',
        'trained_digest':candidate.trained_digest,
        'initial_digest':candidate.initial_digest,
        'source_rows_sha256':_digest(future_rows),
        'case_predictions':{r['case_id']:int(label) for r,label in zip(future_rows,predicted)},
        'train_groups_digest':_digest(candidate.train_groups),
        'steps_actual':candidate.steps,
        'cpu_train_ns':candidate.training_cpu_ns,
        'head_parameters':D*R+(S+1)*R+D*R+(D+1)*C,
        'observed_parameters_changed':candidate.observed_parameters_changed,
        'pretrained_encoder_executed':False,
        'teacher_independent_real_outcomes':False,
        'stochastic_ndu_solved':False,
        'production_accepted':False,
        'authority':'DENY_ALL'
    }
    return result


def evaluate_after_seal(seal,future_rows,*,expected_digest):
    if type(seal) is not dict or _digest(seal)!=expected_digest:
        raise ValueError('sealed prediction file changed')
    _verify(future_rows,'future')
    if seal.get('source_rows_sha256')!=_digest(future_rows):
        raise ValueError('future source changed after predictions')
    if set(seal['case_predictions'])!={r['case_id'] for r in future_rows}:
        raise ValueError('missing/repeated prediction')
    if seal.get('authority')!='DENY_ALL' or seal.get('production_accepted') is not False or seal.get('teacher_independent_real_outcomes') is not False:
        raise ValueError('unsupported promotion')
    true=labels(future_rows) # scorer-only recomputation, not supplied to fit/predict
    acc=sum(seal['case_predictions'][k]==v for k,v in true.items())/len(true)
    return {'teacher_agreement':acc,'evaluated_cases':len(true),
            'external_natural_success':False,'production_accepted':False}


def frozen_control_predictions(candidate, rows):
    """No training: same initial Head bytes, same feature bytes as learned arm."""
    _verify(rows,'future')
    x,h=tensors(rows)
    logits,_=_forward(candidate.initial_weights,x,h)
    return {r['case_id']:int(y) for r,y in zip(rows,np.argmax(logits,axis=1))}


def fit_cheap_linear(train_rows,train_labels,*,seed=19,steps=300,batch=64,lr=.03):
    """Strong cheap 9-feature linear/logistic control, trained on same data."""
    import time
    _verify(train_rows,'train')
    if not 1<=steps<=2000 or not 1<=batch<=256 or not 0<lr<=.05:
        raise ValueError('unregistered budget')
    if set(train_labels)!={r['case_id'] for r in train_rows}:
        raise ValueError('train label mismatch')
    x,_=tensors(train_rows)
    x=x[:,:9]
    target=np.asarray([train_labels[r['case_id']] for r in train_rows])
    w=np.zeros(9,dtype=np.float64)
    avg=np.zeros_like(w);var=np.zeros_like(w)
    rng=np.random.default_rng(seed+3)
    start=time.process_time_ns()
    for step in range(1,steps+1):
        ind=rng.choice(len(x),size=min(batch,len(x)),replace=False)
        s=x[ind]@w
        prob=1/(1+np.exp(-np.clip(s,-30,30)))
        grad=x[ind].T@(prob-target[ind])/len(ind)
        avg=.9*avg+.1*grad
        var=.999*var+.001*grad*grad
        w-=lr*(avg/(1-.9**step))/(np.sqrt(var/(1-.999**step))+1e-8)
    cpu=time.process_time_ns()-start
    return w,cpu


def cheap_linear_predictions(weight,rows):
    _verify(rows,'future')
    if type(weight) is not np.ndarray or weight.shape!=(9,) or not np.isfinite(weight).all():
        raise ValueError('complete bounded linear control required')
    x,_=tensors(rows)
    return {r['case_id']:int(y) for r,y in zip(rows,x[:,:9]@weight>=0)}


def evaluate_controls_after_seal(seals,rows,expected_digest):
    """Score only after all three arm predictions have been frozen together."""
    if type(seals) is not dict or set(seals)!= {'learned_gate','frozen_gate','cheap_linear'}:
        raise ValueError('complete three-arm panel required')
    if _digest(seals)!=expected_digest:
        raise ValueError('panel changed after seal')
    _verify(rows,'future')
    identities={r['case_id'] for r in rows}
    for arm,pred in seals.items():
        if type(pred) is not dict or set(pred)!=identities or any(type(x) is not int or x<0 or x>7 for x in pred.values()):
            raise ValueError('missing or bad three-arm prediction: '+arm)
    truth=labels(rows)
    scores={arm:sum(pred[k]==val for k,val in truth.items())/len(truth)
            for arm,pred in seals.items()}
    return {'teacher_agreement_by_arm':scores,'source_independent_natural_outcome':False,
            'n_future_cases':len(rows),'production_accepted':False,'authority':'DENY_ALL'}
