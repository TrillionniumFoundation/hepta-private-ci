"""Train the same two literal layers and a temporal-convolution comparator by full BP."""
import argparse
from pathlib import Path
import numpy as np
import torch
from torch import nn
from adam import Adam
from torch.nn import functional as F
from common import trdata,calibrate,better,record,usage,sha,WIDTH


class Table(nn.Module):
    def __init__(self,lut):
        super().__init__()
        self.register_buffer('lut',torch.as_tensor(lut))
    def forward(self,v):
        u=((v+12)*((len(self.lut)-1)/24)).clamp(0,len(self.lut)-1)
        a=u.long()
        z=self.lut[a]+(u-a)[...,None]*(self.lut[(a+1).clamp_max(len(self.lut)-1)]-self.lut[a])
        return z.flatten(start_dim=-2)


class Physical(nn.Module):
    def __init__(self,lut,ncls):
        super().__init__()
        self.gate=Table(lut);self.h1=nn.Linear(56,WIDTH);self.h2=nn.Linear(2*WIDTH,WIDTH)
        self.readout=nn.Linear(12*WIDTH,ncls)
    def forward(self,x):
        h=self.gate(self.h1(x));h=self.gate(self.h2(h))
        return self.readout(h.reshape(len(x),6,2,-1).mean(2).flatten(1))
    def export(self):
        def a(t):return t.detach().cpu().numpy().copy()
        return dict(kind=np.array('physical'),w1=a(self.h1.weight.T),b1=a(self.h1.bias),
                    w2=a(self.h2.weight.T),b2=a(self.h2.bias),head=a(self.readout.weight.T),head_bias=a(self.readout.bias))


class Conv(nn.Module):
    def __init__(self,ncls):
        super().__init__()
        self.c1=nn.Conv1d(56,48,3,padding=1);self.c2=nn.Conv1d(48,48,3,padding=1);self.out=nn.Linear(6*48,ncls)
    def forward(self,x):
        h=F.gelu(self.c1(x.transpose(1,2)));h=F.gelu(self.c2(h))
        return self.out(h.transpose(1,2).reshape(len(x),6,2,-1).mean(2).flatten(1))
    def export(self):
        state={k:t.detach().cpu().numpy().copy() for k,t in self.state_dict().items()}
        state['kind']=np.array('conv')
        return state


def main():
    ap=argparse.ArgumentParser();ap.add_argument('--data',type=Path,required=True);ap.add_argument('--out',type=Path,required=True)
    ap.add_argument('--arm',choices=['physical','conv','english'],required=True);ap.add_argument('--seed',type=int,required=True)
    a=ap.parse_args()
    torch.set_num_threads(1);torch.set_num_interop_threads(1)
    (x,y,p),(xd,yd,pd),center,scale=trdata(a.data,a.arm)
    ncls=10 if a.arm=='english' else 20
    x=torch.from_numpy(x);y=torch.from_numpy(y);xd=torch.from_numpy(xd)
    lut=np.load(a.data/'law.npz')['lut']
    best=None;log=[]
    for lr in (.001,.003):
        torch.manual_seed(a.seed)
        model=Conv(ncls) if a.arm=='conv' else Physical(lut,ncls)
        opt=Adam(model.parameters(),lr=lr,weight_decay=.001)
        rng=np.random.default_rng(a.seed+19001)
        for step in range(385):
            if step%96==0:
                with torch.no_grad():
                    scores=torch.cat([model(xd[i:i+192]) for i in range(0,len(xd),192)]).numpy()
                dev,t=calibrate(scores,yd,pd)
                candidate={'dev':dev,'temperature':t,'lr':lr,'step':step}
                log.append(candidate)
                if better(best,candidate):
                    best=candidate
                    state={**model.export(),'center':center,'scale':scale,'temperature':np.array(t)}
            if step==384:break
            rows=rng.integers(0,len(x),size=96)
            loss=F.cross_entropy(model(x[rows]),y[rows]);opt.zero_grad();loss.backward()
            opt.step()
    a.out.mkdir(parents=True,exist_ok=True);path=a.out/'selected.npz';np.savez_compressed(path,**state)
    record(a.out/'fit.json',dict(arm=a.arm,seed=a.seed,best=best,roster=log,checkpoint=sha(path),
          nrecords=len(x),dev_n=len(xd),test_label_access=False,**usage()))
    print(a.arm,a.seed,best['dev']['speaker_acc'],flush=True)
if __name__=='__main__':main()
