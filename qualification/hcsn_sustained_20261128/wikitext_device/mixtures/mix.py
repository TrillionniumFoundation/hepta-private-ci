"""Validation-frozen convex mixtures and retrospective diagnostics on exactly normalized word distributions."""
from argparse import ArgumentParser
from hashlib import sha256
import json
import math
from pathlib import Path
import time
import numpy as np

SEEDS=(137,311,557)
BUCKETS=('previous_EOS','previous_count_0_to_9','previous_count_10_to_99','previous_count_100_or_more')


def digest(path):return sha256(path.read_bytes()).hexdigest()
def read(path):return json.loads(path.read_text())
def write(path,obj):path.write_text(json.dumps(obj,indent=2,allow_nan=False)+'\n')


def stored(root,split):
    vals={};ident={}
    for f in sorted(root.glob('*.npz')):
        name=f.stem
        with np.load(f,allow_pickle=False) as a:
            vals[name]=np.asarray(a[split],dtype=np.float64)
            if name=='bigram':
                bucket=a[split+'_bucket'].astype(int)
        h=digest(f)
        record=root/(name+'.json')
        if record.exists():
            r=read(record);assert r['array_sha256']==h
            ident[name]={'array_sha256':h,'weight_sha256':r['weight_sha256']}
        else:
            assert name=='bigram';ident[name]={'array_sha256':h}
    assert all(len(a)==len(bucket) and np.isfinite(a).all() for a in vals.values())
    return vals,bucket,ident


def plan(deep):
    specs=[]
    def add(fam,s,a,b):
        name=f'{fam}:{s}'
        specs.append((name,a,b))
        return name
    for j,s in enumerate((887,) if deep else SEEDS):
        h=f'hx-{s}-128';t=f'sdpa-{s}-128';m=f'smooth-{s}-128'
        pair=add('HX_SDPA',s,h,t)
        add('SDPA_smooth',s,t,m)
        add('HX_count',s,h,'bigram');add('SDPA_count',s,t,'bigram');add('smooth_count',s,m,'bigram')
        add('HX_SDPA_count',s,pair,'bigram')
        if not deep:
            nextseed=SEEDS[(j+1)%len(SEEDS)]
            add('two_SDPA',s,t,f'sdpa-{nextseed}-128');add('two_HX',s,h,f'hx-{nextseed}-128')
        else:
            add('HX_states',s,h,'hx-887-2048');add('SDPA_states',s,t,'sdpa-887-2048')
            add('longHX_SDPA',s,'hx-887-2048',t)
    return specs


def scaled(a,b):
    base=np.maximum(a,b)
    return base,np.exp(a-base),np.exp(b-base)


def fit_scalar(a,b):
    _,x,y=scaled(a,b);d=y-x
    def grad(lam):return -float(np.mean(d/(x+lam*d))) if lam<.5 else -float(np.mean(d/(y+(1-lam)*(-d))))
    ends=[grad(0.),grad(1.)]
    if ends[0]>=0:return 0.,ends
    if ends[1]<=0:return 1.,ends
    lo,hi=0.,1.
    for _ in range(55):
        m=(lo+hi)*.5
        if grad(m)>0:hi=m
        else:lo=m
    return (lo+hi)*.5,ends


def mixture(a,b,lam):
    base,x,y=scaled(a,b)
    return base+np.log((1-lam)*x+lam*y)


def coefficients(root,dest,deep):
    vals,bk,ids=stored(root,'valid')
    config=dict(deep=bool(deep),parents=ids,validation_examples=len(bk),buckets=BUCKETS,
                counts=np.bincount(bk,minlength=4).tolist(),rows={})
    start=time.perf_counter()
    for name,left,right in plan(deep):
        a=vals[left];b=vals[right]
        alpha,ends=fit_scalar(a,b);g=[]
        for i in range(4):
            mask=bk==i
            g.append(fit_scalar(a[mask],b[mask])[0] if mask.sum()>=256 else alpha)
        fit=mixture(a,b,alpha)
        half=mixture(a,b,.5);grouped=mixture(a,b,np.asarray(g)[bk])
        assert -fit.mean()<=min(-a.mean(),-b.mean(),-half.mean())+1e-12
        config['rows'][name]=dict(left=left,right=right,global_right_weight=alpha,
                                  grouped_right_weights=g,endpoint_derivatives=ends,
                                  validation_nll=float(-fit.mean()),validation_grouped_nll=float(-grouped.mean()))
        vals[name]=fit
    config['fit_seconds']=time.perf_counter()-start
    write(dest/'coefficients.json',config)
    print('frozen_coefficients',digest(dest/'coefficients.json'),config['fit_seconds'],flush=True)


