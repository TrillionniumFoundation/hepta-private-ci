"""Can the unmodified initial network representation select a bias edit without seeing the task graph?"""
import argparse
import os
import sys
import time
from pathlib import Path
import numpy as np


def predict(rows, x, name, k, shuffled=False):
    gains = np.array([r['delta'] for r in rows])
    if shuffled:
        gains = gains[np.random.default_rng(55883).permutation(len(rows))]
    if name == 'constant':
        return gains.mean(axis=0)
    feats = np.array([r['obs'][name] for r in rows])
    scale = feats.std(axis=0)
    used = scale > 1e-8
    dist = (((feats[:, used] - x[name][used]) / scale[used]) ** 2).sum(axis=1)
    neighbors = np.argsort(dist, kind='stable')[:k]
    return gains[neighbors].mean(axis=0)


def select(values):
    # KEEP wins nonpositive predictions and all numerical ties at zero.
    best = int(np.argmax(values))
    return best if values[best] > 1e-10 else 0


def metrics(rows, actions):
    d = np.array([r['delta'][idx] for r,idx in zip(rows,actions)])
    return dict(mean=float(d.mean()), lower=float(d.min()), positive=int((d>1e-10).sum()),
                negative=int((d < -1e-10).sum()), attempted=int(np.count_nonzero(actions)))


