"""Finite-point population, hard-forward LIF, GRU and causal attention comparators."""
import math
import torch
from torch import nn
from torch.nn import functional as ff
from literal_original import Published
CENTERS=(.025,.075,.125,.18,.235,.30,.46,.70)
class PriceLaw(Published):
    def __init__(self):
        super().__init__()
        with torch.enable_grad():
            x=torch.tensor(.18,dtype=torch.float64,requires_grad=True)
            P=torch.tensor(self.p.P0,dtype=torch.float64,requires_grad=True)
            l=self.loss(x,P);e=self.equity(x,P)
            lx,lp=torch.autograd.grad(l,(x,P));ep,=torch.autograd.grad(e,P)
        for n,v in (("L0",l),("Lx",lx),("Lp",lp),("Ep",ep)):self.register_buffer(n,v.detach())
    def loss(self,x,P):
        h=self.p.m;s=self.p.sigma*math.sqrt(h);chi=math.sqrt(self.mu**2+2*self.q*self.var)
        z=x.clamp_min(0)
        def part(sign):
            return torch.exp((-self.mu+sign*chi)*z/self.var)*torch.special.ndtr((-z-sign*chi*h)/s)
        disc=part(1)+part(-1);a=self.c/self.q;b=P/self.p.m
        recovery=self.p.alpha*self.boundary(P)/self.p.m
        return torch.where(x>0,self.disc*(b-a)*self.passage(z,h)+(a-recovery)*disc,
                           a+self.disc*(b-a)-recovery)
    def features(self,x,P,arm):
        if arm=="gate":
            dx=.18*torch.tanh((x-.18)/.18);dp=.28*self.p.P0*torch.tanh((P-self.p.P0)/(.28*self.p.P0))
            return (self.dA0*dx+self.Ep*dp)/20,(self.Lx*dx+self.Lp*dp)*self.dF0/self.Lx
        pos=x.clamp_min(0);E=(torch.where(x>0,self.equity(pos,P),torch.zeros_like(x))-self.A0)/20
        if arm=="probability":
            risk=torch.where(x>0,self.passage(pos,self.p.m),torch.ones_like(x))-self.F0
        else:risk=(self.loss(x,P)-self.L0)*self.dF0/self.Lx
        return E,risk

def killed(x,edges,law,dt=.25):
    z=x.clamp_min(0)[...,None];s=law.p.sigma*math.sqrt(dt)
    S=torch.special.ndtr((z+law.mu*dt-edges)/s)-torch.exp(-2*law.mu*z/law.var)*torch.special.ndtr((-z+law.mu*dt-edges)/s)
    S=torch.where(x[...,None]>0,S,torch.zeros_like(S))
    return torch.cat((S[...,:-1]-S[...,1:],S[...,-1:]),-1),1-S[...,0]

