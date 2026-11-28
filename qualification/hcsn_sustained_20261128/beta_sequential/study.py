"""Transfer BetaEdit's matrix update to the single shared output of trained HCSN parents."""
import argparse
import hashlib
import json
import os
import time
from pathlib import Path

import numpy as np
import torch
from torch.nn import functional as F

SEEDS=(137,311,557)
ARMS=('beta','frozen_projection','no_leakage_penalty','alpha','rls32','task_bp32','parent')
BUDGETS=(0.25,0.5,0.75,1.0)
OLD_SEAL='deea9b35799c5cdc1a9c2c787be6494f4a098d07ef60060567b18383351b5eba'
CONTROL_SEAL='daf667f1a3837e2e544c19dc83278eb0c1052a4e38cab0411301536ce05af4e6'


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def dump(path,obj):
    tmp=path.with_suffix('.next')
    tmp.write_text(json.dumps(obj,sort_keys=True,indent=1,allow_nan=False)+'\n')
    tmp.replace(path)


def tensor(x):
    return torch.from_numpy(x.copy())


def cov_basis(gram):
    ev,u=torch.linalg.eigh((gram+gram.T)/2)
    return u[:,ev<.02]


def write_head(k,residual,u,gram,old_cov,penalty):
    if not u.shape[1]:
        return torch.zeros(k.shape[1],residual.shape[1],dtype=k.dtype)
    uk=k@u
    matrix=10*torch.eye(u.shape[1],dtype=k.dtype)+uk.T@uk+u.T@(gram+penalty*old_cov)@u
    return u@torch.linalg.solve(matrix,uk.T@residual)


def unit():
    g=torch.Generator().manual_seed(940)
    normal=lambda m,n:torch.randn(m,n,generator=g,dtype=torch.float64)
    k,r,a,h=normal(13,8),normal(13,11),normal(7,8),normal(17,8)
    u=torch.linalg.qr(normal(8,4)).Q
    old=a.T@a/7;hist=h.T@h;p=u@u.T
    answer=write_head(k,r,u,hist,old,3000)
    identity=torch.eye(8,dtype=k.dtype)
    direct=torch.linalg.solve(p@(k.T@k+hist+3000*old)+10*identity,p@k.T@r)
    err=float((answer-direct).abs().max())
    if err>1e-10:raise ValueError(err)
    return err


def projected(x,text,w):
    w=w.float()
    return 12*(F.normalize(x@w,dim=1)@F.normalize(text@w,dim=1).T)


def metrics(z,y,stage):
    s=y//6;new=torch.where(s<=stage,6*s+(y%6+1)%6,y)
    loss=F.cross_entropy(z,new,reduction='none')
    good=(z.argmax(1)==new).float()
    masks={'current':s==stage,'past':s<stage,'protected':s>=6}
    return {k:{'nll':float(loss[mask].mean()),'top1':float(good[mask].mean()),'n':int(mask.sum())}
            for k,mask in masks.items() if mask.any()}


def slack(m,p):
    scores=[p['current']['nll']-m['current']['nll']-.10,
            .10+p['protected']['nll']-m['protected']['nll'],
            .02+m['protected']['top1']-p['protected']['top1']]
    if 'past' in m:scores.append(p['past']['nll']-m['past']['nll']-.05)
    return min(scores)


