"""From-scratch inverse-boundary hidden supervision or full-backprop reference."""
from argparse import ArgumentParser
from hashlib import sha256
import json
from pathlib import Path
import sys
import time
import numpy as np
import torch
from model import Network,make_table,direct_layers
root=Path(__file__).resolve().parent
sys.path.insert(0,str(root.parent/"newton_readout"))
from fit_newton import regression,DATA
from fit import load_data,train_head,local_scores,digest
EPOCHS=(1,3,8,15,25)


def snap(net,out,key):
    f=out/(key+".npz")
    np.savez_compressed(f,**{k:v.detach().numpy() for k,v in net.state_dict().items()})
    return digest(f)


def run(out,seed,kind,method):
    start=time.perf_counter()
    x,y,actors,(tr,dev,held)=load_data(DATA)
    x=torch.tensor(x,dtype=torch.float32);yt=torch.from_numpy(y)
    table,gain,error=make_table(kind)
    torch.manual_seed(seed)
    net=Network(kind,table,gain)
    init={k:v.detach().clone() for k,v in net.named_parameters()}
    prefix=f"{kind}-{method}-{seed}"
    common=dict(seed=seed,kind=kind,method=method,gain=gain,table_max_abs=error)
    rows=[]
    def save(label):
        with torch.no_grad():z=net(x[dev]).numpy()
        l,acc=local_scores(z.astype(float),y[dev])
        key=f"{prefix}-{label}"
        delta={k:float(torch.linalg.vector_norm(v.detach()-init[k])) for k,v in net.named_parameters()}
        rows.append(dict(key=key,label=label,dev=float(l.mean()),acc=float(acc.mean()),
                         elapsed=time.perf_counter()-start,weights=snap(net,out,key),
                         dev_sha=sha256(z.tobytes()).hexdigest(),parameter_changes=delta))
    if method=="bp":
        optim=torch.optim.AdamW(net.parameters(),lr=.003,weight_decay=.001)
        order=torch.Generator().manual_seed(seed)
        for epoch in range(1,max(EPOCHS)+1):
            for batch in torch.as_tensor(tr)[torch.randperm(len(tr),generator=order)].split(128):
                z=net(x[batch])
                loss=torch.nn.functional.cross_entropy(z,yt[batch])
                optim.zero_grad(set_to_none=True);loss.backward();optim.step()
            if epoch in EPOCHS:save(str(epoch))
    else:
        common["hidden_writes"]=direct_layers(net,x,tr,yt,seed)
        with torch.no_grad():
            X=net.features(x[tr]).numpy().astype(float);V=net.features(x[dev]).numpy().astype(float)
        mean=X.mean(0);std=X.std(0).clip(.0001)
        X=(X-mean)/std;V=(V-mean)/std
        if method=="direct":
            _,W,b,cfg=train_head(X,y[tr],V,y[dev],"direct")
        else:
            (_,W,b,cfg,diag),_=regression(X,y[tr],V,y[dev],"five_kronecker")
            common["head_update"]=diag
        common["chosen_head_config"]=cfg
        W=W/std[:,None];b=b-mean@W
        with torch.no_grad():
            net.out.weight.copy_(torch.from_numpy(W.T));net.out.bias.copy_(torch.from_numpy(b))
        save("final")
    common["rows"]=rows;common["best"]=min(rows,key=lambda v:v["dev"])["key"]
    common["gate_first"]={str(t):next((r["key"] for r in rows if r["dev"]<=t),None) for t in (3.75,4.10)}
    common["fit_wall"]=time.perf_counter()-start
    fn=out/(prefix+"-seal.json");fn.write_text(json.dumps(common,indent=2)+"\n")
    print(prefix,common["fit_wall"],[round(r["dev"],4) for r in rows],flush=True)


if __name__=="__main__":
    p=ArgumentParser();p.add_argument("out",type=Path);p.add_argument("seed",type=int)
    a=p.parse_args();a.out.mkdir(parents=True,exist_ok=True)
    torch.set_num_threads(1)
    # Vary order by seed; each cell starts afresh and independently pays data and table costs.
    tasks=[(k,m) for k in ("financial","smooth","no_memory") for m in ("direct","five","bp") if (k,m)!=("no_memory","bp")]
    shift={137:0,311:3,557:5}[a.seed]
    for k,m in tasks[shift:]+tasks[:shift]:run(a.out,a.seed,k,m)
