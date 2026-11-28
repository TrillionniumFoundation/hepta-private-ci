"""Rotate actual mini-batch updates over sealed Flickr three-way models and store original dev scores."""
from argparse import ArgumentParser
from functools import lru_cache
from hashlib import sha256
import json
import os
from pathlib import Path
import time

import numpy as np
import torch
from torch.nn import functional as F

from decoder import Corpus, KINDS, architecture

SEEDS=(137,311,557)
BATCH=32


def atomic_json(path,data):
    tmp=path.with_suffix('.json.stage');tmp.write_text(json.dumps(data,indent=2)+'\n');tmp.replace(path)


def hashfile(path):
    with path.open('rb') as f:
        h=sha256()
        while block:=f.read(2**20):h.update(block)
    return h.hexdigest()


def sync(device):
    if device=='cuda':torch.cuda.synchronize()


def assessed(model,data,ids,mode,other=None,cut=False):
    total=[];counts=[]
    with torch.inference_mode():
        for j in range(0,len(ids),64):
            a=ids[j:j+64];p=None if other is None else other[j:j+64]
            x,y,z=data.assemble(a,mode,p)
            scores=F.cross_entropy(model(x,mode,z,cut).transpose(1,2),y,reduction='none',ignore_index=-100)
            total.append(scores.double().sum(1).cpu().numpy())
            counts.append((y>=0).sum(1).cpu().numpy())
    return np.concatenate(total),np.concatenate(counts)


def endpoint(model,data,dev,path):
    model.eval();weights=path.with_suffix('.npz');scores=path.with_name(path.name+'-dev.npz')
    with weights.with_suffix('.staged').open('wb') as f:
        np.savez_compressed(f,**{k:v.detach().cpu().numpy() for k,v in model.state_dict().items()})
    weights.with_suffix('.staged').replace(weights)
    results=[assessed(model,data,dev,m) for m in range(3)]
    loss=np.stack([a for a,b in results],axis=1);counts=np.stack([b for a,b in results],axis=1)
    with scores.with_suffix('.staged').open('wb') as f:np.savez_compressed(f,nll_sum=loss,count=counts,indices=dev)
    scores.with_suffix('.staged').replace(scores)
    return dict(weights=weights.name,weights_sha256=hashfile(weights),development_scores=scores.name,
                development_sha256=hashfile(scores),nll=(loss.sum(0)/counts.sum(0)).tolist(),
                summed_targets=counts.sum(0).tolist())


@lru_cache(maxsize=24)
def shuffled(n,seed,epoch):
    rng=np.random.default_rng(seed+10007*epoch)
    orders=[np.array_split(rng.permutation(n),np.arange(BATCH,n,BATCH)) for _ in range(3)]
    sequence=[]
    for i in range(len(orders[0])):
        for mode in rng.permutation(3):sequence.append((int(mode),orders[mode][i]))
    return sequence


