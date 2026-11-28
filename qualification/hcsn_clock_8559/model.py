"""Original-clock SHD models with a finite, recurrent He–Xiong population."""
from pathlib import Path
import math
import sys
import numpy as np
from scipy.special import ndtr
import torch
from torch import nn
from torch.nn import functional as F

# Import the pinned financial valuation; do not approximate it by an unrelated activation.
sys.path.insert(0,str(Path(__file__).resolve().parent))
from he_xiong import Published

WIDTH, BANDS, STEPS = 48, 28, 28
ATOMS=np.array([.025,.09,.18,.34],dtype=np.float64)
DT=.05
SIGMA=.23
ARMS=('literal','smooth','fixed','no_feedback','lif','cnn','attention')


def exact_prob(wall_shift,mu):
    """Return [old active atom, four live bins + first crossing] for the 50 ms window."""
    x=ATOMS-np.asarray(wall_shift)[...,None]
    m=np.asarray(mu)[...,None]
    live=np.maximum(x,0)
    cut=(ATOMS[1:]+ATOMS[:-1])/2
    edges=np.r_[0.,cut,np.inf]
    x3,m3=live[...,None],m[...,None]
    s=SIGMA*math.sqrt(DT)
    free=ndtr((edges-x3-m3*DT)/s)
    mirror=ndtr((edges+x3-m3*DT)/s)
    parts=np.diff(free-np.exp(-2*m3*x3/SIGMA**2)*mirror,axis=-1)
    parts=np.where(x[...,None]>0,np.maximum(parts,0.),0.)
    hit=1.-parts.sum(-1,keepdims=True)
    out=np.concatenate((parts,hit),axis=-1).clip(0.,1.)
    return out/out.sum(-1,keepdims=True)


def passage(x,mu,t):
    s=SIGMA*math.sqrt(t)
    return ndtr((-x-mu*t)/s)+np.exp(-2*mu*x/SIGMA**2)*ndtr((-x+mu*t)/s)


def reference_prices(x):
    p=Published()
    x=torch.as_tensor(x,dtype=torch.float64)
    vec=[]
    for scale in [0.,1.]:
        P=torch.full_like(x,p.p.P0*(1+scale))
        E=p.equity(x,P)
        def hit(y):
            s=p.p.sigma*math.sqrt(p.p.m)
            dr=y*p.var*p.p.m
            return torch.exp(-(p.a-y)*x)*torch.special.ndtr((-x-dr)/s)+torch.exp(-(p.a+y)*x)*torch.special.ndtr((-x+dr)/s)
        loss=p.disc*(P/p.p.m-p.c/p.q)*hit(p.a)+(p.c/p.q-p.p.alpha*p.boundary(P)/p.p.m)*hit(p.zb)
        vec.append(torch.stack([E/100,loss/100],dim=-1).detach().numpy())
    return np.stack([vec[0],vec[1]-vec[0]]),p.bp*p.p.P0/p.B0


def physical_table(arm):
    shifts=np.linspace(-.45,.45,181)
    drifts=np.linspace(-.35,.15,41)
    shift,mu=np.meshgrid(shifts,drifts,indexing='ij')
    probs=exact_prob(shift,mu)
    coeff,beta=reference_prices(ATOMS)
    if arm=='smooth':
        delta=1e-5
        origin=np.maximum(exact_prob(0.,-.10),1e-8)
        dx=(exact_prob(delta,-.10)-exact_prob(-delta,-.10))/(2*delta)
        dm=(exact_prob(0.,-.10+delta)-exact_prob(0.,-.10-delta))/(2*delta)
        logits=np.log(origin)+shift[...,None,None]*dx/origin+(mu[...,None,None]+.10)*dm/origin
        probs=np.exp(logits-logits.max(-1,keepdims=True));probs/=probs.sum(-1,keepdims=True)
        # Match prices and price slopes at the reset point for all operating principals.
        pc,_=reference_prices(np.array([.18-delta,.18,.18+delta]))
        slope=(pc[:,2]-pc[:,0])/(2*delta)
        coeff=pc[:,1:2]+(ATOMS[None,:,None]-.18)*slope[:,None,:]
    horizons=np.stack([passage(ATOMS[None,:],drifts[:,None],t) for t in [.05,.10,.20]],axis=-1)
    return probs,coeff,horizons,beta


