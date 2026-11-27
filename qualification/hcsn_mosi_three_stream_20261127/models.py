"""Three physical hidden stages and the corresponding supervised and random controls."""
from pathlib import Path
import numpy as np
import torch
from torch import nn

SEEDS=(413,677,941)
WIDTHS=(64,256,1024)
RUNGS=(15,60,180)
SHARED=('fp_h','fp_r','random_h','bp_h','transformer')
EXTRA=('fp_h_text','transformer_text','fp_h_shuffle')
RAW=('raw_all','raw_text','raw_av')
SLICES={'text':slice(0,768),'audio':slice(768,773),'vision':slice(773,793)}
PENALTIES=(.001,.03,.3)


def designs():
    return [(w,k) for w in WIDTHS for k in SHARED]+[(64,k) for k in EXTRA]+[(0,k) for k in RAW]


def modalities(x,k):
    if k in ('fp_h_text','transformer_text','raw_text'):
        x=x.clone();x[...,768:]=0
    if k=='raw_av':
        x=x.clone();x[...,:768]=0
    return x


class Physical(nn.Module):
    def __init__(self,path):
        super().__init__()
        with np.load(path) as z:
            self.register_buffer('table',torch.from_numpy(z['fields'].copy()),persistent=False)
            self.register_buffer('center',torch.from_numpy(z['center'][:2].copy()),persistent=False)
            self.k=float(z['k'])

    def forward(self,drive,only_boundary=False):
        m=torch.full_like(drive[:,0],.18);b0=torch.zeros_like(m);fb=torch.zeros_like(m);values=[]
        for x in drive.unbind(1):
            u=(x+fb).tanh();b=torch.log1p(self.k*u);live=m+b0-b
            ax=(u+1)*((self.table.shape[0]-1)/2)
            ay=live.clamp(0,1.2)*((self.table.shape[1]-1)/1.2)
            i=ax.long().clamp(0,self.table.shape[0]-2);j=ay.long().clamp(0,self.table.shape[1]-2)
            a=(ax-i)[...,None];z=(ay-j)[...,None]
            low=self.table[i,j]+z*(self.table[i,j+1]-self.table[i,j])
            hi=self.table[i+1,j]+z*(self.table[i+1,j+1]-self.table[i+1,j])
            f=low+a*(hi-low)
            fb=.15*(f[...,:2]-self.center).tanh().sum(-1);b0=b;m=f[...,3]
            values.append(b if only_boundary else torch.cat((b[...,None],f[...,:3]),-1).flatten(-2))
        return torch.stack(values,1)


def grouped_repr(h):return torch.cat((h.mean(1),h[:,-1]),-1)


class ThreeStage(nn.Module):
    def __init__(self,width,mode,table):
        super().__init__();self.physical=mode!='fp_r';self.width=width
        self.law=Physical(table) if self.physical else None
        self.layers=nn.ModuleList([nn.Linear(i,width,bias=False) for i in (793,width,width)])
        self.head=nn.Linear(2*width*(4 if self.physical else 1),1)
        for j in range(3):
            w=width*(4 if j==2 and self.physical else 1)
            self.register_buffer('mean'+str(j),torch.zeros(w));self.register_buffer('sd'+str(j),torch.ones(w))

    def activation(self,z,j):
        return self.law(z,only_boundary=(j<2)) if self.physical else z.relu()

    def hidden(self,x):
        for j,layer in enumerate(self.layers):
            x=self.activation(layer(x),j)
            x=(x-getattr(self,'mean'+str(j)))/getattr(self,'sd'+str(j))
        return grouped_repr(x)

    def forward(self,x):return self.head(self.hidden(x)).squeeze(-1)


class Attention(nn.Module):
    def __init__(self,w):
        super().__init__();dims={64:(48,2),256:(96,2),1024:(256,3)};d,depth=dims[w]
        self.proj=nn.Linear(793,d);self.pos=nn.Parameter(.02*torch.randn(6,d))
        self.layers=nn.ModuleList([nn.TransformerEncoderLayer(d,4,4*d,0.,activation='gelu',batch_first=True,norm_first=True) for _ in range(depth)])
        self.norm=nn.LayerNorm(d);self.readout=nn.Linear(2*d,1)

    def forward(self,x):
        h=self.proj(x)+self.pos
        for layer in self.layers:h=layer(h)
        return self.readout(grouped_repr(self.norm(h))).squeeze(-1)


class RawRidge(nn.Module):
    def __init__(self,kind):
        super().__init__();self.kind=kind
        self.head=nn.Linear(2*({'raw_all':793,'raw_text':768,'raw_av':25}[kind]),1)

    def inputs(self,x):
        if self.kind=='raw_text':x=x[...,0:768]
        if self.kind=='raw_av':x=x[...,768:]
        return grouped_repr(x)

    def forward(self,x):return self.head(self.inputs(x)).squeeze(-1)


def model(w,arm,table):
    if arm.startswith('raw_'):return RawRidge(arm)
    if arm.startswith('transformer'):return Attention(w)
    return ThreeStage(w,arm,table)


def batch_size(net):
    return 32 if getattr(net,'width',0)>=1024 else 64


@torch.inference_mode()
def predict(net,x):
    net.eval();return torch.cat([net(t).clamp(-3.,3.) for t in x.split(batch_size(net))]).cpu().numpy()


@torch.inference_mode()
def reapply_layer(net,x,j):
    layer=net.layers[j]
    return torch.cat([net.activation(layer(k),j) for k in x.split(batch_size(net))])


@torch.inference_mode()
def setnorm(net,h,j):
    m=h.mean((0,1));s=h.std((0,1),unbiased=False).clamp(min=1e-4)
    getattr(net,'mean'+str(j)).copy_(m);getattr(net,'sd'+str(j)).copy_(s)
    return (h-m)/s


@torch.inference_mode()
def initialize_norms(net,x):
    for j in range(3):x=setnorm(net,reapply_layer(net,x,j),j)


def metrics(z,y,v):
    ids=np.unique(v);abs_err=abs(z-y)
    return float(np.mean([abs_err[v==g].mean() for g in ids])),float(np.mean((z-y)**2))


def read_split(root,part):
    with np.load(Path(root)/(part+'.npz')) as z:return torch.from_numpy(z['x']),torch.from_numpy(z['y']),z['video']
