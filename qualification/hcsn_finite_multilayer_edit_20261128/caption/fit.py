"""Fit two real sites by forward local solves, reverse gradient, low-rank BP, or a prior shift."""
import argparse
import hashlib
import time
from pathlib import Path

import numpy as np
import torch
from torch.nn import functional as F
from torch.nn.utils import parametrize
from caption_data import Panel,effective,joint_batch,load_net,nll,panels,read,score,sha,sites,write

ARMS=('tied','joint','flow','bp','lora','unigram','wrong')
RUNGS=(15,60,240)


class LowRank(torch.nn.Module):
    def __init__(self,weight,rank):
        super().__init__()
        self.a=torch.nn.Parameter(torch.randn(rank,weight.shape[1])*.02)
        self.b=torch.nn.Parameter(torch.zeros(weight.shape[0],rank))
    
    def forward(self,weight):
        return weight+self.b@self.a


def signed_bias(target,old,size):
    def frequency(y):
        counts=np.bincount(y[y!=0],minlength=size).astype(np.float64)+1
        return counts/counts.sum()
    value=np.log(frequency(target)/frequency(old))
    return torch.tensor(value,dtype=torch.float32)


def fit_proposal(features,residual,rel,weight_norm,fraction):
    h=features.double(); r=residual.double()
    gram=h.T@h/len(h)
    regularizer=rel*gram.diag().mean().clamp_min(1e-8)
    gram.diagonal().add_(regularizer)
    direction=torch.linalg.solve(gram,h.T@r/len(h)).T.to(features.dtype)
    scale=min(1,float(fraction*weight_norm/direction.norm().clamp_min(1e-12)))
    return direction*scale


@torch.no_grad()
def direct_step(net,batch,mode):
    pix,tokens,y=batch; word,physical=sites(net)
    taps={}
    def save_hidden(_,inputs,out):
        taps['h']=out
    def save_signal(_,inputs,out):
        taps['s']=inputs[0][:,4:]
    h1=net.final.register_forward_hook(save_hidden)
    h2=physical.register_forward_hook(save_signal)
    try:
        z=net(pix,tokens)
    finally:
        h1.remove();h2.remove()
    mask=y!=0; logits=z[mask];labels=y[mask]
    p=logits.softmax(-1)
    r=F.one_hot(labels,num_classes=logits.shape[-1]).to(p.dtype)-p
    # Approximate inverse softmax curvature by a bounded diagonal.
    adjusted=r/p.mean(0).clamp_min(.002).sqrt()
    d=[fit_proposal(taps['h'][mask],adjusted,.35,word.weight.norm(),.08)]
    if mode!='tied':
        d.append(fit_proposal(taps['s'][mask],adjusted@word.weight,.30,physical.weight.norm(),.08))
    params=[word.weight,physical.weight][:len(d)]
    base=[q.detach().clone() for q in params]
    def set_sites(coeff):
        for param,start,direction,c in zip(params,base,d,coeff):
            param.copy_(start+c*direction)
    def current_logits():
        return net(pix,tokens)[mask]
    if mode in ('flow','wrong'):
        columns=[]
        for k in range(len(d)):
            coeff=[0.]*len(d);coeff[k]=.04
            set_sites(coeff)
            columns.append((current_logits()-logits)/.04)
        j=torch.stack(columns,-1).double();p64=p.double()
        mu=(j*p64[...,None]).sum(1,keepdim=True)
        centered=j-mu
        gram=torch.einsum('nvi,nv,nvj->ij',centered,p64,centered)/len(j)
        gram.diagonal().add_(.01*gram.diag().mean().clamp_min(.0001))
        linear=torch.einsum('nv,nvi->i',r.double(),j)/len(j)
        steps=torch.linalg.solve(gram,linear).clamp(-2,2).tolist()
    else:
        steps=[1.]*len(d)
    before=F.cross_entropy(logits,labels).item()
    for scale in (1.,.5,.25):
        set_sites([c*scale for c in steps])
        if F.cross_entropy(current_logits(),labels).item()<before:
            return True
    set_sites([0.]*len(d))
    return False


