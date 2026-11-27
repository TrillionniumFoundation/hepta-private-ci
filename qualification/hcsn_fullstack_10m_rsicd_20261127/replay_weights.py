"""Restore a sealed CPU checkpoint from raw pixels, initial seed and its exact update count."""
import argparse,hashlib,sys
from pathlib import Path
import numpy as np
import torch
from torch.nn import functional as F
from study import Data,ROOT,net,sha

def restore(arm,seed,steps,to):
    d=Data();model=net(arm,seed,d);opt=torch.optim.AdamW(model.parameters(),lr=.0005,weight_decay=.01,foreach=False);rng=np.random.default_rng(seed)
    for _ in range(steps):
        ix=rng.choice(d.index['train'],size=8,replace=False);pix,t,y=d.batch(ix);opt.zero_grad(set_to_none=True);out=model(pix,t)
        F.cross_entropy(out.flatten(0,1),y.flatten(),ignore_index=0).backward();torch.nn.utils.clip_grad_norm_(model.parameters(),1);opt.step()
    to.mkdir(parents=True,exist_ok=True);path=to/f's{steps}.pt';tmp=path.with_suffix('.tmp');torch.save(model.state_dict(),tmp);tmp.replace(path)
    return path,sha(path)
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('arm');p.add_argument('seed',type=int);p.add_argument('steps',type=int);p.add_argument('destination',type=Path);p.add_argument('--expected');a=p.parse_args();path,digest=restore(a.arm,a.seed,a.steps,a.destination);print(path,digest);assert a.expected is None or digest==a.expected
