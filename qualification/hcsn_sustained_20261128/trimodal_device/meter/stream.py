"""Inference-only exact recurrent-state and explicit causal KV-cache adapters for the frozen decoder."""
import math
import torch
import torch.nn.functional as F


def financial_block(cell, x, carry):
    projected=cell.projection(cell.norm(x))
    proposal=projected.tanh()
    t=(proposal+1)*((len(cell.table)-1)/2)
    ix=t.long().clamp(0,len(cell.table)-2)
    quotes=cell.table[ix]+(t-ix).unsqueeze(-1)*(cell.table[ix+1]-cell.table[ix])
    equity,credit,flow=quotes.unbind(-1)
    margin=math.log(1.12)-torch.log1p(cell.gain*proposal)
    a=.89+.105*(1-flow)
    f=-.85*equity.tanh()*(.15-margin)+.90*credit.tanh()
    if x.shape[1]==1:
        previous=carry[:,None,:]
        end=a[:,0]*carry+(1-a[:,0])*f[:,0]
    else:
        c=a.cumprod(1)
        state=c*(carry[:,None,:]+(((1-a)*f)/c).cumsum(1))
        previous=torch.cat((carry[:,None,:],state[:,:-1]),1)
        end=state[:,-1].contiguous()
    out=torch.log1p(cell.gain*torch.tanh(projected+3*previous))/cell.gain
    return out,end


def attention_block(cell,x,carry,position):
    key,value=carry
    n,t,d=x.shape
    q,k,v=cell.qkv(cell.norm(x)).reshape(n,t,3,2,d//2).permute(2,0,3,1,4).unbind(0)
    end=position+t
    key[:,:,position:end].copy_(k)
    value[:,:,position:end].copy_(v)
    if position==0:
        z=F.scaled_dot_product_attention(q,k,v,is_causal=True)
    elif t==1:
        z=F.scaled_dot_product_attention(q,key[:,:,:end],value[:,:,:end])
    else:
        # Support arbitrary streaming blocks with an absolute-position lower triangle.
        allowed=torch.arange(end,device=x.device)[None,:]<=torch.arange(position,end,device=x.device)[:,None]
        z=F.scaled_dot_product_attention(q,key[:,:,:end],value[:,:,:end],attn_mask=allowed)
    h=x+cell.out(z.transpose(1,2).reshape(n,t,d))
    return h+cell.ff(h),carry


class StreamingDecoder:
    def __init__(self,net,batch,capacity):
        self.net=net
        self.position=0
        self.capacity=capacity
        self.pos=torch.arange(capacity,device=net.pos.weight.device)
        self.memory=[]
        d=net.embed.embedding_dim
        for cell in net.cells:
            if hasattr(cell,'qkv'):
                self.memory.append(tuple(net.embed.weight.new_empty((batch,2,capacity,d//2)) for _ in range(2)))
            elif cell.kind=='financial':
                self.memory.append(net.embed.weight.new_zeros((batch,d)))
            else:raise ValueError('only the preregistered financial and SDPA arms are supported')
    @property
    def state_bytes(self):
        return sum(p.numel()*p.element_size() for X in self.memory for p in (X if isinstance(X,tuple) else (X,)))
    def append(self,tokens):
        t=tokens.size(1);end=self.position+t
        if t<1 or end>self.capacity:raise ValueError('invalid streaming window')
        h=self.net.embed(tokens)+self.net.pos(self.pos[self.position:end])
        for i,cell in enumerate(self.net.cells):
            if hasattr(cell,'qkv'):
                h,self.memory[i]=attention_block(cell,h,self.memory[i],self.position)
            else:
                h,self.memory[i]=financial_block(cell,h,self.memory[i])
        self.position=end
        return self.net.logits(h)
