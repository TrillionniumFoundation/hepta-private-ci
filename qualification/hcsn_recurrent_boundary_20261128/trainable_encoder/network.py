"""Six-layer encoder using finite-horizon pricing with a common physical transport."""
import numpy as np
import torch
from torch import nn
from encoder import AVText
from hcsn_temporal import Phys


class PriceTables(nn.Module):
    def __init__(self,path,base):
        super().__init__()
        self.base=base
        with np.load(path) as f:
            if not np.allclose(f["grid"],base.grid.cpu().numpy()) or not np.allclose(f["u"],np.linspace(-1,1,65)):
                raise ValueError("embedded grid differs")
            self.register_buffer("mark",torch.from_numpy(f["mark"].astype("float32")))
            self.register_buffer("prices",torch.from_numpy(f["prices"].astype("float32")))

    def at(self,drive):
        coordinate=(drive+1.)*((len(self.mark)-1)/2)
        index=coordinate.long().clamp(0,len(self.mark)-2)
        fraction=coordinate-index
        return (torch.lerp(self.mark[index],self.mark[index+1],fraction),
                torch.lerp(self.prices[index],self.prices[index+1],fraction[...,None,None]))


class SwitchingMixer(Phys):
    def forward(self,x,lower,law,diagnostic=False,intervention=None):
        b,t,d=x.shape
        g=self.groups
        drive=self.drive(x)
        if self.wire is not None:
            drive=drive+self.wire(lower)
        values=self.value(x).reshape(b,t,g,d//g)
        mark=x.new_zeros(b,g)
        ref=x.new_zeros(b,g)
        quote=x.new_zeros(b,g,2)
        mass=law.base.reset.expand(b,g,-1)
        memory=x.new_zeros(b,g,d//g)
        features,marks,contents=[],[],[]
        for frame in range(t):
            u=(drive[:,frame]+self.recurrent(mark)+(quote.tanh()*self.feedback).sum(-1)).tanh()
            new_mark,prices=law.at(u)
            trans=law.base.transition(mark-new_mark)
            hit=(mass*trans[...,-1]).sum(-1)
            mass=(mass[...,None]*trans[...,:-1]).sum(-2)+ref[...,None]*law.base.reset
            ref,mark=hit,new_mark
            quote=(mass[...,None]*prices).sum(-2)
            features.append(torch.stack((mark,hit,mass.sum(-1),quote[...,0],quote[...,1]),-1))
            marks.append(mark)
            memory=memory+(values[:,frame]-memory)*hit[...,None]
            contents.append(memory)
        output=(self.output(torch.stack(contents,1).reshape(b,t,d))
                +self.read(torch.stack(features,1).flatten(2)))
        return output,torch.stack(marks,1),None


def make_model(root,study,arm,seed,data):
    physical=arm in ("returning","stationary","irreversible")
    n=AVText("literal" if physical else arm,96,seed,data.words,root/"src/law4.npz")
    if physical:
        n.law=PriceTables(study/"tables"/(arm+".npz"),n.law)
        for i,old in enumerate(n.mixer):
            layer=SwitchingMixer("literal",96,16,i>0)
            layer.load_state_dict(old.state_dict(),strict=True)
            n.mixer[i]=layer
    return n
