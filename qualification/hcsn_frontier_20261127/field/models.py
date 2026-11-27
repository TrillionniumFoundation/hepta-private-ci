"""Budget-matched continuous margin, recurrent and attention encoders for metered loads."""
import math
import sys
from pathlib import Path

import numpy as np
import torch
from torch import nn
from torch.nn import functional as F


def make_table(core):
    sys.path.insert(0,str(Path(core).resolve()))
    from he_xiong import Published
    law=Published()
    x=torch.linspace(0,3,12289,dtype=torch.float64)
    p=law.p
    def price(x,rel):
        principal=torch.full_like(x,p.P0*(1+rel))
        def hit(y):
            s=p.sigma*math.sqrt(p.m)
            shift=y*law.var*p.m
            return torch.exp(-(law.a-y)*x)*torch.special.ndtr((-x-shift)/s)+torch.exp(-(law.a+y)*x)*torch.special.ndtr((-x+shift)/s)
        loss=law.disc*(principal/p.m-law.c/law.q)*hit(law.a)+(law.c/law.q-p.alpha*law.boundary(principal)/p.m)*hit(law.zb)
        return torch.stack([law.equity(x,principal)/20,loss/20],-1)
    center=price(x,0)
    slope=(price(x,.25)-price(x,-.25))*2
    grid=torch.cat([center,slope,law.move_mean(x)[:,None]],1)
    x0=torch.tensor([.18],dtype=x.dtype)
    eps=1e-5
    c=price(x0,0); q=(price(x0,.25)-price(x0,-.25))*2
    dc=(price(x0+eps,0)-price(x0-eps,0))/(2*eps)
    def dq(z):return (price(z,.25)-price(z,-.25))*2
    ds=(dq(x0+eps)-dq(x0-eps))/(2*eps)
    return tuple(t.float() for t in (grid,c,q,dc,ds)),law.bp*p.P0/law.B0


class PriceCell(nn.Module):
    def __init__(self,kind,w,table):
        super().__init__();self.kind=kind
        values,self.boundary_sensitivity=table
        for n,v in zip(('table','center','slope','jac','slope_jac'),values):
            self.register_buffer(n,v)
        self.drive=nn.Linear(11,w)
        self.rec=nn.Linear(w,w,bias=False)
        self.feedback=nn.Parameter(torch.full((w,2),.15))
        self.head=nn.Sequential(nn.Linear(3*w+8,w),nn.Tanh(),nn.Linear(w,3))

    def forward(self,seq,contract):
        batch,length,_=seq.shape; w=self.rec.out_features
        signal=self.drive(torch.cat([seq,contract[:,None].expand(-1,length,-1)],-1))
        b=signal.new_zeros(batch,w);m=b+.18; v=self.center.expand(batch,w,2)
        for force in signal.unbind(1):
            drive=force+self.rec(b)+(v.tanh()*self.feedback).sum(-1)+contract[:,1:2]*.30
            rel=.28*drive.tanh()
            newb=torch.log1p(self.boundary_sensitivity*rel)
            x=m+b-newb
            u=x.clamp(0,3)*4096
            i=u.long().clamp(max=12287)
            t=self.table[i]+(u-i)[...,None]*(self.table[i+1]-self.table[i])
            m=t[...,4]
            if self.kind=='literal':
                v=t[...,:2]+rel[...,None]*t[...,2:4]
            else:
                local=self.jac+rel[...,None]*self.slope_jac
                v=self.center+rel[...,None]*self.slope+((x-.18)[...,None]*local).tanh()
            b=newb
        return self.head(torch.cat([v.flatten(1),b,contract],1))


class CommonEncoder(nn.Module):
    def __init__(self,kind,w):
        super().__init__();self.kind=kind
        self.embed=nn.Linear(11,w)
        if kind=='gru':
            self.block=nn.GRU(w,w,batch_first=True)
        else:
            self.block=nn.TransformerEncoderLayer(w,4,w*2,0.,batch_first=True,norm_first=False)
            pos=torch.arange(24)[:,None]*torch.exp(torch.arange(0,w,2)*(-math.log(10000)/w))
            code=torch.zeros(24,w);code[:,0::2]=pos.sin();code[:,1::2]=pos.cos()
            self.register_buffer('pos',code);self.register_buffer('mask',torch.ones(24,24,dtype=torch.bool).triu(1))
        self.head=nn.Sequential(nn.Linear(w+8,w),nn.Tanh(),nn.Linear(w,3))

    def forward(self,seq,contract):
        z=self.embed(torch.cat([seq,contract[:,None].expand(-1,seq.shape[1],-1)],-1))
        if self.kind=='gru':
            z,_=self.block(z)
        else:
            z=self.block(z+self.pos,src_mask=self.mask)
        return self.head(torch.cat([z[:,-1],contract],1))


class Data:
    def __init__(self,path):
        with np.load(path) as raw:
            self.seq=torch.from_numpy(raw['seq'])
            self.y=torch.from_numpy(raw['y'])
            prices=torch.from_numpy(raw['tariff'])-1.
            contracts=torch.tensor([[.5,0],[.5,1],[1,0],[1,1]],dtype=torch.float32)
            self.static=torch.cat([contracts[None].expand(len(prices),-1,-1),prices[:,None].expand(-1,4,-1)],-1)
    def __len__(self):
        return len(self.seq)*4
    def sample(self,ids):
        anchors=ids//4; contract=ids%4
        return self.seq[anchors],self.static[anchors,contract],self.y[anchors,contract]
