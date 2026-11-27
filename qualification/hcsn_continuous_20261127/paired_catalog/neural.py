"""Matched differentiable dual-boundary and conventional dual encoders for scratch catalog retrieval."""
from pathlib import Path
import sys,time,json,hashlib,copy,os
import numpy as np
import torch
from torch import nn
from torch.nn import functional as F
from common import ROOT,setup_data,gallery,score,lex
from construct import chunks
from adam import Adam
class PhysicalTower(nn.Module):
    def __init__(self,dim,rank,z,side):
        super().__init__();self.side=side;self.dim=dim;self.rank=rank
        self.first=nn.Linear(dim,rank);self.second=nn.Linear(4*rank,rank)
        self.read=nn.Linear(4*rank*4,rank)
        self.register_buffer('values',torch.from_numpy(z['fields']))
        self.register_buffer('center',torch.from_numpy(z['center']))
        self.k=float(z['k'])
    def flow(self,projected):
        table=self.values;tmax=table.shape[0]-1;xmax=table.shape[1]-1
        prev=torch.zeros_like(projected[:,0]);margin=prev+.18;feed=prev;result=[]
        for piece in projected.unbind(1):
            t=(piece+feed).tanh();b=(t*self.k).log1p()
            x=(margin+prev-b).clamp(0,1.2);ti=(t+1)*(tmax/2);xi=x*(xmax/1.2)
            i=ti.long().clamp(0,tmax-1);j=xi.long().clamp(0,xmax-1)
            v=(ti-i).unsqueeze(-1);w=(xi-j).unsqueeze(-1)
            val=(1-v)*((1-w)*table[i,j]+w*table[i,j+1])+v*((1-w)*table[i+1,j]+w*table[i+1,j+1])
            feed=.15*(val[...,0]-self.center[0]).tanh()+.15*(val[...,1]-self.center[1]).tanh()
            result.append(torch.stack([b,val[...,0],val[...,1],val[...,2]],-1))
            prev=b;margin=val[...,3]
        return torch.stack(result,1)
    def cumulative(self,hidden,linear):
        B=hidden.shape[0]
        w=linear.weight.reshape(self.rank,4,-1)
        return torch.einsum('btd,rtd->btr',hidden.reshape(B,4,-1),w).cumsum(1)+linear.bias
    def forward(self,features):
        if self.side=='x':u=self.cumulative(features,self.first)
        else:u=self.first(features)
        boundary=self.flow(u)[...,0]
        read=self.flow(self.cumulative(boundary,self.second))
        return self.read(read.flatten(1))
class AttnPool(nn.Module):
    def __init__(self,width,tokens):
        super().__init__();self.pos=nn.Parameter(torch.randn(1,tokens,width)*.01)
        self.norm=nn.LayerNorm(width);self.qkv=nn.Linear(width,3*width);self.out=nn.Linear(width,width)
        self.mlp=nn.Sequential(nn.LayerNorm(width),nn.Linear(width,2*width),nn.GELU(),nn.Linear(2*width,width))
    def forward(self,x,valid=None):
        x=x+self.pos[:,:x.size(1)]
        q,k,v=self.qkv(self.norm(x)).reshape(x.size(0),x.size(1),3,4,-1).permute(2,0,3,1,4).unbind(0)
        mask=valid[:,None,None,:] if valid is not None else None
        a=F.scaled_dot_product_attention(q,k,v,attn_mask=mask).transpose(1,2).reshape_as(x)
        x=x+self.out(a);x=x+self.mlp(x)
        if valid is None:return x.mean(1)
        return (x*valid.unsqueeze(-1)).sum(1)/valid.sum(1,keepdim=True).clamp_min(1)
class Conventional(nn.Module):
    def __init__(self,vocab,rank):
        super().__init__();w=64
        self.conv=nn.Sequential(nn.Conv2d(3,32,5,stride=2,padding=2),nn.GroupNorm(4,32),nn.GELU(),nn.Conv2d(32,w,3,stride=2,padding=1),nn.GroupNorm(4,w),nn.GELU(),nn.Conv2d(w,w,3,stride=2,padding=1),nn.GELU())
        self.image_pool=AttnPool(w,16);self.word=nn.Embedding(vocab,w,padding_idx=0);self.text_pool=AttnPool(w,16)
        self.image_read=nn.Linear(w,rank);self.text_read=nn.Linear(w,rank)
    def forward(self,x,t):
        a=self.conv(x).flatten(2).transpose(1,2)
        return self.image_read(self.image_pool(a)),self.text_read(self.text_pool(self.word(t),t!=0))
