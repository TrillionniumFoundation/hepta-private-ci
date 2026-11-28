"""A parameter-matched shared encoder for audio-video and candidate label texts."""
import torch
from torch import nn
from torch.nn import functional as F
from hcsn_temporal import Phys, Attention, Law


class AVText(nn.Module):
    def __init__(self,arm,width,seed,words,law):
        super().__init__()
        torch.manual_seed(seed)
        self.arm=arm
        self.width=width
        self.groups=32 if width==4096 else 16
        self.law=Law(law)
        self.sound=nn.Linear(64,width)
        self.face=nn.Linear(28*28,width)
        self.word=nn.Embedding(words,width,padding_idx=0)
        self.position=nn.Parameter(torch.randn(12,width)*.015)
        self.type_code=nn.Parameter(torch.randn(2,width)*.015)
        self.n1=nn.ModuleList(nn.LayerNorm(width) for _ in range(6))
        self.n2=nn.ModuleList(nn.LayerNorm(width) for _ in range(6))
        self.ff=nn.ModuleList(nn.Sequential(nn.Linear(width,width*4),nn.GELU(),nn.Linear(width*4,width)) for _ in range(6))
        self.out=nn.Sequential(nn.LayerNorm(width),nn.Linear(width,256,bias=False))
        torch.manual_seed(seed+21019)
        self.mixer=nn.ModuleList(Attention(width) if arm=='sdpa' else Phys(arm,width,self.groups,j>0) for j in range(6))

    def encode(self,h):
        mark=None
        for mixer,n1,n2,ff in zip(self.mixer,self.n1,self.n2,self.ff):
            y,mark,_=mixer(n1(h),mark,self.law)
            h=h+y
            h=h+ff(n2(h))
        return F.normalize(self.out(h[:,-1]).float(),dim=-1)

    def encode_chunk(self,h,state=None):
        """Encode new embedded frames and return the recurrent state for the next chunk."""
        if h.ndim!=3 or h.size(1)==0:
            raise ValueError("expected a nonempty [batch,time,width] chunk")
        previous=(None,)*len(self.mixer) if state is None else state
        if len(previous)!=len(self.mixer):
            raise ValueError("one state per mixer is required")
        lower=None
        next_state=[]
        for mixer,n1,n2,ff,old in zip(self.mixer,self.n1,self.n2,self.ff,previous):
            y,lower,_,new=mixer.forward_chunk(n1(h),lower,self.law,old)
            h=h+y
            h=h+ff(n2(h))
            next_state.append(new)
        return F.normalize(self.out(h[:,-1]).float(),dim=-1),tuple(next_state)

    def front(self,v,a):
        return self.face(v.float().flatten(2)/127.5-1)+self.sound(a)+self.position+self.type_code[0]

    def text(self,t):
        return self.word(t)+self.position+self.type_code[1]

    def forward(self,v,a,t):
        h=torch.cat((self.front(v,a),self.text(t)))
        return self.encode(h).split((len(v),len(t)),dim=0)


def pair_loss(v,t,labels):
    logits=(v@t.T)*12.
    target=(labels[:,None]==labels).float()
    return -.5*((logits.log_softmax(1)*target).sum(1)/target.sum(1)).mean()-.5*((logits.T.log_softmax(1)*target).sum(1)/target.sum(1)).mean()