def train(task,out):
    evidence={}
    parent_seal=task/'run/development_seal.json'
    control_seal=task/'matched_mu32/development_seal.json'
    if digest(parent_seal)!=OLD_SEAL or digest(control_seal)!=CONTROL_SEAL:
        raise ValueError('source selection identity')
    old=json.loads(parent_seal.read_text())
    controls=json.loads(control_seal.read_text())['registry']
    for seed in SEEDS:
        src=task/'run'/str(seed)/'basis.npz'
        if digest(src)!=old['parents'][str(seed)]['archive_sha256']:raise ValueError('basis')
        with np.load(src,allow_pickle=False) as data:
            keys=tensor(data['train']).double();text=tensor(data['text']);y=tensor(data['train_y'])
            ids=data['train_ids'].copy();w0=tensor(data['W0']).double()
            dev=tensor(data['dev']);dy=tensor(data['dev_y'])
        eligible=np.flatnonzero(y.numpy()//6>=6)
        eligible=eligible[np.argsort(ids[eligible],kind='stable')]
        anchors=np.random.default_rng(912731).choice(eligible,128,replace=False)
        anchors=anchors[np.argsort(ids[anchors],kind='stable')]
        a=torch.cat([text.double(),keys[anchors]])
        old_cov=a.T@a/len(a)
        template=F.normalize(text.double()@w0,dim=1)
        parent_logits=projected(dev,text,w0)
        for arm in ARMS:
            clock=time.perf_counter();stage_clocks=[]
            u=cov_basis(old_cov);hist=torch.zeros_like(old_cov)
            w=w0.clone();seen=last_refresh=0
            logs=[];states={}
            for stage in range(6):
                t0=time.perf_counter()
                order=np.flatnonzero(y.numpy()//6==stage);order=order[np.argsort(ids[order],kind='stable')]
                diagnostics=[]
                if arm in ('rls32','task_bp32'):
                    fixed='rls-32' if arm=='rls32' else 'ce-32'
                    p=task/'matched_mu32'/str(seed)/fixed/f'stage{stage}.npz'
                    if digest(p)!=controls[f'{seed}/{fixed}'][str(stage)]['weights_sha256']:
                        raise ValueError('control weights')
                    with np.load(p,allow_pickle=False) as c:w=tensor(c['W0' if arm=='rls32' else 'W128']).double()
                elif arm!='parent':
                    penalty=3000 if arm in ('beta','frozen_projection') else 0
                    for start in range(0,len(order),32):
                        rows=order[start:start+32]
                        k=keys[rows];target=6*stage+(y[rows]%6+1)%6
                        v=(k@w0).norm(dim=1,keepdim=True)*template[target]
                        refresh=(arm in ('beta','no_leakage_penalty') and seen-last_refresh>=1000)
                        if refresh:
                            # The history-only ablation retains the same P schedule as beta.
                            u=cov_basis((hist/seen+3000*old_cov)/3001)
                            last_refresh=seen
                        delta=write_head(k,v-k@w,u,hist,old_cov,penalty)
                        size=float(delta.norm())/len(k)**.5
                        if size>20:raise ValueError('published update guard')
                        w=(w+delta).float().double()
                        hist+=k.T@k
                        diagnostics.append([seen,u.shape[1],refresh,size]);seen+=len(k)
                core_s=time.perf_counter()-t0
                base=metrics(parent_logits,dy,stage)
                candidates={}
                for gain in BUDGETS:
                    # Development-only deployment interpolation. The unscaled w is propagated.
                    h=(w0+gain*(w-w0)).float()
                    m=metrics(projected(dev,text,h),dy,stage)
                    candidates[str(gain)]={'metrics':m,'slack':slack(m,base)}
                stage_clocks.append(core_s)
                logs.append({'stage':stage,'core_s':core_s,'diagnostics':diagnostics,
                             'dev_candidates':candidates})
                states['s'+str(stage)]=w.float().numpy()
            np.savez_compressed(out/f'{arm}-{seed}.npz',**states)
            evidence[f'{arm}-{seed}']={'states_sha256':digest(out/f'{arm}-{seed}.npz'),
                                      'stages':logs,'preparation_fit_dev_save_s':time.perf_counter()-clock}
    # Single deployment gain per method, shared across all three models and all six stages.
    selection={}
    for arm in ARMS:
        options=[]
        for g in BUDGETS:
            scores=[evidence[f'{arm}-{s}']['stages'][i]['dev_candidates'][str(g)]['slack']
                    for s in SEEDS for i in range(6)]
            options.append(((sum(x>=0 for x in scores),float(np.median(scores)),min(scores),-g),g))
        selection[arm]=max(options)[1]
    note={'unit_author_system_max_abs':unit(),'source_sha256':digest(Path(__file__)),
          'parents':{str(s):old['parents'][str(s)] for s in SEEDS},'parent_seal':OLD_SEAL,
          'archived_baseline_seal':CONTROL_SEAL,'evidence':evidence,'gains':selection}
    dump(out/'development_seal.json',note)
    return note


def evaluate(task,out,seal):
    data=[];score_records={};actor_ids=None;array_bytes=0;worst_error=0.;final={}
    for seed in SEEDS:
        base=task/'run'/str(seed);info=json.loads((base/'held.json').read_text());path=base/'held.npz'
        if digest(path)!=info['archive_sha256']:raise ValueError('held inputs')
        with np.load(path,allow_pickle=False) as f:
            x=tensor(f['held']);text=tensor(f['text']);y=tensor(f['held_y']);w0=tensor(f['W0'])
            ids=f['held_ids'].copy()
        actor=np.array([v.split('_')[0] for v in ids])
        if actor_ids is None:actor_ids=actor
        if not np.array_equal(actor_ids,actor):raise ValueError('misaligned test')
        old=projected(x,text,w0)
        for arm in ARMS:
            fp=out/f'{arm}-{seed}.npz'; reg=seal['evidence'][f'{arm}-{seed}']
            if digest(fp)!=reg['states_sha256']:raise ValueError('development freeze')
            with np.load(fp,allow_pickle=False) as heads:
                for stage in range(6):
                    w=tensor(heads['s'+str(stage)])
                    for profile,g in [('unit',1.),('dev_gain',seal['gains'][arm])]:
                        h=w0+g*(w-w0);z=projected(x,text,h)
                        m=metrics(z,y,stage);p=metrics(old,y,stage)
                        allowed=reg['stages'][stage]['dev_candidates'][str(g)]['slack']>=0
                        score_records[f'{seed}/{arm}/{stage}/{profile}']={
                            'metrics':m,'parent':p,'held_slack':slack(m,p),
                            'dev_pass':allowed,'both_pass':bool(allowed and slack(m,p)>=0)}
                        if stage==5:
                            target=torch.where(y//6<6,6*(y//6)+(y%6+1)%6,y)
                            loss=F.cross_entropy(z,target,reduction='none').numpy()
                            final[seed,arm,profile]=loss
                            # Independent float64 projection using NumPy norms.
                            av=x.numpy().astype('float64')@h.numpy();tx=text.numpy().astype('float64')@h.numpy()
                            ref=12*(av/np.linalg.norm(av,axis=1,keepdims=True))@(tx/np.linalg.norm(tx,axis=1,keepdims=True)).T
                            worst_error=max(worst_error,float(np.max(np.abs(ref-z.numpy()))))
                            if profile=='unit':
                                np.savez_compressed(out/f'logits-{arm}-{seed}.npz',scores=z.numpy(),ids=ids,y=y.numpy())
                                array_bytes+=z.nelement()*z.element_size()
    if worst_error>3e-5:raise ValueError('cross-language projection')
    unique=np.unique(actor_ids);ix=np.random.default_rng(83573).integers(len(unique),size=(4000,len(unique)))
    contrasts={}
    for profile in ('unit','dev_gain'):
        for other in ('parent','rls32','task_bp32','frozen_projection','no_leakage_penalty','alpha'):
            values=np.mean([final[s,'beta',profile]-final[s,other,profile] for s in SEEDS],axis=0)
            for group,mask in {'current':y.numpy()//6==5,'past':y.numpy()//6<5,'protected':y.numpy()//6>=6}.items():
                counts=np.array([((actor_ids==a)&mask).sum() for a in unique])
                sums=np.array([values[(actor_ids==a)&mask].sum() for a in unique])
                sample=sums[ix].sum(1)/counts[ix].sum(1)
                contrasts[f'{profile}/{other}/{group}']=[float(values[mask].mean()),*np.quantile(sample,[.025,.975]).tolist()]
    summary={}
    for profile in ('unit','dev_gain'):
        for arm in ARMS:
            bystage=[sum(score_records[f'{seed}/{arm}/{i}/{profile}']['both_pass'] for seed in SEEDS) for i in range(6)]
            m={g:float(np.mean([score_records[f'{s}/{arm}/5/{profile}']['metrics'][g]['nll'] for s in SEEDS]))
               for g in ('current','past','protected')}
            summary[f'{profile}/{arm}']={'both_gate_seed_count_by_stage':bystage,'last_nll':m}
    result={'selection_sha256':digest(out/'development_seal.json'),'clips':len(y),'actors':len(unique),
            'float64_logit_replay_max_error':worst_error,'last_unit_all_arm_uncompressed_logits_bytes':array_bytes,
            'gains':seal['gains'],'summary':summary,'paired_actor_nll_beta_minus_other':contrasts,'rows':score_records}
    dump(out/'terminal.json',result)
    print(json.dumps({'sha256':digest(out/'terminal.json'),'summary':summary,'gains':seal['gains']}),flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('task',type=Path);parser.add_argument('out',type=Path)
    a=parser.parse_args();torch.set_num_threads(1);torch.set_num_interop_threads(1)
    a.out.mkdir(parents=True,exist_ok=True);done=a.out/'terminal.json';seal=a.out/'development_seal.json'
    if not done.exists():
        frozen=json.loads(seal.read_text()) if seal.exists() else train(a.task,a.out)
        if frozen['source_sha256']!=digest(Path(__file__)):raise ValueError('existing owner')
        evaluate(a.task,a.out,frozen)