class Population(nn.Module):
    def __init__(self,dim,arm):
        super().__init__()
        self.arm=arm
        arr,prices,horizons,beta=physical_table(arm)
        self.register_buffer('table',torch.tensor(arr.reshape(-1,4,5),dtype=torch.float32))
        self.register_buffer('coeff',torch.tensor(prices,dtype=torch.float32))
        self.register_buffer('probes',torch.tensor(horizons,dtype=torch.float32))
        self.beta=beta
        self.inp=nn.Linear(dim,WIDTH)
        self.recurrent=nn.Linear(WIDTH,WIDTH,bias=False)
        self.feedback=nn.Parameter(torch.full((WIDTH,2),.15))
        self.emitter=nn.Parameter(torch.tensor([1.,1.,.5,-.5,.3,.2,.1]).repeat(WIDTH,1))
        self.register_buffer('reset',torch.tensor([0.,0.,1.,0.]))

    def transition(self,shift,mu):
        i=((shift+.45)/.005).clamp(0,180)
        j=((mu+.35)/.0125).clamp(0,40)
        ix=i.long().clamp(max=179);jx=j.long().clamp(max=39)
        ai=(i-ix).unsqueeze(-1).unsqueeze(-1)
        aj=(j-jx).unsqueeze(-1).unsqueeze(-1)
        pos=ix*41+jx
        a=torch.lerp(self.table[pos],self.table[pos+1],aj)
        b=torch.lerp(self.table[pos+41],self.table[pos+42],aj)
        return torch.lerp(a,b,ai),jx,aj

    def forward(self,x):
        drive=self.inp(x);z=torch.zeros_like(drive[:,0]);wall=z;signal=z;refr=z
        price=z[...,None].expand(-1,-1,2)
        mass=self.reset.expand(*z.shape,4)
        history=[]
        for frame in drive.unbind(1):
            fb=(torch.tanh(price)*self.feedback).sum(-1)
            u=frame+self.recurrent(signal)+(0.*fb if self.arm=='no_feedback' else fb)
            bounded=torch.tanh(u)
            relative=.21*bounded if self.arm!='fixed' else 0.*bounded
            new_wall=torch.log1p(self.beta*relative)
            mu=-.10+.25*bounded
            kernel,j,frac=self.transition(new_wall-wall,mu)
            arrival=(mass[...,None]*kernel).sum(-2)
            mass=arrival[...,:4]+refr[...,None]*self.reset
            refr=arrival[...,4]
            price=(mass[...,None]*(self.coeff[0]+relative[...,None,None]*self.coeff[1])).sum(-2)
            horizon=torch.lerp(self.probes[j],self.probes[j+1],frac)
            horizons=(mass[...,None]*horizon).sum(-2)
            coords=torch.cat((new_wall[...,None],refr[...,None],price,horizons),dim=-1)
            signal=(coords*self.emitter).sum(-1);wall=new_wall
            history.append(signal)
        return torch.stack(history,dim=1)


class Lif(nn.Module):
    def __init__(self,dim):
        super().__init__()
        self.inp=nn.Linear(dim,WIDTH);self.rec=nn.Linear(WIDTH,WIDTH,bias=False)
        self.decay=nn.Parameter(torch.full((WIDTH,),1.5))
        self.threshold=nn.Parameter(torch.zeros(WIDTH))
    def forward(self,x):
        drive=self.inp(x);mem=torch.zeros_like(drive[:,0]);spk=mem;rows=[]
        for cur in drive.unbind(1):
            u=self.decay.sigmoid()*mem+cur+self.rec(spk)
            delta=u-(.25+F.softplus(self.threshold))
            smooth=torch.sigmoid(5*delta)
            nxt=((delta>0).to(u)+smooth-smooth.detach())*(1-spk.detach())
            mem=u*(1-nxt.detach());spk=nxt;rows.append(spk)
        return torch.stack(rows,1)


class Classifier(nn.Module):
    def __init__(self,arm):
        super().__init__()
        self.arm=arm
        if arm in ('literal','smooth','fixed','no_feedback','lif'):
            mod=Lif if arm=='lif' else lambda n: Population(n,arm)
            self.one=mod(BANDS);self.two=mod(WIDTH)
        elif arm=='cnn':
            self.one=nn.Conv1d(BANDS,WIDTH,5);self.two=nn.Conv1d(WIDTH,WIDTH,5)
        elif arm=='attention':
            self.proj=nn.Linear(BANDS,WIDTH)
            self.pos=nn.Parameter(torch.randn(1,STEPS,WIDTH)*.02)
            self.one=self.attention();self.two=self.attention()
        else: raise ValueError(arm)
        self.head=nn.Linear(4*WIDTH,20)

    @staticmethod
    def attention():
        return nn.TransformerEncoderLayer(WIDTH,4,dim_feedforward=2*WIDTH,batch_first=True,
                                          dropout=0.,activation='gelu',norm_first=True)
    def forward(self,x):
        if self.arm=='cnn':
            h=F.gelu(self.one(F.pad(x.transpose(1,2),(4,0))))
            y=F.gelu(self.two(F.pad(h,(4,0)))).transpose(1,2)
        elif self.arm=='attention':
            h=self.proj(x)+self.pos[:,:x.size(1)]
            mask=torch.ones(x.shape[1],x.shape[1],device=x.device,dtype=torch.bool).triu(1)
            y=self.two(self.one(h,src_mask=mask),src_mask=mask)
        else:
            y=self.two(self.one(x))
        return self.head(y.reshape(x.size(0),4,7,WIDTH).mean(2).flatten(1))
