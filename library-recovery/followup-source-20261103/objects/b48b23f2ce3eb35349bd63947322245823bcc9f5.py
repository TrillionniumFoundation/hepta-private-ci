#!/usr/bin/env python3
"""Reproducible synthetic qualification harness; NOT production or Laya evidence."""
import argparse, csv, hashlib, json, os, platform, random, statistics, time
from pathlib import Path
import numpy as np
import torch
from torch import nn

KINDS = ('linear','film','lowrank8','lowrank16','mlp','swiglu')

class Head(nn.Module):
    def __init__(self, kind, dim, width, budget):
        super().__init__(); self.kind=kind; self.dim=dim
        if kind=='linear': self.proj=nn.Linear(dim,width)
        elif kind=='film':
            self.gamma=nn.Parameter(torch.ones(dim)); self.beta=nn.Parameter(torch.zeros(dim)); self.proj=nn.Linear(dim,width)
        elif kind.startswith('lowrank'):
            rank=int(kind[len('lowrank'):]); self.base=nn.Linear(dim,width); self.down=nn.Linear(dim,rank,bias=False); self.up=nn.Linear(rank,width,bias=False)
        elif kind in ('mlp','swiglu'):
            mult=2 if kind=='swiglu' else 1
            hidden=max(1,int((budget-width)/(dim+width*mult+mult)))
            self.a=nn.Linear(dim,hidden)
            if kind=='swiglu': self.gate=nn.Linear(dim,hidden)
            self.out=nn.Linear(hidden,width)
        else: raise ValueError(kind)
    def forward(self,x):
        if self.kind=='linear': return self.proj(x)
        if self.kind=='film': return self.proj(x*self.gamma+self.beta)
        if self.kind.startswith('lowrank'): return self.base(x)+self.up(self.down(x))
        if self.kind=='swiglu': return self.out(torch.nn.functional.silu(self.gate(x))*self.a(x))
        return self.out(torch.nn.functional.gelu(self.a(x)))

def metrics(logits,y):
    probs=torch.softmax(logits.float(),dim=-1); conf,pred=probs.max(-1)
    acc=(pred==y).float().mean().item(); brier=((probs-torch.nn.functional.one_hot(y,logits.shape[-1]).float())**2).sum(-1).mean().item()
    ece=0.
    for k in range(10):
        lo=k/10; hi=(k+1)/10
        mask=(conf>=lo)&(conf<hi if k<9 else conf<=hi)
        if mask.any(): ece+=mask.float().mean().item()*abs((pred[mask]==y[mask]).float().mean().item()-conf[mask].mean().item())
    return {'accuracy':acc,'brier':brier,'ece':ece,'n':int(len(y))}

def cpu_rss():
    import resource
    return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss*1024 if platform.system()=='Linux' else None

def run_head(args,out):
    torch.set_num_threads(args.threads); torch.manual_seed(args.seed); np.random.seed(args.seed)
    # Frozen deterministic teacher; synthetic IID label data only, no claims about real tasks.
    g=torch.Generator().manual_seed(args.seed)
    teacher=torch.randn(args.dim,args.classes,generator=g)/args.dim**.5
    def sample(n,shift=0):
        x=torch.randn(n,args.dim,generator=g)+shift
        logits=x@teacher
        y=logits.argmax(-1)
        return x,y
    x,y=sample(args.samples); val,v_y=sample(args.validation); old_x,old_y=sample(args.validation)
    ood,ood_y=sample(args.validation,shift=0.8)
    rows=[]
    for budget in args.budgets:
        for kind in KINDS:
            torch.manual_seed(args.seed)
            model=Head(kind,args.dim,args.classes,budget)
            nparams=sum(p.numel() for p in model.parameters())
            # Avoid treating an over-budget architecture as a valid parameter-matched comparison.
            if nparams>budget: rows.append({'kind':kind,'budget':budget,'nparams':nparams,'status':'over_budget'});continue
            opt=torch.optim.AdamW(model.parameters(),lr=args.lr)
            t0=time.perf_counter(); before=metrics(model(old_x).detach(),old_y)
            for step in range(args.steps):
                idx=torch.randint(0,len(y),(min(args.batch,len(y)),),generator=g)
                loss=torch.nn.functional.cross_entropy(model(x[idx]),y[idx]); opt.zero_grad(); loss.backward(); opt.step()
            training=time.perf_counter()-t0
            with torch.inference_mode():
                val_met=metrics(model(val),v_y); ood_met=metrics(model(ood),ood_y)
                # Future-window proxy deliberately disjoint samples from same synthetic distribution.
                retention=metrics(model(old_x),old_y)
            rows.append({'kind':kind,'budget':budget,'nparams':nparams,'status':'synthetic_only',
                         'train_seconds':round(training,4),'train_loss':round(loss.item(),6),
                         'val_accuracy':val_met['accuracy'],'brier':val_met['brier'],'ece':val_met['ece'],
                         'ood_accuracy':ood_met['accuracy'],'old_before_accuracy':before['accuracy'],
                         'old_after_accuracy':retention['accuracy'], 'peak_rss_bytes':cpu_rss()})
    out.write_text(json.dumps({'metadata':meta(args),'warning':'SYNTHETIC ONLY. No Laya, independent evaluator, NDU, or production qualification.', 'results':rows},indent=2),encoding='utf8')
    print('head experiments:',len(rows),'records; output',out)

