"""Two causal blocks with an exact scalar-posterior He–Xiong boundary interface."""
from dataclasses import replace
from functools import lru_cache
import math

import torch
from torch import nn
from torch.nn import functional as F
from closed_form import Contract, Prices


@lru_cache(maxsize=1)
def finance():
    means=[]
    for v in (-1.,0.,1.):
        p=Prices(replace(Contract(),principal=61.68*(1+.28*v)))
        means.append([p.boundary,p.equity(.04),p.equity(.24),p.credit_loss(.04),p.credit_loss(.24)])
    for l,c,r in zip(*means):
        if abs((l+r)/2-c)>2e-10:raise ArithmeticError("Table-I affine reconstruction")
    return means


class Spiking(torch.autograd.Function):
    """Hard reset in forward; unit triangular threshold derivative in backward."""
    @staticmethod
    def forward(ctx, current, decay):
        current_t=current.transpose(0,1).contiguous()
        mem=torch.zeros_like(current_t[0])
        spikes=torch.empty_like(current_t);over=torch.empty_like(current_t)
        for t in range(len(current_t)):
            pre=decay*mem+current_t[t]
            over[t]=pre-1.
            bit=(pre>=1.).to(current.dtype)
            spikes[t]=bit
            mem=pre*(1-bit)
        ctx.save_for_backward(over,spikes,decay)
        return spikes.transpose(0,1)

    @staticmethod
    def backward(ctx,adj):
        over,spikes,decay=ctx.saved_tensors
        grad=torch.empty_like(over);carry=torch.zeros_like(over[0])
        adj=adj.transpose(0,1)
        for t in range(len(over)-1,-1,-1):
            surrogate=(1-over[t].abs()).clamp(min=0.)
            g=adj[t]*surrogate+carry*((1-spikes[t])-(1+over[t])*surrogate)
            grad[t]=g;carry=decay*g
        return grad.transpose(0,1),None


class Block(nn.Module):
    def __init__(self,d,kind):
        super().__init__()
        self.kind=kind
        self.pre=nn.LayerNorm(d)
        self.qkv=nn.Linear(d,3*d)
        self.out=nn.Linear(d,d)
        self.ff=nn.Sequential(nn.LayerNorm(d),nn.Linear(d,2*d),nn.GELU(),nn.Linear(2*d,d))
        self.register_buffer('decay',torch.tensor([.8,.9,.97,.99]*(d//4)))
        self.register_buffer('histpow',self.decay[None,:]**torch.arange(128)[:,None])
        tables = torch.tensor(finance(),dtype=torch.float64)
        self.register_buffer('center',tables[1].float())
        self.register_buffer('slope',((tables[2]-tables[0])/2).float())

    def forward(self,x):
        q,k,v=self.qkv(self.pre(x)).chunk(3,dim=-1)
        if self.kind=='sdpa':
            def heads(arr):
                return arr.unflatten(-1,(4,arr.size(-1)//4)).transpose(1,2)
            a=F.scaled_dot_product_attention(heads(q),heads(k),heads(v),is_causal=True)
            m=a.transpose(1,2).flatten(-2)
            z=x+self.out(m)
        else:
            p=self.histpow[:x.size(1)]
            history=torch.cumsum(k*(1-self.decay)/p,dim=1)*p
            u=torch.tanh(q+history)
            w=torch.sigmoid(v)
            if self.kind=='hx':
                # Exactly average the two original price observations on a
                # probability law with log-margins .04 and .24.
                e0=self.center[1]+self.slope[1]*u
                e1=self.center[2]+self.slope[2]*u
                l0=self.center[3]+self.slope[3]*u
                l1=self.center[4]+self.slope[4]*u
                equity=e0+w*(e1-e0)
                loss=l0+w*(l1-l0)
                signal=u+equity/self.center[2]-loss/self.center[3]
            elif self.kind=='lif':
                signal=Spiking.apply(.55+.85*(q+v+history),self.decay)
            else:
                signal=u+torch.tanh(w+u)-torch.sigmoid(u-w)
            z=x+self.out(signal)
        z=z+self.ff(z)
        if self.kind=='hx':
            # This is the entire block output and the sole inter-block wire.
            # Every component is exactly log(B/B0)/(dB/dv / B0).
            c=self.slope[0]/self.center[0]
            z=torch.log1p(c*torch.tanh(z))/c
        return z


class WordHead(nn.Module):
    """Exact normalized class × conditional rank probabilities, direct top-128 words."""
    def __init__(self,d,vocab):
        super().__init__()
        self.direct=128;self.width=128;self.vocab=vocab
        self.groups=math.ceil((vocab-self.direct)/self.width)
        self.root=nn.Linear(d,self.direct+self.groups)
        self.condition=nn.Embedding(self.groups,d)
        self.rank=nn.Linear(d,self.width)
        self.prior=nn.Embedding(self.groups,self.width)
        nn.init.zeros_(self.prior.weight)
        self.register_buffer('bins',torch.arange(self.width))

    def forward(self,h,t):
        rare=t>=self.direct
        g=(t[rare]-self.direct)//self.width
        rank=(t[rare]-self.direct)%self.width
        root_target=t.clone()
        root_target[rare]=g+self.direct
        nll=F.cross_entropy(self.root(h),root_target,reduction='none')
        logits=self.rank(F.gelu(h[rare]+self.condition(g)))+self.prior(g)
        mask=self.direct+g[:,None]*self.width+self.bins[None,:]>=self.vocab
        conditional=F.cross_entropy(logits.masked_fill(mask,-torch.inf),rank,reduction='none')
        return nll.index_add(0,rare.nonzero(as_tuple=True)[0],conditional)


class LanguageModel(nn.Module):
    def __init__(self,vocab,kind,d=32):
        super().__init__()
        self.emb=nn.Embedding(vocab,d)
        self.pos=nn.Parameter(torch.empty(128,d))
        nn.init.normal_(self.pos,std=.02)
        self.blocks=nn.ModuleList([Block(d,kind) for _ in range(2)])
        self.norm=nn.LayerNorm(d)
        self.head=WordHead(d,vocab)

    def encode(self,ids,cut=False):
        h=self.emb(ids)+self.pos[:ids.size(1)]
        h=self.blocks[0](h)
        if cut:h=h*0
        return self.norm(self.blocks[1](h))

    def losses(self,ids,targets,cut=False):
        h=self.encode(ids,cut).flatten(0,1)
        tgt=targets.flatten()
        ok=tgt>=0
        if torch.any(~ok):
            h=h[ok];tgt=tgt[ok]
        return self.head(h,tgt)
