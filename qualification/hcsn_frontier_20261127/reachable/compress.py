"""Measure compression error on reachable states under previously unseen control schedules."""
import argparse
import json
import sys
import time
from pathlib import Path

import numpy as np
from scipy.special import ndtr

from witness import Population

HORIZONS=(1,2,4,8)


def histories(rng,count,length,ood):
    if not ood:
        out=rng.normal(0,.07,(count,length))
        for t in range(1,length):out[:,t]+=.48*out[:,t-1]
    else:
        sign=rng.choice([-1.,1.],count)
        out=np.zeros((count,length))
        for t in range(length):
            sign=np.where(rng.random(count)<.16,-sign,sign)
            out[:,t]=.15*sign+rng.normal(0,.025,count)
        jump=rng.random(out.shape)<.10
        out[jump]=rng.uniform(-.17,.17,jump.sum())
    return out.clip(-.17,.17)


def trans(pop,ds):
    x=pop.grid[None,:,None]+ds[:,None,None]
    pos=x>0;x=x.clip(min=0)
    s=pop.sigma*np.sqrt(pop.dt); drift=pop.mu*pop.dt
    w=np.exp(-pop.k*x)
    c=ndtr((pop.cuts-x-drift)/s)-w*ndtr((pop.cuts+x-drift)/s)
    live=np.maximum(0,np.diff(np.concatenate([c,1-w],-1),axis=-1))*pos
    mat=np.zeros((len(ds),pop.n+1,pop.n+1)); mat[:,:-1,:-1]=live
    mat[:,:-1,-1]=1-live.sum(-1);mat[:,-1,:-1]=pop.reset
    np.testing.assert_allclose(mat.sum(-1),1,atol=2e-15)
    return mat


def endpoints(pop,drive):
    states=[]
    for chunk in range(0,len(drive),100):
        u=drive[chunk:chunk+100]
        last=np.zeros(len(u));v=np.repeat(np.r_[pop.reset,0][None,:],len(u),0)
        for level in np.column_stack([u,last]).T:
            v=np.einsum('ki,kij->kj',v,trans(pop,last-level))
            last=level
        states.append(v)
    return np.vstack(states)


def queries(pop,levels):
    f=pop.port[:,0];n=len(levels)
    cumulative=np.broadcast_to(np.eye(pop.n+1),(n,pop.n+1,pop.n+1))
    old=np.zeros(n);out=[]
    for i,new in enumerate(levels.T,1):
        cumulative=cumulative@trans(pop,old-new);old=new
        if i in HORIZONS:out.append(cumulative@f)
    return np.stack(out,1).reshape(-1,pop.n+1).T


def err(a):
    return {'rmse':float(np.sqrt(np.mean(a**2))),'p95':float(np.quantile(np.abs(a),.95)),'max':float(np.max(np.abs(a)))}


def run(core):
    sys.path.insert(0,str(core.resolve()))
    import torch
    from population import BoundaryPopulation
    torch.set_num_threads(1)
    t0=time.perf_counter()
    pop=Population(BoundaryPopulation(1,1,atoms=12))
    training=endpoints(pop,histories(np.random.default_rng(84721),1600,20,False))
    states={k:endpoints(pop,histories(np.random.default_rng(seed),800,20,shift)) for k,seed,shift in [('nominal',40821,False),('persistent',95602,True)]}
    bank=queries(pop,histories(np.random.default_rng(92747),128,8,False))
    banks={k:queries(pop,histories(np.random.default_rng(seed),96,8,shift)) for k,seed,shift in [('nominal',64101,False),('persistent',71033,True)]}
    ref=training.mean(0);centered=training-ref;d=training.shape[1];projection=np.eye(d)-np.ones((d,d))/d
    basis,sig,_=np.linalg.svd(projection@bank,full_matrices=False)
    _,sp,vt=np.linalg.svd(centered,full_matrices=False)
    ports={'priced':pop.port[:,:3],'augmented':pop.port,'full':np.eye(d)}
    for k in (3,7,11):
        ports[f'future{k}']=basis[:,:k]
        ports[f'pca{k}']=vt[:k].T
    rows={}
    for name,columns in ports.items():
        samples=centered@columns; decoder=np.linalg.lstsq(samples,centered,rcond=1e-12)[0]
        sv=np.linalg.svd(samples,compute_uv=False);nonzero=sv[sv>sv[0]*1e-12]
        cases={}
        for drives,state in states.items():
            for policy,future in banks.items():
                encoded=(state-ref)@columns
                decoded_future=decoder@future
                predictions=encoded@decoded_future+ref@future
                error=predictions-state@future
                cases[drives+'-'+policy]={'all':err(error),'by_horizon':{h:err(error[:,j::4]) for j,h in enumerate(HORIZONS)}}
                if name=='full':assert np.max(abs(error))<2e-12
        # Isolated array costs: same sizes, warmed, medians of repeated single-thread batches.
        st=states['nominal']-ref;fut=banks['nominal'];msg=st@columns;read=decoder@fut
        def cost(fn):
            for _ in range(5):fn()
            timings=[]
            for _ in range(9):
                start=time.perf_counter_ns()
                for _ in range(16):fn()
                timings.append((time.perf_counter_ns()-start)/16/len(st))
            return float(np.median(timings))
        rows[name]={'width':columns.shape[1],'numerical_rank':len(nonzero),'condition_nonzero':float(nonzero[0]/nonzero[-1]),'batch_encode_ns_per_history':cost(lambda:st@columns),'decode_384_queries_ns_per_history':cost(lambda:msg@read),'cases':cases}
    # One schedule and one endpoint at a time may be encoded directly by its killed-kernel adjoint.
    schedule=histories(np.random.default_rng(33678),1,8,True)
    q=queries(pop,schedule)[:,-1]
    st=states['persistent']; mass=st.copy(); last=0.
    for new in schedule[0]:
        mass=mass@pop.matrix(last-new)[0];last=new
    exact=float(np.max(np.abs(st@q-mass[:,-1])))
    assert exact<2e-12
    return {'atoms':12,'training_histories':1600,'test_histories_per_domain':800,'training_schedules':128,'test_schedules_per_policy':96,'horizons':HORIZONS,'sv_state':sp.tolist(),'sv_dictionary':sig.tolist(),'one_query_exact_gap':exact,'runtime_s':time.perf_counter()-t0,'rows':rows}


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--core',type=Path,required=True);p.add_argument('--out',type=Path,required=True)
    args=p.parse_args();report=run(args.core)
    args.out.write_text(json.dumps(report,indent=1)+'\n')
    for n,row in report['rows'].items():print(n,row['cases']['persistent-persistent']['all'])
