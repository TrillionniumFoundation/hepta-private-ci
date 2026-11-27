"""Incremental He–Xiong cells with explicit delayed continuous boundary communication."""
from dataclasses import dataclass
from typing import NamedTuple
import torch
from torch import nn
from torch.nn import functional as F
from .cell import LiteralCell

class Population(NamedTuple):
    log_boundary:torch.Tensor
    next_margin:torch.Tensor
    equity:torch.Tensor
    first_hit:torch.Tensor

@dataclass(frozen=True)
class StreamState:
    tick:int
    populations:tuple[Population,...]

    def detach(self):
        return StreamState(self.tick,tuple(Population(*(v.detach() for v in p)) for p in self.populations))

class HeptaContinuousSpikingNetwork(nn.Module):
    """Only the previous receiving population's boundary is sent to the next layer."""
    def __init__(self,input_size=6,widths=(8,),kind='literal'):
        super().__init__()
        if input_size<1 or not widths or any(n<2 or n%2 for n in widths):
            raise ValueError('positive input size and even layer widths >=2 required')
        if kind not in ('literal','zero','tangent','ordinary'):raise ValueError('unknown operator')
        self.input_size=input_size
        self.widths=tuple(widths)
        self.layers=nn.ModuleList(LiteralCell(kind,input_size if k==0 else widths[k-1]//2,n) for k,n in enumerate(widths))

    def initial_state(self,batch):
        if batch<1:raise ValueError('empty batch')
        states=[]
        for cell in self.layers:
            blank=cell.drive.weight.new_zeros(batch,cell.n)
            states.append(Population(blank,blank+.18,blank+cell.law.A0,blank+cell.law.F0))
        return StreamState(0,tuple(states))

    @staticmethod
    def step_cell(cell,frame,old,mute=False):
        law=cell.law
        rel=(.4*((old.equity-law.A0)/20).tanh()+.4*(old.first_hit-law.F0).tanh()) if cell.kind!='zero' else 0.
        msg=old.log_boundary if not mute else torch.zeros_like(old.log_boundary)
        u=F.pad(cell.drive(frame),(0,cell.n//2))+F.linear(msg,cell.rec.weight*cell.mask)+rel
        P=law.p.P0*(1+.28*u.tanh())
        b=(law.boundary(P)/law.B0).log()
        x=old.next_margin+old.log_boundary-b
        if cell.kind=='tangent':
            a=law.A0+law.dA0*(x-.18);f=law.F0+law.dF0*(x-.18)
        elif cell.kind=='ordinary':
            a=law.A0+20*((x-.18)*law.dA0/20).tanh();f=law.F0+((x-.18)*law.dF0).tanh()
        else:
            a,f=law.values(x,P)
        pop=Population(b,law.move_mean(x),a,f)
        n=cell.n//2
        logits=cell.readout(torch.cat(((a[:,n:]-law.A0)/20,f[:,n:]-law.F0),dim=1))
        return logits,pop

    def forward(self,frames,state=None,mute_links=False):
        if frames.ndim!=3 or frames.shape[-1]!=self.input_size or frames.shape[0]==0:
            raise ValueError('expected nonempty [time,batch,input_size]')
        if state is None:state=self.initial_state(frames.shape[1])
        if len(state.populations)!=len(self.layers) or state.tick<0:
            raise ValueError('inconsistent stream state')
        for layer,p in zip(self.layers,state.populations):
            if any(v.shape!=(frames.shape[1],layer.n) or v.dtype!=layer.drive.weight.dtype or v.device!=layer.drive.weight.device for v in p):
                raise ValueError('physical state and model mismatch')
        outputs=[]
        for frame in frames.to(self.layers[0].drive.weight):
            new=[]
            for i,(cell,pop) in enumerate(zip(self.layers,state.populations)):
                previous=frame if i==0 else state.populations[i-1].log_boundary[:,self.widths[i-1]//2:]
                if mute_links and i:previous=torch.zeros_like(previous)
                logits,updated=self.step_cell(cell,previous,pop)
                new.append(updated)
            outputs.append(logits);state=StreamState(state.tick+1,tuple(new))
        return torch.stack(outputs),state

def inverse_local_drive(law,absolute_before,target,iterations=64):
    """Exact scalar boundary inversion followed by monotone finite-horizon first-passage inversion."""
    if absolute_before.shape!=target.shape or torch.any(~torch.isfinite(absolute_before)) or torch.any(~torch.isfinite(target)):
        raise ValueError('finite paired values required')
    if torch.any(absolute_before<=0) or torch.any((target<=0)|(target>=1)):raise ValueError('target requires an interior live cell')
    lo=torch.zeros_like(target);hi=torch.full_like(target,1.)
    while torch.any(law.passage(hi,law.p.m)>target):
        hi=2*hi
        if torch.any(hi>1024):raise ValueError('unbracketed margin')
    for _ in range(iterations):
        mid=(lo+hi)*.5
        above=law.passage(mid,law.p.m)>target
        lo=torch.where(above,mid,lo);hi=torch.where(above,hi,mid)
    x=(lo+hi)*.5
    b=absolute_before*torch.exp(-x)
    principal=(b-law.bc*law.p.C)/law.bp
    z=(principal/law.p.P0-1)/.28
    if torch.any(z.abs()>=1):raise ValueError('risk target is outside the bounded principal interval')
    return z.atanh()
