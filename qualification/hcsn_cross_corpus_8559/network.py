"""A shared two-layer boundary/attention encoder with learned image and language inputs."""
import torch
from torch import nn
from torch.nn import functional as F
from population_mixer import Attention, Law, Phys


class Encoder(nn.Module):
    def __init__(self,arm,seed,vocab,law):
        super().__init__()
        width=64
        self.law=Law(law);self.arm=arm
        with torch.random.fork_rng(devices=[]):
            torch.manual_seed(seed)
            self.patch=nn.Conv2d(3,width,8,8)
            self.words=nn.Embedding(vocab,width,padding_idx=0)
            self.pos=nn.Parameter(torch.randn(2,4,width)*.02)
            self.norm=nn.ModuleList(nn.LayerNorm(width) for _ in range(2))
            self.mid=nn.ModuleList(nn.LayerNorm(width) for _ in range(2))
            self.ff=nn.ModuleList(nn.Sequential(nn.Linear(width,2*width),nn.GELU(),nn.Linear(2*width,width)) for _ in range(2))
            self.read=nn.ModuleList(nn.Sequential(nn.LayerNorm(width),nn.Linear(width,32)) for _ in range(2))
            torch.manual_seed(seed+411)
            self.mix=nn.ModuleList(Attention(width) if arm=='sdpa' else Phys(arm,width,4,i>0) for i in range(2))
    def forward(self,images,text):
        b=len(images)
        x=self.patch(images.permute(0,3,1,2).float()/127.5-1).mean(-1).transpose(1,2)
        t=self.words(text).view(b,4,6,-1)
        t=t.sum(2)/text.ne(0).view(b,4,6,1).sum(2).clamp_min(1)
        h=torch.cat([x+self.pos[0],t+self.pos[1]]);previous=None
        for mix,n,m,ff in zip(self.mix,self.norm,self.mid,self.ff):
            y,previous,_=mix(n(h),previous,self.law)
            h=h+y;h=h+ff(m(h))
        a,z=h[:b].mean(1),h[b:].mean(1)
        return F.normalize(self.read[0](a)),F.normalize(self.read[1](z))
