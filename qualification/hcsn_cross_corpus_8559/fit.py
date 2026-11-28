import argparse
import hashlib
import json
from pathlib import Path
import resource
import time

import numpy as np
import torch
from torch.nn import functional as F
from network import Encoder
from score import score_embeddings


def read_inputs(p):
    d=np.load(p)
    return (torch.from_numpy(d['images']),torch.from_numpy(d['tokens'].astype(np.int64)),d['groups'],d['split'],int(d['vocab']))

@torch.no_grad()
def embed(model,pix,tok,rows):
    model.eval()
    i,t=[],[]
    for select in np.array_split(rows,max(1,(len(rows)+63)//64)):
        a,b=model(pix[select],tok[select,0]);i.append(a.numpy());t.append(b.numpy())
    return np.concatenate(i),np.concatenate(t)

def run(work,law,arm,seed):
    torch.set_num_threads(1);torch.manual_seed(seed)
    prefix=work/'fits'/f'{arm}-{seed}';prefix.mkdir(exist_ok=True,parents=True)
    t0=time.perf_counter();c0=time.process_time()
    pix,tok,groups,splits,vocab=read_inputs(work/'input.npz')
    tr=np.flatnonzero(splits==0);dev=np.flatnonzero(splits==1)
    rng=np.random.default_rng(seed);model=Encoder(arm,seed,vocab,law)
    opt=torch.optim.AdamW(model.parameters(),lr=.001,weight_decay=.01)
    setup=time.perf_counter()-t0;measure=[];training=0.;dev_cost=0.;cstart=time.process_time();pre_mem=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    for step in range(1,513):
        a=time.perf_counter();model.train()
        rows=rng.choice(tr,32,replace=False);caps=(step+np.arange(32))%5
        x,y=model(pix[rows],tok[rows,caps]);z=15*(x@y.T)
        labels=torch.from_numpy(groups[rows,caps]);mask=labels[:,None].eq(labels[None,:]).to(z.dtype);p=mask/mask.sum(1,keepdim=True)
        loss=-.5*((p*z.log_softmax(1)).sum(1).mean()+(p*z.T.log_softmax(1)).sum(1).mean());opt.zero_grad();loss.backward();torch.nn.utils.clip_grad_norm_(model.parameters(),1);opt.step()
        training+=time.perf_counter()-a
        if step not in (32,128,512):continue
        a=time.perf_counter();im,txt=embed(model,pix,tok,dev);v=score_embeddings(im,txt,groups[dev,0])[:,:,0].mean()
        dev_cost+=time.perf_counter()-a
        path=prefix/f'{step}.pt';torch.save(model.state_dict(),path)
        measure.append(dict(step=step,dev_concordance=float(v),loss=float(loss.detach()),wall_s=time.perf_counter()-t0,cpu_s=time.process_time()-cstart,fit_wall_s=training,validation_wall_s=dev_cost,sha256=hashlib.sha256(path.read_bytes()).hexdigest()))
        (prefix/'trace.json').write_text(json.dumps(measure,indent=2)+'\n');print(arm,seed,step,v,round(measure[-1]['wall_s'],1),flush=True)
    best=max(measure,key=lambda r:r['dev_concordance'])
    clocks={str(b):max([r for r in measure if r['cpu_s']<=b],key=lambda r:r['dev_concordance'],default=None) for b in (10,40,120)}
    rec=dict(arm=arm,seed=seed,n_param=sum(p.numel() for p in model.parameters()),setup_s=setup,rungs=measure,selected=best['step'],budgets=clocks,peak_kib=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,total_wall_s=time.perf_counter()-t0,total_cpu_s=time.process_time()-c0)
    (prefix/'selected.json').write_text(json.dumps(rec,indent=2)+'\n')

if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('work',type=Path);ap.add_argument('law',type=Path);ap.add_argument('arm',choices=['literal','smooth','sdpa']);ap.add_argument('seed',type=int);a=ap.parse_args();run(a.work,a.law,a.arm,a.seed)
