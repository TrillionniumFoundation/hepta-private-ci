"""Single global development-selected stronger soft-anchor coefficient and measured key geometry."""
import argparse
import hashlib
import json
from pathlib import Path
import time
import numpy as np
import torch
from torch.nn import functional as F
from rls_core import prior,rls_step,projected,target_labels,select_masks,summarize,gate,outcomes
from study_edit import read,write,sha,npz,load_arrays,SEEDS

MUS=(8,16,32,64,128,256,512)
PROTO='36fb767acb580807a2ccdc32c300af4fc583d19ca5d7532e19a97f93c9d16177'


def matrices(b):
    y=b['train_y'];ix=b['train_ids'];w=b['W0'].double();text=b['text'].double();keys=b['train'].double()
    keep=np.flatnonzero(y.numpy()//6>=6);keep=keep[np.argsort(ix[keep],kind='stable')]
    take=np.random.default_rng(912731).choice(keep,128,replace=False);take=take[np.argsort(ix[take],kind='stable')]
    anchors=torch.cat((text,keys[take]));proto=F.normalize(text@w,dim=-1);batches=[]
    for j in range(6):
        ids=np.flatnonzero(y.numpy()//6==j);ids=ids[np.argsort(ix[ids],kind='stable')]
        k=keys[ids];z=target_labels(y[ids],j);batches.append((k,(k@w).norm(dim=1,keepdim=True)*proto[z]))
    return w,anchors,batches


def geometry(a,k):
    _,sigma,vh=torch.linalg.svd(a,full_matrices=False)
    cut32=sigma[0]*max(a.shape)*np.finfo(np.float32).eps
    cut64=sigma[0]*max(a.shape)*np.finfo(np.float64).eps
    rank=int((sigma>cut32).sum());res=k-(k@vh[:rank].T)@vh[:rank]
    return {'singular_values':sigma.tolist(),'rank_fp64':int((sigma>cut64).sum()),'rank_at_fp32_relative_tolerance':rank,
            'condition':float(sigma[0]/sigma[-1]),'edit_key_energy_outside_fp32_anchor_space':float(res.square().sum()/k.square().sum())}


def run(task):
    torch.set_num_threads(1);torch.set_num_interop_threads(1)
    base=task/'run';dst=task/'preservation_diagnostic';dst.mkdir(exist_ok=True)
    assert sha(task/'PRESERVATION_DIAGNOSTIC.md')==PROTO
    mainseal=read(base/'development_seal.json');term=read(base/'terminal.json')
    assert term['seal_sha256']==sha(base/'development_seal.json')
    records={};geos={};all_states={};start=time.perf_counter()
    for seed in SEEDS:
        b=load_arrays(base/str(seed)/'basis.npz')
        assert sha(base/str(seed)/'basis.npz')==mainseal['parents'][str(seed)]['archive_sha256']
        w,a,batches=matrices(b);geos[str(seed)]=geometry(a,torch.cat([k for k,v in batches]))
        baseline=projected(b['dev'],b['text'],w.float());y=b['dev_y'];gt=torch.zeros(96,96,dtype=torch.float64);rt=torch.zeros_like(w)
        for j,(k,v) in enumerate(batches):
            gt+=k.T@k;rt+=k.T@v;base_metrics=summarize(baseline,baseline,y,j)
            for mu in MUS:
                s,t=prior(w,a,mu);q=torch.linalg.solve(s+gt,t+rt)
                z=projected(b['dev'],b['text'],q.float());m=summarize(z,baseline,y,j)
                all_states[seed,mu,j]=q
                records.setdefault(str(mu),{}).setdefault(str(seed),{})[str(j)]={'pass':bool(gate(m,base_metrics)),'development':m}
    def rank(mu):
        ls=records[str(mu)];m=np.array([[ls[str(seed)][str(j)]['pass'] for j in range(6)] for seed in SEEDS])
        return (int(m.all()),int(m[:,-1].all()),int(sum(m[:,-1])),int(m.all(0).sum()),int(m.sum()),-mu)
    chosen=max(MUS,key=rank);writes={};parity=0.
    for seed in SEEDS:
        b=load_arrays(base/str(seed)/'basis.npz');w0,a,batches=matrices(b);s,_=prior(w0,a,chosen);p=torch.linalg.inv(s);w=w0.clone();parts={}
        for j,(k,v) in enumerate(batches):
            w,p=rls_step(w,p,k,v);delta=float((w-all_states[seed,chosen,j]).abs().max());parity=max(parity,delta)
            assert delta<2e-6;parts[f'W{j}']=w.float().numpy()
        out=dst/f'heads-{seed}.npz';npz(out,**parts);writes[str(seed)]=sha(out)
    seal={'protocol_sha256':PROTO,'source_sha256':sha(Path(__file__)),'primary_seal':term['seal_sha256'],'anchor_geometry':geos,'mu':chosen,
          'all_development':records,'rank_values':{str(v):rank(v) for v in MUS},'weight_sha256':writes,
          'maximum_woodbury_batch_error':parity,'development_s':time.perf_counter()-start}
    locked=dst/'development_seal.json'
    if locked.exists():
        old=read(locked)
        for k in seal:
            if k!='development_s':assert seal[k]==old[k] or json.dumps(seal[k],sort_keys=True)==json.dumps(old[k],sort_keys=True)
        seal=old
    else:write(locked,seal)
    print('fixed',chosen,sha(locked),'geometry',[(k,g['rank_at_fp32_relative_tolerance']) for k,g in geos.items()],flush=True)
    cold={};diffs={};raw={}
    for seed in SEEDS:
        b=load_arrays(base/str(seed)/'held.npz');y=b['held_y'];ids=b['held_ids'];actors=np.array([v.split('_')[0] for v in ids])
        old=projected(b['held'],b['text'],b['W0']);w=load_arrays(dst/f'heads-{seed}.npz');raw={'ids':ids,'y':y.numpy()};cold[str(seed)]={}
        for j in range(6):
            z=projected(b['held'],b['text'],w[f'W{j}']);raw[f'scores{j}']=z.numpy();m=summarize(z,old,y,j);parent=summarize(old,old,y,j)
            cold[str(seed)][str(j)]={'development_gate':records[str(chosen)][str(seed)][str(j)]['pass'],'held_gate':bool(gate(m,parent)),
                                     'scores':m,'parent':parent}
            after=outcomes(z,old,y,j);before=outcomes(old,old,y,j);diffs[seed,j]={k:after[k]-before[k] for k in ('nll','top1','kl_parent_edited')}
        npz(dst/f'held-{seed}.npz',**raw)
    who=np.unique(actors);idx=np.random.default_rng(83573).integers(len(who),size=(4000,len(who)))
    effects={}
    for j in range(6):
        effects[str(j)]={}
        for group,mt in select_masks(y,j).items():
            m=mt.numpy()
            if not m.any():continue
            counts=np.array([np.sum(m&(actors==v)) for v in who]);effects[str(j)][group]={}
            for k in ('nll','top1','kl_parent_edited'):
                d=np.mean([diffs[s,j][k] for s in SEEDS],axis=0);sums=np.array([d[m&(actors==v)].sum() for v in who])
                effects[str(j)][group][k]={'mean':float(d[m].mean()),'CI95':np.quantile(sums[idx].sum(1)/counts[idx].sum(1),[.025,.975]).tolist()}
    terminal={'mu':chosen,'selection_sha256':sha(locked),'cold':cold,'paired_vs_parent':effects,'all_dev_and_held_seeds_per_stage':[
       sum(int(cold[str(s)][str(j)]['development_gate'] and cold[str(s)][str(j)]['held_gate']) for s in SEEDS) for j in range(6)],
       'held_files':{str(s):sha(dst/f'held-{s}.npz') for s in SEEDS}}
    write(dst/'terminal.json',terminal);print('held',terminal['all_dev_and_held_seeds_per_stage'],sha(dst/'terminal.json'),flush=True)


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('root',type=Path);run(p.parse_args().root.resolve())