def macro(z):
    return np.pad(z,(0,(-len(z))%128)).reshape(-1,128).sum(1)


def test(root,dest):
    frozen=dest/'coefficients.json';cfg=read(frozen)
    vals,bk,ids=stored(root,'test')
    assert cfg['parents']==ids
    N=len(bk);start=time.perf_counter()
    out=dict(coefficient_sha256=digest(frozen),test_targets=N,parents={},rows={},contrasts={})
    counts=macro(np.ones(N));raw={'counts':counts}
    for name,a in vals.items():
        out['parents'][name]={'nll':float(-a.mean()),'ppl':float(np.exp(-a.mean()))}
        raw['parent_'+name]=macro(-a)
    for name,fit in cfg['rows'].items():
        a,b=vals[fit['left']],vals[fit['right']]
        alpha=fit['global_right_weight'];g=np.asarray(fit['grouped_right_weights'])
        z=mixture(a,b,alpha);zs=mixture(a,b,g[bk]);half=mixture(a,b,.5)
        oracle=np.maximum(a,b)
        h=fit['validation_nll']
        info=dict(global_right_weight=alpha,grouped_right_weights=g.tolist(),
                  validation_nll=h,nll=float(-z.mean()),ppl=float(np.exp(-z.mean())),
                  grouped_nll=float(-zs.mean()),grouped_ppl=float(np.exp(-zs.mean())),
                  half_nll=float(-half.mean()),infeasible_oracle_target_nll=float(-oracle.mean()),
                  delta_to_better_test_parent=float(-z.mean()-min(-a.mean(),-b.mean())))
        out['rows'][name]=info;raw['global_'+name]=macro(-z);raw['grouped_'+name]=macro(-zs)
        vals[name]=z
    aggregate=[('HX_SDPA','SDPA_smooth'),('HX_count','SDPA_count'),('HX_SDPA_count','SDPA_count'),
               ('HX_SDPA','bigram'),('HX_count','bigram'),('SDPA_count','bigram')]
    if cfg['deep']:
        aggregate.extend([('longHX_SDPA','HX_SDPA'),('HX_states','HX_128'),('SDPA_states','SDPA_128')])
    else:aggregate.extend([('HX_SDPA','two_SDPA'),('HX_SDPA','two_HX')])
    sample=np.random.default_rng(88412);pad=(-len(counts))%32
    den=np.pad(counts,(0,pad)).reshape(-1,32).sum(1)
    ix=sample.integers(0,len(den),(5000,len(den)))
    def pick(key,s):
        if key=='bigram':return raw['parent_bigram']
        if key in ('HX_128','SDPA_128'):return raw['parent_'+key.split('_')[0].lower()+f'-{s}-128']
        return raw['global_'+key+':'+str(s)]
    for l,r in aggregate:
        ds=np.mean([pick(l,s)-pick(r,s) for s in ([887] if cfg['deep'] else SEEDS)],axis=0)
        numer=np.pad(ds,(0,pad)).reshape(-1,32).sum(1)
        sample=numer[ix].sum(1)/den[ix].sum(1)
        out['contrasts'][l+' minus '+r]=[float(ds.sum()/N),*np.quantile(sample,[.025,.975]).tolist()]
    for name in cfg['rows']:
        ds=raw['grouped_'+name]-raw['global_'+name]
        numer=np.pad(ds,(0,pad)).reshape(-1,32).sum(1)
        sample=numer[ix].sum(1)/den[ix].sum(1)
        out['rows'][name]['grouped_minus_global_interval']=[float(ds.sum()/N),*np.quantile(sample,[.025,.975]).tolist()]
    path=dest/'test_blocks.npz';np.savez_compressed(path,**raw)
    out['test_block_sha256']=digest(path);out['test_seconds']=time.perf_counter()-start
    write(dest/'test.json',out)
    print('audited_test',len(out['rows']),out['contrasts'],flush=True)


if __name__=='__main__':
    p=ArgumentParser();p.add_argument('stage',choices=('fit','test'));p.add_argument('source',type=Path)
    p.add_argument('out',type=Path);p.add_argument('--deep',action='store_true')
    a=p.parse_args();a.out.mkdir(exist_ok=True,parents=True)
    if a.stage=='fit':coefficients(a.source,a.out,a.deep)
    else:test(a.source,a.out)
