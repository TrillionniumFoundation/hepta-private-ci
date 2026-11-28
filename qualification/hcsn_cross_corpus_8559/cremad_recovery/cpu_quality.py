"""Independent one-thread full-width CREMA-D quality proof with no accelerator calls."""
import argparse
import fcntl
import hashlib
import json
import os
from pathlib import Path
import resource
import sys
import time

import numpy as np
import torch
from torch.nn import functional as F

ARMS=('literal','smooth','lif','sdpa')
SEED=137
EXPECTED_DATA='18423277257e2e487521d83a8c116bc7cf5599411f4ff769e569bd849beae6ad'


def sha(path):
    with path.open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()


def write(path,obj):
    tmp=path.with_suffix('.part');tmp.write_text(json.dumps(obj,indent=2)+'\n');os.replace(tmp,path)


def state(path,model):
    tmp=path.with_suffix('.part');torch.save(model.state_dict(),tmp);os.replace(tmp,path);return sha(path)


def yield_gpu_priority(parent):
    p=parent/'recovery-8559/progress.json';t=time.perf_counter()
    while p.exists() and json.loads(p.read_text()).get('state')=='executing':time.sleep(25)
    return time.perf_counter()-t


def build(parent,arm,n):
    from encoder import AVText
    return AVText(arm,4096,SEED,n,parent/'src/law4.npz').cpu()


class Data:
    def __init__(self,root):
        p=root/'data/data.npz';assert sha(p)==EXPECTED_DATA
        with np.load(p) as z:
            self.names=z['ids'];self.split=z['split'];self.v=torch.from_numpy(z['images']);a=z['audio'];tr=self.split==0
            mean=a[tr].mean((0,1),dtype=np.float64).astype(np.float32)
            sd=a[tr].std((0,1),dtype=np.float64).clip(.01).astype(np.float32)
            self.a=torch.from_numpy((a-mean)/sd);self.y=torch.from_numpy(z['labels']).long();self.tokens=torch.from_numpy(z['tokens']).long()
        self.n=int(self.tokens.max())+1
        self.tr=np.flatnonzero(self.split==0);self.dev=np.flatnonzero(self.split==1);self.test=np.flatnonzero(self.split==2)
        actors=sorted(set(x.split('_')[0] for x in self.names[self.dev]))
        def key(i):return hashlib.sha256(('crema-cpu-quality-8559|'+self.names[i]).encode()).hexdigest()
        self.panel=np.array([i for a in actors for i in sorted((i for i in self.dev if self.names[i].startswith(a+'_')),key=key)[:8]])
        assert len(self.panel)==112


@torch.no_grad()
def scores(model,d,rows,parent,variants=False):
    model.eval();chunks=[];paused=0.;t0=time.perf_counter()
    with torch.autocast('cpu',dtype=torch.bfloat16):
        for block in d.tokens.split(16):
            paused+=yield_gpu_priority(parent);chunks.append(model.encode(model.text(block)))
    texts=torch.cat(chunks).float();results={}
    other=rows.copy()
    for actor in sorted(set(x.split('_')[0] for x in d.names[rows])):
        ix=np.array([i for i,x in enumerate(d.names[rows]) if x.startswith(actor+'_')]);perm=np.random.default_rng(int(actor)+6312).permutation(ix);other[perm]=rows[np.roll(perm,1)]
    modes=('aligned','video_swapped','audio_swapped','both_swapped') if variants else ('aligned',)
    for mode in modes:
        values=[]
        for i in range(0,len(rows),16):
            paused+=yield_gpu_priority(parent);r=rows[i:i+16];o=other[i:i+16]
            with torch.autocast('cpu',dtype=torch.bfloat16):
                h=model.encode(model.front(d.v[o if mode in ('video_swapped','both_swapped') else r],d.a[o if mode in ('audio_swapped','both_swapped') else r]))
            values.append((12*(h.float()@texts.T)).numpy())
        results[mode]=np.concatenate(values)
    return results,{'elapsed_active_s':time.perf_counter()-t0-paused,'elapsed_paused_s':paused}


def save_scores(p,scoreset,d,rows):
    with p.with_suffix('.part').open('wb') as f:np.savez_compressed(f,**scoreset,ids=d.names[rows],labels=d.y[rows].numpy())
    os.replace(p.with_suffix('.part'),p)
    return {name:{'nll':float(F.cross_entropy(torch.from_numpy(logits),d.y[rows])),'top1':float((logits.argmax(1)==d.y[rows].numpy()).mean())} for name,logits in scoreset.items()}


