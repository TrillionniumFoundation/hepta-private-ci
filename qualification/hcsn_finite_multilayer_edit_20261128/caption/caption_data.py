"""Data and frozen predictor access shared by adaptation and an independent cold scorer."""
import hashlib
import json
import time
from pathlib import Path

import numpy as np
import torch
from torch.nn import functional as F
from physics_caption import Captioner


def sha(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream,'sha256').hexdigest()


def read(path):
    return json.loads(path.read_text())


def write(path,value):
    tmp=path.with_suffix('.pending')
    tmp.write_text(json.dumps(value,indent=1,allow_nan=False)+'\n')
    tmp.replace(path)


class Panel:
    def __init__(self,p,x,y,names):
        self.p=p
        self.x=x
        self.y=y
        self.names=np.asarray(names)
    
    def __len__(self):
        return len(self.y)
    
    def batch(self,indices,image_indices=None,label_indices=None):
        a=indices if image_indices is None else image_indices
        b=indices if label_indices is None else label_indices
        return (torch.from_numpy(np.ascontiguousarray(self.p[a])),
                torch.from_numpy(self.x[indices].astype(np.int64)),
                torch.from_numpy(self.y[b].astype(np.int64)))


def panels(old,fresh,heldout):
    meta=read(old/'data.json')
    pixel=np.load(meta['pixels'],mmap_mode='r')
    with np.load(old/'data.npz') as source:
        inp,targets=source['inputs'],source['targets']
        groups=(('old_test','test'),) if heldout else (('old_train','train'),('old_dev','development'))
        result={}
        for name,split in groups:
            ix=source[split]
            if name=='old_train':
                ix=np.asarray(sorted(ix,key=lambda k:hashlib.sha256(f'RSICD-{k}'.encode()).digest())[:512])
            result[name]=Panel(pixel[ix],inp[ix],targets[ix],ix)
    for split in (('test',) if heldout else ('train','dev')):
        with np.load(fresh/(split+'.npz')) as image:
            result[split]=Panel(image['pix'],image['x'],image['y'],image['name'])
    return result


def load_net(root,arch,seed):
    location=root/'runs'/f'{arch}-{seed}'
    reg=read(location/'selected.json')
    assert sha(location/'selected.pt')==reg['sha']
    net=Captioner(arch,seed,read(root/'data.json')['vocab_size'],root/'law4.npz')
    net.load_state_dict(torch.load(location/'selected.pt',weights_only=True,map_location='cpu'))
    net.requires_grad_(False)
    net.eval()
    return net,reg


def sites(net):
    return net.words,net.mixers[-1].read


def effective(net,bias):
    return [x.weight.detach().clone() for x in sites(net)]+[bias.detach().clone()]


def score(net,panel,bias,shift=False):
    losses=[]; known=[]; counts=[]; known_counts=[]
    with torch.no_grad():
        for i in range(0,len(panel),8):
            ix=np.arange(i,min(len(panel),i+8))
            pixels,tokens,target=panel.batch(ix,(ix+1)%len(panel) if shift else None)
            out=net(pixels,tokens)+bias
            loss=F.cross_entropy(out.transpose(1,2),target,ignore_index=0,reduction='none')
            valid=target>=4
            losses.extend(loss.double().sum(1).tolist());counts.extend((target!=0).sum(1).tolist())
            known.extend((loss*valid).double().sum(1).tolist());known_counts.extend(valid.sum(1).tolist())
    return np.array([losses,counts,known,known_counts],dtype=np.float64)


def nll(scores):
    return float(scores[0].sum()/scores[1].sum())


def joint_batch(domains,rng,wrong):
    new=domains['train'];old=domains['old_train']
    u=rng.choice(len(new),8,replace=False);v=rng.choice(len(old),8,replace=False)
    a=new.batch(u,label_indices=np.roll(u,1) if wrong else None)
    b=old.batch(v)
    return tuple(torch.cat((x,y)) for x,y in zip(a,b))
