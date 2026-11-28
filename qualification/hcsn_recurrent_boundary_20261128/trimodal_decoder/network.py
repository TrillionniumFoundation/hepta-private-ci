from pathlib import Path
import sys
import math
import torch
import torch.nn.functional as F
from torch import nn
sys.path.insert(0,str(Path(__file__).resolve().parent.parent/"direct_hidden"))
from model import make_table
from data import LENGTH


class Core(nn.Module):
    def __init__(self,d,kind,table,gain):
        super().__init__()
        self.norm=nn.LayerNorm(d);self.projection=nn.Linear(d,d)
        self.kind=kind;self.gain=gain
        self.register_buffer("table",table)
        if kind=="lif":self.leak=nn.Parameter(torch.full((d,),1.5))

    def forward(self,x):
        z=self.projection(self.norm(x))
        if self.kind=="lif":
            spikes=[];m=torch.zeros_like(z[:,0]);leak=self.leak.sigmoid()
            for inp in z.unbind(1):
                m=leak*m+inp
                h=(m>.6).to(m.dtype);smooth=torch.sigmoid(5*(m-.6))
                fire=h+(smooth-smooth.detach())
                m=m*(1-fire);spikes.append(fire)
            return torch.stack(spikes,dim=1)
        v=z.tanh()
        cost=(v+1)*((len(self.table)-1)/2)
        i=cost.long().clamp(0,len(self.table)-2)
        q=self.table[i]+(cost-i).unsqueeze(-1)*(self.table[i+1]-self.table[i])
        e,l,f=q.unbind(-1)
        lb=torch.log1p(self.gain*v)
        margin=math.log(1.12)-lb
        a=.89+.105*(1-f)
        force=-.85*e.tanh()*(.15-margin)+.90*l.tanh()
        # Exact causal linear accumulator for this proposed-price cell, reset per utterance.
        cumulative=a.cumprod(1)
        state=cumulative*(((1-a)*force)/cumulative).cumsum(1)
        prev=F.pad(state[:,:-1],(0,0,1,0))
        return torch.log1p(self.gain*torch.tanh(z+3*prev))/self.gain


class Attention(nn.Module):
    def __init__(self,d):
        super().__init__()
        self.norm=nn.LayerNorm(d);self.qkv=nn.Linear(d,3*d);self.out=nn.Linear(d,d)
        self.ff=nn.Sequential(nn.LayerNorm(d),nn.Linear(d,2*d),nn.GELU(),nn.Linear(2*d,d))

    def forward(self,x):
        n,t,d=x.shape
        q,k,v=self.qkv(self.norm(x)).reshape(n,t,3,2,d//2).permute(2,0,3,1,4).unbind(0)
        a=F.scaled_dot_product_attention(q,k,v,is_causal=True)
        h=x+self.out(a.transpose(1,2).reshape(n,t,d))
        return h+self.ff(h)


class Decoder(nn.Module):
    def __init__(self,V,d,kind,table,gain):
        super().__init__()
        self.embed=nn.Embedding(V,d);self.pos=nn.Embedding(LENGTH,d)
        self.cells=nn.ModuleList([Attention(d) if kind.startswith("sdpa") else Core(d,kind,table,gain) for _ in range(2)])
        self.logits=nn.Linear(d,V)

    def forward(self,x,cut=False):
        a=self.embed(x)+self.pos(torch.arange(x.size(1),device=x.device))
        a=self.cells[0](a)
        return self.logits(self.cells[1](torch.zeros_like(a) if cut else a))


def architecture(vocab,kind,seed):
    torch.manual_seed(seed)
    table,gain,err=make_table("financial" if kind=="financial" else "smooth")
    d=32
    if kind=="sdpa_matched":
        target=sum(v.numel() for v in Decoder(vocab,32,"financial",table,gain).parameters())
        d=min(range(6,34,2),key=lambda k:abs(sum(v.numel() for v in Decoder(vocab,k,kind,table,gain).parameters())-target))
        torch.manual_seed(seed)
    return Decoder(vocab,d,kind,table,gain),d,err
