"""Direct versus marginal initialization on identical differentiable He–Xiong towers."""
import argparse
from pathlib import Path
import time
import json
import numpy as np
import torch
from torch import nn

from study import ROOT, SEEDS, setup_data, gallery, score, sha, atomic, encode
from common import CCA, lex, unit
from construct import fit, first_out, deeper
from neural import PhysicalTower, masked_infonce
from adam import Adam

def random_side(R,rank,g):
    m=R.mean(0,dtype=np.float64).astype(np.float32)
    w=g.standard_normal((R.shape[1],rank),dtype=np.float32)
    w/=np.maximum(((R-m)@w).std(0),1e-6)
    return m,w

def make_init(kind,V,d,tr,z,seed):
    if kind=="warm":return fit(V,d,tr,"literal",24,.1,seed,z)
    g=np.random.default_rng(seed);first=CCA();second=CCA();head=CCA()
    for side,raw in [("x",np.asarray(V[tr])),("y",lex(d["tokens"][tr]))]:
        m,w=random_side(raw,24,g);setattr(first,"m"+side,m);setattr(first,"w"+side,w)
        a=np.concatenate([first_out(V[tr[i:i+256]],d["tokens"][tr[i:i+256]],first,side,z,"literal") for i in range(0,len(tr),256)])
        m,w=random_side(a,24,g);setattr(second,"m"+side,m);setattr(second,"w"+side,w)
        b=np.concatenate([deeper(a[i:i+256],second,side,z,"literal") for i in range(0,len(a),256)])
        m,w=random_side(b,24,g);setattr(head,"m"+side,m);setattr(head,"w"+side,w)
    return dict(first=first,second=second,head=head)
class Tower(nn.Module):
    flow=PhysicalTower.flow
    def __init__(self,side,models,z):
        super().__init__();self.side=side;self.k=float(z["k"])
        self.register_buffer("values",torch.from_numpy(z["fields"]))
        self.register_buffer("center",torch.from_numpy(z["center"]))
        self.weights=nn.ParameterList([])
        for j,key in enumerate(("first","second","head")):
            layer=models[key]
            self.register_buffer("mean"+str(j),torch.from_numpy(getattr(layer,"m"+side)))
            self.weights.append(nn.Parameter(torch.from_numpy(getattr(layer,"w"+side)).clone()))
    def cumulative(self,A,W):
        return torch.einsum("btd,tdr->btr",A.reshape(A.shape[0],4,-1),W.reshape(4,-1,W.shape[1])).cumsum(1)
    def forward(self,A):
        centered=A-self.mean0
        u=self.cumulative(centered,self.weights[0]) if self.side=="x" else centered@self.weights[0]
        q=self.flow(u)[...,0].flatten(1)
        b=self.flow(self.cumulative(q-self.mean1,self.weights[1])).flatten(1)
        return (b-self.mean2)@self.weights[2]

class Towers(nn.Module):
    def __init__(self,m,z):
        super().__init__();self.image=Tower("x",m,z);self.text=Tower("y",m,z)
    def forward(self,x,y):return self.image(x),self.text(y)

def inputs(d,V,ix):
    return torch.tensor(V[ix]),torch.from_numpy(np.stack([lex(d['tokens'][ix],j) for j in [4,8,12,16]],axis=1))
def embeddings(model,d,V,ix):
    l=[];r=[]
    with torch.no_grad():
        for j in range(0,len(ix),96):
            x,y=model(*inputs(d,V,ix[j:j+96]));l.append(x.numpy());r.append(y.numpy())
    return np.concatenate(l),np.concatenate(r)

