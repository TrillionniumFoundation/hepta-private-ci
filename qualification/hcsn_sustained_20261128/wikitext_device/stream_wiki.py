"""Streaming implementation of the frozen WikiText HX and SDPA models, with explicit cyclic positions."""
import torch
from torch.nn import functional as F


class State:
    def __init__(self,net,kind,batch,capacity):
        self.net=net;self.kind=kind;self.i=0;self.capacity=capacity
        self.mem=[]
        for block in net.blocks:
            d=net.emb.embedding_dim
            if kind=='hx':self.mem.append(net.pos.new_zeros(batch,d))
            else:self.mem.append(tuple(net.pos.new_empty(batch,4,capacity,d//4) for _ in range(2)))

    def live_state_bytes(self):
        return sum(t.numel()*t.element_size() for x in self.mem for t in (x if isinstance(x,tuple) else (x,)))

    def hx(self,bl,h,state):
        q,k,v=bl.qkv(bl.pre(h)).chunk(3,-1)
        if h.size(1)==1:
            st=state*bl.decay+k[:,0]*(1-bl.decay)
            hist=st[:,None,:]
        else:
            parts=[];st=state
            for k0 in k.split(64,dim=1):
                pow=bl.histpow[:k0.size(1)]
                part=(st[:,None,:]*bl.decay+torch.cumsum(k0*(1-bl.decay)/pow,dim=1))*pow
                parts.append(part);st=part[:,-1].contiguous()
            hist=torch.cat(parts,1)
        u=torch.tanh(q+hist);w=v.sigmoid()
        e0=bl.center[1]+bl.slope[1]*u;e1=bl.center[2]+bl.slope[2]*u
        l0=bl.center[3]+bl.slope[3]*u;l1=bl.center[4]+bl.slope[4]*u
        signal=u+(e0+w*(e1-e0))/bl.center[2]-(l0+w*(l1-l0))/bl.center[3]
        z=h+bl.out(signal);z=z+bl.ff(z);ratio=bl.slope[0]/bl.center[0]
        return torch.log1p(ratio*torch.tanh(z))/ratio,st

    def attention(self,bl,h,mem):
        q,k,v=bl.qkv(bl.pre(h)).chunk(3,-1)
        def heads(z):return z.unflatten(-1,(4,z.size(-1)//4)).transpose(1,2)
        q,k,v=map(heads,(q,k,v));K,V=mem;n=h.shape[1];end=self.i+n
        K[:,:,self.i:end].copy_(k);V[:,:,self.i:end].copy_(v)
        if self.i==0:o=F.scaled_dot_product_attention(q,k,v,is_causal=True)
        elif n==1:o=F.scaled_dot_product_attention(q,K[:,:,:end],V[:,:,:end])
        else:
            mask=torch.arange(end,device=h.device)[None,:]<=torch.arange(self.i,end,device=h.device)[:,None]
            o=F.scaled_dot_product_attention(q,K[:,:,:end],V[:,:,:end],attn_mask=mask)
        z=h+bl.out(o.transpose(1,2).flatten(-2));return z+bl.ff(z),mem

    def append(self,x):
        end=self.i+x.shape[1]
        if end>self.capacity or x.size(1)<1:raise ValueError('context capacity')
        period=len(self.net.pos)
        if x.size(1)==1:
            pos=self.net.pos[self.i%period:self.i%period+1]
        elif self.i//period==(end-1)//period:
            pos=self.net.pos[self.i%period:(end-1)%period+1]
        else:
            ordinal=torch.arange(self.i,end,device=x.device)%period
            pos=self.net.pos[ordinal]
        h=self.net.emb(x)+pos
        for j,bl in enumerate(self.net.blocks):
            h,self.mem[j]=(self.hx if self.kind=='hx' else self.attention)(bl,h,self.mem[j])
        self.i=end
        return self.net.norm(h)


def log_probs(head,h):
    """Exact full-support normalized word distribution including all rare groups."""
    first=F.log_softmax(head.root(h),-1)
    hgroup=F.gelu(h[:,None,:]+head.condition.weight[None,:,:])
    conditional=head.rank(hgroup)+head.prior.weight[None,:,:]
    flat_ids=torch.arange(head.groups*head.width,device=h.device).view(head.groups,head.width)
    conditional=conditional.masked_fill(flat_ids[None,:,:]+head.direct>=head.vocab,-torch.inf)
    rare=(first[:,head.direct:,None]+F.log_softmax(conditional,-1)).flatten(1)[:,:head.vocab-head.direct]
    return torch.cat((first[:,:head.direct],rare),1)