def main():
    p=argparse.ArgumentParser()
    for arg in ('base','prior','law','unc','out'): p.add_argument(arg,type=Path)
    p.add_argument('--entropy')
    a=p.parse_args();a.out.mkdir(parents=True,exist_ok=False)
    sys.path[:0]=[str(a.base.resolve()/'neuron'),str(a.prior.resolve()),str(Path(__file__).resolve().parent.parent/'ambiguity')]
    from study import forward
    from experiment import vg,read,checked,context,head,pin,digest,canonical,save,exact_radius,model_with_head
    from public_sampling import public_world
    start=time.monotonic();protocol=read(a.base/'neuron/pinned/PROTOCOL_FROZEN.json');ctx=context(protocol)
    fitrows=read(a.prior/'records/veto/WORLDS.json')['cases']+read(a.law/'WORLDS.json')['cases']
    devrows=read(a.unc/'WORLDS.json')['cases']
    used=set(protocol['known_schedule_hashes'])
    for phase in ('selection','confirmation'):
        h=read(a.base/'neuron/pinned/evidence/run'/f'{phase}_attempt001/output/WORLDS_FROZEN.json')
        used.update(w['schedule_sha256'] for dom in h['groups'].values() for group in dom.values() for w in group['worlds'])
    used.update(w['fingerprint'] for w in read(a.base/'neuron/run/WORLDS.json')['cases'])
    for f in (a.base/'fullbp/run/WORLDS.json',a.prior/'records/study/WORLDS.json'):
        used.update(w['schedule'] for w in read(f)['cases'])
    for w in fitrows+devrows: used.add(w['schedule'])
    roots=['constant','public43','full85','hidden48','logits4','shuffle85']
    ks=[3,9];grid=[0.,-.24,-.12,.12,.24]
    seal=save(a.out/'METHOD.json',dict(source=pin(__file__)['sha256'],archive_sets=[len(fitrows),len(devrows)],excluded=len(used),grid=grid,roots=roots,ks=ks,
       document='Fit on 160 previous full-graph returns, select representation/k on 80 validation tasks by mean of min(endpoint gains); select a second comparator with zero observed dev losses. '
                'Decide using initial features only, prior to revealing the test graph. The grid optimum uses a later evaluation graph and is an oracle comparator. Five independent fits each use their own prior examples.'))['sha256']
    fits=protocol['fit_ids']; models={f:read(checked(a.base/'neuron/inputs',protocol['fits'][str(f)]['model'])['path']) for f in fits}
    serialized={}
    for f in fits:
        base=models[f]; anchor=head(base); bound=exact_radius(anchor)['numeric_radius']/np.sqrt(3)
        assert max(abs(x) for x in grid)<bound
        for idx,shift in enumerate(grid):
            if idx==0: serialized[f,idx]=base;continue
            m=anchor.copy();m[:3,-1]+=shift; model,_=model_with_head(base,m,'Q')
            path=a.out/'models'/f'{f}_{idx}.json.gz';save(path,model);saved=read(path)
            assert digest(canonical(model).encode())==digest(canonical(saved).encode())
            serialized[f,idx]=saved
    def observation(w):
        f=w['fit'];pub=w['public'];base=models[f];initial=ctx.initial(pub)
        x,_=vg.semantic_inputs(ctx,pub,ctx.NumpyPolicy(base),[initial],lambda:None)
        h=vg.strict_hidden(base,x); logits=vg.strict_scores(head(base),h)[2][0]
        return dict(public43=x[0,:43],full85=x[0],hidden48=h[0,:48],logits4=logits)
    def observe_returns(w, obs):
        f=w['fit'];pub=w['public'];base=models[f]
        g=vg.build(ctx,pub,base,protocol['state_cap'],lambda:None)
        x,_=vg.semantic_inputs(ctx,pub,ctx.NumpyPolicy(base),g['states'],lambda:None)
        assert np.array_equal(x[g['initial']],obs['full85'])
        h=vg.strict_hidden(base,x);rc=[]
        for idx in range(len(grid)):
            scores=vg.strict_scores(head(serialized[f,idx]),h)[0]
            act=np.where(g['masks'],scores,-np.inf).argmax(axis=1)
            rc.append(forward(g,act))
        diff=np.array(rc)-rc[0]
        delta=np.minimum(diff[:,0]-diff[:,1],diff[:,0]-2.*diff[:,1])
        return dict(fit=f,world=w['schedule'],obs=obs,delta=delta,n=len(h))
    train=[observe_returns(w,observation(w)) for w in fitrows]
    dev=[observe_returns(w,observation(w)) for w in devrows]
    train_by_fit={f:[r for r in train if r['fit']==f] for f in fits}
    def picks(f,obs):
        d={'KEEP':0}
        for name in roots:
            for k in ([0] if name=='constant' else ks):
                vals=predict(train_by_fit[f],obs,'full85' if name=='shuffle85' else name,k,name=='shuffle85')
                d[f'{name}_{k}']=select(vals)
        return d
    val=[picks(r['fit'],r['obs']) for r in dev]
    names=list(val[0])
    scores={n:metrics(dev,[d[n] for d in val]) for n in names}
    admissible=[n for n in names if scores[n]['negative']==0 and 'shuffle' not in n]
    eligible=[n for n in names if 'shuffle' not in n]
    winners={b:max(lst,key=lambda n:scores[n]['mean']) for b,lst in [('MEAN',eligible),('ZERO_DEV_LOSS',admissible)]}
    freeze=save(a.out/'SELECTION.json',dict(dev=scores,winners=winners,train_source=[r['world'] for r in train],val_source=[r['world'] for r in dev],method=seal))['sha256']
    entropy=bytes.fromhex(a.entropy) if a.entropy else os.urandom(32);fresh=[]
    for f in fits:
        for dom in ('iid','ood'):
            rng=np.random.default_rng(int(digest(entropy+canonical([freeze,f,dom]).encode()),16))
            for j in range(8):
                pub=public_world(rng,protocol['public_domains'][dom],protocol['public_domains']['prior_distances'],f'root_{f}_{dom}_{j}')
                key=digest(canonical({k:pub[k] for k in protocol['schedule_fields']}).encode())
                if key in used:raise ValueError('schedule collision')
                used.add(key);fresh.append(dict(fit=f,domain=dom,world=j,schedule=key,public=pub))
    save(a.out/'WORLDS.json',dict(selection=freeze,entropy=entropy.hex(),cases=fresh))
    pred=[picks(w['fit'],observation(w)) for w in fresh]
    save(a.out/'PREDICTIONS.json',dict(selection=freeze,rows=[dict(world=w['schedule'],picks=d) for w,d in zip(fresh,pred)]))
    test=[observe_returns(w,observation(w)) for w in fresh]
    test_scores={n:metrics(test,[d[n] for d in pred]) for n in names}
    test_scores['HINDSIGHT_GRID']=metrics(test,[select(r['delta']) for r in test])
    report=dict(selected=winners,dev=scores,test=test_scores,selected_test={k:test_scores[v] for k,v in winners.items()},
                tested=80,train=160,dev_n=80,states=sum(r['n'] for r in train+dev+test),wall_s=time.monotonic()-start)
    save(a.out/'ROWS.json',[dict(fit=r['fit'],world=r['world'],deltas=r['delta'].tolist()) for r in test]);save(a.out/'SUMMARY.json',report)
if __name__=='__main__':main()
