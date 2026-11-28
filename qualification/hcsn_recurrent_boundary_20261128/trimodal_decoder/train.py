"""Train shared conditional decoders on every acoustic, visual and word target."""
from argparse import ArgumentParser
from hashlib import sha256
import json
from pathlib import Path
import time
import numpy as np
import torch
import torch.nn.functional as F
from data import streams,START
from network import architecture
ARMS=("financial","smooth","lif","sdpa_matched","sdpa_width")
SEEDS=(137,311,557)
BATCH=96


def evaluate(net,x,y,idx,modes,cut=False):
    z=[];p=[]
    with torch.no_grad():
        for b in torch.as_tensor(idx).split(BATCH):
            scores=net(x[b],cut=cut)[:,START:].log_softmax(-1)
            t=y[b];valid=t!=-100
            prob=scores.gather(-1,t.clamp_min(0).unsqueeze(-1)).squeeze(-1)
            z.append(torch.where(valid,prob,0).cpu().numpy())
            p.append(scores.argmax(-1).cpu().numpy().astype("int16"))
    logp=np.concatenate(z);pred=np.concatenate(p);truth=y[idx].cpu().numpy()
    nll=[float(-logp[modes[idx]==i].sum(dtype='float64')/(truth[modes[idx]==i]!=-100).sum()) for i in range(3)]
    return nll,logp,pred


def train(folder,seed,kind):
    start=time.perf_counter();cpu0=time.process_time();x,y,splits,actors,modes,V,dicts=streams()
    tr,dev,held=splits
    net,d,err=architecture(V,kind,seed)
    begin_training=time.perf_counter()
    opt=torch.optim.AdamW(net.parameters(),lr=.002,weight_decay=.01)
    rng=torch.Generator().manual_seed(seed);steps=0;seen=0;target_count=0;active=0.;rows=[]
    active_cpu=0.
    key=f"{kind}-{seed}"
    while len({label for row in rows for label in row['labels']})<2:
        for batch in torch.as_tensor(tr)[torch.randperm(len(tr),generator=rng)].split(BATCH):
            since=time.perf_counter();cp=time.process_time()
            z=net(x[batch])[:,START:];t=y[batch]
            loss=F.cross_entropy(z.reshape(-1,V),t.flatten(),ignore_index=-100)
            opt.zero_grad(set_to_none=True);loss.backward()
            torch.nn.utils.clip_grad_norm_(net.parameters(),1.);opt.step()
            active_cpu+=time.process_time()-cp
            active+=time.perf_counter()-since
            seen+=len(batch);steps+=1;target_count+=int((t!=-100).sum())
            reached={label for row in rows for label in row['labels']}
            labels=[]
            if seen==len(tr) and 'epoch1' not in reached:labels.append('epoch1')
            if active>=60 and 'time60' not in reached:labels.append('time60')
            if labels:
                nll,values,pred=evaluate(net,x,y,dev,modes)
                print(key,labels,steps,seen,active,nll,flush=True)
                f=folder/(key+"-"+"-".join(labels)+".npz")
                np.savez_compressed(f,**{k:v.detach().cpu().numpy() for k,v in net.state_dict().items()})
                scores=folder/(f.stem+"-dev.npz");np.savez_compressed(scores,logp=values,pred=pred)
                rows.append(dict(labels=labels,steps=steps,examples=seen,targets=target_count,
                                 update_s=active,update_cpu=active_cpu,elapsed=time.perf_counter()-start,
                                 dev=nll,weights=f.name,sha256=sha256(f.read_bytes()).hexdigest(),
                                 dev_file=scores.name,dev_sha=sha256(scores.read_bytes()).hexdigest()))
            if len({label for row in rows for label in row['labels']})==2:break
    best=min(rows,key=lambda r:np.mean(r["dev"]))["weights"]
    j=dict(arm=kind,seed=seed,best=best,width=d,params=sum(p.numel() for p in net.parameters()),
           setup_s=begin_training-start,rows=rows,queue_time=time.perf_counter()-start,
           process_cpu=time.process_time()-cpu0,table_error=err,vocabulary=V,
           transcript_vocabulary=dicts,train_conditional=len(tr))
    (folder/(key+"-seal.json")).write_text(json.dumps(j,indent=2)+"\n")


if __name__=="__main__":
    p=ArgumentParser();p.add_argument("out",type=Path);p.add_argument("seed",type=int);p.add_argument("--arm",choices=ARMS)
    a=p.parse_args();a.out.mkdir(parents=True,exist_ok=True)
    torch.set_num_threads(1)
    order=SEEDS.index(a.seed)*2
    for k in ((a.arm,) if a.arm else ARMS[order:]+ARMS[:order]):
        if not (a.out/(f"{k}-{a.seed}-seal.json")).exists():train(a.out,a.seed,k)
