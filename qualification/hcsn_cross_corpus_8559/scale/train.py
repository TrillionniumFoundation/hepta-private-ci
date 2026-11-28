"""Restartable, single-core source-only scale experiment with exact optimizer/sampler resume."""
import argparse
from contextlib import contextmanager
import fcntl
import hashlib
import json
import os
from pathlib import Path
import sys
import time

import numpy as np
import torch
from torch.nn import functional as F
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from encoder import Encoder
from score import score_embeddings

CLOCK=[30,120,600,2100,4200]
STEPS=[128,512,2048,8192,32768,65536]
SEEDS=[2039,4729,8047]
ARMS=['literal','smooth','lif','sdpa']


def digest(p):return hashlib.sha256(p.read_bytes()).hexdigest()


def save(model,path):
    tmp=path.with_name(path.name+'.part')
    torch.save(model,tmp);os.replace(tmp,path)


def write(path,ob):
    tmp=path.with_name(path.name+'.part')
    tmp.write_text(json.dumps(ob,indent=2)+'\n');os.replace(tmp,path)


def arrays(path):
    return {k:np.load(path/(k+'.npy'),mmap_mode='r') for k in ('pixels','tokens','splits','ids','groups')}


def tensors(data,rows,k):
    return torch.from_numpy(np.asarray(data['pixels'][rows])),torch.from_numpy(np.asarray(data['tokens'][rows,k],np.int64))


@torch.no_grad()
def encoded(model,d,rows):
    im=[];text=[];model.eval()
    for i in range(0,len(rows),128):
        rows_i=rows[i:i+128];a,b=model(*tensors(d,rows_i,0))
        im.append(a.numpy());text.append(b.numpy())
    return np.concatenate(im),np.concatenate(text)


def fast_concordance(q,k,groups):
    vals=[]
    for a,b in ((q,k),(k,q)):
        for j in range(0,len(a),64):
            s=a[j:j+64]@b.T;idx=np.arange(j,j+len(s))
            y=s[np.arange(len(s)),idx,None];mask=groups[idx,None]!=groups[None,:]
            vals.extend((((s<y)+.5*(s==y))*mask).sum(1)/mask.sum(1))
    return float(np.mean(vals))


def launch(work,law,seed,arm,target):
    assert target in CLOCK and arm in ARMS and seed in SEEDS
    beg=time.perf_counter();cpu0=time.process_time()
    dest=work/'fits'/f'{arm}-{seed}';dest.mkdir(exist_ok=True,parents=True)
    with (dest/'fit.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        torch.set_num_threads(1);torch.manual_seed(seed);rng=np.random.default_rng(seed)
        d=arrays(work/'data');src=[np.flatnonzero(d['splits']==s+'_train') for s in ('rs','nw')]
        dev={s:np.flatnonzero(d['splits']==s+'_dev') for s in ('rs','nw')}
        ds=json.loads((work/'data/data.json').read_text());net=Encoder(arm,seed,ds['vocab'],law)
        opt=torch.optim.AdamW(net.parameters(),lr=.001,weight_decay=.01)
        statefile=dest/'resume.pt'
        if statefile.exists():
            keep=torch.load(statefile,weights_only=False,map_location='cpu')
            assert (keep['seed'],keep['arm'],keep['law_sha'])==(seed,arm,digest(law))
            net.load_state_dict(keep['model']);opt.load_state_dict(keep['opt']);rng.bit_generator.state=keep['rng'];torch.set_rng_state(keep['torch_rng'])
            ledger=keep['ledger']
        else:
            ledger=dict(step=0,train_cpu=0.,train_wall=0.,validation_cpu=0.,validation_wall=0.,checkpoint_wall=0.,setup_wall=0.,setup_cpu=0.,clock_done=[],steps_done=[],events=[],starts=0)
        if target in ledger['clock_done']:return
        ledger['starts']+=1;ledger['setup_wall']+=time.perf_counter()-beg;ledger['setup_cpu']+=time.process_time()-cpu0
        law_hash=digest(law);last_backup=ledger['train_cpu']
        def checkpoint():
            save(dict(arm=arm,seed=seed,law_sha=law_hash,model=net.state_dict(),opt=opt.state_dict(),rng=rng.bit_generator.state,torch_rng=torch.get_rng_state(),ledger=ledger),statefile)
            write(dest/'progress.json',ledger)
        while target not in ledger['clock_done']:
            cpu=time.process_time();wall=time.perf_counter();net.train()
            rows=np.concatenate([rng.choice(ids,16,replace=False) for ids in src]);rows=rows[rng.permutation(32)]
            step=ledger['step']+1;cols=(step+np.arange(32))%5
            x,y=net(*tensors(d,rows,cols));s=15*(x@y.T);grp=torch.from_numpy(d['groups'][rows,cols]);mask=grp[:,None].eq(grp[None,:]).to(s.dtype);p=mask/mask.sum(1,keepdim=True)
            loss=-.5*((p*s.log_softmax(1)).sum(1).mean()+(p*s.T.log_softmax(1)).sum(1).mean())
            opt.zero_grad();loss.backward();torch.nn.utils.clip_grad_norm_(net.parameters(),1);opt.step()
            ledger['train_cpu']+=time.process_time()-cpu;ledger['train_wall']+=time.perf_counter()-wall;ledger['step']=step
            eligible=[k for k in CLOCK if k<=target and k not in ledger['clock_done'] and ledger['train_cpu']>=k]
            equal=step in STEPS and step not in ledger['steps_done']
            if eligible or equal:
                t,c=time.perf_counter(),time.process_time();sc={}
                for name,sel in dev.items():sc[name]=fast_concordance(*encoded(net,d,sel),d['groups'][sel,0])
                val_wall=time.perf_counter()-t;ledger['validation_wall']+=val_wall;ledger['validation_cpu']+=time.process_time()-c
                w=dest/f's{step}.pt';t=time.perf_counter();save(net.state_dict(),w);whash=digest(w);ledger['checkpoint_wall']+=time.perf_counter()-t
                rec=dict(step=step,budgets=eligible,update_endpoint=bool(equal),source_dev=sc,dev_mean=np.mean(list(sc.values())),sha256=whash,loss=float(loss.detach()),
                         train_cpu_s=ledger['train_cpu'],train_wall_s=ledger['train_wall'],validation_cumulative_s=ledger['validation_wall'],startup_cumulative_s=ledger['setup_wall'],checkpoint_cumulative_s=ledger['checkpoint_wall'])
                ledger['events'].append(rec);ledger['clock_done'].extend(eligible)
                if equal:ledger['steps_done'].append(step)
                checkpoint();last_backup=ledger['train_cpu']
                print(arm,seed,step,eligible,round(rec['train_cpu_s'],2),sc,flush=True)
            elif ledger['train_cpu']-last_backup>=90:
                checkpoint();last_backup=ledger['train_cpu']
        if target==CLOCK[-1]:
            best=max(ledger['events'],key=lambda r:r['dev_mean'])
            write(dest/'selected.json',dict(seed=seed,arm=arm,n_param=sum(p.numel() for p in net.parameters()),best=best,ledger=ledger))


if __name__=='__main__':
    a=argparse.ArgumentParser();a.add_argument('work',type=Path);a.add_argument('law',type=Path);a.add_argument('seed',type=int);a.add_argument('arm');a.add_argument('target',type=int);args=a.parse_args()
    launch(args.work,args.law,args.seed,args.arm,args.target)
