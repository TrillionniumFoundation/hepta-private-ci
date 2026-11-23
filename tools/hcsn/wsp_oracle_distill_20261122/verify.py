"""Numerical cross-check against independent hard-action scoring and forward payoff accumulation."""
from pathlib import Path
import gzip
import sys
import time
import numpy as np
from experiment import (ROOT, SOURCE, FEATURE_GROUPS, ARMS, RIDGE, moments, checked, head,
                        gen_items, exact_radius, pin, read, context, vg, save, digest, canonical)


def independent_scores(model, X):
    net=model["network"]
    # Separate from the strict elementwise forward implementation in the pinned reader.
    z=X@np.asarray(net["w1"]).T+np.asarray(net["b1"])
    out=np.tanh(z)@np.asarray(net["w2"]).T+np.asarray(net["b2"])
    b=np.tanh(out[:,3]/2)
    return np.column_stack([np.zeros(len(X)),out[:,:3],-b,b])


def forward_payoff(graph, scores):
    allowed=np.asarray(graph['masks'])
    actions=np.where(allowed,scores,-np.inf).argmax(1)
    occ=np.zeros(len(allowed));occ[graph['initial']]=1.
    reward=cost=mass=0.
    for i in graph['order']:
        if not occ[i]:
            continue
        a=actions[i]
        if a in (0,4,5):
            reward+=occ[i]*graph['terminal'][i][a];mass+=occ[i]
        else:
            for p,j,fee in graph['edges'][i][a-1]:
                flow=occ[i]*p
                occ[j]+=flow;cost+=flow*fee
    if abs(mass-1)>2e-10:
        raise ValueError('terminal mass')
    return reward-cost


def audit(run):
    start=time.process_time()
    method=read(run/'METHOD.json')
    assert pin(ROOT/'experiment.py')['sha256']==method['script']
    p=read(SOURCE/'PROTOCOL_FROZEN.json'); ctx=context(p)
    records=read(run/'WORLD_RESULTS.json')
    cases=read(run/'WORLDS.json')['cases']
    metadata=read(run/'CANDIDATES.json')
    seal=digest(canonical({fit:{arm:v['model_sha256'] for arm,v in item['arms'].items()} for fit,item in metadata.items()}).encode())
    assert seal==read(run/'MODEL_SEAL.json')['sha256']==read(run/'ENTROPY.json')['model_seal']
    previous_hashes=set(p['known_schedule_hashes'])
    for phase in ('selection','confirmation'):
        s=read(SOURCE/'evidence/run'/f'{phase}_attempt001/output/WORLDS_FROZEN.json')
        previous_hashes.update(w['schedule_sha256'] for groups in s['groups'].values() for dom in groups.values() for w in dom['worlds'])
    assert len(previous_hashes)==3956
    rebuilt=[]
    entropy=bytes.fromhex(read(run/'ENTROPY.json')['entropy'])
    from public_sampling import public_world
    for fit in p['fit_ids']:
        for dom in ('iid','ood'):
            s=digest(entropy+canonical(['score-distill-v1',seal,fit,dom]).encode())
            rng=np.random.default_rng(int(s,16))
            for idx in range(16):
                pub=public_world(rng,p['public_domains'][dom],p['public_domains']['prior_distances'],f'distill_{fit}_{dom}_{idx}')
                key=digest(canonical({k:pub[k] for k in p['schedule_fields']}).encode())
                assert key not in previous_hashes
                previous_hashes.add(key)
                rebuilt.append((key,pub))
    assert rebuilt==[(c['fingerprint'],c['public']) for c in cases]
    kkt={};max_payoff_error=0.; comparisons=0
    for fit in p['fit_ids']:
        base,items=gen_items(p,ROOT/'inputs',fit)
        anchor=head(base); m=metadata[str(fit)]
        models={a:read(run/'models'/v['model_name']) for a,v in m['arms'].items()}
        for a,v in m['arms'].items():
            assert pin(run/'models'/v['model_name'])['sha256']==v['model_sha256']
            assert exact_radius(anchor,head(models[a]))['within_shared_ball']
            assert all(models[a][k]==base[k] for k in base if k!='network')
            assert all(models[a]['network'][k]==base['network'][k] for k in ('w1','b1'))
        g,l,_,_=moments(items,anchor,fit,False)
        d=head(models['DIRECT'])-anchor
        res=np.einsum('rij,rj->ri',g,d)+(RIDGE+m['mu'])*d-l
        kkt[fit]=float(np.max(np.abs(res)))
        assert kkt[fit]<1e-9 and m['mu']>=0
        assert abs(m['mu']*(np.linalg.norm(d)-m['radius']))<1e-9
        for case,generated in zip(cases,records,strict=True):
            if case['fit']!=fit: continue
            assert case['fingerprint']==generated['schedule']
            graph=vg.build(ctx,case['public'],base,p['state_cap'],lambda:None)
            X,_=vg.semantic_inputs(ctx,case['public'],ctx.NumpyPolicy(base),graph['states'],lambda:None)
            assert X.shape==(generated['state_rows'],85)
            for name in (*ARMS,*FEATURE_GROUPS):
                xx=X.copy()
                if name in FEATURE_GROUPS: xx[:,FEATURE_GROUPS[name]]=0
                model=models.get(name,models['KEEP'])
                v=forward_payoff(graph,independent_scores(model,xx))
                err=abs(v-generated['metrics'][name]['value'])
                max_payoff_error=max(max_payoff_error,err)
                if err>1e-9: raise ArithmeticError((case['fingerprint'],name,err))
                comparisons+=1
    return dict(candidate_seal=seal,worlds=len(cases),hard_policy_values=comparisons,max_payoff_error=max_payoff_error,
                direct_kkt_max_per_fit=kkt,process_cpu=time.process_time()-start,
                caveat='shares pinned graph and semantic feature construction; separately computes FP64 feedforward, actions and forward expected payoff')

if __name__=='__main__':
    run=Path(sys.argv[1]);save(run/'VERIFICATION.json',audit(run))
