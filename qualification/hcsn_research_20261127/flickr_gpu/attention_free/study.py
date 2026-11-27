"""Fit from scratch at a strict common wall budget, or cold-score one immutable candidate."""
from pathlib import Path
import argparse
import copy
import hashlib
import json
import os
import resource
import sys
import time

START=time.monotonic()
SRC=Path(__file__).resolve().parent
ROOT=Path(os.environ.get('HEPTA_FLICKR_ROOT',SRC.parents[1]))
sys.path.insert(0,str(SRC))
from free_boundary_decoder import ARMS,Captioner
import numpy as np
import torch
from torch.nn import functional as F
from panel import Samples,score

BASE=ROOT/'attention_free'
RESULT=BASE/'results'
SEEDS=(17011,24203,39827)
BUDGET=300


def sha(p):
    with p.open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()


def sources():
    return {k:sha(SRC/k) for k in ('PROTOCOL.md','free_boundary_decoder.py','study.py','cohort.py','qualify.py','run.py')}


def write(p,v):
    t=p.with_name(p.name+'.part');t.write_text(json.dumps(v,sort_keys=True,indent=2,allow_nan=False));t.replace(p)


def state_identity(model,common=False):
    h=hashlib.sha256()
    for k,v in model.state_dict().items():
        if common and (k.startswith('mixers.') or k.startswith('last_mark.')):continue
        h.update(k.encode()+b'\0');h.update(v.detach().cpu().numpy().tobytes())
    return h.hexdigest()


def fit(arm,seed):
    out=RESULT/f'{arm}-{seed}';out.mkdir(exist_ok=True,parents=True)
    if (out/'fit.json').exists():
        j=json.loads((out/'fit.json').read_text());assert sha(out/'selected.pt')==j['selected']
        return
    m=json.loads((ROOT/'data/manifest.json').read_text())
    assert sha(ROOT/'data/manifest.json')=='ba7083f60f12be990ede3f9a60f04524aa81228989bf6384f1684f225c26dd1e'
    tr=Samples(ROOT/'data','train',m);dv=Samples(ROOT/'data','validation',m)
    ix=np.asarray(sorted(range(len(dv.pix)),key=lambda i:hashlib.sha256(b'flickr-caption-prereg-128'+bytes(dv.ids[i])).digest())[:128])
    model=Captioner(arm,seed)
    opt=torch.optim.AdamW(model.parameters(),lr=.0005,weight_decay=.01)
    rng=np.random.default_rng(seed)
    r=dict(arm=arm,seed=seed,source=sources(),initial=state_identity(model),common_initial=state_identity(model,True),
         params=sum(p.numel() for p in model.parameters()),vocab=3490,device='cpu',torch=str(torch.__version__),
         train_images=len(tr.pix),dev_images=len(ix),torch_threads=torch.get_num_threads(),
         development_ids_sha256=hashlib.sha256(dv.ids[ix].tobytes()).hexdigest(),history=[])
    r['setup_seconds']=time.monotonic()-START
    best=float('inf');selected=None;step=0;tokens=0;train_seconds=0.;start=time.monotonic();t_cpu=time.process_time()
    for t in (0,35,110,235,BUDGET):
        model.train()
        tick=time.monotonic()
        while time.monotonic()-start<t:
            imgs=rng.integers(len(tr.pix),size=32);cs=rng.integers(5,size=32)
            im,tx=tr.batch(imgs,cs,torch.device('cpu'))
            y=tx[:,1:];opt.zero_grad(set_to_none=True)
            logits=model(im,tx[:,:-1])
            loss=F.cross_entropy(logits.transpose(1,2),y,ignore_index=0);loss.backward()
            norm=torch.nn.utils.clip_grad_norm_(model.parameters(),1)
            if not torch.isfinite(norm) or not torch.isfinite(loss):raise ValueError((arm,seed,step))
            opt.step();step+=1;tokens+=int(y.count_nonzero())
        train_seconds+=time.monotonic()-tick
        if t==BUDGET:break
        dvtime=time.monotonic()
        val,c=score(model,dv,ix,torch.device('cpu'))
        nll=float(val.sum()/c.sum())
        prospective=copy.deepcopy(model.state_dict()) if nll<best else None
        at=time.monotonic()-start
        r['history'].append(dict(requested=t,observed=at,dev_and_snapshot_seconds=time.monotonic()-dvtime,nll=nll,
                        steps=step,tokens=tokens,training_seconds=train_seconds,eligible=at<=BUDGET))
        if prospective is not None and at<=BUDGET:
            selected=prospective;best=nll;r['best_step']=step;r['best_seconds']=at
    assert selected is not None
    r.update(final_steps=step,final_tokens=tokens,train_seconds=train_seconds,
        combined_wall=time.monotonic()-start,combined_cpu=time.process_time()-t_cpu,best_nll=best)
    t=out/'selected.part';torch.save(selected,t);t.replace(out/'selected.pt')
    r['selected']=sha(out/'selected.pt');r['child_wall_seconds']=time.monotonic()-START
    r['child_cpu_seconds']=time.process_time();r['peak_rss_kib']=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    write(out/'fit.json',r);print('fit',arm,seed,step,best,flush=True)


def test(arm,seed):
    name=f'{arm}-{seed}';out=RESULT/name
    seal=json.loads((RESULT/'seal.json').read_text())
    assert len(seal['states'])==len(ARMS)*len(SEEDS) and seal['states'][name]==sha(out/'selected.pt')
    assert seal['source']==sources() and seal['external_manifest']==sha(BASE/'external/manifest.json')
    if (out/'test.json').exists():
        assert sha(out/'external.npz')==json.loads((out/'test.json').read_text())['scores'];return
    external=json.loads((BASE/'external/manifest.json').read_text())
    assert external['arrays_sha256']==sha(BASE/'external/external.npz')
    with np.load(BASE/'external/external.npz') as a:
        data=Samples.__new__(Samples);data.pix=a['images'];data.cap=a['tokens'];ids=a['ids']
    model=Captioner(arm,seed);model.load_state_dict(torch.load(out/'selected.pt',weights_only=True));model.eval()
    ix=np.arange(len(data.pix))
    l,n=score(model,data,ix,torch.device('cpu'));s,n2=score(model,data,ix,torch.device('cpu'),True)
    assert np.array_equal(n,n2)
    np.savez_compressed(out/'external.npz',paired=l,shifted=s,counts=n,ids=ids)
    r=dict(nll=float(l.sum()/n.sum()),shift_penalty=float((s-l).sum()/n.sum()),images=len(ix),tokens=int(n.sum()),
        selected=seal['states'][name],scores=sha(out/'external.npz'),child_wall_seconds=time.monotonic()-START,
        child_cpu_seconds=time.process_time(),peak_rss_kib=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
    write(out/'test.json',r);print('test',arm,seed,r['nll'],flush=True)


def main():
    p=argparse.ArgumentParser();p.add_argument('mode',choices=('fit','test'));p.add_argument('arm',choices=ARMS);p.add_argument('seed',type=int,choices=SEEDS)
    a=p.parse_args();torch.set_num_threads(1);torch.set_num_interop_threads(1)
    (fit if a.mode=='fit' else test)(a.arm,a.seed)


if __name__=='__main__':main()
