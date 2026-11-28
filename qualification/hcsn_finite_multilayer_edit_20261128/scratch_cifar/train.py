"""Train real from-scratch models at matched nested single-core CPU budgets."""
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
from cifar_net import Examples,Net,intercept,raw_view
from cifar_local import local_fit


BUDGETS=(30,120,600,1800)
TEMPERATURES=(.5,1,4,16,64)


class Deadline(Exception):
    pass


def write(file,value):
    tmp=file.with_suffix('.pending')
    tmp.write_text(json.dumps(value,indent=1,allow_nan=False)+'\n')
    tmp.replace(file)


def sha(p):
    with p.open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()


def trainable(net,raw):
    if raw is not None:return {'raw':raw.detach().numpy(),'temperature':net.temperature.detach().numpy()}
    return dict({f'w{i}':w.detach().numpy() for i,w in enumerate(net.w)},
                head=net.head.detach().numpy(),temperature=net.temperature.detach().numpy())


def metrics(logits,labels,coarse,children,temperature):
    z=logits*temperature
    fine=(z.argmax(-1)==labels).float().mean().item()
    coarse_acc=((z.softmax(-1)@children).argmax(-1)==coarse).float().mean().item()
    nll=F.cross_entropy(z,labels).item()
    return [fine,coarse_acc,nll]


@torch.no_grad()
def evaluate(net,data,raw):
    allz=[]
    for s in range(0,len(data.y),64):
        x,_,_=data.batch(np.arange(s,min(s+64,len(data.y))))
        logits=net(x)/net.temperature if raw is None else intercept(raw_view(x))@raw
        allz.append(logits)
    z=torch.cat(allz);y=torch.from_numpy(data.y);c=torch.from_numpy(data.c);children=torch.from_numpy(data.children)
    vals=[metrics(z,y,c,children,t) for t in TEMPERATURES]
    i=min(range(len(vals)),key=lambda j:vals[j][2])
    return vals[i],TEMPERATURES[i]


def ranked(values):
    return (values[0],values[1],-values[2])


def fit(a):
    torch.set_num_threads(1)
    dest=a.out/f'{a.kind}-{a.seed}-{a.method}';dest.mkdir(exist_ok=True,parents=True)
    result=dest/'result.json'
    if result.exists():return
    wall=time.perf_counter();cpu=time.process_time()
    train=Examples(a.data,'train');dev=Examples(a.data,'dev')
    net=Net(a.law,a.kind,a.seed);init={f'w{i}':w.detach().clone() for i,w in enumerate(net.w)}
    init['head']=net.head.detach().clone()
    steps=0;seen=0;bounds={};trace=[];top=None
    def clock():
        return time.process_time()-cpu,time.perf_counter()-wall
    def check():
        c,w=clock()
        for b in BUDGETS:
            if c>=b and b not in bounds:bounds[b]=[c,w]
        if c>=BUDGETS[-1]:raise Deadline()
    def observe(model,raw,detail):
        nonlocal top
        v,temp=evaluate(model,dev,raw)
        model.temperature.fill_(temp)
        c,w=clock()
        row=dict(detail=detail,step=steps,samples=seen,valid=v,temperature=temp,cpu=c,wall=w,file=None,sha=None)
        if top is None or ranked(v)>top:
            path=dest/f'candidate-{len(trace)}.npz'
            np.savez_compressed(path,**trainable(model,raw))
            c,w=clock();row.update(file=path.name,sha=sha(path),cpu=c,wall=w)
            top=ranked(v)
        trace.append(row)
        write(dest/'live.json',dict(arch=a.kind,seed=a.seed,arm=a.method,clock=[c,w],trace=trace,bounds=bounds))
        print(a.kind,a.seed,a.method,detail,steps,round(c,2),v,flush=True)
    raw=torch.zeros(193,100) if a.method=='raw' else None
    observe(net,raw,{'initial':True})
    try:
        if a.method=='bp':
            models=[net,Net(a.law,a.kind,a.seed)]
            rates=(.001,.003)
            opts=[torch.optim.AdamW(m.parameters(),lr=rate,weight_decay=.001,foreach=False) for m,rate in zip(models,rates)]
            rng=np.random.default_rng(a.seed+428559);queue=rng.permutation(len(train.y));index=0
            marks=[7.,18.,44.,90.,165.,270.,415.,535.,700.,950.,1230.,1500.,1700.]
            while True:
                check()
                if index+64>len(queue):
                    queue=rng.permutation(len(train.y));index=0
                ids=queue[index:index+64];index+=64
                for model,opt,rate in zip(models,opts,rates):
                    x,y,_=train.batch(ids)
                    model.temperature.fill_(1.)
                    opt.zero_grad(set_to_none=True)
                    z=model(x);loss=F.cross_entropy(z,y);loss.backward()
                    torch.nn.utils.clip_grad_norm_(model.parameters(),3.)
                    opt.step();steps+=1;seen+=len(x)
                if marks and clock()[0]>=marks[0]:
                    marks.pop(0)
                    for model,rate in zip(models,rates):
                        observe(model,None,{'lr':rate,'valid_cycle':len(trace)})
        else:
            levels=(4,16,64,500)
            variants=((.01,1.),(.1,.5),(.001,1.5))
            if a.method in ('rf','raw'):variants=tuple((r,0.) for r in (.01,.1,.001))
            for level in levels:
                for reg,mix in variants:
                    check();model=Net(a.law,a.kind,a.seed)
                    ix=train.subset(level)
                    raw=local_fit(model,train,ix,a.method,reg,mix,check)
                    steps+=1;seen+=len(ix)
                    observe(model,raw,dict(examples=len(ix),per_class_cap=level,ridge=reg,label_gain=mix))
    except Deadline:
        pass
    c,w=clock()
    for b in BUDGETS:bounds.setdefault(b,[c,w])
    selected={};keep=set()
    for b in BUDGETS:
        regs=[r for r in trace if r['cpu']<=b]
        if not regs:
            selected[str(b)]={'choice':None,'bounds':bounds[b]};continue
        best=max(regs,key=lambda r:(*ranked(r['valid']),-r['cpu']))
        assert best['file']
        entry=dict(choice=dict(best),bounds=bounds[b])
        with np.load(dest/best['file']) as data:
            degree={}
            for k in data.files:
                if k=='temperature':continue
                v=torch.from_numpy(data[k].astype('float64'))
                update=v-init[k].double() if k in init else v
                degree[k]=dict(shape=list(v.shape),norm_delta=float(update.norm()),effective_rank=int(torch.linalg.matrix_rank(update).item()))
            entry['writes']=degree
        selected[str(b)]=entry;keep.add(best['file'])
    write(result,dict(arch=a.kind,seed=a.seed,method=a.method,picks=selected,trace=trace,steps=steps,total_nominal_sample_visits=seen,
        wall=w,cpu=c,affinity=sorted(os.sched_getaffinity(0)),peak_rss=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
        started_epoch=time.time()-w,finished_epoch=time.time(),data=sha(a.data/'data.json'),law=sha(a.law),parameter_count=sum(x.numel() for x in net.parameters())))
    for f in dest.glob('candidate-*.npz'):
        if f.name not in keep:f.unlink()


if __name__=='__main__':
    p=argparse.ArgumentParser()
    for n in ('data','law','out'):p.add_argument(n,type=Path)
    p.add_argument('kind',choices=('literal','smooth','dense'));p.add_argument('seed',type=int)
    p.add_argument('method',choices=('bp','boundary','fp','rf','raw','wrong'))
    fit(p.parse_args())
