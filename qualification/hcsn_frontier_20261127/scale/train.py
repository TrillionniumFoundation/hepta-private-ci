"""Offline paired image-caption training; assembled with pinned pricing code and public inputs."""
import base64
import contextlib
import hashlib
import io
import json
import os
from pathlib import Path
import platform
import tempfile
import time

import numpy as np
import torch
from torch import nn
from torch.nn import functional as F

# An assembled standalone copy prepends Published/BoundaryPopulation and embeds PACK, CAP.
SIZES=((384,6),(640,8))
ARMS=('physical','smooth','mean','dense')
SEEDS=(137,391,757)


def law_tables():
    cell=BoundaryPopulation(1,1,12)
    p=cell.prices;x=cell.grid
    shifts=torch.arange(-3072,3073,dtype=torch.float64)/4096
    margin=x+shifts[:,None]
    with torch.no_grad():
        q,f=cell.kernels(margin)
        def price(grid):
            original=cell.grid
            cell.grid=grid
            rel=grid.new_tensor([-.25,0,.25]);e,l=cell.priced_channels((1+rel)*p.p.P0)
            cell.grid=original
            return torch.stack([e,l],-1)/20
        values=price(x)
        def geom(v):
            return torch.cat([v[1],2*(v[2]-v[0])],-1)
        exactp=geom(values)
        a0=x.new_tensor([.18]);eps=1e-5
        price0=price(a0);dp=(price(a0+eps)-price(a0-eps))/(2*eps)
        ordinary=geom(price0+torch.tanh((x[None,:,None]-.18)*dp))
        f0=p.passage(a0,.25);slope=(p.passage(a0+eps,.25)-p.passage(a0-eps,.25))/(2*eps)
        soft=torch.where(margin>0,torch.sigmoid(torch.logit(f0)+(margin-.18)*slope/(f0*(1-f0))),torch.ones_like(f))
        scale=torch.where(f<1-1e-15,(1-soft)/(1-f).clamp_min(1e-15),torch.zeros_like(f))
        special=torch.cat([q,f[...,None]],-1)
        smooth=torch.cat([q*scale[...,None],soft[...,None]],-1)
        assert (special.sum(-1)-1).abs().max()<1e-12
        assert (smooth.sum(-1)-1).abs().max()<1e-8
    return dict(physical=(special.float(),exactp.float()),smooth=(smooth.float(),ordinary.float()),
                reset=cell.reset_weights.float(),ratio=p.bp*p.p.P0/p.B0)


class Prefix(nn.Module):
    def __init__(self,d,kind,tables):
        super().__init__();self.kind=kind
        self.content=nn.Linear(12,d)
        if kind in ('physical','smooth'):
            self.drive=nn.Linear(12,8)
            self.feedback=nn.Parameter(torch.full((8,2),.15))
            tr,price=tables[kind]
            self.register_buffer('tr',tr,persistent=False);self.register_buffer('price',price,persistent=False)
            self.register_buffer('reset',tables['reset'],persistent=False);self.ratio=tables['ratio']

    def forward(self,patch):
        content=self.content(patch)
        if self.kind=='dense':return content.flatten(1,2)
        if self.kind=='mean':return content.mean(2)
        B=patch.shape[0];U=8;A=12
        with torch.autocast(device_type=patch.device.type,enabled=False):
            drives=self.drive(patch.float()).reshape(B*4,4,U)
            m=self.reset.expand(B*4,U,A);f=drives.new_zeros(B*4,U);b=f
            v=drives.new_zeros(B*4,U,2);weights=[]
            for x in drives.unbind(1):
                rel=.28*torch.tanh(x+.25*b+(v.tanh()*self.feedback).sum(-1))
                newb=torch.log1p(self.ratio*rel)
                u=((b-newb)*4096+3072).clamp(0,6144)
                ix=u.long().clamp(max=6143)
                k=self.tr[ix]+(u-ix)[...,None,None]*(self.tr[ix+1]-self.tr[ix])
                projected=(m.unsqueeze(-2)@k).squeeze(-2)
                m=projected[...,:A]+f[...,None]*self.reset; f=projected[...,A]
                e=self.price[:,:2]+rel[...,None,None]*self.price[:,2:]
                v=(m[...,None]*e).sum(-2);b=newb
                weights.append(f.mean(-1))
            omega=torch.stack(weights,-1).reshape(B,4,4)
            omega=(omega+1e-5)/(omega.sum(-1,keepdim=True)+4e-5)
        return (content*omega[...,None].to(content.dtype)).sum(2)