class Cell:
    def __init__(self,arm,seed,nwords,device,run):
        self.name=f'{arm}-{seed}';self.arm=arm;self.seed=seed
        self.net=architecture(nwords,arm,seed).to(device)
        self.opt=torch.optim.AdamW(self.net.parameters(),lr=.002,weight_decay=.01,foreach=False)
        self.step=0;self.active=0.;self.seen=0;self.targets=0;self.saved={}
        self.statefile=run/(self.name+'-resume.pt')
        if self.statefile.exists():
            orig=torch.load(self.statefile,map_location=device,weights_only=True)
            self.net.load_state_dict(orig['net']);self.opt.load_state_dict(orig['opt'])
            for x in ('step','active','seen','targets','saved'):setattr(self,x,orig[x])

    def persist(self):
        tmp=self.statefile.with_suffix('.tmp')
        torch.save(dict(net=self.net.state_dict(),opt=self.opt.state_dict(),**{k:getattr(self,k) for k in
                        ('step','active','seen','targets','saved')}),tmp)
        tmp.replace(self.statefile)

    def updates(self,data,train,dev,device,run,segment):
        per_epoch=3*((len(train)+BATCH-1)//BATCH)
        self.net.train()
        for _ in range(segment):
            epoch,index=divmod(self.step,per_epoch);m,local=shuffled(len(train),self.seed,epoch)[index]
            sync(device);clock=time.perf_counter()
            x,y,start=data.assemble(train[local],m)
            self.opt.zero_grad(set_to_none=True)
            loss=F.cross_entropy(self.net(x,m,start).flatten(0,1),y.flatten(),ignore_index=-100)
            loss.backward();torch.nn.utils.clip_grad_norm_(self.net.parameters(),1.);self.opt.step()
            sync(device);self.active+=time.perf_counter()-clock
            self.step+=1;self.seen+=len(local);self.targets+=int((y>=0).sum().item())
            labels=[]
            if self.step==per_epoch:labels.append('epoch1')
            if self.step==3*per_epoch:labels.append('epoch3')
            if self.active>=600 and 'time600' not in self.saved:labels.append('time600')
            if labels:
                frozen=endpoint(self.net,data,dev,run/(self.name+'-'+labels[0]))
                for lab in labels:self.saved[lab]=dict(step=self.step,seen=self.seen,targets=self.targets,
                                          update_wall_s=self.active,**frozen)
                self.persist()
                print(self.name,labels,'step',self.step,'active',round(self.active,2),'dev',frozen['nll'],flush=True)
                self.net.train()
            if len(self.saved)==3:break
        self.persist()


def main(args):
    datafiles=args.data;out=args.out;out.mkdir(parents=True,exist_ok=True)
    if args.wait:
        while not (datafiles/'dataset.json').exists():time.sleep(30)
    os.environ['OMP_NUM_THREADS']='1';torch.set_num_threads(1)
    if args.device=='cuda' and not torch.cuda.is_available():raise RuntimeError('requested GPU absent')
    if args.device=='cuda':torch.backends.cuda.matmul.allow_tf32=False
    p=datafiles/'codes.npz';meta=json.loads((datafiles/'dataset.json').read_text())
    if hashfile(p)!=meta['derived_sha256']:raise IOError('derived observations differ')
    data=Corpus(p,args.device);train=np.flatnonzero(data.split==0);dev=np.flatnonzero(data.split==1)
    start=time.time();cells=[Cell(arm,seed,len(meta['vocabulary']),args.device,out) for seed in SEEDS for arm in KINDS]
    hardware=dict(device=args.device,name=torch.cuda.get_device_name() if args.device=='cuda' else 'CPU',torch=str(torch.__version__),
                  cuda=torch.version.cuda,hip=torch.version.hip,source=meta['derived_sha256'],train_captions=len(train),
                  development_captions=len(dev),startup_timestamp=start)
    if not (out/'launch.json').exists():atomic_json(out/'launch.json',hardware)
    it=0
    while any(len(c.saved)<3 for c in cells):
        for c in cells[it%len(cells):]+cells[:it%len(cells)]:
            if len(c.saved)<3:c.updates(data,train,dev,args.device,out,96)
        it+=1
        atomic_json(out/'progress.json',{c.name:{'updates':c.step,'seen':c.seen,'active':c.active,'rungs':list(c.saved)} for c in cells})
    panel={}
    for c in cells:
        chosen=min(c.saved,key=lambda k:sum(c.saved[k]['nll'])/3)
        panel[c.name]={'seed':c.seed,'arm':c.arm,'chosen':chosen,'all':c.saved,'width':c.net.width,
                       'params':sum(x.numel() for x in c.net.parameters())}
    atomic_json(out/'sealed-development.json',dict(utc=time.time(),hardware=hardware,panel=panel))


if __name__=='__main__':
    parser=ArgumentParser();parser.add_argument('data',type=Path);parser.add_argument('out',type=Path)
    parser.add_argument('--device',choices=('cuda','cpu'),required=True);parser.add_argument('--wait',action='store_true')
    main(parser.parse_args())
