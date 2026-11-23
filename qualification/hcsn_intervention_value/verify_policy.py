"""Independent numerical replay for source-held-out stopping and 66 sealed policies.

Reuses published physical feature kernels and the independent episode accounting law.
It does not run the campaign solver, selection code, backward updates or teacher.
"""
import argparse
from functools import lru_cache
import hashlib
import json
import math
from pathlib import Path
import numpy as np
import torch
from .independent import outcome
from .policy import representation,features
from .run import check_seal,check_test_receipt

SEEDS=(181391,284729,395201)
ARMS=[('plain','keep')]+[(m,o) for m in ('context','fixed','learned','qvi','external') for o in ('keep','bp')]


def read(p): return json.loads(p.read_text())


def same(a,b): np.testing.assert_allclose(a,b,rtol=2e-8,atol=2e-9)


def require(ok,msg):
    if not ok: raise ValueError(msg)


def digest(p): return hashlib.sha256(p.read_bytes()).hexdigest()


def data(path):
    with np.load(path,allow_pickle=False) as f: return {k:f[k] for k in f.files}


def context(s):
    # Assemble each prefix separately; no access to observations after its decision.
    rows=[]
    for t in range(6):
        f=s['scores'][:,:t+1]; x=s['x'][:,:t+1]; g=f[:,:,1]-f[:,:,0]
        time=s['dt'][:,1:t+1].sum(1)
        rows.append(np.column_stack((x[:,-1],x.mean(1),f[:,-1],g[:,-1],np.abs(g[:,-1]),
            g[:,-1]-g[:,max(0,t-1)],np.abs(g).mean(1),time,np.repeat(np.eye(6)[[t]],len(x),axis=0))))
    return np.stack(rows,1)


def discount(u,dt): return np.exp(-.2*dt)*u+2*np.expm1(-.2*dt)


def nuisance_replay(s,z,fold,paid):
    masks=1<<fold; full=(1<<(max(fold)+1))-1; n,h,d=z.shape
    realized=np.stack(((s['scores'].argmax(-1)==s['target'][:,None]).astype(float),
           (s['read_scores'].argmax(-1)==s['target'][:,None]).astype(float)-.30),axis=-1)
    if not paid: realized[:,:,1]=0.

    def pred_dataset(weights,x):
        mu,sd,coef,b,off=weights
        return np.clip((x-mu)/sd@coef+b+off,[0.,-.30,-2.30],[1.,.70,1.])

    @lru_cache(None)
    def params(bits,t):
        if bits==0:
            return np.zeros(d),np.ones(d),np.zeros((d,3)),np.array([.5,.2,.5]),np.zeros(3)
        ids=np.flatnonzero(bits&masks); groups=s['group'][ids]
        y=labels(bits,t)[ids]; v=z[ids,t]
        w=np.array([1/np.sum(groups==g) for g in groups]); w/=w.sum()
        mu=w@v; sd=np.sqrt(w@(v-mu)**2).clip(min=1e-6); b=w@y
        a=np.sqrt(w[:,None])*(v-mu)/sd; target=(y-b)*np.sqrt(w[:,None])
        # Independent augmented least squares, compared with the original primal or dual normal equations.
        coef=np.linalg.lstsq(np.vstack((a,np.sqrt(.08)*np.eye(d))),np.vstack((target,np.zeros((d,3)))),rcond=None)[0]
        off=np.zeros(3)
        if bits.bit_count()>1:
            e=np.empty_like(y)
            for bit in np.unique(masks[ids]):
                r=(masks[ids]==bit); e[r]=y[r]-pred_dataset(params(bits^int(bit),t),v[r])
            sources=set(groups); off=sum((e[groups==g].mean(0) for g in sorted(sources)),np.zeros(3))/(4+len(sources))
        return mu,sd,coef,b,off

    @lru_cache(None)
    def returns(bits,t):
        q=pred_dataset(params(bits,t),z[:,t]); q=q.copy()
        if not paid: q[:,1]=-np.inf
        if t==5: q[:,2]=-np.inf
        act=q.argmax(-1); result=realized[np.arange(n),t,np.minimum(1,act)]
        if t<5: result=np.where(act==2,discount(returns(bits,t+1),s['dt'][:,t+1]),result)
        return result

    @lru_cache(None)
    def labels(bits,t):
        y=np.zeros((n,3)); y[:,:2]=realized[:,t]
        if t==5: y[:,2]=y[:,0]
        else:
            for bit in np.unique(masks):
                if not int(bit)&bits: continue
                ix=masks==bit
                y[ix,2]=discount(returns(bits^int(bit),t+1)[ix],s['dt'][ix,t+1])
        return y

    def deploy(z2): return np.stack([pred_dataset(params(full,t),z2[:,t]) for t in range(6)],1)
    train_q=np.empty((n,h,3)); train_y=np.stack([labels(full,t) for t in range(6)],1)
    for bit in np.unique(masks):
        ix=masks==bit
        for t in range(6): train_q[ix,t]=pred_dataset(params(full^int(bit),t),z[ix,t])
    return train_y,train_q,deploy


