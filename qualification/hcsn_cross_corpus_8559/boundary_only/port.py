"""Two learned image/language layers whose only data-dependent inter-layer state is their boundary."""
from pathlib import Path
import sys

import torch
from torch import nn
from torch.nn import functional as F

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from population_mixer import Attention,Law

W,G=64,8
ARMS=('literal','smooth','attention')
SEEDS=(4171,6817,9203)


class Population(nn.Module):
    def __init__(self,smooth):
        super().__init__();self.smooth=smooth
        self.drive=nn.Linear(W,G);self.recurrent=nn.Linear(G,G,bias=False)
        self.feedback=nn.Parameter(torch.full((G,2),.15))
    def forward(self,x,law,read_features):
        n,t,_=x.shape;d=self.drive(x);prev=x.new_zeros(n,G);ref=torch.zeros_like(prev)
        prices=x.new_zeros(n,G,2);mass=law.reset.expand(n,G,-1);marks=[];features=[]
        for j in range(t):
            u=(d[:,j]+self.recurrent(prev)+(prices.tanh()*self.feedback).sum(-1)).tanh()
            b=torch.log1p(law.kappa*u);transition=law.transition(prev-b)
            flow=(mass*transition[...,-1]).sum(-1)
            mass=(mass.unsqueeze(-1)*transition[...,:-1]).sum(-2)+ref[...,None]*law.reset
            prices=(mass[...,None]*law.prices(u,self.smooth)).sum(-2)
            marks.append(b)
            if read_features:features.append(torch.stack([b,flow,mass.sum(-1),prices[...,0],prices[...,1]],dim=-1).flatten(1,2))
            ref=flow;prev=b
        return torch.stack(marks,1),torch.stack(features,1) if features else None


class PortEncoder(nn.Module):
    def __init__(self,arm,bits,seed,vocab,law):
        super().__init__();assert arm in ARMS and bits in (8,32);self.arm=arm;self.bits=bits;self.law=Law(law)
        self.register_buffer('lo',torch.log1p(-self.law.kappa));self.register_buffer('hi',torch.log1p(self.law.kappa))
        with torch.random.fork_rng(devices=[]):
            torch.manual_seed(seed)
            self.patch=nn.Conv2d(3,W,8,stride=8);self.word=nn.Embedding(vocab,W,padding_idx=0)
            self.pos=nn.Parameter(torch.randn(2,4,W)*.02)
            self.pre=nn.Sequential(nn.LayerNorm(W),nn.Linear(W,2*W),nn.GELU(),nn.Linear(2*W,W))
            self.bridge=nn.Linear(G,W);self.post=nn.Sequential(nn.LayerNorm(W),nn.Linear(W,2*W),nn.GELU(),nn.Linear(2*W,W))
            self.read=nn.ModuleList([nn.Sequential(nn.LayerNorm(W),nn.Linear(W,32)) for _ in range(2)])
            torch.manual_seed(seed+19183)
            if arm=='attention':
                self.low_att=Attention(W);self.lower_project=nn.Linear(W,G)
                self.high_att=Attention(W)
            else:
                self.lower_cell=Population(arm=='smooth');self.upper_cell=Population(arm=='smooth')
                self.upper_project=nn.Linear(G*5,W)
    def lower(self,images,text):
        im=self.patch(images.permute(0,3,1,2).float()/127.5-1).mean(-1).transpose(1,2)
        b=len(text);z=self.word(text).view(b,4,6,W);tx=z.sum(2)/text.ne(0).view(b,4,6,1).sum(2).clamp_min(1)
        x=torch.cat((im+self.pos[0],tx+self.pos[1]));x=x+self.pre(x)
        if self.arm=='attention':
            y,_,_=self.low_att(x,None,None)
            return torch.log1p(self.law.kappa*self.lower_project(x+y).tanh())
        return self.lower_cell(x,self.law,False)[0]
    def serialize(self,boundary):
        if self.bits==32:return boundary.float()
        return ((boundary-self.lo)*(255/(self.hi-self.lo))).round().clamp(0,255).to(torch.uint8)
    def decode(self,wire):
        if self.bits==32:
            assert wire.dtype==torch.float32
            return wire
        assert wire.dtype==torch.uint8
        return self.lo+wire.float()*((self.hi-self.lo)/255)
    def upper(self,b):
        # This method receives no photo, text, lower hidden state or index. Every data dependency enters via b.
        x=self.bridge(b)
        if self.arm=='attention':y,_,_=self.high_att(x,None,None)
        else:
            _,features=self.upper_cell(x,self.law,True);y=self.upper_project(features)
        x=x+y;x=x+self.post(x);i,t=x.chunk(2,0)
        return F.normalize(self.read[0](i.mean(1))),F.normalize(self.read[1](t.mean(1)))
    def forward(self,images,text):
        b=self.lower(images,text);q=self.decode(self.serialize(b))
        if self.bits==8 and self.training:q=q+(b-b.detach())
        return self.upper(q)
