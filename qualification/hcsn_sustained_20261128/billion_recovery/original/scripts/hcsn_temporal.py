"""All six temporal layers are causal four-atom He–Xiong population mixers or matched controls."""
from pathlib import Path
import numpy as np
import torch
from torch import nn
from torch.nn import functional as F

ARMS=('literal','smooth','no_wire','no_E','no_L','no_prices','lif','sdpa')
WIDTH=416
GROUPS=16
DEPTH=6

class Law(nn.Module):
    def __init__(self, path):
        super().__init__()
        with np.load(path) as data:
            for key in data.files:self.register_buffer(key,torch.from_numpy(np.asarray(data[key],dtype=np.float32).copy()))
    def transition(self,shift):
        u=(shift.clamp(-.8,.8)+.8)*((len(self.kernel)-1)/1.6)
        i=u.long().clamp(max=len(self.kernel)-2)
        return torch.lerp(self.kernel[i],self.kernel[i+1],(u-i)[...,None,None])
    def prices(self,u,smooth):
        if not smooth:return self.pmid + u[...,None,None]*self.pd
        diff=(self.grid-.18)[:,None]*self.slope + u[...,None,None]*self.du
        return self.center+torch.tanh(diff)

class Phys(nn.Module):
    def __init__(self,kind,width,groups,upper):
        super().__init__();self.kind=kind;self.groups=groups;self.width=width
        self.drive=nn.Linear(width,groups);self.recurrent=nn.Linear(groups,groups,bias=False)
        self.wire=nn.Linear(groups,groups,bias=False) if upper else None
        self.value=nn.Linear(width,width);self.output=nn.Linear(width,width)
        self.read=nn.Linear(5*groups,width,bias=False)
        self.feedback=nn.Parameter(torch.full((groups,2),.15))
    def forward(self,x,lower,law,diagnostic=False,intervention=None):
        batch,length,d=x.shape;g=self.groups
        drive=self.drive(x);values=self.value(x).reshape(batch,length,g,d//g)
        if self.wire is not None:
            wire=self.wire(lower)
            if intervention and 'wire' in intervention:wire=wire+intervention['wire']
            drive=drive+(wire*0 if self.kind=='no_wire' else wire)
        zeros=x.new_zeros(batch,g);oldb=zeros;ref=zeros;prices=x.new_zeros(batch,g,2)
        mass=law.reset.expand(batch,g,-1);mem=x.new_zeros(batch,g,d//g);volt=zeros
        path=[];marks=[];content=[];stats=[]
        keep=x.new_tensor([self.kind not in ('no_E','no_prices'),self.kind not in ('no_L','no_prices')])
        for t in range(length):
            if self.kind=='lif':
                volt=.8*volt+drive[:,t]+self.recurrent(oldb)
                rate=torch.sigmoid(4*(volt-1));hit=(volt>=1).to(x.dtype)+rate-rate.detach();volt=volt*(1-hit)
                mark=hit;flow=hit;active=1-hit;ref=hit;oldb=hit;signal=torch.stack((mark,flow,active,zeros,zeros),-1)
            else:
                drive_t=drive[:,t]+self.recurrent(oldb)+(torch.tanh(prices)*self.feedback).sum(-1)
                u=drive_t.tanh();mark=torch.log1p(law.kappa*u);transport=law.transition(oldb-mark)
                flow=(mass*transport[...,-1]).sum(-1)
                mass=(mass.unsqueeze(-1)*transport[...,:-1]).sum(-2)+ref[...,None]*law.reset
                ref=flow;active=mass.sum(-1);oldb=mark
                observed=(mass[...,None]*law.prices(u,self.kind=='smooth')).sum(-2)
                if intervention and 'prices' in intervention:observed=observed+intervention['prices']
                prices=observed*keep
                signal=torch.stack((mark,flow,active,prices[...,0],prices[...,1]),-1)
                if diagnostic:stats.append(torch.stack((flow,active,ref,mark,prices[...,0],prices[...,1]),-1))
            mem=mem+(values[:,t]-mem)*flow[...,None]
            path.append(signal);marks.append(mark);content.append(mem)
        features=torch.stack(path,1).flatten(2);y=self.output(torch.stack(content,1).reshape(batch,length,d))+self.read(features)
        return y,torch.stack(marks,1),torch.stack(stats,1) if stats else None

class Attention(nn.Module):
    def __init__(self,width):
        super().__init__();self.inner=width//2;self.qkv=nn.Linear(width,3*self.inner);self.out=nn.Linear(self.inner,width)
    def forward(self,x,lower,law,diagnostic=False,intervention=None):
        b,t,d=x.shape;q,k,v=self.qkv(x).reshape(b,t,3,8,self.inner//8).permute(2,0,3,1,4).unbind(0)
        h=F.scaled_dot_product_attention(q,k,v,is_causal=True)
        return self.out(h.transpose(1,2).reshape(b,t,self.inner)),None,None

class Captioner(nn.Module):
    def __init__(self,kind,seed,vocab,law_path,width=WIDTH,depth=DEPTH,groups=GROUPS):
        super().__init__();assert kind in ARMS and width%groups==0;self.kind=kind;self.law=Law(law_path)
        with torch.random.fork_rng(devices=[]):
            torch.manual_seed(seed);self.patch=nn.Conv2d(3,width,8,stride=8);self.pp=nn.Parameter(torch.randn(16,width)*.02)
            self.words=nn.Embedding(vocab,width);nn.init.normal_(self.words.weight,std=.02);self.pos=nn.Parameter(torch.randn(17,width)*.02)
            self.n1=nn.ModuleList(nn.LayerNorm(width) for _ in range(depth));self.n2=nn.ModuleList(nn.LayerNorm(width) for _ in range(depth))
            self.ff=nn.ModuleList(nn.Sequential(nn.Linear(width,4*width),nn.GELU(),nn.Linear(4*width,width)) for _ in range(depth));self.final=nn.LayerNorm(width)
            torch.manual_seed(seed+21019);self.mixers=nn.ModuleList(Attention(width) if kind=='sdpa' else Phys(kind,width,groups,i>0) for i in range(depth))
    def forward(self,pixels,tokens,diagnostic=False,intervention=None):
        h=self.patch(pixels.permute(0,3,1,2).float()*(1/127.5)-1).flatten(2).transpose(1,2)+self.pp
        h=h.reshape(len(h),4,4,h.size(-1)).mean(2)
        h=torch.cat((h,self.words(tokens)+self.pos[:tokens.size(1)]),dim=1);mark=None;details=[]
        for i,layer in enumerate(self.mixers):
            y,mark,det=layer(self.n1[i](h),mark,self.law,diagnostic,(intervention or {}).get(i));h=h+y;h=h+self.ff[i](self.n2[i](h))
            if diagnostic:details.append(det)
        logits=F.linear(self.final(h[:,4:]),self.words.weight)
        return (logits,details) if diagnostic else logits