def fit(parent,out,a,d):
    from encoder import pair_loss
    from run import probes
    cell=out/'fits'/a;cell.mkdir(exist_ok=True,parents=True)
    if (cell/'fit.json').exists():return
    start=time.perf_counter();cpu=time.process_time();torch.manual_seed(SEED);rng=np.random.default_rng(SEED+7369)
    model=build(parent,a,d.n);params=sum(x.numel() for x in model.parameters());assert params>10**9
    opt=torch.optim.AdamW(model.parameters(),lr=.0001,weight_decay=.01,foreach=False)
    init=probes(model);rows=[];checks=[];paused=0.
    # An interrupted partial run restarts from its original deterministic seed; preserve finished cells.
    for step in range(17):
        if step:
            paused+=yield_gpu_priority(parent);t0=time.perf_counter();c0=time.process_time();i=rng.choice(d.tr,16);labels=d.y[i]
            model.train();opt.zero_grad(set_to_none=True)
            with torch.autocast('cpu',dtype=torch.bfloat16):
                x,y=model(d.v[i],d.a[i],d.tokens[labels]);loss=pair_loss(x,y,labels)
            loss.backward();grad=torch.nn.utils.clip_grad_norm_(model.parameters(),1.)
            assert torch.isfinite(loss) and torch.isfinite(grad)
            opt.step();r={'step':step,'loss':float(loss.detach()),'grad_norm':float(grad),'cpu_s':time.process_time()-c0,'wall_active_s':time.perf_counter()-t0,'peak_rss_kib':resource.getrusage(resource.RUSAGE_SELF).ru_maxrss}
            if step==1:
                now=probes(model);r.update(trainable=params,grad_scalars=sum(p.numel() for p in model.parameters() if p.grad is not None),tensor_count=len(now),changed_probes=sum(not torch.equal(init[k],now[k]) for k in now))
            rows.append(r);write(cell/'steps.json',rows);print('step',a,step,r['loss'],r['wall_active_s'],flush=True)
        if step not in (0,4,16):continue
        panel,clock=scores(model,d,d.panel,parent);paused+=clock['elapsed_paused_s'];p=cell/f'panel-{step}.npz';res=save_scores(p,panel,d,d.panel)
        rec={'step':step,'panel':res,'times':clock,'panel_sha256':sha(p)}
        if step:
            wt=cell/f'weights-{step}.pt';rec['weights_sha256']=state(wt,model)
        if step==16:
            full,fullclock=scores(model,d,d.dev,parent);paused+=fullclock['elapsed_paused_s'];fp=cell/'full-dev-16.npz';rec['full_development']=save_scores(fp,full,d,d.dev);rec['full_dev_sha256']=sha(fp);rec['full_development_times']=fullclock
        checks.append(rec);write(cell/'observations.json',checks);print('dev',a,step,res,flush=True)
    best=min(checks[1:],key=lambda x:x['panel']['aligned']['nll'])
    write(cell/'fit.json',dict(arm=a,width=4096,seed=SEED,params=params,observations=checks,train_steps=rows,selected_step=best['step'],train_clips_seen=256,elapsed_wall_s=time.perf_counter()-start,active_wall_s=time.perf_counter()-start-paused,paused_wall_s=paused,cpu_s=time.process_time()-cpu,dev_nll_reduction=checks[0]['panel']['aligned']['nll']-checks[-1]['panel']['aligned']['nll']))


def main(parent,out,one):
    torch.set_num_threads(1);sys.path.insert(0,str(parent/'src'));out.mkdir(parents=True,exist_ok=True)
    d=Data(parent)
    if one:fit(parent,out,one,d);return
    import subprocess
    with (out/'task.lock').open('a') as owner:
        fcntl.flock(owner,fcntl.LOCK_EX|fcntl.LOCK_NB)
        for a in ARMS:
            # Each cold process releases Adam moments and all original graphs before initializing another arm.
            subprocess.run([sys.executable,'-u',__file__,str(parent),str(out),'--arm',a],check=True)
        frozen={}
        for a in ARMS:
            p=out/'fits'/a;v=json.loads((p/'fit.json').read_text());frozen[a]=sha(p/'fit.json')
            for obs in v['observations']:
                if obs['step']:assert sha(p/f"weights-{obs['step']}.pt")==obs['weights_sha256']
        if not (out/'seal.json').exists():write(out/'seal.json',{'fits':frozen,'data':EXPECTED_DATA,'source':sha(Path(__file__))})
        for a in ARMS:
            dest=out/'cold'/a;dest.mkdir(parents=True,exist_ok=True)
            if (dest/'result.json').exists():continue
            rec=json.loads((out/'fits'/a/'fit.json').read_text());model=build(parent,a,d.n);step=rec['selected_step']
            file=out/'fits'/a/f'weights-{step}.pt';model.load_state_dict(torch.load(file,map_location='cpu',weights_only=True,mmap=True))
            z,clock=scores(model,d,d.test,parent,variants=True);p=dest/'logits.npz';s=save_scores(p,z,d,d.test)
            write(dest/'result.json',dict(arm=a,step=step,metrics=s,times=clock,sha256=sha(p)));del model
        print('complete independent CPU panel',flush=True)


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('parent',type=Path);p.add_argument('out',type=Path);p.add_argument('--arm',choices=ARMS)
    a=p.parse_args();main(a.parent.resolve(),a.out.resolve(),a.arm)
