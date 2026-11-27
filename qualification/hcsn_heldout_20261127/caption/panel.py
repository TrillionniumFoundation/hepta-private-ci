"""Interleaved equal-time training, restartable cell checkpoints and process-cold tests."""
import argparse
import datetime as dt
import hashlib
import json
import os
import platform
import subprocess
import sys
import time
from pathlib import Path

import numpy as np
import torch
from torch.nn import functional as F
from model import ARMS, Captioner

SEEDS=(17011,24203,39827)
# Cumulative elapsed seconds; every row reaches the same final 42-minute budget.
BUDGET=(20,120,420,720,1020,1320,1620,1920,2220,2520)

def sha(path):
    with path.open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()
def at():
    return dt.datetime.now(dt.timezone.utc).isoformat()
def write_json(path,obj):
    temp=path.with_suffix(path.suffix+'.tmp')
    temp.write_text(json.dumps(obj,sort_keys=True,allow_nan=False))
    temp.replace(path)
def save(path,obj):
    temp=path.with_suffix('.part')
    torch.save(obj,temp)
    temp.replace(path)
def sync(device):
    if device.type=='cuda':torch.cuda.synchronize()

class Samples:
    def __init__(self,root,name,manifest):
        d=manifest['splits'][name]
        for filename,expected in d['files'].items():
            if sha(root/filename)!=expected:raise ValueError(filename)
        self.pix=np.load(root/f'{name}_pixels.npy',mmap_mode='r')
        self.cap=np.load(root/f'{name}_tokens.npy',mmap_mode='r')
        self.ids=np.load(root/f'{name}_ids.npy',mmap_mode='r')
        assert len(self.pix)==d['images']
    def batch(self,images,captions,device,shift=0):
        pix=torch.from_numpy(self.pix[(images+shift)%len(self.pix)]).to(device)
        text=torch.from_numpy(self.cap[images,captions].astype(np.int64)).to(device)
        return pix,text