def run(kind,seed):
    start=time.perf_counter();torch.set_num_threads(1);out=ROOT/"warm"/(kind+"-"+str(seed))
    out.mkdir(parents=True,exist_ok=True)
    d,V=setup_data();tr=np.flatnonzero(d["split"]==0);dv=gallery(d,1)
    with np.load(ROOT/"law.npz") as f:z=dict(f)
    ztime=time.perf_counter();m=make_init(kind,V,d,tr,z,seed);init_s=time.perf_counter()-ztime
    nets=[Towers(m,z) for _ in range(2)]
    check=tr[:24];expected=encode(V,d,check,m,"literal",z)
    got=embeddings(nets[0],d,V,check)
    error=max(float(abs(unit(x)-unit(y)).max()) for x,y in zip(expected,got))
    if error>3e-4:raise RuntimeError(f"initialization replay discrepancy {error}")
    rates=[.0003,.001];opts=[Adam(net.parameters(),lr,weight_decay=.001) for net,lr in zip(nets,rates)]
    gens=[np.random.default_rng(seed),np.random.default_rng(seed)];steps=[0,0];hist=[];best=None
    order=([0,1] if SEEDS.index(seed)%2==0 else [1,0]);data_sha=sha(ROOT/"prepared.json")
    def evaluate(i):
        nonlocal best
        arr=embeddings(nets[i],d,V,dv);met,_=score(*arr,d,dv);qual=(met["strict_R1"],met["strict_R5"])
        row={"step":steps[i],"lr":rates[i],"dev_r1":qual[0],"dev_r5":qual[1],"state":None}
        if best is None or qual>best:
            checkpoint=out/f'lr{i}-s{steps[i]}.pt';torch.save(nets[i].state_dict(),checkpoint);row["state"]=checkpoint.name;row["sha256"]=sha(checkpoint);best=qual
        row["time"]=time.perf_counter()-start;hist.append(row);atomic(out/"history.json",hist)
    for i in order:evaluate(i)
    while time.perf_counter()-start<60:
        for i in order:
            if time.perf_counter()-start>=60:break
            for _ in range(8):
                ix=gens[i].choice(tr,64,replace=False);opts[i].zero_grad()
                x,y=nets[i](*inputs(d,V,ix));loss=masked_infonce(x,y,torch.tensor(d["title"][ix]));loss.backward();opts[i].step();steps[i]+=1
            evaluate(i)
    atomic(out/"complete.json",dict(elapsed=time.perf_counter()-start,seed=seed,kind=kind,initialization_seconds=init_s,zero_replay_max_error=error,steps=steps,input_sha=data_sha))

def seal():
    selected={}
    for k in ('warm','marginal'):
        for seed in SEEDS:
            out=ROOT/"warm"/f'{k}-{seed}'
            if not (out/"complete.json").exists():raise RuntimeError('fit incomplete')
            hist=json.loads((out/"history.json").read_text())
            for b in (0,12,60):
                q=[r for r in hist if r["state"] and (r["time"]<=b if b else r["step"]==0)]
                if q:
                    row=max(q,key=lambda r:(r["dev_r1"],r["dev_r5"],-r["time"]))
                    assert sha(out/row["state"])==row["sha256"];selected[f"{k}/{seed}/{b}"]=row
    atomic(ROOT/"warm"/"seal.json",selected)

def confirm():
    torch.set_num_threads(1);d,V=setup_data();ix=gallery(d,2);tr=np.flatnonzero(d['split']==0)
    with np.load(ROOT/"law.npz") as f:z=dict(f)
    base=make_init("warm",V,d,tr,z,109);cache={};ranks={};scores={}
    selections=json.loads((ROOT/"warm"/"seal.json").read_text())
    for name,row in selections.items():
        k,seed,b=name.split("/");out=ROOT/"warm"/f'{k}-{seed}';path=out/row["state"];h=sha(path);assert h==row["sha256"]
        if h not in cache:
            net=Towers(base,z);net.load_state_dict(torch.load(path,map_location="cpu",weights_only=True));I,T=embeddings(net,d,V,ix);met,r=score(I,T,d,ix);cache[h]=met,np.stack(list(r.values())).astype(np.int16)
        scores[name],ranks[name]=cache[h]
    p=ROOT/"warm"/"cold_ranks.npz";np.savez_compressed(p,**ranks)
    with np.load(ROOT/"short"/"cold_ranks.npz") as base:
        intervals={}
        for label,a,b,budget in [('warm_zero','warm','warm',0),('warm_marginal','warm','marginal',60),('warm_conventional','warm','conventional',60)]:
            if a=="warm" and b=="conventional":
                y=[base[f"conventional/{s}/60"] for s in SEEDS]
            else:y=[ranks[f"{b}/{s}/{budget}"] for s in SEEDS]
            x=[ranks[f'{a}/{s}/60'] for s in SEEDS]
            dlt=np.mean([((u[:,:,0]==1).astype(float)-(v[:,:,0]==1)).mean(0) for u,v in zip(x,y)],0)
            g=np.random.default_rng(220711);a0=np.concatenate([dlt[g.integers(len(ix),size=(100,len(ix)))].mean(1) for _ in range(80)])
            intervals[label]={"estimate":float(dlt.mean()),"paired95":np.quantile(a0,[.025,.975]).tolist()}
    atomic(ROOT/"warm"/"results.json",{"scores":scores,"paired":intervals,"rank_sha":sha(p),"seal_sha":sha(ROOT/'warm'/'seal.json')})
if __name__=="__main__":
    p=argparse.ArgumentParser();p.add_argument("action",choices=['fit','seal','confirm']);p.add_argument("kind",nargs="?");p.add_argument("seed",nargs="?",type=int);a=p.parse_args()
    if a.action=='fit':run(a.kind,a.seed)
    elif a.action=='seal':seal()
    else:confirm()
