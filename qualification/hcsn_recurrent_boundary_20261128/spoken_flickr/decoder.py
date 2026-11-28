"""A single causal decoder for real Flickr image patches, spoken energy codes, and caption words."""
from functools import lru_cache
import math
from pathlib import Path
import sys

import numpy as np
import torch
from torch import nn
from torch.nn import functional as F

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'trimodal_decoder'))
from network import Core, Attention, make_table

KINDS=('financial','smooth','lif','sdpa')
LENGTHS=(16,16,48)
OFFSETS=(4,68,132)


class Corpus:
    def __init__(self,path,device):
        with np.load(path,allow_pickle=False) as data:
            photo=data['photo_index']
            self.photo=photo.copy()
            self.caption=data['caption_index'].copy()
            self.split=data['split'].copy()
            words=data['words'].copy()
            words[np.arange(48)[None,:]>=data['word_length'][:,None]]=-100
            self.modalities=[torch.as_tensor(x,dtype=torch.long,device=device)
                             for x in (data['visual'][photo],data['audio'],words)]
            self.word_count=int(data['words'].max())+1
        self.device=device

    def prefix(self,indices,mode,other=None):
        chunks=[]
        for m in range(3):
            if m==mode:continue
            j=indices if other is None else other
            src=self.modalities[m][j]
            chunks.append(torch.full_like(src[:,:1],1+m))
            chunks.append(torch.where(src>=0,src+OFFSETS[m],0))
        chunks.append(torch.full_like(chunks[0],1+mode))
        return torch.cat(chunks,dim=1)

    def assemble(self,indices,mode,other=None):
        target=self.modalities[mode][indices]
        prefix=self.prefix(indices,mode,other)
        tokens=target[:,:-1]
        x=torch.cat((prefix,torch.where(tokens>=0,tokens+OFFSETS[mode],0)),dim=1)
        return x,target,prefix.shape[1]-1


@lru_cache(maxsize=2)
def table(kind):
    return make_table(kind)


class ThreeWay(nn.Module):
    def __init__(self,nwords,kind,width):
        super().__init__()
        self.kind=kind;self.width=width
        self.embed=nn.Embedding(nwords+OFFSETS[2],width)
        self.position=nn.Embedding(82,width)
        self.outputs=nn.ModuleList(nn.Linear(width,n) for n in (64,64,nwords))
        if kind=='sdpa':
            self.layers=nn.ModuleList(Attention(width) for _ in range(2))
        else:
            values,gain,_=table('financial' if kind=='financial' else 'smooth')
            self.layers=nn.ModuleList(Core(width,kind,values,gain) for _ in range(2))

    def forward(self,x,mode,offset,cut=False):
        h=self.embed(x)+self.position(torch.arange(x.size(1),device=x.device))
        h=self.layers[0](h)
        if cut:h=h*0
        return self.outputs[mode](self.layers[1](h)[:,offset:])

    def step(self,token,pos,mode,states):
        h=self.embed(token)+self.position.weight[pos]
        new_states=[]
        for layer,state in zip(self.layers,states):
            if self.kind=='sdpa':
                q,k,v=layer.qkv(layer.norm(h)).reshape(len(h),3,2,h.size(1)//2).unbind(1)
                k,v=k.unsqueeze(2),v.unsqueeze(2)
                if state is not None:k,v=torch.cat((state[0],k),2),torch.cat((state[1],v),2)
                a=F.scaled_dot_product_attention(q.unsqueeze(2),k,v).squeeze(2).reshape_as(h)
                h=h+layer.out(a);h=h+layer.ff(h);new_states.append((k,v));continue
            z=layer.projection(layer.norm(h))
            if state is None:state=torch.zeros_like(z)
            if self.kind=='lif':
                voltage=layer.leak.sigmoid()*state+z;fire=(voltage>.6).to(z.dtype)
                new_states.append(voltage*(1-fire));h=fire;continue
            val=z.tanh();idx=(val+1)*((len(layer.table)-1)/2)
            lo=idx.long().clamp(0,len(layer.table)-2)
            price=layer.table[lo]+(idx-lo).unsqueeze(-1)*(layer.table[lo+1]-layer.table[lo])
            eq,loss,hit=price.unbind(-1);margin=math.log(1.12)-torch.log1p(layer.gain*val)
            a=.89+.105*(1-hit);force=-.85*eq.tanh()*(.15-margin)+.90*loss.tanh()
            new_states.append(a*state+(1-a)*force)
            h=torch.log1p(layer.gain*torch.tanh(z+3*state))/layer.gain
        return self.outputs[mode](h),new_states


def architecture(nwords,kind,seed):
    torch.manual_seed(seed)
    width=48
    if kind=='sdpa':
        # Count the affine shapes exactly, then verify the instantiated count.
        target=sum(p.numel() for p in ThreeWay(nwords,'financial',48).parameters())
        def param(d):
            embed=(nwords+132+82)*d
            heads=(d+1)*(128+nwords)
            return embed+heads+2*(8*d*d+11*d)
        width=min(range(8,50,2),key=lambda d:abs(param(d)-target))
        torch.manual_seed(seed)
    model=ThreeWay(nwords,kind,width)
    if kind=='sdpa' and sum(p.numel() for p in model.parameters())!=param(width):
        raise ArithmeticError('attention parameter count')
    return model


def greedy(model,data,idx,mode):
    prefix=data.prefix(idx,mode);states=[None,None];ids=[]
    for t in range(prefix.size(1)):logits,states=model.step(prefix[:,t],t,mode,states)
    for i in range(LENGTHS[mode]):
        token=logits.argmax(-1);ids.append(token)
        if mode==2 and i and torch.stack(ids,1).eq(1).any(1).all():break
        if i+1<LENGTHS[mode]:logits,states=model.step(token+OFFSETS[mode],prefix.size(1)+i,mode,states)
    pred=torch.stack(ids,1)
    if pred.size(1)<LENGTHS[mode]:pred=F.pad(pred,(0,LENGTHS[mode]-pred.size(1)),value=0)
    return pred