@torch.no_grad()
def score(model,data,subset,device,swap=False):
    model.eval()
    totals=np.zeros(len(subset),dtype=np.float64)
    counts=np.zeros(len(subset),dtype=np.int64)
    for start in range(0,len(subset)*5,32):
        idx=np.arange(start,min(start+32,len(subset)*5))
        ids=subset[idx//5]
        im,tx=data.batch(ids,idx%5,device,int(swap))
        pred=model(im,tx[:,:-1])
        losses=F.cross_entropy(pred.transpose(1,2),tx[:,1:],reduction='none',ignore_index=0)
        np.add.at(totals,idx//5,losses.double().sum(1).cpu().numpy())
        np.add.at(counts,idx//5,(tx[:,1:]!=0).sum(1).cpu().numpy())
    assert np.isfinite(totals).all() and (counts>0).all()
    return totals,counts

def run_cell(arm,seed,budget,root,manifest,train,valid,val_ids,device):
    directory=root/f'{arm}-{seed}'
    directory.mkdir(exist_ok=True)
    last=directory/'resume.pt'
    torch.manual_seed(seed)
    model=Captioner(arm,len(manifest['vocab'])).to(device)
    opt=torch.optim.AdamW(model.parameters(),lr=.0005,weight_decay=.01)
    rng=np.random.default_rng(seed)
    current={'exposure_s':0.,'steps':0,'tokens':0,'best_nll':None,'train_s':0.,'dev_s':0.,'checkpoints':[]}
    if last.exists():
        ck=torch.load(last,map_location='cpu',weights_only=False)
        assert ck['arm']==arm and ck['seed']==seed and ck['device']==str(device)
        model.load_state_dict(ck['model']);opt.load_state_dict(ck['optimizer'])
        current=ck['current'];rng.bit_generator.state=ck['rng']
    if current['exposure_s']>=budget:return
    model.train()
    start=time.perf_counter()
    initial=current['exposure_s']
    while True:
        images=rng.integers(len(train.pix),size=32)
        caps=rng.integers(5,size=32)
        im,tx=train.batch(images,caps,device)
        y=tx[:,1:]
        opt.zero_grad(set_to_none=True)
        logits=model(im,tx[:,:-1])
        loss=F.cross_entropy(logits.transpose(1,2),y,ignore_index=0)
        loss.backward()
        norm=torch.nn.utils.clip_grad_norm_(model.parameters(),1.)
        if not torch.isfinite(loss).item() or not torch.isfinite(norm).item():
            raise ValueError(f'nonfinite model {arm} {seed} {current["steps"]}')
        opt.step()
        current['steps']+=1
        current['tokens']+=int(y.count_nonzero())
        if current['steps'] in (50,200,1000,4000):
            current.setdefault('matched_steps',[]).append([current['steps'],float(loss),initial+time.perf_counter()-start])
        sync(device)
        if initial+time.perf_counter()-start>=budget:break
    training=time.perf_counter()-start
    tic=time.perf_counter()
    total,counts=score(model,valid,val_ids,device)
    sync(device)
    dev_s=time.perf_counter()-tic
    nll=float(total.sum()/counts.sum())
    current['train_s']+=training;current['dev_s']+=dev_s
    current['exposure_s']+=training+dev_s
    current['checkpoints'].append({'at':at(),'nominal_s':budget,'steps':current['steps'],'train_s':current['train_s'],'dev_s':current['dev_s'],'nll':nll,'tokens':current['tokens']})
    if current['best_nll'] is None or nll<current['best_nll']:
        current['best_nll']=nll;current['best_step']=current['steps']
        save(directory/'selected.pt',model.state_dict())
    save(last,{'arm':arm,'seed':seed,'model':model.state_dict(),'optimizer':opt.state_dict(),'device':str(device),'rng':rng.bit_generator.state,'current':current})
    current['parameters']=sum(p.numel() for p in model.parameters())
    if device.type=='cuda':current['peak_allocated_bytes']=torch.cuda.max_memory_allocated()
    write_json(directory/'fit.json',current)
    print(at(),arm,seed,'train_steps',current['steps'],'dev_NLL',round(nll,6),'train_sec',round(current['train_s'],2),flush=True)

def runtime(args):
    torch.set_num_threads(args.threads)
    torch.set_num_interop_threads(1)
    if args.device=='cuda' and not torch.cuda.is_available():raise RuntimeError('CUDA device unavailable')
    device=torch.device(args.device)
    if device.type=='cuda':
        if not (torch.ones((16,16),device=device)@torch.ones((16,16),device=device)).eq(16).all().item():raise RuntimeError('GPU matrix check')
    return device

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('mode',choices=['fit','test','summarize'])
    parser.add_argument('--data',type=Path,required=True)
    parser.add_argument('--out',type=Path,required=True)
    parser.add_argument('--device',default='cpu',choices=['cpu','cuda'])
    parser.add_argument('--threads',type=int,default=1)
    parser.add_argument('--arm',choices=ARMS);parser.add_argument('--seed',type=int)
    args=parser.parse_args()
    device=runtime(args);root=args.out.resolve();root.mkdir(exist_ok=True,parents=True)
    src=Path(__file__).parent.resolve()
    manifest=json.loads((args.data/'manifest.json').read_text())
    if args.mode=='fit':
        env={'os':platform.platform(),'torch':str(torch.__version__),'device':str(device),'dtype':'float32','threads':args.threads,'source':{n:sha(src/n) for n in ['panel.py','model.py','parent_cell.py','prepare.py','PROTOCOL.md','SOURCE_AMENDMENT.md']},'dataset':sha(args.data/'manifest.json'),'device_name':torch.cuda.get_device_name() if device.type=='cuda' else platform.machine()}
        if (root/'environment.json').exists():
            assert json.loads((root/'environment.json').read_text())==env,'existing panel has different environment/source'
        else:write_json(root/'environment.json',env)
        train=Samples(args.data,'train',manifest);valid=Samples(args.data,'validation',manifest)
        val_ids=np.asarray(sorted(range(len(valid.pix)),key=lambda i:hashlib.sha256(b'flickr-caption-prereg-128'+bytes(valid.ids[i])).digest())[:128])
        for budget in BUDGET:
            for i,seed in enumerate(SEEDS):
                order=ARMS[i:]+ARMS[:i]
                for arm in order:
                    run_cell(arm,seed,budget,root,manifest,train,valid,val_ids,device)
        states={f'{arm}-{seed}':sha(root/f'{arm}-{seed}'/'selected.pt') for arm in ARMS for seed in SEEDS}
        seal={'source':env['source'],'dataset':env['dataset'],'states':states,'at':at()}
        if (root/'seal.json').exists():
            old=json.loads((root/'seal.json').read_text())
            assert all(old[k]==seal[k] for k in ('source','dataset','states'))
        else:write_json(root/'seal.json',seal)
        for arm in ARMS:
            for seed in SEEDS:
                subprocess.run([sys.executable,str(src/'panel.py'),'test','--data',str(args.data.resolve()),'--out',str(root),'--device',args.device,'--threads',str(args.threads),'--arm',arm,'--seed',str(seed)],check=True)
        subprocess.run([sys.executable,str(src/'panel.py'),'summarize','--data',str(args.data.resolve()),'--out',str(root),'--threads',str(args.threads)],check=True)
    elif args.mode=='test':
        name=f'{args.arm}-{args.seed}'; seal=json.loads((root/'seal.json').read_text())
        assert len(seal['states'])==15 and sha(root/name/'selected.pt')==seal['states'][name] and seal['dataset']==sha(args.data/'manifest.json')
        assert all(sha(src/f)==s for f,s in seal['source'].items())
        torch.manual_seed(args.seed)
        model=Captioner(args.arm,len(manifest['vocab'])).to(device)
        model.load_state_dict(torch.load(root/name/'selected.pt',map_location=device,weights_only=True))
        values={}
        for split in ('validation','test'):
            data=Samples(args.data,split,manifest);ids=np.arange(len(data.pix))
            true,n=score(model,data,ids,device);wrong,n2=score(model,data,ids,device,True)
            assert np.array_equal(n,n2)
            values.update({split+'_sum':true,split+'_swapped':wrong,split+'_counts':n,split+'_ids':data.ids})
        dest=root/name/'cold.npz';np.savez_compressed(dest,**values)
        write_json(root/name/'cold.json',{'prediction':sha(dest),'selected':seal['states'][name],'at':at(),'nll':float(values['test_sum'].sum()/values['test_counts'].sum())})
    else:
        rng=np.random.default_rng(20261127);groups=[];out={};pooled={}
        for arm in ARMS:
            values=[];ns=[];swaps=[];rows=[]
            for seed in SEEDS:
                sub=root/f'{arm}-{seed}';cold=json.loads((sub/'cold.json').read_text())
                assert sha(sub/'cold.npz')==cold['prediction']
                with np.load(sub/'cold.npz') as rec:
                    observed=rec['test_ids'].tolist()
                    if groups:assert groups==observed
                    groups=observed
                    values.append(rec['test_sum']);ns.append(rec['test_counts']);swaps.append(rec['test_swapped'])
                fit=json.loads((sub/'fit.json').read_text())
                rows.append({'seed':seed,'best_step':fit['best_step'],'steps':fit['steps'],'tokens':fit['tokens'],'train_s':fit['train_s'],'dev_s':fit['dev_s'],'nll':cold['nll']})
            assert all(np.array_equal(ns[0],c) for c in ns)
            pooled[arm]=np.mean(values,axis=0);n=ns[0]
            out[arm]={'seeds':rows,'test_nll':float(pooled[arm].sum()/n.sum()),'conditioning_gain':float((np.mean(swaps,axis=0)-pooled[arm]).sum()/n.sum())}
        draws=rng.integers(len(n),size=(5000,len(n)))
        for control in ('dense','smooth','lif','mean'):
            d=pooled['hcsn']-pooled[control];v=d[draws].sum(1)/n[draws].sum(1)
            out['hcsn'][f'minus_{control}']={'nll':float(d.sum()/n.sum()),'paired_image_95':np.quantile(v,[.025,.975]).tolist()}
        write_json(root/'summary.json',out);print(json.dumps(out,indent=2))

if __name__=='__main__':main()
