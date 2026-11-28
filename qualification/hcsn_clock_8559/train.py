"""Restartable, single-core SHD training panel. Never reads the official test file."""
import argparse
import hashlib
import json
import os
import resource
import time
from pathlib import Path
import numpy as np
import torch
from torch.nn import functional as F
from model import ARMS, Classifier

SEEDS=(137,311,557)
RUNGS=(30,180,720,1800)
MATCHED={1,8,24,64,128,256,512,1024,2048,4096,8192,16384,32768,65536}


def digest(p):
    with p.open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()


def atomic_json(p,data):
    tmp=p.with_suffix(p.suffix+'.tmp')
    tmp.write_text(json.dumps(data,indent=2,allow_nan=False)+'\n')
    os.replace(tmp,p)


def save(p,state):
    tmp=p.with_suffix('.partial')
    torch.save(state,tmp);os.replace(tmp,p)


def params(model):
    return {k:p.detach().clone() for k,p in model.named_parameters()}


def apply(model,weights):
    assert weights.keys()==dict(model.named_parameters()).keys()
    with torch.no_grad():
        for k,p in model.named_parameters():p.copy_(weights[k])


class Data:
    def __init__(self,root):
        begin=time.perf_counter()
        with np.load(root/'train-natural.npz') as a:
            x=torch.from_numpy(np.log1p(a['counts'].astype('float32')))
            y=torch.from_numpy(a['y'].astype('int64'))
            s=torch.from_numpy(a['speaker'].astype('int64'))
        dev=(s==3)|(s==10)
        self.m=x[~dev].mean((0,1));self.s=x[~dev].std((0,1)).clamp_min(.05)
        x=(x-self.m)/self.s
        self.x=x[~dev];self.y=y[~dev];self.xd=x[dev];self.yd=y[dev];self.sd=s[dev]
        self.setup_wall_s=time.perf_counter()-begin


def evaluate(model,x,y,speakers):
    model.eval()
    with torch.no_grad():
        logits=torch.cat([model(batch) for batch in x.split(48)])
    hit=(logits.argmax(-1)==y).float()
    acc=float(torch.stack([hit[speakers==s].mean() for s in speakers.unique()]).mean())
    return {'dev_macro':acc,'dev_nll':float(F.cross_entropy(logits,y))}


