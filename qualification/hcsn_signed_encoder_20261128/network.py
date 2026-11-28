"""A full six-layer AVText encoder with an identified feedback intervention in physical drift."""
from pathlib import Path
import torch
from encoder import AVText
from hcsn_temporal import Phys
from force_kernel import MU,DT,table,transport,signed_term

ARMS=("signed","free","nonfinancial","noforce")
class ForceMixer(Phys):
    def __init__(self,arm,upper):
        super().__init__("literal",96,16,upper)
        self.arm=arm
    def forward(self,x,lower,law,diagnostic=False,intervention=None):
        batch,frames,width=x.shape
        g=self.groups
        drive=self.drive(x)
        if self.wire is not None:drive=drive+self.wire(lower)
        value=self.value(x).reshape(batch,frames,g,width//g)
        mass=law.reset.expand(batch,g,-1)
        ref=x.new_zeros(batch,g);mark=x.new_zeros(batch,g);quote=x.new_zeros(batch,g,2)
        memory=x.new_zeros(batch,g,width//g)
        contents=[];features=[];marks=[]
        for t in range(frames):
            u=(drive[:,t]+self.recurrent(mark)).tanh()
            newmark=torch.log1p(law.kappa*u)
            force=signed_term(self.arm,self.feedback,mass,ref,quote,law.grid,law.reset)
            relative_drift=MU-.15*u+force+(mark-newmark)/DT
            prob=transport(law.force_transition,relative_drift)
            moved=(mass[...,None]*prob).sum(-2)
            mass=moved[...,:-1]+ref[...,None]*law.reset
            ref=moved[...,-1];mark=newmark
            quote=(mass[...,None]*law.prices(u,False)).sum(-2)
            memory=memory+(value[:,t]-memory)*ref[...,None]
            features.append(torch.stack((mark,ref,mass.sum(-1),quote[...,0],quote[...,1]),-1))
            marks.append(mark);contents.append(memory)
        y=self.output(torch.stack(contents,1).reshape(batch,frames,width))+self.read(torch.stack(features,1).flatten(2))
        return y,torch.stack(marks,1),None

def make_model(root,arm,seed,words):
    if arm not in ARMS:raise ValueError(arm)
    net=AVText("literal",96,seed,words,Path(root)/"src/law4.npz")
    kernel=table(net.law.grid.cpu().numpy())
    net.law.register_buffer("force_transition",torch.from_numpy(kernel.astype("float32")))
    for idx,old in enumerate(net.mixer):
        new=ForceMixer(arm,idx>0);new.load_state_dict(old.state_dict())
        with torch.no_grad():new.feedback.zero_()
        net.mixer[idx]=new
    return net