def run_stress(args,out):
    torch.set_num_threads(args.threads); torch.manual_seed(args.seed)
    # Structural capacity / shared-feature reuse test; not model backend throughput.
    rng=random.Random(args.seed); results=[]
    for cells in args.cells:
        for reuse in ('same','partial','distinct'):
            for active_ratio in (0.1,0.5,1.0):
                active=max(1,round(cells*active_ratio)); keys=max(1, 1 if reuse=='same' else (active//8 if reuse=='partial' else active))
                # Shared projection intentionally lightweight to avoid conflating synthetic timings with BERT.
                feature_bank=torch.randn(keys,args.dim); h=Head('film',args.dim,args.classes,args.budgets[0]); h.eval()
                cache={}; hits=0; requests=0; lat=[]; start=time.perf_counter()
                with torch.inference_mode():
                    for _ in range(args.rounds):
                        for c in range(active):
                            k=0 if reuse=='same' else (c%keys)
                            t0=time.perf_counter()
                            if k not in cache: cache[k]=feature_bank[k].clone()
                            else: hits+=1
                            _=h(cache[k].unsqueeze(0));lat.append((time.perf_counter()-t0)*1e6);requests+=1
                elapsed=time.perf_counter()-start
                lat.sort(); percentile=lambda p:lat[min(len(lat)-1,max(0,int(np.ceil(p*len(lat))-1)))]
                results.append({'cells':cells,'active':active,'reuse':reuse,'requests':requests,
                    'hit_ratio':hits/requests,'throughput_rps':requests/elapsed,'p50_us':percentile(.5),
                    'p95_us':percentile(.95),'p99_us':percentile(.99),'peak_rss_bytes':cpu_rss(),
                    'cache_tensors':len(cache),'head_params':sum(p.numel() for p in h.parameters()),
                    'status':'synthetic_kernel_not_real_encoder'})
                print('stress',cells,reuse,active,round(requests/elapsed,1),'rps')
    out.write_text(json.dumps({'metadata':meta(args),'warning':'SYNTHETIC ONLY. Timings are CPU Python overhead + toy Head, NOT Hepta production or real encoder.', 'results':results},indent=2),encoding='utf8')

def meta(args):
    return {'seed':args.seed,'python':platform.python_version(),'torch':torch.__version__, 'device':'cpu', 'args':vars(args)}

def gate(args,out):
    # Fail closed; never represent synthetic measurements as genuine model evidence.
    required=['model_digest','dataset_digest','split_manifest_digest','hardware_id','baseline_receipt','evaluator_receipt','ndu_receipt','future_window_receipt','negative_transfer_receipt','recovery_receipt']
    evidence={}
    if args.evidence:
        evidence=json.loads(Path(args.evidence).read_text())
    missing=[key for key in required if not isinstance(evidence.get(key),str) or len(evidence[key].strip())<12]
    # Hash format / signed receipt validation must be done by independent owners, not this tool.
    report={'gate':'BLOCKED','missing_or_incomplete':missing,'reason':'No independent signed verification available in this standalone harness',
            'required':required,'warning':'Presence of field strings never passes production gate.'}
    out.write_text(json.dumps(report,indent=2));print(json.dumps(report,indent=2))

def main():
    p=argparse.ArgumentParser();p.add_argument('mode',choices=['head','stress','gate']);p.add_argument('--output',default=None)
    p.add_argument('--seed',type=int,default=42);p.add_argument('--dim',type=int,default=256);p.add_argument('--classes',type=int,default=4)
    p.add_argument('--samples',type=int,default=2048);p.add_argument('--validation',type=int,default=512)
    p.add_argument('--steps',type=int,default=40);p.add_argument('--batch',type=int,default=64);p.add_argument('--lr',type=float,default=1e-3)
    p.add_argument('--budgets',type=int,nargs='+',default=[2048,16384,65536,262144]);p.add_argument('--cells',type=int,nargs='+',default=[64,256,1024,4096]);p.add_argument('--rounds',type=int,default=2);p.add_argument('--threads',type=int,default=1)
    p.add_argument('--evidence',default=None)
    a=p.parse_args();out=Path(a.output or f'{a.mode}_result.json');out.parent.mkdir(parents=True,exist_ok=True)
    if a.mode=='head':run_head(a,out)
    elif a.mode=='stress':run_stress(a,out)
    else:gate(a,out)
if __name__=='__main__':main()
