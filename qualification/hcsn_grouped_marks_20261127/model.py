"""Patch release and an otherwise shared autoregressive caption decoder."""
import math

import torch
from torch import nn
from torch.nn import functional as F
from parent_cell import Published

ARMS=("hcsn","smooth","lif","mean","dense")

class LawTable(nn.Module):
    """Exact affine principal dependence, linear interpolation only in live distance."""
    def __init__(self):
        super().__init__()
        law=Published()
        self.principal=law.p.P0
        self.kappa=.28*law.bp*law.p.P0/law.B0
        self.a0=float(law.A0)
        self.f0=float(law.F0)
        self.da=float(law.dA0)
        self.df=float(law.dF0)
        self.spacing=2.0/8192
        with torch.no_grad():
            grid=torch.arange(8193,dtype=torch.float64)*self.spacing
            a=law.equity(grid,law.p.P0)
            b=law.equity(grid,law.p.P0+1.)-a
            ar=torch.stack([a,b,law.passage(grid,1.),law.passage(grid,.25),law.move_mean(grid)],dim=1)
            self.register_buffer("table",ar.float())
            self.h0=float(law.passage(torch.tensor(.18,dtype=torch.float64),.25))
            dx=1e-6
            self.dh=float((law.passage(torch.tensor(.18+dx,dtype=torch.float64),.25)-law.passage(torch.tensor(.18-dx,dtype=torch.float64),.25))/(2*dx))

    def lookup(self,x):
        pos=(x.clamp(min=0,max=2.)/self.spacing)
        lo=pos.long().clamp(max=len(self.table)-2)
        frac=(pos-lo).unsqueeze(-1)
        return torch.lerp(self.table[lo],self.table[lo+1],frac)

class Router(nn.Module):
    def __init__(self,arm,d):
        super().__init__()
        self.arm=arm
        if arm in ("hcsn","smooth","lif"):
            self.drive=nn.Linear(d,4)
            self.rec=nn.Linear(4,4,bias=False)
            self.law=LawTable()

    def forward(self,patches):
        # four rows, each with four ordered patch positions
        n,_,width=patches.shape
        rows=patches.reshape(n*4,4,width)
        if self.arm=="dense":return patches
        if self.arm=="mean":return rows.mean(1).reshape(n,4,width)
        law=self.law
        drives=self.drive(rows)
        prior=drives.new_zeros((n*4,4))
        margin=prior+.18
        av=prior+law.a0
        fv=prior+law.f0
        remaining=prior[:,:1]+1
        total=patches.new_zeros((n*4,width))
        for t in range(4):
            # Last patch receives all surviving content mass, with no trainable fallback.
            if t==3:
                total=total+remaining*rows[:,t]
                break
            if self.arm=="lif":
                voltage=.8*margin+drives[:,t]+self.rec(prior)
                soft=torch.sigmoid(4*(voltage-1.))
                hit=(voltage>=1.).to(voltage.dtype)+soft-soft.detach()
                margin=voltage*(1-hit)
                prior=hit
            else:
                feedback=.4*torch.tanh((av-law.a0)/20)+.4*torch.tanh(fv-law.f0)
                drive=torch.tanh(drives[:,t]+self.rec(prior)+feedback)
                b=torch.log1p(law.kappa*drive)
                x=margin+prior-b
                eq,slope,year,quarter,margin=law.lookup(x).unbind(-1)
                if self.arm=="hcsn":
                    av=torch.where(x>0,eq+slope*(.28*law.principal*drive),0.)
                    fv=year
                    hit=quarter
                else:
                    av=law.a0+20*torch.tanh((x-.18)*law.da/20)
                    fv=law.f0+torch.tanh((x-.18)*law.df)
                    logit=math.log(law.h0/(1-law.h0))+(x-.18)*law.dh/(law.h0*(1-law.h0))
                    hit=torch.sigmoid(logit)
                prior=b
            fraction=hit.mean(-1,keepdim=True)
            mass=remaining*fraction
            total=total+mass*rows[:,t]
            remaining=remaining-mass
        return total.reshape(n,4,width)

class DecoderBlock(nn.Module):
    def __init__(self,d):
        super().__init__()
        self.n1=nn.LayerNorm(d)
        self.n2=nn.LayerNorm(d)
        self.qkv=nn.Linear(d,3*d)
        self.out=nn.Linear(d,d)
        self.ff=nn.Sequential(nn.Linear(d,2*d),nn.GELU(),nn.Linear(2*d,d))
    def forward(self,x):
        b,t,d=x.shape
        q,k,v=self.qkv(self.n1(x)).reshape(b,t,3,4,d//4).permute(2,0,3,1,4).unbind(0)
        h=F.scaled_dot_product_attention(q,k,v,is_causal=True)
        x=x+self.out(h.transpose(1,2).reshape(b,t,d))
        return x+self.ff(self.n2(x))

class Captioner(nn.Module):
    def __init__(self,arm,vocab,d=96):
        super().__init__()
        self.patch=nn.Conv2d(3,d,kernel_size=16,stride=16)
        self.image_pos=nn.Parameter(torch.zeros(1,16,d))
        self.embed=nn.Embedding(vocab,d)
        self.text_pos=nn.Parameter(torch.zeros(1,31,d))
        self.decoder=nn.Sequential(DecoderBlock(d),DecoderBlock(d),nn.LayerNorm(d))
        self.pred=nn.Linear(d,vocab,bias=False)
        self.pred.weight=self.embed.weight
        nn.init.normal_(self.embed.weight,std=.02)
        nn.init.normal_(self.image_pos,std=.02)
        nn.init.normal_(self.text_pos,std=.02)
        # Construct router last so common modules start byte-identically at each seed.
        self.router=Router(arm,d)
    def forward(self,images,tokens):
        marks=self.patch(images.permute(0,3,1,2).float()/127.5-1).flatten(2).transpose(1,2)+self.image_pos
        visual=self.router(marks)
        text=self.embed(tokens)+self.text_pos[:,:tokens.size(1)]
        encoded=self.decoder(torch.cat([visual,text],1))[:,visual.size(1):]
        return self.pred(encoded)
