"""Two recurrent hidden layers connected only by the true He–Xiong boundary."""
from dataclasses import replace
from pathlib import Path
import sys
import numpy as np
import torch
from torch import nn
from scipy.special import expit
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/"hcsn_sustained_20261128"/"resolvent"))
from closed_form import Contract,Prices

WIDTH=32
NODES=2049


def channels(v,base,p):
    pv=Prices(replace(p,principal=p.principal*(1+.65*v)))
    asset=1.12*base.boundary;x=np.log(asset/pv.boundary)
    loss=pv.credit_loss(x) if x>0 else pv.c/pv.q+pv.A-p.recovery*asset/p.maturity
    return [pv.equity(x)/20.,loss/20.,pv.hit(x)]


def make_table(kind):
    p=Contract();base=Prices(p)
    gain=Prices(replace(p,principal=p.principal*1.65)).boundary/base.boundary-1
    nodes=np.linspace(-1,1,NODES)
    if kind=="financial":
        table=np.array([channels(v,base,p) for v in nodes])
        rng=np.random.default_rng(20261128);probes=rng.uniform(-1,1,300)
        ref=np.array([channels(v,base,p) for v in probes])
        interp=np.column_stack([np.interp(probes,nodes,z) for z in table.T])
        error=np.max(abs(interp-ref),axis=0)
        if max(error)>.001:raise ValueError(f"physical quote grid error {error}")
    elif kind in ("smooth","no_memory"):
        x=np.log(1.12)-np.log1p(gain*nodes)
        table=np.column_stack((np.logaddexp(0,6*x)/3,np.logaddexp(0,-6*x)/3,expit(-7*x)))
        error=np.zeros(3)
    else:raise ValueError(kind)
    return torch.from_numpy(table.astype('float32')),float(gain),error.tolist()


class Network(nn.Module):
    def __init__(self,kind,table,gain):
        super().__init__()
        self.kind=kind;self.gain=gain
        self.register_buffer("table",table)
        self.layers=nn.ModuleList([nn.Linear(8,WIDTH),nn.Linear(WIDTH,WIDTH)])
        self.out=nn.Linear(4*WIDTH,72)

    def activity(self,z):
        v=torch.tanh(z)
        log_ratio=torch.log1p(self.gain*v)
        wire=log_ratio/self.gain
        index=(v+1)*((NODES-1)/2)
        i=torch.floor(index).long().clamp(0,NODES-2)
        frac=(index-i).unsqueeze(-1)
        quote=self.table[i]+frac*(self.table[i+1]-self.table[i])
        return wire,quote,log_ratio

    def memory(self,m,quote,log_ratio):
        if self.kind=="no_memory":return torch.zeros_like(m)
        e,l,f=quote.unbind(-1)
        margin=np.log(1.12)-log_ratio
        return .35*m-.32*torch.tanh(e)*(.15-margin)+.38*torch.tanh(l)-.25*f

    def run_layer(self,x,k,disconnect=False):
        cell=self.layers[k]
        m=x.new_zeros((len(x),WIDTH));wire=[];states=[]
        for frame in x.unbind(1):
            states.append(m)
            a,q,lb=self.activity(cell(frame)+m)
            m=self.memory(m,q,lb)
            wire.append(torch.zeros_like(a) if disconnect else a)
        return torch.stack(wire,1),torch.stack(states,1)

    def features(self,x,disconnect=False):
        a,_=self.run_layer(x,0,disconnect)
        b,_=self.run_layer(a,1)
        return b.flatten(1)

    def forward(self,x,disconnect=False):
        return self.out(self.features(x,disconnect))


def direct_layers(net,X,train,y,seed):
    rng=np.random.default_rng(seed)
    records=[]
    with torch.no_grad():
        source=X[train]
        for i,layer in enumerate(net.layers):
            code=torch.from_numpy((.55*(2*rng.integers(0,2,(72,WIDTH))-1)).astype("float32"))[y[train]]
            target=torch.atanh(code)
            wire,q,lb=net.activity(target)
            err=float(torch.max(torch.abs(torch.expm1(net.gain*wire)/net.gain-code)))
            m=torch.zeros_like(code);ms=[]
            for _ in range(4):
                ms.append(m);m=net.memory(m,q,lb)
            states=torch.stack(ms,1)
            design=source.flatten(0,1).double()
            mean=design.mean(0);D=design-mean
            penalized=D.T@D/len(D)+.002*torch.eye(D.shape[1],dtype=D.dtype)
            residual=[]
            for attempt in range(2):
                wanted=(target[:,None,:]-states).flatten(0,1).double()
                b=wanted.mean(0);W=torch.linalg.solve(penalized,D.T@(wanted-b)/len(D))
                layer.weight.copy_(W.T);layer.bias.copy_(b-mean@W)
                produced,states=net.run_layer(source,i)
                residual.append(float(((produced-net.activity(target)[0][:,None,:])**2).mean().sqrt()))
            source=produced
            records.append(dict(inverse_error=err,rms_boundary_errors=residual))
    return records