def run(a):
    torch.set_num_threads(1)
    out=a.out/f'{a.arch}-{a.seed}';out.mkdir(exist_ok=True,parents=True)
    if (out/(a.arm+'.json')).exists():
        return
    init_w=time.perf_counter();init_c=time.process_time()
    net,parent=load_net(a.parents,a.arch,a.seed)
    data=panels(a.parents,a.fresh,False)
    words,phys=sites(net);bias=torch.zeros(words.weight.shape[0])
    cache=out/'parent.json'
    made_parent_eval=not cache.exists()
    if made_parent_eval:
        ws=time.perf_counter();cs=time.process_time()
        dn=nll(score(net,data['dev'],bias));do=nll(score(net,data['old_dev'],bias))
        write(cache,{'new':dn,'old':do,'wall':time.perf_counter()-ws,'cpu':time.process_time()-cs,
                     'parent_sha':parent['sha'],'source_train_wall':parent['parent_source_s']})
    base=read(cache)
    initial_loading=dict(wall=time.perf_counter()-init_w,cpu=time.process_time()-init_c)
    w0=time.perf_counter();c0=time.process_time()
    def clocks():
        return time.process_time()-c0,time.perf_counter()-w0
    rng=np.random.default_rng(38559+a.seed)
    torch.manual_seed(a.seed+593)
    model_sites=sites(net);opt=None
    if a.arm in ('bp','lora'):
        if a.arm=='lora':
            for site in model_sites:
                parametrize.register_parametrization(site,'weight',LowRank(site.weight,8))
            params=[v for site in model_sites for v in site.parameters() if v.requires_grad]
        else:
            params=[s.weight.requires_grad_(True) for s in model_sites]
        opt=torch.optim.AdamW(params,lr=.003 if a.arm=='lora' else .0003,weight_decay=.0,foreach=False)
    offset=signed_bias(data['train'].y,data['old_train'].y,len(bias)) if a.arm=='unigram' else None
    record=[dict(step=0,new=base['new'],old=base['old'],cpu=0.,wall=0.,file=None,sha=None)]
    best_seen=base['new'];steps=0;accepted=0;bounds={}
    def evaluate():
        nonlocal best_seen
        new=nll(score(net,data['dev'],bias));old=nll(score(net,data['old_dev'],bias))
        c,w=clocks()
        rec=dict(step=steps,new=new,old=old,cpu=c,wall=w,file=None,sha=None)
        if old<=base['old']+.03 and new<best_seen:
            path=out/f'{a.arm}-iteration{steps}.npz'
            weights=effective(net,bias)
            np.savez_compressed(path,W=weights[0].numpy(),P=weights[1].numpy(),b=weights[2].numpy())
            c,w=clocks()
            rec.update(cpu=c,wall=w,file=path.name,sha=sha(path))
            best_seen=new
        record.append(rec)
    schedule=[1.,7.,23.,47.,80.,135.,205.]
    factors=(.1,.25,.5,.75,1.)
    while clocks()[0]<RUNGS[-1]:
        if a.arm=='unigram':
            if steps==len(factors):
                break
            bias=offset*factors[steps]
        else:
            batch=joint_batch(data,rng,a.arm=='wrong')
            if opt is None:
                accepted+=int(direct_step(net,batch,a.arm))
            else:
                opt.zero_grad(set_to_none=True)
                pix,t,y=batch
                z=net(pix,t)
                loss=F.cross_entropy(z.flatten(0,1),y.flatten(),ignore_index=0)
                loss.backward()
                torch.nn.utils.clip_grad_norm_(params,1.0)
                opt.step()
        steps+=1;c,w=clocks()
        if a.arm=='unigram' or (schedule and c>=schedule[0]):
            evaluate();c,w=clocks()
            schedule=[s for s in schedule if s>c]
        for budget in RUNGS:
            if c>=budget and budget not in bounds:
                bounds[budget]=[c,w]
    final=clocks()
    if a.arm=='unigram':
        for b in RUNGS:bounds.setdefault(b,list(final))
    for b in RUNGS:bounds.setdefault(b,list(final))
    selected={}
    for b in RUNGS:
        eligible=[r for r in record if r['cpu']<=b and r['old']<=base['old']+.03]
        winner=min(eligible,key=lambda row:(row['new'],row['cpu']))
        selected[str(b)]=dict(choice=winner,actual_upper_cpu=bounds[b][0],actual_upper_wall=bounds[b][1])
    keep={p['choice']['file'] for p in selected.values()}
    for f in out.glob(a.arm+'-iteration*.npz'):
        if f.name not in keep:f.unlink()
    write(out/(a.arm+'.json'),dict(arch=a.arch,seed=a.seed,arm=a.arm,steps=steps,accepted_forward_steps=accepted,
        times=list(final),setup=initial_loading,setup_measured_parent_eval=made_parent_eval,parent=parent['sha'],site_shapes=[list(s.weight.shape) for s in model_sites],
        optimizer_coefficients=sum(p.numel() for p in params) if opt else None,picks=selected,trace=record))
    print(a.arch,a.seed,a.arm,steps,list(final),flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    for label in ('parents','fresh','out'):parser.add_argument(label,type=Path)
    parser.add_argument('arch');parser.add_argument('seed',type=int);parser.add_argument('arm',choices=ARMS)
    run(parser.parse_args())