class Pair(nn.Module):
    def __init__(self,kind,d,z,rank=48):
        super().__init__();self.kind=kind
        if kind=='physical_bp':
            self.image=PhysicalTower(336,rank,z,'x');self.text=PhysicalTower(512,rank,z,'y')
        else:self.backbone=Conventional(int(np.max(d['tokens']))+1,rank)
    def forward(self,x,t):
        if self.kind=='physical_bp':return self.image(x),self.text(t)
        return self.backbone(x,t)
class Inputs:
    def __init__(self,kind,d,vision,dev):
        self.kind=kind;self.d=d;self.dev=dev;self.vision=vision
        self.pixel=np.load(ROOT/'pixels32.npy',mmap_mode='r')
        self.center=None
        if kind=='physical_bp':
            ix=np.flatnonzero(d['split']==0)
            self.center=vision[ix].mean(0);self.spread=np.maximum(vision[ix].std(0),.03)
    def batch(self,ix):
        w=self.d['tokens'][ix]
        if self.kind=='physical_bp':
            a=(self.vision[ix]-self.center)/self.spread
            t=np.stack([lex(w,p) for p in [4,8,12,16]],1)
        else:
            a=(self.pixel[ix].astype('float32')/255.-.5).transpose(0,3,1,2);t=w.astype(np.int64)
        return torch.from_numpy(np.ascontiguousarray(a)).to(self.dev),torch.from_numpy(t).to(self.dev)
def predictions(net,inputs,ix):
    net.eval();image=[];text=[]
    with torch.no_grad():
        for ids in chunks(ix,128):
            a,b=net(*inputs.batch(ids));image.append(a.cpu().numpy());text.append(b.cpu().numpy())
    return np.concatenate(image),np.concatenate(text)
def fresh(kind,d,vision,device):
    with np.load(ROOT/'law.npz') as f:z=dict(f)
    return Pair(kind,d,z).to(device),Inputs(kind,d,vision,device)
def masked_infonce(x,y,aliases):
    sims=F.normalize(x,dim=-1)@F.normalize(y,dim=-1).T/.07
    mask=(aliases[:,None]==aliases[None,:])&~torch.eye(len(aliases),dtype=torch.bool,device=aliases.device)
    sims=sims.masked_fill(mask,-1e4)
    labels=torch.arange(len(x),device=x.device)
    return (F.cross_entropy(sims,labels)+F.cross_entropy(sims.T,labels))/2
def fit(kind,seed):
    begin=time.monotonic();torch.set_num_threads(1);torch.manual_seed(seed)
    d,V=setup_data();tr=np.flatnonzero(d['split']==0);dv=gallery(d,1);device=os.environ.get('HCSN_CATALOG_DEVICE','cpu')
    net,inputs=fresh(kind,d,V,device);rng=np.random.default_rng(seed);target=ROOT/'neural_fitted';target.mkdir(exist_ok=True)
    path=target/f'{kind}-{seed}'
    meta=Path(str(path)+'.json')
    if meta.exists():return
    opt=Adam(net.parameters(),.001,weight_decay=.001);n=0;active=0.;best=(-1,-1);hist=[]
    for step in range(1537):
        if step in [0,96,384,1536]:
            x,y=predictions(net,inputs,dv);metrics,_=score(x,y,d,dv)
            hist.append(dict(step=step,active_s=active,metrics=metrics))
            observed=(metrics['strict_R1'],metrics['strict_R5'])
            if observed>best:
                best=observed;selected=step;torch.save(net.state_dict(),str(path)+'.pt')
            if step==1536:break
        t=time.perf_counter();ix=rng.choice(tr,96,replace=False);net.train();opt.zero_grad()
        x,y=net(*inputs.batch(ix));loss=masked_infonce(x,y,torch.tensor(d['title'][ix],device=device))
        loss.backward();opt.step()
        if device!='cpu':torch.cuda.synchronize()
        active+=time.perf_counter()-t
    result={'kind':kind,'seed':seed,'device':device,'torch':torch.__version__,'params':sum(p.numel() for p in net.parameters()),'selected':selected,'development':hist,'complete_wall_s':time.monotonic()-begin,'sha256':hashlib.sha256(Path(str(path)+'.pt').read_bytes()).hexdigest()}
    meta.write_text(json.dumps(result,indent=1));print(kind,seed,selected,hist[-1],flush=True)
if __name__=='__main__':fit(sys.argv[1],int(sys.argv[2]))
