"""Train, seal, and cold-score the jointly fitted audiovisual/text encoders."""
import argparse
from contextlib import contextmanager
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import time
import numpy as np
import torch
from torch.nn import functional as F
from encoder import AVText,pair_loss

ARMS=('literal','smooth','lif','sdpa')
SEEDS=(137,311,557)
PREC='cuda'


def sha(path):
    with path.open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()


def dump(path,obj):
    temp=path.with_suffix(path.suffix+'.part')
    temp.write_text(json.dumps(obj,ensure_ascii=False,indent=1,allow_nan=False)+'\n')
    temp.replace(path)


def autocast():
    return torch.autocast(PREC,dtype=torch.bfloat16,enabled=torch.cuda.is_bf16_supported())


def synchronize():
    torch.cuda.synchronize()


def make_net(root,arm,width,seed,words):
    return AVText(arm,width,seed,words,root/'src/law4.npz').to(PREC)


class Split:
    def __init__(self,root,mode):
        data=root/'data';meta=json.loads((data/'prepared.json').read_text())
        assert sha(data/'data.npz')==meta['data_sha256']
        with np.load(data/'data.npz') as z:
            fold=z['split']
            train=fold==0
            self.tokens=torch.from_numpy(z['tokens']).long().to(PREC)
            self.words=int(self.tokens.max().item()+1)
            mean=z['audio'][train].mean((0,1),dtype=np.float64).astype('float32')
            std=z['audio'][train].std((0,1),dtype=np.float64).clip(.01).astype('float32')
            take=np.flatnonzero(fold!=2 if mode=='fit' else fold==2)
            self.v=torch.from_numpy(z['images'][take]).to(PREC)
            self.a=torch.from_numpy((z['audio'][take]-mean)/std).to(PREC)
            self.y=torch.from_numpy(z['labels'][take]).to(PREC).long()
            self.key=z['ids'][take];self.fold=fold[take]
            self.train=np.flatnonzero(self.fold==0);self.dev=np.flatnonzero(self.fold==1)
            self.evidence=meta


@torch.no_grad()
def inference(net,d,ids,variants=False):
    net.eval()
    # Separate permutations preserve speaker identity. Both sensor-only contrasts share the permutation.
    video_ids=ids.copy()
    for actor in sorted({v.split('_')[0] for v in d.key[ids]}):
        sel=np.array([i for i,k in enumerate(d.key[ids]) if k.startswith(actor+'_')]);assert len(sel)>1
        shuf=np.random.default_rng(int(actor)+6312).permutation(sel)
        video_ids[shuf]=ids[np.roll(shuf,1)]
    out={}
    with autocast():
        text=torch.cat([net.encode(net.text(t)) for t in d.tokens.split(16)])
        modes=('aligned','video_swapped','audio_swapped','both_swapped') if variants else ('aligned',)
        for mode in modes:
            scores=[]
            for begin in range(0,len(ids),16):
                ss=slice(begin,begin+16);correct=ids[ss];wrong=video_ids[ss]
                v=d.v[wrong if mode in ('video_swapped','both_swapped') else correct]
                a=d.a[wrong if mode in ('audio_swapped','both_swapped') else correct]
                embed=net.encode(net.front(v,a))
                with torch.autocast('cuda',enabled=False):
                    scores.append((12*(embed.float()@text.float().T)).cpu())
            out[mode]=torch.cat(scores).numpy()
    return out


def counters(model):
    p=list(model.parameters());return {'trainable':sum(q.numel() for q in p if q.requires_grad),
        'allocated_grad_scalars':sum(q.numel() for q in p if q.grad is not None),
        'allocated_grad_tensors':sum(q.grad is not None for q in p),'tensors':len(p)}


def probes(model):
    # Each finite 17-value rotating probe makes pre/post changes checkable without a second 4 GB weight copy.
    return {k:v.detach().reshape(-1)[torch.linspace(0,v.numel()-1,min(17,v.numel()),device=v.device).long()].float().cpu().clone()
            for k,v in model.named_parameters()}