class Captioner(nn.Module):
    def __init__(self,d,depth,vocab,arm,tables):
        super().__init__()
        self.tokens=nn.Embedding(vocab,d)
        self.text_pos=nn.Parameter(torch.randn(22,d)*.01)
        self.image_pos=nn.Parameter(torch.randn(16,d)*.01)
        self.layers=nn.ModuleList([nn.TransformerEncoderLayer(d,d//64,4*d,0.,activation='gelu',batch_first=True,norm_first=True) for _ in range(depth)])
        self.norm=nn.LayerNorm(d)
        self.logits=nn.Linear(d,vocab,bias=False)
        self.front=Prefix(d,arm,tables)
        self.register_buffer('mask',torch.ones(38,38,dtype=torch.bool).triu(1),persistent=False)

    def forward(self,x,ids):
        prefix=self.front(x);n=prefix.shape[1]
        z=torch.cat([prefix+self.image_pos[:n],self.tokens(ids)+self.text_pos[:ids.shape[1]]],1)
        mask=self.mask[:z.shape[1],:z.shape[1]]
        for layer in self.layers:z=layer(z,src_mask=mask,is_causal=True)
        return self.logits(self.norm(z[:,n:]))


def decode(pack,device):
    with np.load(io.BytesIO(pack)) as ds:
        u=ds['images'];rgb=np.stack([(u>>5)/7,((u>>2)&7)/7,(u&3)/3],-1).astype(np.float32)*2-1
        x=torch.tensor(rgb,device=device).reshape(-1,4,2,4,2,3).permute(0,1,3,2,4,5).reshape(-1,4,4,12)
        c=torch.tensor(ds['captions'].astype(np.int64),device=device)
        sp=ds['split'];v=int(ds['vocab_size'])
    return x,c,[np.flatnonzero(sp==i) for i in range(3)],v


def sha(path):
    h=hashlib.sha256()
    with open(path,'rb') as f:
        for block in iter(lambda:f.read(4*1024*1024),b''):h.update(block)
    return h.hexdigest()


def dump(path,data):
    Path(path).write_text(json.dumps(data,allow_nan=False)+'\n')


def cast(device):
    return torch.autocast('cuda',dtype=torch.float16) if device.type=='cuda' else contextlib.nullcontext()


@torch.inference_mode()
def evalset(net,x,c,ids,device,switch=False):
    net.eval();losses=[];counts=[]
    source=np.roll(ids,1) if switch else ids
    for start in range(0,len(ids),16):
        targets=c[ids[start:start+16]].reshape(-1,c.shape[-1])
        pics=x[source[start:start+16]].repeat_interleave(c.shape[1],0)
        with cast(device):scores=net(pics,targets[:,:-1])
        y=targets[:,1:];loss=F.cross_entropy(scores.float().flatten(0,1),y.flatten(),ignore_index=0,reduction='none').reshape_as(y)
        losses.extend(loss.reshape(-1,c.shape[1],y.shape[-1]).sum(2).cpu().tolist())
        counts.extend(y.ne(0).reshape(-1,c.shape[1],y.shape[-1]).sum(2).cpu().tolist())
    return np.array(losses),np.array(counts)


def main():
    clock=time.monotonic();device=torch.device('cuda')
    if not torch.cuda.is_available():raise RuntimeError('Registered GPU unavailable')
    torch.set_num_threads(1);torch.backends.mha.set_fastpath_enabled(False)
    gpu=torch.cuda.get_device_name()
    if 'T4' not in gpu:raise RuntimeError('Expected specified T4, saw '+gpu)
    torch.manual_seed(4421);a=torch.randn(128,128,device=device);proof=float((a@a.T).diagonal().mean())
    torch.cuda.synchronize()
    pack=base64.b85decode(PACK);x,c,splits,vocab=decode(pack,device)
    table=law_tables()
    temp=Path(tempfile.mkdtemp(prefix='hcsn-ucm-'))
    rungs=sorted({min(CAP,v) for v in (15,60,180,360)})
    ytrain=c[splits[0]].cpu().numpy()[:,:,1:].ravel();ct=np.bincount(ytrain[ytrain!=0],minlength=vocab)+1;ct[0]=0
    freqs=ct/ct.sum();val=c[splits[1]].cpu().numpy()[:,:,1:].ravel();base=float(-np.log(freqs[val[val!=0]]).mean())
    run={'gpu':gpu,'cuda':torch.version.cuda,'torch':str(torch.__version__),'smoke_gram':proof,'pack_sha256':hashlib.sha256(pack).hexdigest(),'caps':rungs,'splits':[len(p) for p in splits],'vocab':vocab,'unigram_dev_nll':base,'targets':[base-d for d in (.25,.75,1.25,1.75)],'setup_wall_s':time.monotonic()-clock,'models':{}}
    for d,depth in SIZES:
        for j,seed in enumerate(SEEDS):
            for offset in range(4):
                arm=ARMS[(offset+j)%4];key=f'{d}-{seed}-{arm}'
                torch.manual_seed(seed);torch.cuda.manual_seed_all(seed)
                net=Captioner(d,depth,vocab,arm,table).to(device)
                opt=torch.optim.AdamW(net.parameters(),lr=.0003,weight_decay=.01)
                scaler=torch.amp.GradScaler('cuda')
                rng=np.random.default_rng(seed+228);steps=0;skipped=0;active=0.;history=[];best=float('inf');pt=temp/(key+'.pt')
                torch.cuda.reset_peak_memory_stats();setup=time.monotonic()
                for rung in rungs:
                    while active<rung:
                        tic=time.monotonic()
                        ab=rng.choice(splits[0],24);ca=rng.integers(0,c.shape[1],24)
                        label=c[ab,ca];net.train();opt.zero_grad(set_to_none=True)
                        with cast(device):scores=net(x[ab],label[:,:-1])
                        loss=F.cross_entropy(scores.float().flatten(0,1),label[:,1:].flatten(),ignore_index=0)
                        if not torch.isfinite(loss):raise RuntimeError('Nonfinite loss, preserving terminal failure')
                        scaler.scale(loss).backward();scaler.unscale_(opt)
                        torch.nn.utils.clip_grad_norm_(net.parameters(),1.);before=scaler.get_scale();scaler.step(opt);scaler.update()
                        skipped+=int(scaler.get_scale()<before)
                        torch.cuda.synchronize();active+=time.monotonic()-tic;steps+=1
                    st=time.monotonic();losses,counts=evalset(net,x,c,splits[1],device)
                    val=float(losses.sum()/counts.sum())
                    timing={'requested_s':rung,'optimizer_wall_s':active,'steps':steps,'updates_skipped_by_gradscaler':skipped,'dev_nll':val,'validation_s':time.monotonic()-st}
                    if val<best:
                        torch.save(net.state_dict(),pt);best=val;best_rung=rung
                    history.append(timing);print(key,rung,steps,val,flush=True)
                run['models'][key]={'history':history,'params':sum(p.numel() for p in net.parameters()),'selected_rung':best_rung,'selected_sha256':sha(pt),'peak_bytes':torch.cuda.max_memory_allocated(),'fit_wall_s':time.monotonic()-setup}
                del net,opt,scaler;torch.cuda.empty_cache()
                dump('progress.json',run)
    dump('seal.json',run)
    pred={};coldstart=time.monotonic()
    for d,depth in SIZES:
        for seed in SEEDS:
            for arm in ARMS:
                key=f'{d}-{seed}-{arm}';pt=temp/(key+'.pt')
                assert sha(pt)==run['models'][key]['selected_sha256']
                net=Captioner(d,depth,vocab,arm,table).to(device)
                net.load_state_dict(torch.load(pt,map_location=device,weights_only=True))
                q,n=evalset(net,x,c,splits[2],device);alt,m=evalset(net,x,c,splits[2],device,True)
                assert np.array_equal(n,m)
                pred[key]=q;pred[key+'-shuffled']=alt;pred['tokens']=n
                del net;torch.cuda.empty_cache()
    np.savez_compressed('predictions.npz',**pred)
    dump('result.json',{'seal':sha('seal.json'),'predictions':sha('predictions.npz'),'cold_wall_s':time.monotonic()-coldstart,'total_process_wall_s':time.monotonic()-clock,'gpu':gpu,'weighted_nll':{k:float(v.sum()/n.sum()) for k,v in pred.items() if k!='tokens'}})
    print('sealed-and-scored',sha('result.json'),flush=True)


if __name__=='__main__':main()