class Population(nn.Module):
    def __init__(self,d,cls,arm,n=4):
        super().__init__();self.arm=arm;self.law=PriceLaw()
        self.drive=nn.Linear(d,n);self.rec=nn.Linear(n,n,bias=False)
        self.gain=nn.Parameter(torch.full((2,n),math.log(math.expm1(.4))))
        self.head=nn.Linear(4*n,cls)
        c=torch.tensor(CENTERS,dtype=torch.float64)
        self.register_buffer("centers",c);self.register_buffer("edges",torch.cat((c.new_zeros(1),(c[1:]+c[:-1])/2)))
        self.register_buffer("initial",(c==.18).double());self.register_buffer("reset",(c==.3).double());self.double()
    def forward(self,seq,remove="",trace=False):
        b=seq.new_zeros(len(seq),self.drive.out_features);e=r=refr=b
        active=self.initial.expand(len(seq),self.drive.out_features,-1);never=active
        gains=ff.softplus(self.gain);bounds=[];spikes=[];audit=[]
        for frame in seq.unbind(1):
            d=self.drive(frame)+self.rec(b)
            if remove not in ("both","equity"):d=d+gains[0]*torch.tanh(e)
            if remove not in ("both","risk"):d=d+gains[1]*torch.tanh(r)
            P=self.law.p.P0*(1+.28*torch.tanh(d));newb=torch.log(self.law.boundary(P)/self.law.B0)
            x=self.centers+(b-newb)[...,None]
            ee,rr=self.law.features(x,P[...,None],self.arm)
            e=(active*ee).sum(-1);r=(active*rr).sum(-1)
            K,H=killed(x,self.edges,self.law);h=(active*H).sum(-1)
            new=(active[...,None]*K).sum(-2)
            if remove=="reset":refr=refr+h
            else:new=new+refr[...,None]*self.reset;refr=h
            if trace:
                first=(never*H).sum(-1);never=(never[...,None]*K).sum(-2)
                audit.append(torch.stack((h,first,h-first,new.sum(-1)+refr,P,newb),-1))
            active,b=new,newb;bounds.append(b);spikes.append(h)
        v=self.head(torch.cat((b,h,torch.stack(bounds,1).mean(1),torch.stack(spikes,1).mean(1)),-1))
        return (v,torch.stack(audit,1)) if trace else v

class LIF(nn.Module):
    def __init__(self,d,cls,n=4):
        super().__init__();self.drive=nn.Linear(d,n);self.rec=nn.Linear(n,n,bias=False)
        self.dynamics=nn.Parameter(torch.zeros(2,n));self.head=nn.Linear(4*n,cls);self.double()
    def forward(self,seq):
        u=seq.new_zeros(len(seq),self.drive.out_features);s=u;volt=[];events=[]
        threshold=.3+ff.softplus(self.dynamics[1]);decay=torch.sigmoid(self.dynamics[0])
        for frame in seq.unbind(1):
            pre=decay*u+self.drive(frame)+self.rec(s);smooth=torch.sigmoid(5*(pre-threshold))
            s=(pre>=threshold).to(pre)+smooth-smooth.detach();u=pre-s*threshold
            volt.append(pre);events.append(s)
        return self.head(torch.cat((pre,s,torch.stack(volt,1).mean(1),torch.stack(events,1).mean(1)),-1))
class GRU(nn.Module):
    def __init__(self,d,cls,n=4):
        super().__init__();self.gru=nn.GRU(d,n,batch_first=True);self.head=nn.Linear(2*n,cls);self.double()
    def forward(self,seq):
        h,_=self.gru(seq);return self.head(torch.cat((h[:,-1],h.mean(1)),-1))
class Encoder(nn.Module):
    def __init__(self,d,cls,w):
        super().__init__();self.heads=2 if w==16 else 1
        self.embed=nn.Linear(d,w);self.position=nn.Parameter(torch.empty(8,w));nn.init.normal_(self.position,std=.02)
        self.n1=nn.LayerNorm(w);self.qkv=nn.Linear(w,3*w);self.project=nn.Linear(w,w)
        self.n2=nn.LayerNorm(w);self.ff=nn.Sequential(nn.Linear(w,2*w),nn.GELU(),nn.Linear(2*w,w))
        self.out=nn.Linear(2*w,cls);self.double()
    def forward(self,seq):
        h=self.embed(seq)+self.position;b,t,w=h.shape
        q,k,v=self.qkv(self.n1(h)).reshape(b,t,3,self.heads,w//self.heads).permute(2,0,3,1,4)
        a=ff.scaled_dot_product_attention(q,k,v,is_causal=True)
        h=h+self.project(a.transpose(1,2).reshape(b,t,w));h=h+self.ff(self.n2(h))
        return self.out(torch.cat((h[:,-1],h.mean(1)),1))
def make(arm,d,k):
    if arm=="lif":return LIF(d,k)
    if arm=="gru":return GRU(d,k)
    if arm.startswith("transformer"):return Encoder(d,k,int(arm.removeprefix("transformer")))
    return Population(d,k,arm)
