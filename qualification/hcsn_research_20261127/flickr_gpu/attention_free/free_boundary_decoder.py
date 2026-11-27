"""Two-layer causal captioner with an optional explicit between-layer boundary stream."""
import math
from pathlib import Path
import importlib.util
import os
import sys

import torch
from torch import nn
from torch.nn import functional as F

ROOT=Path(os.environ.get('HEPTA_FLICKR_ROOT',Path(__file__).resolve().parents[2]))
sys.path.insert(0,str(ROOT))
# Load the pinned upstream implementation by filename, since this experiment is also named model.py.
spec=importlib.util.spec_from_file_location('flickr_original_captioner',ROOT/'model.py')
upstream=importlib.util.module_from_spec(spec);spec.loader.exec_module(upstream)
LawTable=upstream.LawTable
ARMS=('hcsn','no_wire','smooth','lif','diagonal_ssm','attention_sdpa')


class AttentionMixer(nn.Module):
    def __init__(self,d):
        super().__init__()
        self.qkv=nn.Linear(d,3*d)
        self.out=nn.Linear(d,d)

    def forward(self,x,lower=None):
        b,t,d=x.shape
        q,k,v=self.qkv(x).reshape(b,t,3,4,d//4).permute(2,0,3,1,4).unbind(0)
        h=F.scaled_dot_product_attention(q,k,v,is_causal=True)
        return self.out(h.transpose(1,2).reshape(b,t,d)),None


class ContinuousMixer(nn.Module):
    def __init__(self,kind,d,units,upper):
        super().__init__()
        self.kind=kind
        self.units=units
        self.group=d//units
        self.drive=nn.Linear(d,units)
        self.value=nn.Linear(d,d)
        self.mix_out=nn.Linear(d,d)
        self.receiver=nn.Linear(units,units,bias=False) if upper else None
        if kind=='diagonal_ssm':
            self.log_rate=nn.Parameter(torch.zeros(units))
        else:
            self.recurrent=nn.Linear(units,units,bias=False)
        if kind in ('hcsn','no_wire','smooth'):
            self.law=LawTable()

    def forward(self,x,lower=None):
        size,length,width=x.shape
        values=self.value(x).reshape(size,length,self.units,self.group)
        drives=self.drive(x)
        if self.receiver is not None:
            if lower is None:raise ValueError('Upper recurrent layer requires a mark')
            wire=self.receiver(lower)
            drives=drives+(wire*0 if self.kind=='no_wire' else wire)
        prev=x.new_zeros(size,self.units)
        memory=x.new_zeros(size,self.units,self.group)
        margin=prev+.18
        if self.kind in ('hcsn','no_wire','smooth'):
            law=self.law
            equity=prev+law.a0
            annual=prev+law.f0
        if self.kind=='diagonal_ssm':
            retention=(-F.softplus(self.log_rate)*F.softplus(drives)).exp()
        collected=[];marks=[]
        for t in range(length):
            if self.kind=='diagonal_ssm':
                release=1-retention[:,t]
                emitted=release
            elif self.kind=='lif':
                voltage=.8*margin+drives[:,t]+self.recurrent(prev)
                soft=torch.sigmoid(4*(voltage-1.))
                release=(voltage>=1).to(voltage.dtype)+soft-soft.detach()
                margin=voltage*(1-release)
                emitted=release
            else:
                feedback=.4*torch.tanh((equity-law.a0)/20)+.4*torch.tanh(annual-law.f0)
                control=torch.tanh(drives[:,t]+self.recurrent(prev)+feedback)
                emitted=torch.log1p(law.kappa*control)
                live=margin+prev-emitted
                eq,slope,year,quarter,margin=law.lookup(live).unbind(-1)
                if self.kind in ('hcsn','no_wire'):
                    equity=torch.where(live>0,eq+slope*(.28*law.principal*control),0.)
                    annual=year
                    release=quarter
                else:
                    equity=law.a0+20*torch.tanh((live-.18)*law.da/20)
                    annual=law.f0+torch.tanh((live-.18)*law.df)
                    logits=math.log(law.h0/(1-law.h0))+(live-.18)*law.dh/(law.h0*(1-law.h0))
                    release=torch.sigmoid(logits)
            memory=memory+(values[:,t]-memory)*release.unsqueeze(-1)
            prev=emitted
            collected.append(memory)
            marks.append(emitted)
        content=torch.stack(collected,dim=1).reshape(size,length,width)
        return self.mix_out(content),torch.stack(marks,dim=1)


class Captioner(nn.Module):
    def __init__(self,kind,seed,vocab=3490,d=64,units=8):
        super().__init__()
        self.kind=kind
        with torch.random.fork_rng(devices=[]):
            torch.manual_seed(seed)
            self.patch=nn.Conv2d(3,d,16,stride=16)
            self.patch_pos=nn.Parameter(torch.zeros(1,16,d))
            self.text_pos=nn.Parameter(torch.zeros(1,31,d))
            self.words=nn.Embedding(vocab,d)
            self.norm_in=nn.ModuleList(nn.LayerNorm(d) for _ in range(2))
            self.norm_ff=nn.ModuleList(nn.LayerNorm(d) for _ in range(2))
            self.ff=nn.ModuleList(nn.Sequential(nn.Linear(d,2*d),nn.GELU(),nn.Linear(2*d,d)) for _ in range(2))
            self.norm_out=nn.LayerNorm(d)
            self.head=nn.Linear(d,vocab,bias=False)
            self.head.weight=self.words.weight
            nn.init.normal_(self.words.weight,std=.02)
            nn.init.normal_(self.text_pos,std=.02)
            nn.init.normal_(self.patch_pos,std=.02)
            torch.manual_seed(seed+64140)
            if kind=='attention_sdpa':
                self.mixers=nn.ModuleList(AttentionMixer(d) for _ in range(2))
                self.last_mark=None
            else:
                self.mixers=nn.ModuleList(ContinuousMixer(kind,d,units,i==1) for i in range(2))
                self.last_mark=nn.Linear(units,d,bias=False)

    def forward(self,images,tokens):
        p=self.patch(images.permute(0,3,1,2).float()/127.5-1).flatten(2).transpose(1,2)+self.patch_pos
        visual=p.reshape(len(p),4,4,p.size(-1)).mean(dim=2)
        txt=self.words(tokens)+self.text_pos[:,:tokens.size(1)]
        x=torch.cat((visual,txt),1)
        mark=None
        for i,mixer in enumerate(self.mixers):
            y,mark=mixer(self.norm_in[i](x),mark)
            x=x+y
            x=x+self.ff[i](self.norm_ff[i](x))
        if self.last_mark is not None:
            x=x+self.last_mark(mark)
        return self.head(self.norm_out(x[:,visual.size(1):]))
