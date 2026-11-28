"""Same writable three-layer architecture with physical, matched-smooth, or dense-ReLU fields."""
import json
from pathlib import Path
import numpy as np
import torch
from torch import nn


WIDTH=32


class Examples:
    def __init__(self,root,split):
        self.pix=np.load(root/(split+'_pixels.npy'),mmap_mode='r')
        with np.load(root/(split+'_targets.npz')) as f:
            self.y=f['fine'].astype('int64')
            self.c=f['coarse'].astype('int64')
        self.mean=torch.tensor(json.loads((root/'data.json').read_text())['train_rgb_mean'],dtype=torch.float32)
        self.children=np.zeros((100,20),dtype=np.float32)
        self.children[self.y,self.c]=1
        assert np.all(self.children.sum(1)==1)
    
    def subset(self,max_per_label):
        return np.concatenate([np.flatnonzero(self.y==l)[:max_per_label] for l in range(100)])
    
    def batch(self,ix):
        pix=torch.from_numpy(np.asarray(self.pix[ix])).float().div_(255).sub_(self.mean).mul_(4)
        patches=pix.reshape(-1,4,8,4,8,3).permute(0,1,3,2,4,5).reshape(-1,16,192)
        return patches,torch.from_numpy(self.y[ix]),torch.from_numpy(self.c[ix])


class Fields(nn.Module):
    def __init__(self,law,kind):
        super().__init__()
        with np.load(law) as d:
            fields=d['fields'].astype('float64');cen=d['center'].astype('float64');k=float(d['k'])
            if kind=='smooth':
                u=np.linspace(-1,1,len(fields))[:,None,None]
                m=np.linspace(0,1.2,fields.shape[1])[None,:,None]
                hi=np.maximum(fields.max(axis=(0,1)),1.01*cen);hi[2:]=[1,1.2]
                q=cen/hi
                slope=hi*q*(1-q)
                value=np.log(q/(1-q))+(u*d['du']+(m-.18)*d['dm'])/slope
                tab=hi/(1+np.exp(-np.clip(value,-100,100)))
            else:tab=fields
            sc=fields[24:137,:192,:3].reshape(-1,3).std(0)
        self.kind=kind
        self.k=k
        self.register_buffer('tab',torch.from_numpy(tab.astype('float32')))
        self.register_buffer('ref',torch.tensor([0,*cen[:3]],dtype=torch.float32))
        self.register_buffer('scale',torch.tensor([max(.5*k,.001),*np.maximum(sc,.001)],dtype=torch.float32))
    
    def interpolate(self,u,m):
        nx,ny=self.tab.shape[:2]
        x=(u+1)*((nx-1)/2)
        y=m*((ny-1)/1.2)
        ix=x.long().clamp(0,nx-2);iy=y.long().clamp(0,ny-2)
        ax=(x-ix).unsqueeze(-1);ay=(y-iy).unsqueeze(-1)
        first=torch.lerp(self.tab[ix,iy],self.tab[ix,iy+1],ay)
        second=torch.lerp(self.tab[ix+1,iy],self.tab[ix+1,iy+1],ay)
        return torch.lerp(first,second,ax)
    
    def forward(self,d,forced=False):
        if self.kind=='dense':
            if forced:raise ValueError('dense control has no boundary')
            return torch.stack([d.relu(),(-d).relu(),(d-1).relu(),(-d-1).relu()],dim=-1).flatten(-2)
        m=d.new_full((len(d),d.shape[-1]),.18)
        prev=torch.zeros_like(m);fb=torch.zeros_like(m);records=[]
        for i in range(d.shape[1]):
            target=d[:,i]
            if forced:
                records.append(target-fb)
            u=torch.tanh(target if forced else target+fb)
            bound=torch.log1p(self.k*u)
            value=self.interpolate(u,(m+prev-bound).clamp(0,1.2))
            if not forced:
                signal=torch.cat((bound.unsqueeze(-1),value[...,:3]),-1)
                records.append(((signal-self.ref)/self.scale).clamp(-6,6).flatten(-2))
            m=value[...,3];prev=bound
            fb=.15*torch.tanh(value[...,:2]-self.ref[1:3]).sum(-1)
        return torch.stack(records,1)


def intercept(h):
    return torch.cat((h,torch.ones_like(h[...,:1])),dim=-1)


def quadrants(h):
    n,_,d=h.shape
    return h.reshape(n,2,2,2,2,d).mean((2,4)).reshape(n,4*d)


def raw_view(x):
    n=len(x)
    return x.reshape(n,4,4,2,4,2,4,3).mean((4,6)).flatten(1)


class Net(nn.Module):
    def __init__(self,law,kind,seed):
        super().__init__()
        g=torch.Generator().manual_seed(seed)
        self.seed=seed;self.kind=kind;self.fields=Fields(law,kind)
        dims=(192,4*WIDTH,4*WIDTH)
        self.w=nn.ParameterList([nn.Parameter(torch.randn(n+1,WIDTH,generator=g)/np.sqrt(n)) for n in dims])
        self.head=nn.Parameter(torch.randn(4*4*WIDTH+1,100,generator=g)*.01)
        self.register_buffer('temperature',torch.tensor(1.))
    
    def representation(self,x,depth=3):
        for w in self.w[:depth]:
            x=self.fields(intercept(x)@w)
        return x
    
    def forward(self,x):
        return (intercept(quadrants(self.representation(x)))@self.head)*self.temperature


def init_code(seed,index,in_dim):
    g=torch.Generator().manual_seed(seed+28559*(index+1))
    return torch.randn(in_dim,WIDTH,generator=g)/np.sqrt(in_dim),torch.randn(100,WIDTH,generator=g)