def fit(root,arm,width,seed):
    tic=time.monotonic();d=Split(root,'fit')
    out=root/'fits'/f'{width}-{seed}-{arm}';out.mkdir(parents=True,exist_ok=True)
    if (out/'fit.json').exists():return
    model=make_net(root,arm,width,seed,d.words);p0=probes(model)
    optimizer=torch.optim.AdamW(model.parameters(),lr=.0001 if width==4096 else .0003,weight_decay=.01,foreach=False)
    gen=np.random.default_rng(seed+7369);state=out/'latest.pt'
    # Completed fits and checkpoints are immutable. An interrupted fit restarts deterministically from its initial seed;
    # capture a new, actually observed clock and reuse no state from the abandoned trajectory.
    history=[];wall=0.;steps=0;events={};proof={};end=600 if width==4096 else 300
    devy=d.y[d.dev].cpu()
    torch.cuda.reset_peak_memory_stats()
    while wall<end or steps<16:
        start=time.monotonic();ix=gen.choice(d.train,16);y=d.y[ix]
        model.train();optimizer.zero_grad(set_to_none=True)
        with autocast():a,t=model(d.v[ix],d.a[ix],d.tokens[y]);loss=pair_loss(a,t,y)
        assert torch.isfinite(loss).item()
        loss.backward();gnorm=torch.nn.utils.clip_grad_norm_(model.parameters(),1.)
        if not torch.isfinite(gnorm).item():raise ArithmeticError('nonfinite gradient')
        optimizer.step();synchronize();wall+=time.monotonic()-start;steps+=1
        if steps==1:
            now=probes(model)
            proof=dict(**counters(model),parameter_probes=len(now),changed_tensor_probes=sum(not torch.equal(p0[k],now[k]) for k in now),
                       physics_feedback_probe=[float((now[k]-p0[k]).abs().max()) for k in now if k.endswith('.feedback')],
                       first_grad_norm=float(gnorm),first_loss=float(loss.detach()),peak_bytes_first_step=torch.cuda.max_memory_allocated())
        tags=[lab for lab,met in [('step4',steps==4),('step16',steps==16),('time60',wall>=60),('end',wall>=end)] if met and lab not in events]
        if not tags:continue
        devstart=time.monotonic();scores=inference(model,d,d.dev)['aligned']
        nll=F.cross_entropy(torch.from_numpy(scores),devy).item();dev_s=time.monotonic()-devstart
        ck=out/f'step-{steps}.pt';st=time.monotonic();temp=ck.with_suffix('.part')
        torch.save(model.state_dict(),temp);temp.replace(ck);digest=sha(ck);serialize=time.monotonic()-st
        rec=dict(tags=tags,steps=steps,train_clips=steps*16,train_wall=wall,fit_wall=time.monotonic()-tic,
                 validation_wall=dev_s,checkpoint_wall=serialize,nll=nll,checkpoint=ck.name,sha256=digest)
        for tag in tags:events[tag]=rec
        history.append(rec);dump(out/'observations.json',history)
        print('observe',width,arm,seed,steps,tags,round(wall,2),round(nll,6),flush=True)
    chosen=min(history,key=lambda x:(x['nll'],x['steps']))
    record=dict(width=width,arm=arm,seed=seed,history=history,events=events,chosen=chosen,first_step=proof,
                total_wall=time.monotonic()-tic,peak_gpu_allocated=torch.cuda.max_memory_allocated(),
                peak_gpu_reserved=torch.cuda.max_memory_reserved(),prepared_sha256=sha(root/'data/prepared.json'),
                tensor_source=sha(root/'src/hcsn_temporal.py'),encoder_source=sha(root/'src/encoder.py'),implementation=sha(Path(__file__)),
                device=torch.cuda.get_device_name(0),torch=str(torch.__version__),rocm=str(torch.version.hip),
                bfloat16_autocast=torch.cuda.is_bf16_supported(),finished=dt.datetime.now(dt.timezone.utc).isoformat())
    assert set(events)=={'step4','step16','time60','end'}
    if width==4096: assert proof['trainable']>10**9
    dump(out/'fit.json',record)


def all_cells():
    return [(width,sd,ARMS[(ix+j)%4]) for ix,sd in enumerate(SEEDS) for width in (416,4096) for j in range(4)]


def seal(root):
    result={}
    for width,sd,arm in all_cells():
        key=f'{width}-{sd}-{arm}';folder=root/'fits'/key;f=folder/'fit.json'
        doc=json.loads(f.read_text())
        for row in doc['history']:assert sha(folder/row['checkpoint'])==row['sha256']
        result[key]=sha(f)
    value=dict(fits=result,prepared_sha256=sha(root/'data/prepared.json'),source=sha(Path(__file__)),protocol=sha(root/'src/PROTOCOL.md'))
    outfile=root/'seal.json'
    if outfile.exists():assert json.loads(outfile.read_text())==value
    else:dump(outfile,value)


def cold(root,width,sd,arm):
    tic=time.monotonic();key=f'{width}-{sd}-{arm}';path=root/'cold'/key;path.mkdir(parents=True,exist_ok=True)
    sealfile=root/'seal.json';sealed=json.loads(sealfile.read_text());assert len(sealed['fits'])==24
    f=root/'fits'/key/'fit.json';assert sha(f)==sealed['fits'][key];doc=json.loads(f.read_text())
    if (path/'result.json').exists():return
    d=Split(root,'cold');model=make_net(root,arm,width,sd,d.words)
    tables={};clock=[];ids=np.arange(len(d.fold))
    for row in doc['history']:
        st=time.monotonic();file=f.parent/row['checkpoint'];assert sha(file)==row['sha256']
        model.load_state_dict(torch.load(file,map_location='cpu',weights_only=True,mmap=True))
        synchronize();load_s=time.monotonic()-st;clock0=time.monotonic()
        obs=inference(model,d,ids,True);synchronize()
        prefix=str(row['steps'])+'-';tables.update({prefix+m:t for m,t in obs.items()})
        clock.append(dict(steps=row['steps'],load_wall=load_s,predict_four_wall=time.monotonic()-clock0))
    dest=path/'logits.npz'
    with dest.with_suffix('.part').open('wb') as w:np.savez_compressed(w,labels=d.y.cpu().numpy(),ids=d.key,**tables)
    dest.with_suffix('.part').replace(dest)
    dump(path/'result.json',dict(seal=sha(sealfile),fit=sha(f),logits=sha(dest),times=clock,process_wall=time.monotonic()-tic))
    print('cold complete',key,len(ids),flush=True)


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('root',type=Path);p.add_argument('mode',choices=['fit','cold','seal']);p.add_argument('--arm');p.add_argument('--width',type=int);p.add_argument('--seed',type=int)
    args=p.parse_args()
    torch.set_num_threads(1)
    if args.mode=='seal':seal(args.root)
    if args.mode=='fit':fit(args.root,args.arm,args.width,args.seed)
    if args.mode=='cold':cold(args.root,args.width,args.seed,args.arm)
