"""64 hard spikes per position, transmitted as exactly eight unsigned bytes."""
import argparse
import json
from pathlib import Path
import sys

import torch
from torch import nn
from torch.nn import functional as F

from port import PortEncoder,SEEDS,W
import train_port


class LIFLayer(nn.Module):
    def __init__(self):
        super().__init__();self.drive=nn.Linear(W,W);self.feedback=nn.Linear(W,W,bias=False)
    def forward(self,x):
        charge=x.new_zeros(len(x),W);hit=torch.zeros_like(charge);all_hits=[]
        for v in self.drive(x).unbind(1):
            charge=.8*charge+v+self.feedback(hit)
            rate=(4*(charge-1)).sigmoid();hit=(charge>=1).to(x.dtype)+(rate-rate.detach())
            charge=charge*(1-hit);all_hits.append(hit)
        return torch.stack(all_hits,1)


class SpikeEncoder(nn.Module):
    def __init__(self,arm,bits,seed,vocab,law):
        super().__init__();assert arm=='lif_packed' and bits==8;self.bits=8;self.arm=arm
        # Copy only the requested initialized common modules; no discarded attention parameter enters this net.
        original=PortEncoder('attention',8,seed,vocab,law)
        self.patch=original.patch;self.word=original.word;self.pos=original.pos
        self.pre=original.pre;self.post=original.post;self.read=original.read
        self.register_buffer('lo',torch.tensor(0.));self.register_buffer('hi',torch.tensor(1.))
        self.register_buffer('shifts',torch.arange(8,dtype=torch.int64));self.clamp_wire_code=0
        with torch.random.fork_rng(devices=[]):
            torch.manual_seed(seed+19183);self.lower_cell=LIFLayer();self.upper_cell=LIFLayer();self.bridge=nn.Linear(W,W)
    def lower(self,images,text):
        im=self.patch(images.permute(0,3,1,2).float()/127.5-1).mean(-1).transpose(1,2)
        b=len(text);z=self.word(text).view(b,4,6,W);tx=z.sum(2)/text.ne(0).view(b,4,6,1).sum(2).clamp_min(1)
        x=torch.cat((im+self.pos[0],tx+self.pos[1]));return self.lower_cell(x+self.pre(x))
    def serialize(self,spikes):
        return (spikes.detach().long().reshape(*spikes.shape[:-1],8,8)<<self.shifts).sum(-1).to(torch.uint8)
    def decode(self,wire):
        assert wire.dtype==torch.uint8
        return ((wire.long().unsqueeze(-1)>>self.shifts)&1).float().flatten(-2)
    def upper(self,spikes):
        h=self.bridge(spikes);h=h+self.upper_cell(h);h=h+self.post(h);im,tx=h.chunk(2)
        return F.normalize(self.read[0](im.mean(1))),F.normalize(self.read[1](tx.mean(1)))
    def forward(self,images,text):
        spikes=self.lower(images,text);decoded=self.decode(self.serialize(spikes))
        if self.training:decoded=decoded+(spikes-spikes.detach())
        return self.upper(decoded)


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('source',type=Path);p.add_argument('out',type=Path);p.add_argument('law',type=Path);a=p.parse_args()
    train_port.PortEncoder=SpikeEncoder
    for seed in SEEDS:train_port.fit(a.source,a.out,a.law,'lif_packed',8,seed)