def head(h,y,group):
    h=h.reshape(-1,h.shape[-1]); y=y.reshape(-1,3); g=np.repeat(group,6)
    w=np.array([1/np.sum(g==v) for v in g]); w/=w.sum(); xm=w@h; ym=w@y
    x=h-xm; coef=np.linalg.solve((x*w[:,None]).T@x+.001*np.eye(x.shape[1]),(x*w[:,None]).T@(y-ym))
    return np.vstack((coef,ym-xm@coef))


def outcomes(q,s,paid,immediate=False):
    a=q.copy(); a[:,-1,2]=-np.inf
    if not paid: a[:,:,1]=-np.inf
    if immediate: a[:,:,2]=-np.inf
    choices=a.argmax(-1); times=np.argmax(choices!=2,axis=-1)
    return outcome(s,times,choices[np.arange(len(q)),times])


def check_metric(actual,saved,full):
    for key in ('utility','r1','reads','waiting_queries','wait_steps','read_after_wait'): same(actual[key],saved[key])
    for key in ('per_source','per_source_r1'):
        require(set(actual[key])==set(saved[key]),'changed independent group')
        for g,v in actual[key].items(): same(v,saved[key][g])
    if full:
        for key in ('episode_hit','episode_utility','exit_prefix','terminal_action'): same(actual[key],saved[key])


