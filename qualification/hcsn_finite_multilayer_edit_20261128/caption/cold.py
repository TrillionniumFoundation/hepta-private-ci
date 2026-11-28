"""Freeze all supports and states, then score original images, shifted images and class logits independently."""
import argparse
import json
import time
from pathlib import Path

import numpy as np
import torch
from caption_data import load_net,panels,read,sha,sites,write

ARMS=('keep','tied','joint','flow','bp','lora','unigram','wrong')
SEEDS=(109,271,463)
STEPS=(15,60,240)


def registration(a):
    out={}
    for arch in ('literal','smooth'):
        for seed in SEEDS:
            key=f'{arch}-{seed}'
            root=a.models/key
            parent=read(a.parents/'runs'/key/'selected.json')
            assert parent['sha']==sha(a.parents/'runs'/key/'selected.pt')
            out[key]={'parent':parent['sha'],'old_dev_selection':sha(a.parents/'runs'/key/'selected.json'),
                      'fits':{'keep':{'0':['keep',None]}}}
            for method in ARMS[1:]:
                f=root/(method+'.json');fit=read(f)
                assert fit['parent']==parent['sha']
                cases={}
                for step in STEPS:
                    p=fit['picks'][str(step)]['choice']
                    blob=root/p['file'] if p['file'] else None
                    if blob:assert sha(blob)==p['sha']
                    cases[str(step)]=[p['sha'] or 'keep',p['file']]
                out[key]['fits'][method]=cases
                out[key].setdefault('training',{})[method]=sha(f)
    files=[a.parents/n for n in ('law4.npz','data.json','data.npz','vocabulary.json')]
    files.extend(a.fresh/n for n in ('train.npz','dev.npz','test.npz','identities.json','data.json'))
    meta=read(a.parents/'data.json')
    old_pixels=Path(meta['pixels'])
    assert sha(old_pixels)==meta['pixel_sha']
    return dict(models=out,images=meta['pixel_sha'],files={str(f.resolve()):sha(f) for f in files},
                source={p.name:sha(p) for p in sorted(Path(__file__).parent.glob('*.py'))},
                protocol=sha(Path(__file__).with_name('PROTOCOL.md')))


def losses(net,panel,bias,shift):
    # Use independent true-next-token gather and float64 logsumexp, preserving all token positions.
    cost=[]
    with torch.inference_mode():
        for i in range(0,len(panel),8):
            idx=np.arange(i,min(i+8,len(panel)))
            pixels,text,target=panel.batch(idx,(idx+1)%len(panel) if shift else None)
            z=(net(pixels,text)+bias).double()
            likelihood=torch.logsumexp(z,-1)-torch.take_along_dim(z,target.unsqueeze(-1),dim=-1).squeeze(-1)
            cost.append(torch.where(target!=0,likelihood,0.).numpy())
    return np.concatenate(cost)


def cold(a):
    torch.set_num_threads(1)
    manifest=read(a.work/'seal.json')
    current=registration(a)
    assert manifest==current
    key=f'{a.arch}-{a.seed}'
    model,reg=load_net(a.parents,a.arch,a.seed)
    g=manifest['models'][key]
    panels0=panels(a.parents,a.fresh,True)
    w,h=sites(model)
    base=[q.weight.detach().clone() for q in (w,h)]
    outputs=a.work/key
    outputs.mkdir(exist_ok=True)
    target=outputs/'targets.npz'
    if not target.exists():
        np.savez_compressed(target,**{f'{k}_{n}':v for k,t in panels0.items()
            for n,v in (('y',t.y),('ids',t.names))})
    cases={digest:file for values in g['fits'].values() for digest,file in values.values()}
    for digest,filename in cases.items():
        dest=outputs/(digest+'.npz');timefile=outputs/(digest+'.json')
        if dest.exists() and timefile.exists() and sha(dest)==read(timefile)['sha']:continue
        tick=time.perf_counter();cpu=time.process_time()
        bias=torch.zeros(w.weight.shape[0])
        with torch.no_grad():
            if filename:
                local=a.models/key/filename
                assert sha(local)==digest
                with np.load(local) as f:
                    w.weight.copy_(torch.from_numpy(f['W']));h.weight.copy_(torch.from_numpy(f['P']));bias=torch.from_numpy(f['b'])
            else:
                w.weight.copy_(base[0]);h.weight.copy_(base[1])
        evidence={}
        for k,t in panels0.items():
            evidence[k]=losses(model,t,bias,False)
            evidence[k+'_shifted']=losses(model,t,bias,True)
        dur=[time.process_time()-cpu,time.perf_counter()-tick]
        np.savez_compressed(dest,**evidence)
        write(timefile,dict(cpu=dur[0],wall=dur[1],sha=sha(dest),parent=reg['sha'],choice=digest))
        print(key,digest[:12],dur,flush=True)
    write(outputs/'complete.json',{'distinct':len(cases),'actual_tokens':{k:int((s.y!=0).sum()) for k,s in panels0.items()},
                                    'targets':sha(target),'seal':sha(a.work/'seal.json')})


if __name__=='__main__':
    p=argparse.ArgumentParser()
    p.add_argument('mode',choices=('seal','cold'))
    for n in ('parents','fresh','models','work'):p.add_argument(n,type=Path)
    p.add_argument('--arch',choices=('literal','smooth'));p.add_argument('--seed',type=int,choices=SEEDS)
    a=p.parse_args();a.work.mkdir(exist_ok=True,parents=True)
    if a.mode=='seal':
        out=a.work/'seal.json'
        if out.exists():raise FileExistsError(out)
        write(out,registration(a))
    else:
        assert a.seed and a.arch
        cold(a)
