"""All writable sites of a causal RGB/word predictor, with physical, matched and attention variants."""
import json
import math
import sys
from pathlib import Path
import numpy as np
import torch
from torch import nn
from torch.nn import functional as F
try:
    from cifar_net import Fields,intercept
except ImportError:
    sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scratch_cifar'))
    from cifar_net import Fields,intercept


class Data:
    def __init__(self,root,name):
        self.pix=np.load(root/(name+'_pixels.npy'),mmap_mode='r')
        with np.load(root/(name+'_text.npz')) as d:
            self.x=d['x'];self.y=d['y'];self.names=d['names']
        self.count=len(self.x)
    
    def batch(self,indices,photo=None):
        indices=np.asarray(indices);ix=indices//5;j=indices%5
        if photo is None:photo=ix
        return (torch.tensor(np.array(self.pix[photo])),torch.tensor(self.x[ix,j].astype('int64')),
                torch.tensor(self.y[ix,j].astype('int64')))
    
    def subset(self,limit):
        return np.arange(min(limit,self.count)*5)


def patches(pixels):
    n=len(pixels);rgb=pixels.float().div(127.5).sub(1.)
    return rgb.reshape(n,4,8,4,8,3).permute(0,1,3,2,4,5).reshape(n,16,192)


def positions(length,dim):
    frequency=torch.exp(-math.log(10000.)*torch.arange(0,dim,2)/dim)
    phase=torch.arange(length)[:,None]*frequency[None]
    return .1*torch.stack((phase.sin(),phase.cos()),dim=-1).flatten(1)


def prior(data,V):
    freq=np.bincount(data.y[data.y!=0],minlength=V).astype('float64')+.25
    return torch.tensor(freq/freq.sum(),dtype=torch.float32)


class CaptionNet(nn.Module):
    def __init__(self,V,width,arch,seed,lut,freq):
        super().__init__()
        self.vocab=V;self.width=width;self.arch=arch;self.seed=seed
        with torch.random.fork_rng(devices=[]):
            torch.manual_seed(seed);self.image=nn.Parameter(torch.randn(193,width)/math.sqrt(192))
            self.token=nn.Parameter(torch.randn(V,width)*.06)
            if arch=='transformer':
                self.blocks=nn.ModuleList(nn.TransformerEncoderLayer(width,8,4*width,0.,activation='gelu',
                      batch_first=True,norm_first=True) for _ in range(3))
                self.final=nn.LayerNorm(width);d=width
            else:
                self.field=Fields(lut,arch)
                self.weights=nn.ParameterList([nn.Parameter(torch.randn(v+1,width)/math.sqrt(v)) for v in (width,4*width,4*width)])
                d=4*width
            self.output=nn.Parameter(torch.randn(d+1,V)*(.01/math.sqrt(d)))
        self.register_buffer('positions',positions(21,width))
        self.register_buffer('logprior',freq.log())
        self.register_buffer('temperature',torch.tensor(1.))
    
    def inputs(self,pixels,tokens):
        v=intercept(patches(pixels))@self.image
        v=v.reshape(len(v),2,2,2,2,self.width).mean((2,4)).reshape(len(v),4,self.width)
        v=torch.tanh(v)
        text=F.embedding(tokens,self.token)+.5*v.mean(1,keepdim=True)
        h=torch.cat((v,text),1)
        return h+self.positions[:h.shape[1]]
    
    def layers(self,h,depth=3):
        if self.arch=='transformer':
            mask=torch.ones(h.shape[1],h.shape[1],device=h.device,dtype=torch.bool).triu(1)
            for module in self.blocks[:depth]:h=module(h,src_mask=mask,is_causal=True)
            return self.final(h) if depth==3 else h
        for w in self.weights[:depth]:
            h=self.field(intercept(h)@w)
        return h
    
    def features(self,p,t):
        return self.layers(self.inputs(p,t))[:,4:]
    
    def logits(self,feat):
        return (intercept(feat)@self.output)*self.temperature+self.logprior
    
    def forward(self,p,t):
        return self.logits(self.features(p,t))