def verify(data_dir,root,fit_only):
    seal=check_seal(root)
    if not fit_only: check_test_receipt(data_dir,root)
    meta=read(root/'prepare/metadata.json'); names=['train','dev','retain']+([] if fit_only else ['test'])
    splits={n:data(data_dir/(n+'.npz')) for n in names}; z={n:context(s) for n,s in splits.items()}
    for n in names[:3]: require(digest(data_dir/(n+'.npz'))==meta['inputs'][n],'changed fitting data')
    tr=splits['train']; w=np.array([1/np.sum(tr['group']==g) for g in tr['group']]); w/=w.sum()
    mu=w@z['train'].mean(1); sd=np.sqrt(w@((z['train']-mu)**2).mean(1)).clip(min=1e-6); same(mu,meta['mu']);same(sd,meta['scale'])
    counts=dict(arm_selections=0,conditional_linear_refits=0,development_and_retention_decisions=0,
                test_policies_with_controls=0,test_episode_actions=0,teacher_targets=0)
    seedscores={}; summary={} if fit_only else {(r['seed'],r['mode'],r['method']):r for r in read(root/'summary.json')['rows']}; derived={}
    max_q=0.; max_head=0.
    for avail in ('read','noread'):
        paid=avail=='read'; registered=read(root/'prepare'/(avail+'.json')); fold=np.asarray(registered['fold_ids'])
        for attr in ('group','source'):
            for gid in set(tr[attr]): require(len(set(fold[tr[attr]==gid]))==1,'training provenance crossed folds')
        y,qtrain,estimator=nuisance_replay(tr,z['train'],fold,paid)
        same(y,registered['targets']); same(qtrain,registered['held']); counts['teacher_targets']+=y.size
        arrays={}
        for n,s in splits.items():
            q=qtrain if n=='train' else estimator(z[n]); inp=z[n]
            reconstructed=[]
            for t,b in enumerate(registered['models']):
                raw=(inp[:,t]-b['mu'])/b['scale']@np.array(b['coef'])+b['bias']+b['offset']
                reconstructed.append(np.clip(raw,[0,-.3,-2.3],[1,.7,1]))
            same(estimator(inp),np.stack(reconstructed,1))
            arrays[n]={'zt':torch.tensor((inp-mu)/sd),'qt':torch.tensor(q),'clock':torch.tensor(s['dt'],dtype=torch.float64)}
        for seed in SEEDS:
            for mode,method in ARMS:
                key=f'{avail}-{mode}-{method}-{seed}.json'; saved=read(root/'fit'/key); report=saved['report']; model=representation(mode,seed,len(mu)); make=features(model,mode,paid)
                attempts=report['attempts']; require(len(attempts)==(5 if method=='bp' else 1),'incorrect number of candidate updates')
                best=None; heads=[]
                with torch.no_grad():
                    def predict(v,n,coef): return make(torch.as_tensor(v,dtype=torch.float64),arrays[n]).numpy()@coef[:-1]+coef[-1]
                    for index,attempt in enumerate(attempts):
                        v=attempt['theta']; ht=make(torch.tensor(v,dtype=torch.float64),arrays['train']).numpy(); coef=head(ht,y,tr['group']); heads.append(coef)
                        hq=ht@coef[:-1]+coef[-1]; loss=w@((hq-y)**2).sum(-1).mean(1)+.001*(coef[:-1]**2).sum(); same(loss,attempt['train_objective'])
                        dv=outcomes(predict(v,'dev',coef),splits['dev'],paid); re=outcomes(predict(v,'retain',coef),splits['retain'],paid)
                        for name,comp in [('dev',dv),('retain',re)]: check_metric(comp,attempt['diagnostics'][0][name],False)
                        if index==0: ref=re
                        worst=min(re['per_source'][k]-ref['per_source'][k] for k in ref['per_source']); allowed=worst>=-.05-1e-12
                        same(worst,attempt['diagnostics'][0]['worst_retain_delta']); require(allowed==attempt['allowed'],'retention decision'); same(dv['utility'],attempt['utility'])
                        if allowed and (best is None or dv['utility']>best[0]+1e-12): best=(dv['utility'],index)
                        counts['conditional_linear_refits']+=1; counts['development_and_retention_decisions']+=2
                    i=best[1]; require(i==report['selected_index'],'DEV selection/tie'); same(heads[i],saved['head']); same(heads[0],saved['keep_head']);same(attempts[i]['theta'],saved['theta']);counts['arm_selections']+=1
                    max_head=max(max_head,float(np.abs(heads[i]-np.array(saved['head'])).max()))
                    devq=predict(saved['theta'],'dev',heads[i]); devref={}
                    for nm in ['immediate_conditional','immediate_free']+(['immediate_paid'] if paid else []):
                        template=devq.copy()
                        if nm!='immediate_conditional': template[:]=0; template[:,:,int(nm=='immediate_paid')]=1
                        dvref=outcomes(template,splits['dev'],paid,True);check_metric(dvref,saved['immediate_dev'][nm],False);devref[nm]=dvref['utility']
                    choice=max(devref,key=devref.get);require(choice==saved['immediate_choice'],'incorrect DEV-locked immediate control')
                    if fit_only: continue
                    result=read(root/'confirm'/key); te=splits['test']; q=predict(saved['theta'],'test',heads[i]); q0=predict(saved['keep_theta'],'test',heads[0]); same(q,result['q']); max_q=max(max_q,float(np.abs(q-np.array(result['q'])).max()))
                    selected=outcomes(q,te,paid); keep=outcomes(q0,te,paid); suppressed=outcomes(q,te,False)
                    for name,actual in [('chosen',selected),('keep',keep),('disable_read',suppressed)]: check_metric(actual,result[name],True)
                    for nm in result['immediate_controls']:
                        template=q.copy()
                        if nm!='immediate_conditional': template[:]=0; template[:,:,int(nm=='immediate_paid')]=1
                        check_metric(outcomes(template,te,paid,True),result['immediate_controls'][nm],True)
                    same(min(selected['per_source'][g]-keep['per_source'][g] for g in keep['per_source']),result['worst_delta'])
                    require(list(map(str,te['query_id']))==result['query_id'],'changed TEST episode')
                    resources=result['task_resources']; require(resources=={'test_sha':digest(data_dir/'test.npz'),'sealed_fit_sha':digest(root/'fit'/key),'selection_seal_sha':seal},'unbound confirmation')
                    counts['test_policies_with_controls']+=1; counts['test_episode_actions']+=len(te['target'])*(3+len(result['immediate_controls']))
                    ident=(seed,mode,method); seedscores[avail,ident]=selected['utility']
                    row=summary[ident]
                    if paid:
                        same(row['utility'],selected['utility']);same(row['r1'],selected['r1'])
                        fast=result['immediate_controls'][choice]
                        worst=min(selected['per_source'][g]-keep['per_source'][g] for g in selected['per_source'])
                        absolute=(selected['utility']>=.60-1e-12 and selected['r1']>=.70-1e-12 and worst>=-.05-1e-12)
                        derived[ident]={'absolute':absolute,'full':selected,'immediate':fast}
                    else:
                        full=derived[ident]['full']; instant=derived[ident]['immediate']; paidgain=full['utility']-selected['utility']; timegain=full['utility']-instant['utility']
                        same(row['paid_gain_vs_matched_noread'],paidgain); same(row['gain_vs_dev_locked_immediate'],timegain)
                        checks=[]
                        for label,other in [('versus_refit_noread',selected),('versus_dev_locked_immediate',instant)]:
                            ds=[full['per_source'][g]-other['per_source'][g] for g in full['per_source']]; n=len(ds); wins=sum(v>1e-12 for v in ds)
                            p=sum(math.comb(n,j) for j in range(wins,n+1))/2**n; stored=row['source_support'][label]
                            same(p,stored['one_sided_sign_p']);same(wins,stored['positive']);checks.append(p<=.025+1e-12)
                        pos=paidgain>1e-12 and full['reads']>0;timing=pos and timegain>1e-12 and full['waiting_queries']>0
                        absolute=derived[ident]['absolute']; supported=timing and all(checks)
                        for k,v in {'pass_capability':absolute,'positive_paid_value':pos,'positive_paid_timing':timing,'supported_paid_timing':supported,'pass_joint':absolute and supported}.items():
                            require(bool(row[k])==v,'wrong declared gate '+k)
    if not fit_only:
        for m,o in ARMS:
            family=read(root/'summary.json')['families'][f'{m}-{o}']
            for gate,value in family.items(): require(value==all(summary[seed,m,o][gate] for seed in SEEDS),'incorrect all-seed family gate')
    return dict(passed=True,selection_seal=seal,phase='fit' if fit_only else 'confirm',counts=counts,max_selected_head_difference=max_head,
                max_test_action_score_difference=max_q,scope='Independent nested stopping rewards, calibrated nuisance values, original physical features, normal-equation heads, all attempted DEV/RETAIN actions and selections. Confirmation includes proposed and masked/restricted policies and per-query utility. BP search trajectories are replayed at their saved displacements, not gradient-audited.')


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__); p.add_argument('data',type=Path);p.add_argument('evidence',type=Path);p.add_argument('--fit-only',action='store_true');p.add_argument('--output',type=Path)
    args=p.parse_args();torch.set_num_threads(1); result=verify(args.data,args.evidence,args.fit_only)
    rendered=json.dumps(result,indent=2,allow_nan=False);print(rendered)
    if args.output:
        with args.output.open('x') as f:f.write(rendered+'\n')
