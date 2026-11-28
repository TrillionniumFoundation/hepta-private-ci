"""Restartable registered original-modality MELD encoder training, validation and weight sealing."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import sys
import time
import numpy as np
import torch
from torch.nn import functional as F
from encoder import Encoder,ARMS
SEEDS=(137,311,557)
RUNGS=(30,180,720,1800)
class Data:
    def __init__(self,root,split):
        self.x=[np.load(root/split/(k+'.npy'),mmap_mode='r') for k in ('video','audio','text')]
        self.y=np.load(root/split/'label.npy',mmap_mode='r')
        self.dialog=np.load(root/split/'dialogue.npy',mmap_mode='r')
        self.clean=np.load(root/split/'clean.npy',mmap_mode='r')
        self.ids=np.flatnonzero(self.clean)
    def batch(self,idx):
        x=[torch.from_numpy(np.asarray(a[idx])) for a in self.x]
        return (x[0],x[1],x[2].long()),torch.as_tensor(np.asarray(self.y[idx]),dtype=torch.long)
def digest(p):
    with p.open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()
def atomic(p,item):
    t=p.with_suffix(p.suffix+'.partial');t.write_text(json.dumps(item,allow_nan=False,indent=1)+'\n');os.replace(t,p)
def save(p,item):
    t=p.with_suffix(p.suffix+'.partial');torch.save(item,t);os.replace(t,p)
def weights(model):return {n:p.detach().cpu().clone() for n,p in model.named_parameters()}
def apply(model,state):
    assert set(state)==dict(model.named_parameters()).keys()
    with torch.no_grad():
        for n,p in model.named_parameters():p.copy_(state[n])
def measures(y,logits,dialog):
    pred=logits.argmax(-1)
    cm=np.bincount(y*7+pred,minlength=49).reshape(7,7)
    diag=np.diag(cm);f1=2*diag/np.maximum(1,cm.sum(0)+cm.sum(1))
    weights=np.zeros(len(y))
    for d in np.unique(dialog):weights[dialog==d]=1./np.sum(dialog==d)
    z=logits.astype('float64');z-=z.max(-1,keepdims=True);logp=z-np.log(np.exp(z).sum(-1,keepdims=True));p=np.exp(logp).max(-1)
    calibration=sum(abs(float(np.sum((p-(pred==y))*((p>i/10)&(p<=(i+1)/10)))))/len(y) for i in range(10))
    return dict(macro_f1=float(f1.mean()),dialogue_acc=float(np.average(y==pred,weights=weights)),
              unweighted_acc=float(np.mean(y==pred)),nll=float(-logp[np.arange(len(y)),y].mean()),ece=calibration,
              recall=(diag/np.maximum(1,cm.sum(1))).tolist(),confusion=cm.tolist())
def infer(m,d,view='natural',clean=True):
    m.eval();ids=d.ids if clean else np.arange(len(d.y));z=[]
    with torch.no_grad():
        for i in range(0,len(ids),32):
            x,_=d.batch(ids[i:i+32]);z.append(m(*x,view=view).numpy())
    res=np.concatenate(z);assert np.isfinite(res).all()
    return ids,res
def fit(root,out,arm,seed,rung):
    out=out/f'{arm}-{seed}';out.mkdir(exist_ok=True,parents=True);r=out/f'rung-{rung}.json';chosen=out/f'selected-{rung}.pt'
    if r.exists():assert digest(chosen)==json.loads(r.read_text())['selected_sha256'];return
    begin=time.perf_counter();new=Data(root,'train');val=Data(root,'dev')
    torch.manual_seed(seed);m=Encoder(arm);optimizer=torch.optim.AdamW(m.parameters(),lr=.001,weight_decay=.01)
    g=torch.Generator().manual_seed(seed+15553);cp=out/'resume.pt'
    stats=dict(step=0,fit_cpu_s=0.,fit_wall_s=0.,overhead_s=0.,best=None,history=[])
    if cp.exists():
        q=torch.load(cp,weights_only=True,map_location='cpu')
        apply(m,q['params']);optimizer.load_state_dict(q['optimizer']);g.set_state(q['rng']);stats=q['stats']
    stats['overhead_s']+=time.perf_counter()-begin
    def checkpoint():
        st=time.perf_counter();save(cp,dict(params=weights(m),optimizer=optimizer.state_dict(),rng=g.get_state(),stats=stats));stats['overhead_s']+=time.perf_counter()-st
    last=stats['fit_cpu_s']
    m.train()
    while stats['fit_cpu_s']<rung:
        cpu=time.process_time();wall=time.perf_counter()
        ids=new.ids[torch.randint(len(new.ids),(32,),generator=g).numpy()]
        x,y=new.batch(ids);optimizer.zero_grad(set_to_none=True);pred=m(*x);loss=F.cross_entropy(pred,y);loss.backward()
        torch.nn.utils.clip_grad_norm_(m.parameters(),1.,error_if_nonfinite=True);optimizer.step()
        if not torch.isfinite(loss):raise FloatingPointError((seed,arm))
        stats['step']+=1;stats['fit_cpu_s']+=time.process_time()-cpu;stats['fit_wall_s']+=time.perf_counter()-wall
        if stats['fit_cpu_s']-last>=30:checkpoint();last=stats['fit_cpu_s']
    st=time.perf_counter();ids,z=infer(m,val);v=measures(val.y[ids].astype(int),z,val.dialog[ids])
    item={**v,'rung':rung,'step':stats['step']};prev=stats['best']
    if prev is None or (v['macro_f1'],-v['nll'],-stats['step'])>(prev['macro_f1'],-prev['nll'],-prev['step']):
        stats['best']=item;save(out/'best.pt',weights(m))
    save(chosen,torch.load(out/'best.pt',weights_only=True))
    if stats['history'] and stats['history'][-1]['rung']==rung:stats['history'].pop()
    stats['history'].append(item);stats['overhead_s']+=time.perf_counter()-st
    checkpoint()
    atomic(r,dict(**stats,arm=arm,seed=seed,selected_sha256=digest(chosen),params=sum(p.numel() for p in m.parameters()),now=time.time(),cpu=sorted(os.sched_getaffinity(0))))
    print(arm,seed,rung,stats['step'],stats['best']['macro_f1'],flush=True)
def cold(root,runs,out,rung):
    rows=json.loads((runs/f'seal-{rung}.json').read_text())
    if {(q['arm'],q['seed']) for q in rows}!={(a,s) for a in ARMS for s in SEEDS}:raise ValueError('incomplete manifest')
    d=Data(root,'test');out.mkdir(exist_ok=True,parents=True)
    for rec in rows:
        arm,seed=rec['arm'],rec['seed'];name=f'{arm}-{seed}'
        f=runs/name/f'selected-{rung}.pt';assert digest(f)==rec['selected_sha256']
        receipt=out/(name+'.json');scores=out/(name+'.npz')
        if receipt.exists():assert digest(scores)==json.loads(receipt.read_text())['score_sha256'];continue
        started=time.perf_counter()
        m=Encoder(arm);apply(m,torch.load(f,weights_only=True));times={};views=['natural','no_text','no_audio','no_video']
        if arm in ('literal','smooth'):views+=['no_wall','shuffle_wall','no_prices']
        zs={}
        for v in views:
            t=time.perf_counter();ids,z=infer(m,d,v,False);times[v]=time.perf_counter()-t;zs[v]=z
        tmp=out/(name+'.partial')
        with tmp.open('wb') as h:np.savez_compressed(h,**zs,y=d.y,clean=d.clean,dialogue=d.dialog,row=ids)
        os.replace(tmp,scores);atom=dict(arm=arm,seed=seed,rung=rung,selected_sha256=digest(f),score_sha256=digest(scores),view_wall_s=times,complete_wall_s=time.perf_counter()-started)
        atomic(receipt,atom)
    atomic(out/'complete.json',{p.name:digest(p) for p in out.glob('*.npz')})
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('mode',choices=('fit','cold'));p.add_argument('arrays',type=Path);p.add_argument('runs',type=Path);p.add_argument('rung',type=int)
    p.add_argument('--arm',choices=ARMS);p.add_argument('--seed',type=int);p.add_argument('--out',type=Path)
    a=p.parse_args();torch.set_num_threads(1);torch.set_num_interop_threads(1)
    if a.mode=='fit':fit(a.arrays,a.runs,a.arm,a.seed,a.rung)
    else:cold(a.arrays,a.runs,a.out,a.rung)