def train_one(data,folder,arm,seed,budget):
    out=folder/f'{arm}-{seed}'
    out.mkdir(parents=True,exist_ok=True)
    record=out/f'rung-{budget}.json';selected=out/f'selected-{budget}.pt'
    if record.exists():
        old=json.loads(record.read_text())
        if digest(selected)!=old['selected_hash']:raise ValueError('Bad selected checkpoint')
        return
    begin=time.perf_counter()
    torch.manual_seed(seed)
    model=Classifier(arm);opt=torch.optim.AdamW(model.parameters(),lr=.001,weight_decay=.01)
    gen=torch.Generator().manual_seed(seed+17001)
    runfile=out/'resume.pt'
    fresh={'step':0,'fit_cpu_s':0.,'fit_wall_s':0.,'overhead_wall_s':0.,'best':None,
           'validation':[],'resumes':0,'loss':None,'last_matched':0}
    state=fresh
    if runfile.exists():
        checkpoint=torch.load(runfile,map_location='cpu',weights_only=True)
        if (checkpoint['arm'],checkpoint['seed'])!=(arm,seed):raise ValueError('checkpoint identity')
        state=checkpoint['stats']
        apply(model,checkpoint['weights']);opt.load_state_dict(checkpoint['optimizer']);gen.set_state(checkpoint['stream'])
        state['resumes']+=1
    state['overhead_wall_s']+=time.perf_counter()-begin
    def checkpoint():
        stamp=time.perf_counter()
        save(runfile,dict(arm=arm,seed=seed,weights=params(model),optimizer=opt.state_dict(),stream=gen.get_state(),stats=state))
        state['overhead_wall_s']+=time.perf_counter()-stamp
    last_save=state['fit_cpu_s']
    model.train()
    while state['fit_cpu_s']<budget:
        cpu=time.process_time();wall=time.perf_counter()
        idx=torch.randint(data.x.shape[0],(48,),generator=gen)
        logits=model(data.x[idx]);loss=F.cross_entropy(logits,data.y[idx])
        if not torch.isfinite(loss):raise ArithmeticError((arm,seed,state['step'],'nonfinite objective'))
        opt.zero_grad(set_to_none=True);loss.backward()
        torch.nn.utils.clip_grad_norm_(model.parameters(),1.,error_if_nonfinite=True)
        opt.step()
        state['step']+=1;state['loss']=float(loss.detach())
        state['fit_cpu_s']+=time.process_time()-cpu;state['fit_wall_s']+=time.perf_counter()-wall
        if state['step'] in MATCHED:
            stamp=time.perf_counter()
            save(out/f'update-{state["step"]}.pt',params(model));state['last_matched']=state['step']
            state['overhead_wall_s']+=time.perf_counter()-stamp
        if state['fit_cpu_s']-last_save>=30.:
            checkpoint();last_save=state['fit_cpu_s']
    start_eval=time.perf_counter()
    val=evaluate(model,data.xd,data.yd,data.sd)
    val.update(step=state['step'],budget=budget,fit_cpu_s=state['fit_cpu_s'])
    best=state['best']
    if best is None or (val['dev_macro'],-val['dev_nll'],-val['step'])>(best['dev_macro'],-best['dev_nll'],-best['step']):
        state['best']=dict(val);save(out/'best.pt',params(model))
    # Each rung retains the selected parameter states independently even after the best changes.
    save(selected,torch.load(out/'best.pt',map_location='cpu',weights_only=True))
    if state['validation'] and state['validation'][-1]['budget']==budget:state['validation'].pop()
    state['validation'].append(val)
    state['overhead_wall_s']+=time.perf_counter()-start_eval
    checkpoint()
    receipt=dict(state,arm=arm,seed=seed,budget=budget,param_count=sum(x.numel() for x in model.parameters()),
                 train_records=len(data.x),dev_records=len(data.xd),data_setup_wall_s=data.setup_wall_s,
                 selected_hash=digest(selected),torch_version=str(torch.__version__),affinity=sorted(os.sched_getaffinity(0)),
                 rss_highwater_kib=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
                 observed_at=time.time())
    atomic_json(record,receipt)
    print(json.dumps({k:receipt[k] for k in ('arm','seed','budget','step','loss','best','fit_wall_s','observed_at')}),flush=True)


def panel(root,out,budgets,seeds,arms):
    torch.set_num_threads(1);torch.set_num_interop_threads(1)
    data=Data(root)
    out.mkdir(parents=True,exist_ok=True)
    for budget in budgets:
        jobs=[(a,s) for s in seeds for a in arms]
        rng=np.random.default_rng(201126+budget)
        for i in rng.permutation(len(jobs)):
            a,s=jobs[i];train_one(data,out,a,s,budget)
        entries=[]
        for a,s in jobs:
            f=out/f'{a}-{s}'/f'rung-{budget}.json';entry=json.loads(f.read_text())
            entries.append(dict(arm=a,seed=s,budget=budget,receipt_sha256=digest(f),selected_sha256=entry['selected_hash']))
        atomic_json(out/f'seal-{budget}.json',entries)
        print('SEALED',budget,flush=True)

if __name__=='__main__':
    p=argparse.ArgumentParser()
    p.add_argument('data',type=Path);p.add_argument('out',type=Path);p.add_argument('--rungs',type=int,nargs='+',default=RUNGS)
    p.add_argument('--seeds',type=int,nargs='+',default=SEEDS);p.add_argument('--arms',nargs='+',choices=ARMS,default=ARMS)
    a=p.parse_args();panel(a.data,a.out,a.rungs,a.seeds,a.arms)
