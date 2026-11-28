"""Normal AVText and chunked entry points with a closed-form law prepared per invocation."""
import torch
from torch.nn import functional as F

from encoder import AVText
from exact_law import AnalyticLaw


class AnalyticAVText(AVText):
    def __init__(self,width,seed,words,law,*,learn_contract=False,continuous=False):
        super().__init__("literal",width,seed,words,law)
        self.law=AnalyticLaw(self.law.grid,self.law.reset,learn_contract=learn_contract,continuous=continuous)

    def encode(self,h):
        law=self.law.for_input(h)
        lower=None
        for mixer,n1,n2,ff in zip(self.mixer,self.n1,self.n2,self.ff):
            update,lower,_=mixer(n1(h),lower,law)
            h=h+update
            h=h+ff(n2(h))
        return F.normalize(self.out(h[:,-1]).float(),dim=-1)

    def encode_chunk(self,h,state=None):
        if h.ndim!=3 or h.size(1)==0:raise ValueError("expected a nonempty [batch,time,width] chunk")
        previous=(None,)*len(self.mixer) if state is None else state
        if len(previous)!=len(self.mixer):raise ValueError("one state per mixer")
        law=self.law.for_input(h)
        lower=None;new=[]
        for mixer,n1,n2,ff,old in zip(self.mixer,self.n1,self.n2,self.ff,previous):
            update,lower,_,next_state=mixer.forward_chunk(n1(h),lower,law,old)
            new.append(next_state);h=h+update;h=h+ff(n2(h))
        return F.normalize(self.out(h[:,-1]).float(),dim=-1),tuple(new)
