"""Wall-only continuous population encoder with batched stationary prices and expected refractory occupancy."""
import functools
from pathlib import Path
import sys
import math
import numpy as np
import torch
from torch import nn
from torch.nn import functional as F
sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
from model import BANDS, WIDTH, Classifier,reference_prices,passage

ARMS=('wall_literal','wall_smooth','wall_direct','wall_flexible','cnn')
GRID=.001;REF=.10;TOP=.90;DT=.05;DRIFT=-.10
@functools.lru_cache(None)
def tables():
    x=np.arange(901)*GRID
    coeff,beta=reference_prices(x)
    passage_values=passage(x,DRIFT,DT)
    return torch.tensor(coeff,dtype=torch.float32),torch.tensor(passage_values,dtype=torch.float32),beta

def affine_prefix(a,b):
    """Inclusive prefix of scalar affine maps r -> a r+b, initially r=0."""
    hop=1
    while hop<b.shape[1]:
        old_a,old_b=a,b
        a=torch.cat([old_a[:,:hop],old_a[:,hop:]*old_a[:,:-hop]],1)
        b=torch.cat([old_b[:,:hop],old_b[:,hop:]+old_a[:,hop:]*old_b[:,:-hop]],1)
        hop*=2
    return b
class Wall(nn.Module):
    def __init__(self,dim,kind):
        super().__init__()
        self.kind=kind;pr,prob,self.beta=tables()
        self.register_buffer('price',pr);self.register_buffer('p_hit',prob)
        self.causal=nn.Conv1d(dim,2*WIDTH,3)
        self.memory=nn.Parameter(torch.zeros(WIDTH));self.retain=nn.Parameter(torch.full((WIDTH,),.4))
        self.gains=nn.Parameter(torch.tensor([1.,.4,-.4,.55,-.20]).repeat(WIDTH,1))
        if kind=='wall_flexible':self.profile=nn.Parameter(torch.zeros(17,5))
        i=int(round(REF/GRID));vals=pr[:,i];slopes=(pr[:,i+1]-pr[:,i-1])/(2*GRID)
        self.register_buffer('p0',vals);self.register_buffer('dp0',slopes)
        self.register_buffer('q0',prob[i]);self.register_buffer('dq0',(prob[i+1]-prob[i-1])/(2*GRID))
    def response(self,x,rel):
        if self.kind=='wall_literal':
            coord=(x/GRID).clamp(0,len(self.p_hit)-1);ix=coord.long().clamp(max=len(self.p_hit)-2);f=coord-ix
            base=torch.lerp(self.price[0,ix],self.price[0,ix+1],f[...,None])
            slope=torch.lerp(self.price[1,ix],self.price[1,ix+1],f[...,None])
            price=base+rel[...,None]*slope
            hit=torch.lerp(self.p_hit[ix],self.p_hit[ix+1],f)
            return price[...,0],price[...,1],hit
        delta=x-REF
        ref=self.p0[0]+rel[...,None]*self.p0[1];sl=self.dp0[0]+rel[...,None]*self.dp0[1]
        E0=ref[...,0].clamp_min(.00001);L0=ref[...,1].clamp_min(.00001)
        eq=E0*F.softplus((2*math.log(2.)*sl[...,0]/E0)*delta)/math.log(2.)
        loss=L0*(1.+torch.tanh((sl[...,1]/L0)*delta))
        logit=torch.logit(self.q0)+(self.dq0/(self.q0*(1.-self.q0)))*delta
        if self.kind=='wall_flexible':
            index=((x+.30)/.075).clamp(0,16);i=index.long().clamp(max=15)
            t=torch.lerp(self.profile[i],self.profile[i+1],(index-i)[...,None])
            eq=eq+.15*(t[...,0]+rel*t[...,1]).tanh()
            loss=loss+.15*(t[...,2]+rel*t[...,3]).tanh()
            logit=logit+5*t[...,4].tanh()
        return eq,loss,logit.sigmoid()

    def forward(self,x,view='natural',state=False):
        h,b=self.causal(F.pad(x.transpose(1,2),(2,0))).transpose(1,2).chunk(2,-1)
        if self.kind=='wall_direct':
            outgoing=torch.log1p(self.beta*.21*torch.tanh(h*self.gains[:,0]))
            return (outgoing,()) if state else outgoing
        bounded=b.tanh();relative=.21*bounded;wall=torch.log1p(self.beta*relative)
        g=.03+.94*self.memory.sigmoid()
        index=torch.arange(x.shape[1],device=x.device)
        shift=index[:,None]-index[None,:]
        kernel=(1.-g[:,None,None])*g[:,None,None].pow(shift.clamp_min(0)[None])*((shift>=0)[None])
        filtered=torch.einsum('bsw,wts->btw',h.tanh(),kernel)
        margin=.12+.30*filtered-wall
        eq,loss,q=self.response(margin,relative)
        r=affine_prefix(self.retain.sigmoid()-q,q)
        pre=F.pad(r[:,:-1],(0,0,1,0))
        flux=(1.-pre)*q
        local=torch.stack([h,torch.tanh((eq-self.p0[0,0])*18),torch.tanh((loss-self.p0[0,1])*12),
                           flux,r],-1)
        mix=(local*self.gains).sum(-1)
        if view=='no_equity':mix=mix-local[...,1]*self.gains[:,1]
        if view=='no_flux':mix=mix-local[...,3]*self.gains[:,3]
        outgoing=torch.log1p(self.beta*.21*mix.tanh())
        return (outgoing,(r,pre,flux,q,margin,eq,loss)) if state else outgoing
class WallClassifier(nn.Module):
    def __init__(self,arm):
        super().__init__()
        if arm not in ARMS:raise ValueError(arm)
        self.arm=arm
        if arm=='cnn':self.model=Classifier('cnn');return
        self.one=Wall(BANDS,arm);self.two=Wall(WIDTH,arm);self.head=nn.Linear(4*WIDTH,20)
    def event_stream(self,x,view='natural'):
        coord=self.one(x,view)
        if view=='clamp_wire':coord=torch.zeros_like(coord)
        if view=='shuffle_wire':coord=coord.roll(1,0)
        return self.two(coord/(self.one.beta*.21),view)/(self.two.beta*.21)
    def forward(self,x,view='natural'):
        if self.arm=='cnn':return self.model(x)
        out=self.event_stream(x,view)
        return self.head(out.reshape(x.shape[0],4,7,WIDTH).mean(2).flatten(1))
