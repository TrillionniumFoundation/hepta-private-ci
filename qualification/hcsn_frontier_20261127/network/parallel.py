"""An associative scan for price-law cells with input-determined barrier schedules."""
import torch
from torch import nn

from affine_ports import AffineBoundaryPopulation


def inclusive_products(matrices):
    """Inclusive prefix scan in temporal order, using O(T) small matrix products."""
    n=len(matrices)
    if n==1:return matrices
    pairs=matrices[:n//2*2:2]@matrices[1::2]
    even=inclusive_products(pairs)  # Prefixes ending at timesteps 1,3,5,...
    if n==2:return torch.cat([matrices[:1],even],0)
    odd_after=even[:(n-1)//2]@matrices[2::2]
    odd=torch.cat([matrices[:1],odd_after],0)
    interleaved=torch.stack([odd[:n//2],even],1).flatten(0,1)
    return torch.cat([interleaved,odd[-1:]],0) if n%2 else interleaved


def serial_states(p,matrices):
    rows=[]
    for m in matrices.unbind(0):
        p=(p.unsqueeze(-2)@m).squeeze(-2);rows.append(p)
    return torch.stack(rows)


def block_states(p,matrices,block=16):
    """Reduce inside each block, compute all starts, then transport vectors within blocks."""
    T=len(matrices);tail=(-T)%block
    if tail:
        eye=torch.eye(p.shape[-1],dtype=p.dtype,device=p.device)
        matrices=torch.cat([matrices,eye.expand(tail,*matrices.shape[1:])])
    groups=matrices.reshape(-1,block,*matrices.shape[1:])
    if len(groups)==1:return serial_states(p,matrices[:T])
    # Gather products of complete blocks without multiplying out every inner prefix.
    bars=groups[:-1].transpose(0,1)
    while len(bars)>1:
        n=len(bars);paired=bars[:n//2*2:2]@bars[1::2]
        bars=torch.cat([paired,bars[-1:]]) if n%2 else paired
    starts_later=(p.unsqueeze(-2)@inclusive_products(bars[0])).squeeze(-2)
    starts=torch.cat([p[None],starts_later])
    return serial_states(starts,groups.transpose(0,1)).transpose(0,1).flatten(0,1)[:T]


class InputDrivenLayer(nn.Module):
    def __init__(self,input_size,width,atoms):
        super().__init__()
        self.law=AffineBoundaryPopulation(input_size,width,atoms=atoms)
        # Internal pressure depends solely on the input in this architecture.
        del self.law.recurrent
        del self.law.feedback

    def forward(self,frames,initial=None,mode='serial',block=16):
        c=self.law;frames=frames.to(c.sender.weight)
        if initial is None:
            live,ref,old,_=c.initial(frames.shape[1])
            p=torch.cat([live,ref[...,None]],-1)
        else:p,old=initial
        principal=c.prices.p.P0*(1+.28*c.sender(frames).tanh())
        b=(c.prices.boundary(principal)/c.prices.B0).log()
        last=torch.cat([old.unsqueeze(0),b[:-1]],0)
        surv,hit=c.kernels(c.grid+(last-b).unsqueeze(-1))
        top=torch.cat([surv,hit.unsqueeze(-1)],-1)
        reset=torch.cat([c.reset_weights,c.reset_weights.new_zeros(1)])
        bottom=reset.expand(*top.shape[:-2],1,len(reset))
        transition=torch.cat([top,bottom],-2)
        if mode=='serial':states=serial_states(p,transition)
        elif mode=='scan':states=(p.unsqueeze(-2)@inclusive_products(transition)).squeeze(-2)
        elif mode=='block':states=block_states(p,transition,block)
        else:raise ValueError(f'unknown transport mode {mode}')
        mass=states[...,:-1];flow=states[...,-1]
        eq,loss=c.priced_channels(principal)
        values=torch.stack([b,flow,(mass*eq).sum(-1)/20,(mass*loss).sum(-1)/20],-1)
        return values,(states[-1],b[-1])


class ScanSpikingNetwork(nn.Module):
    def __init__(self,inputs,width,outputs,atoms=12):
        super().__init__();self.first=InputDrivenLayer(inputs,width,atoms);self.second=InputDrivenLayer(width*4,width,atoms)
        self.head=nn.Linear(width*4,outputs,dtype=torch.float64)

    def forward(self,frames,state=None,mode='serial',block=16):
        if frames.ndim!=3 or len(frames)<1:raise ValueError('expected nonempty [time,batch,feature]')
        s1,s2=state if state is not None else (None,None)
        msg,s1=self.first(frames,s1,mode,block)
        out,s2=self.second(msg.flatten(-2),s2,mode,block)
        return self.head(out.flatten(-2)),(s1,s2)
