"""Train one resumable, registered GPU configuration without loading test arrays."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import time

import numpy as np
import torch
from torch.nn import functional as F

from grouped_router import build_model

MILESTONES = (5, 10, 20, 30, 45, 60, 80, 100, 120, 150, 180, 240, 300, 360, 420)
ROOT = Path(os.environ['HCSN_GROUPED_STUDY']).resolve()
DATA = Path(os.environ['HEPTA_FLICKR_ROOT']).resolve()/'data'
SRC = Path(__file__).resolve().parent
ARMS = ('grouped_hcsn', 'hcsn', 'grouped_smooth', 'lif', 'mean', 'dense')
TUNING = (6259,9283)
CONFIRM = (104729,104743,104759,104761,104773,104779,104789,104801,104803,104827,104831,104849)
RATES = (.0002,.0005,.001)
CONTROL_ORDER = ('dense', 'grouped_smooth', 'mean', 'lif')


def sha(path):
    with path.open('rb') as f:
        return hashlib.file_digest(f,'sha256').hexdigest()


def json_file(path):
    return json.loads(path.read_text())


def write_json(path,value):
    text=json.dumps(value,sort_keys=True,allow_nan=False)+'\n'
    temp=path.with_suffix(path.suffix+'.partial')
    temp.write_text(text)
    temp.replace(path)


def save(path,value):
    temp=path.with_suffix(path.suffix+'.partial')
    torch.save(value,temp)
    temp.replace(path)


class Samples:
    def __init__(self,pixels,tokens,ids):
        self.pixels=pixels
        self.tokens=tokens
        self.ids=ids
        if len(self.ids)!=len(self.pixels) or self.tokens.shape!=(len(self.ids),5,32):
            raise RuntimeError('Mismatched image and token arrays')

    def batch(self,images,captions,swapped=False):
        visual_indices=(images+int(swapped))%len(self.ids)
        pixels=torch.as_tensor(self.pixels[visual_indices],device='cuda')
        caps=torch.as_tensor(self.tokens[images,captions].astype(np.int64),device='cuda')
        return pixels,caps


def external(split):
    manifest=json_file(ROOT/'gallery/manifest.json')['cohorts'][split]
    path=ROOT/'gallery'/manifest['file']
    assert sha(path)==manifest['sha256']
    with np.load(path,allow_pickle=False) as z:
        return Samples(z['images'],z['tokens'],z['ids'])


def training():
    manifest=json_file(DATA/'manifest.json')
    files=manifest['splits']['train']['files']
    for n,h in files.items():
        assert sha(DATA/n)==h
    arrays=[np.load(DATA/('train_'+kind+'.npy'),mmap_mode='r') for kind in ('pixels','tokens','ids')]
    return Samples(*arrays),len(manifest['vocab'])


@torch.no_grad()
def score(model,data,images,swap=False):
    model.eval()
    loss=np.zeros(len(images),np.float64)
    counts=np.zeros(len(images),np.int64)
    for start in range(0,5*len(images),32):
        rows=np.arange(start,min(start+32,5*len(images)))
        pixels,text=data.batch(images[rows//5],rows%5,swap)
        pred=model(pixels,text[:,:-1])
        nll=F.cross_entropy(pred.transpose(1,2),text[:,1:],ignore_index=0,reduction='none')
        np.add.at(loss,rows//5,nll.double().sum(1).cpu().numpy())
        np.add.at(counts,rows//5,(text[:,1:]!=0).sum(1).cpu().numpy())
    if not np.isfinite(loss).all() or not (counts>0).all():
        raise ValueError('Invalid score')
    return loss,counts


def identity():
    return {k:sha(SRC/k) for k in ('fit.py','grouped_router.py','model.py','parent_cell.py','PROTOCOL.md','acquire.py')}


def env_identity():
    props=torch.cuda.get_device_properties(0)
    return dict(torch=str(torch.__version__),gpu=props.name,total_memory=props.total_memory,
                hip=str(torch.version.hip),cuda=str(torch.version.cuda),threads=torch.get_num_threads())


def run_path(phase,arm,seed,lr):
    return ROOT/'runs'/phase/f'{arm}-{seed}-{lr:.4g}'


def fit(args):
    start_total=time.perf_counter()
    assert torch.cuda.is_available()
    torch.set_num_threads(1)
    torch.set_num_interop_threads(1)
    train,vocab=training()
    dev=external('development')
    assert len(train.ids)==5999 and len(dev.ids)==320 and len(set(train.ids)&set(dev.ids))==0
    development=np.arange(128)
    out=run_path(args.phase,args.arm,args.seed,args.lr)
    out.mkdir(parents=True,exist_ok=True)
    ceiling=180 if args.phase=='tune' else 420
    assert args.seed in (TUNING if args.phase=='tune' else CONFIRM)
    assert args.lr in RATES
    control=json_file(ROOT/'tuning_seal.json') if args.phase=='confirm' else None
    if control:
        assert args.lr==control['rates'][args.arm]
    target_levels=control['targets'] if control else []
    contract=dict(arm=args.arm,seed=args.seed,rate=args.lr,phase=args.phase,source=identity(),
                  gallery=sha(ROOT/'gallery/manifest.json'),flickr=sha(DATA/'manifest.json'),environment=env_identity(),
                  targets=target_levels,nominal_ceiling=ceiling)
    if (out/'complete.json').exists():
        old=json_file(out/'complete.json')
        assert old['contract']==contract and sha(out/'history.json')==old['history_sha256']
        return
    init=time.perf_counter()
    torch.manual_seed(args.seed)
    warm=build_model(args.arm,vocab).cuda()
    pix=torch.zeros((32,64,64,3),device='cuda',dtype=torch.uint8)
    tok=torch.zeros((32,31),device='cuda',dtype=torch.long)
    warm(pix,tok).mean().backward()
    torch.cuda.synchronize()
    del warm,pix,tok
    torch.manual_seed(args.seed)
    model=build_model(args.arm,vocab).cuda()
    optimizer=torch.optim.AdamW(model.parameters(),lr=args.lr,weight_decay=.01)
    random=np.random.default_rng(args.seed)
    state=dict(steps=0,tokens=0,train_s=0.,dev_s=0.,best=None,first={},history=[],warm_setup_s=time.perf_counter()-init)
    resume=out/'resume.pt'
    if resume.exists():
        rec=torch.load(resume,map_location='cpu',weights_only=False)
        assert rec['contract']==contract
        model.load_state_dict(rec['model']);optimizer.load_state_dict(rec['optimizer'])
        random.bit_generator.state=rec['rng']
        state=rec['state']
    torch.cuda.reset_peak_memory_stats()
    for nominal in MILESTONES:
        if nominal>ceiling:break
        if any(c['stage_s']==nominal for c in state['history']):continue
        model.train();torch.cuda.synchronize();start=time.perf_counter()
        before=state['train_s']+state['dev_s']
        # Every scheduled observation is recorded, including a budget already crossed by evaluation overhead.
        while before+time.perf_counter()-start<nominal:
            ii=random.integers(len(train.ids),size=32);cc=random.integers(5,size=32)
            im,text=train.batch(ii,cc)
            optimizer.zero_grad(set_to_none=True)
            pred=model(im,text[:,:-1])
            objective=F.cross_entropy(pred.transpose(1,2),text[:,1:],ignore_index=0)
            objective.backward()
            norm=torch.nn.utils.clip_grad_norm_(model.parameters(),1.)
            if not torch.isfinite(objective).item() or not torch.isfinite(norm).item():
                raise ValueError(('nonfinite update',args.arm,args.seed,state['steps']))
            optimizer.step();torch.cuda.synchronize()
            state['steps']+=1;state['tokens']+=int(torch.count_nonzero(text[:,1:]))
        torch.cuda.synchronize()
        state['train_s']+=time.perf_counter()-start
        tick=time.perf_counter();loss,counts=score(model,dev,development);torch.cuda.synchronize()
        state['dev_s']+=time.perf_counter()-tick
        avg=float(loss.sum()/counts.sum())
        rec=dict(stage_s=nominal,nll=avg,steps=state['steps'],tokens=state['tokens'],train_s=state['train_s'],dev_s=state['dev_s'])
        improved=state['best'] is None or avg<state['best']['nll']
        reached=[str(i) for i,t in enumerate(target_levels) if str(i) not in state['first'] and avg<=t]
        if improved or reached:
            filename=f'state-{nominal:03d}.pt';save(out/filename,model.state_dict())
            record={**rec,'file':filename,'sha256':sha(out/filename)}
            if improved:state['best']=record
            for i in reached:state['first'][i]=record
        state['history'].append(rec)
        save(resume,dict(contract=contract,model=model.state_dict(),optimizer=optimizer.state_dict(),rng=random.bit_generator.state,state=state))
        write_json(out/'history.json',state)
    # Recover the public history atomically from the final resume if interrupted after the final save.
    write_json(out/'history.json',state)
    completed=dict(contract=contract,history_sha256=sha(out/'history.json'),model_params=sum(p.numel() for p in model.parameters()),
                   gpu_peak_bytes=torch.cuda.max_memory_allocated(),child_seconds_this_attempt=time.perf_counter()-start_total,
                   resume_sha256=sha(resume),final_stage=state['history'][-1]['stage_s'],best=state['best'],first=state['first'])
    assert completed['final_stage']==ceiling
    for rec in [state['best'],*state['first'].values()]:assert sha(out/rec['file'])==rec['sha256']
    write_json(out/'complete.json',completed)
    print(args.phase,args.arm,args.seed,args.lr,'best',state['best']['nll'],'complete',flush=True)


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('phase',choices=('tune','confirm'));p.add_argument('arm',choices=ARMS)
    p.add_argument('seed',type=int);p.add_argument('lr',type=float)
    fit(p.parse_args())
