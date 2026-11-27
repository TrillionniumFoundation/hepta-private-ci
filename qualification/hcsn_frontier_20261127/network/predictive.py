"""A two-layer trainable HCSN using finite-population predictive messages.

Put qualification/hcsn_continuous_20261127/core on PYTHONPATH. State is ordered
as in BoundaryPopulation: live masses, refractory mass, past barrier, past prices.
"""
from pathlib import Path
import json

import torch
from torch import nn

from affine_ports import AffineBoundaryPopulation


def full_mass(state):
    mass,refractory,_,_=state
    return torch.cat([mass,refractory.unsqueeze(-1)],-1)


def forced_flow(cell,state,relative_levels):
    """Probability emitted under a prescribed future barrier plan; differentiable.

    Levels have shape [future,batch,width] and are log boundary levels *relative
    to the present boundary*. A zero level holds the present physical boundary.
    This is an intervention that fixes the barrier over the requested horizon.
    """
    mass,refractory,_,_=state
    if relative_levels.ndim!=3 or tuple(relative_levels.shape[1:])!=tuple(refractory.shape) or relative_levels.shape[0]==0:
        raise ValueError('expected a nonempty [horizon,batch,width] relative barrier plan')
    old=relative_levels[0].new_zeros(refractory.shape)
    rows=[]
    for level in relative_levels.unbind(0):
        surv,hit=cell.kernels(cell.grid+(old-level).unsqueeze(-1))
        flow=(mass*hit).sum(-1)
        mass=mass.unsqueeze(-2).matmul(surv).squeeze(-2)+refractory.unsqueeze(-1)*cell.reset_weights
        refractory=flow;old=level;rows.append(flow)
    return torch.stack(rows)


class PredictiveSpikingNetwork(nn.Module):
    """Implicitly priced sender and receiver, with a fixed task-independent port basis."""
    def __init__(self,input_size,width,outputs,port='predictive'):
        super().__init__()
        dimensions={'boundary':1,'flow':2,'priced':4,'augmented':8,'predictive':8,'full':13}
        if port not in dimensions:raise ValueError(f'unknown population message {port!r}')
        self.port=port
        self.sender=AffineBoundaryPopulation(input_size,width,atoms=12)
        self.receiver=AffineBoundaryPopulation(width*dimensions[port],width,atoms=12)
        basis=json.loads(Path(__file__).with_name('projection7.json').read_text())
        if basis['atoms']!=12 or basis['dt']!=.25:raise ValueError('unexpected projection geometry')
        self.register_buffer('basis',torch.tensor(basis['columns'],dtype=torch.float64))
        self.head=nn.Linear(width*8,outputs,dtype=torch.float64)

    def message(self,raw,state):
        if self.port=='predictive':
            return torch.cat([raw[...,:1],full_mass(state)@self.basis],-1)
        if self.port=='full':
            return torch.cat([raw[...,:1],state[0]],-1)
        return raw[...,:{'boundary':1,'flow':2,'priced':4,'augmented':8}[self.port]]

    def forward(self,frames,state=None):
        if frames.ndim!=3 or frames.shape[0]==0:
            raise ValueError('expected nonempty [time,batch,input_size] tensor')
        s1,s2=(self.sender.initial(frames.shape[1]),self.receiver.initial(frames.shape[1])) if state is None else state
        values=[]
        for x in frames.unbind(0):
            raw,s1=self.sender.step(x,s1)
            msg=self.message(raw,s1)
            r,s2=self.receiver.step(msg.flatten(-2),s2)
            values.append(self.head(r.flatten(-2)))
        return torch.stack(values),(s1,s2)
