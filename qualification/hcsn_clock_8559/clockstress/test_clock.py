"""Test trained layers under a duplicated physical path or genuine higher resolution SHD events."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import sys
import time
import h5py
import numpy as np
import torch
from scipy.special import logsumexp
HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE.parent/'fused'));sys.path.insert(0,str(HERE.parent))
import model as physics
from native_v2 import FusedStepV2
from train import Data,SEEDS,apply,digest,atomic_json

def rebin(folder,factor,cache):
    filename=cache/f'shd-{factor}.npz'
    if filename.exists():return
    source=folder/'shd_test.h5'
    assert digest(source)=='47d8621a092cb483bea9448a93c0a3375a6726d370045090c2f7a77f70f95df3'
    with h5py.File(source) as f:
        tt=f['spikes/times'];uu=f['spikes/units'];y=f['labels'][:]
        ar=np.zeros((len(y),28*factor,28),np.uint16)
        for i in range(len(y)):
            t=tt[i].astype(np.float64);k=np.floor(t/(.05/factor)).astype(int);u=uu[i].astype(int)
            valid=k<28*factor
            a=np.bincount(k[valid]*28+u[valid]//25,minlength=28*factor*28)
            assert a.max()<=65535;ar[i]=a.reshape(28*factor,28)
    with filename.with_suffix('.part').open('wb') as h:np.savez_compressed(h,counts=ar)
    os.replace(filename.with_suffix('.part'),filename)
def layer(mod,x,lag):
    drive=mod.inp(x);z=torch.zeros_like(drive[:,0]);wall=signal=z
    queue=[z]*lag;price=z[...,None].expand(-1,-1,2);mass=mod.reset.expand(*z.shape,4)
    stream=[];integrated=z.clone()
    for frame in drive.unbind(1):
        u=frame+mod.recurrent(signal)+(price.tanh()*mod.feedback).sum(-1)
        release=queue.pop(0)
        out=FusedStepV2.apply(u,wall,mass,release,mod.table,mod.coeff,mod.probes,mod.emitter,mod.beta,False)
        wall=out[...,0];mass=out[...,1:5];hit=out[...,5]
        price=out[...,6:8];signal=out[...,8];integrated+=hit;queue.append(hit);stream.append(signal)
    return torch.stack(stream,1),integrated.mean(1)
def infer(model,x,lag):
    with torch.no_grad():
        a,first=layer(model.one,x,lag);h,second=layer(model.two,a,lag)
        z=model.head(h.reshape(len(x),4,-1,physics.WIDTH).mean(2).flatten(1))
    return z.numpy(),torch.stack([first,second],-1).numpy()
def main(data,runs,old,out,rung):
    torch.set_num_threads(1);torch.set_num_interop_threads(1)
    out.mkdir(exist_ok=True,parents=True)
    base=Data(data);raw={}
    with np.load(data/'test-natural.npz') as q:
        coarse=q['counts'];labels=q['y'];speakers=q['speaker'];rows=q['row']
    for k in (2,4):
        rebin(data,k,out)
        with np.load(out/f'shd-{k}.npz') as f:ar=f['counts']
        assert np.array_equal(ar.reshape(len(ar),28,k,28).sum(2),coarse)
        raw[k]=ar
    nominal=(torch.from_numpy(np.log1p(coarse.astype(np.float32)))-base.m)/base.s
    meta=json.loads((runs/f'seal-{rung}.json').read_text())
    summary={};compiled=None
    for seed in SEEDS:
        info=next(m for m in meta if m['arm']=='literal' and m['seed']==seed)
        weight=runs/f'literal-{seed}'/f'selected-{rung}.pt'
        assert digest(weight)==info['selected_sha256']
        with np.load(old/f'literal-{seed}.npz') as q:
            assert np.array_equal(labels,q['y']) and np.array_equal(rows,q['row'])
            previous=q['natural']
        baseline=None
        for factor in (1,2,4):
            physics.DT=.05/factor
            m=physics.Classifier('literal')
            apply(m,torch.load(weight,map_location='cpu',weights_only=True));m.eval()
            modes=[('repeat',1)] if factor==1 else [('repeat',1),('repeat',factor),('raw',1),('raw',factor)]
            for source,lag in modes:
                tag=f'{seed}-x{factor}-{source}-lag{lag}';p=out/(tag+'.npz')
                if not p.exists():
                    started=time.perf_counter();scores=[];flux=[]
                    for i in range(0,len(labels),48):
                        if source=='repeat':x=nominal[i:i+48].repeat_interleave(factor,1)
                        else:x=(torch.from_numpy(np.log1p(raw[factor][i:i+48].astype(np.float32)*factor))-base.m)/base.s
                        y,count=infer(m,x,lag);scores.append(y);flux.append(count)
                    with p.with_suffix('.partial').open('wb') as h:np.savez_compressed(h,logits=np.concatenate(scores),flux=np.concatenate(flux),wall_s=time.perf_counter()-started)
                    os.replace(p.with_suffix('.partial'),p)
                with np.load(p) as q:z=q['logits'];fl=q['flux'];wall=float(q['wall_s'])
                if factor==1:
                    err=float(np.max(np.abs(z-previous)));baseline=(z.copy(),fl.copy())
                    assert err<3e-4,('nominal reference mismatch',err)
                h=(z.argmax(1)==labels).astype(float);lp=z.astype(float);loss=logsumexp(lp,1)-lp[np.arange(len(lp)),labels]
                rawacc=(baseline[0].argmax(1)==labels).astype(float)
                sp_result={int(s):float(h[speakers==s].mean()) for s in np.unique(speakers)}
                adiff=float(np.mean([(h[speakers==s]-rawacc[speakers==s]).mean() for s in np.unique(speakers)]))
                disagree=float(np.mean(z.argmax(-1)!=baseline[0].argmax(-1)))
                summary[tag]=dict(seed=seed,substeps=factor,path=source,refractory_steps=lag,speaker_macro=float(np.mean(list(sp_result.values()))),
                    by_speaker=sp_result,macro_change=adiff,macro_nll=float(np.mean([loss[speakers==s].mean() for s in np.unique(speakers)])),
                    fraction_labels_changed=disagree,mean_flux_by_layer=fl.mean(0).tolist(),
                    mean_absolute_flux_change=np.mean(np.abs(fl-baseline[1]),axis=0).tolist(),
                    accepts_clock_invariance=bool(disagree<=.01 and abs(adiff)<=.02),
                    original_cold_logit_max=err if factor==1 else None,execution_wall_s=wall,source_checkpoint=digest(weight),score_sha256=digest(p))
                atomic_json(out/'RESULTS.json',summary);print(tag,round(adiff,5),round(disagree,5),flush=True)
if __name__=='__main__':
    p=argparse.ArgumentParser()
    for n in ('data','runs','nominal','out'):p.add_argument(n,type=Path)
    p.add_argument('rung',type=int);a=p.parse_args();main(a.data,a.runs,a.nominal,a.out,a.rung)
