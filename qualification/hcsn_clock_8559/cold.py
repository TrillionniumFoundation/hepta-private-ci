"""Cold-load one sealed SHD rung and persist every emitted logit and input identity."""
import argparse
import json
import os
import time
from pathlib import Path
import numpy as np
import torch
from train import Data, apply, atomic_json, digest
from model import Classifier


def confirm(root,results,out,budget,matched_step=0,device="cpu"):
    torch.set_num_threads(1);torch.set_num_interop_threads(1)
    manifest=results/f'seal-{budget}.json'; rows=json.loads(manifest.read_text())
    assert len(rows)==21 and len({(x['arm'],x['seed']) for x in rows})==21
    common=time.perf_counter();d=Data(root)
    streams={}; row=speaker=y=None
    for name in ('natural','fast','slow'):
        with np.load(root/f'test-{name}.npz') as z:
            if row is None:row,speaker,y=z['row'],z['speaker'],z['y']
            else: assert np.array_equal(z['row'],row) and np.array_equal(z['speaker'],speaker) and np.array_equal(z['y'],y)
            streams[name]=(torch.from_numpy(np.log1p(z['counts'].astype('float32')))-d.m)/d.s
    streams.update(silent=(-d.m/d.s).expand_as(streams['natural']),reverse=streams['natural'].flip([1]))
    common=time.perf_counter()-common
    out.mkdir(parents=True,exist_ok=True)
    for info in rows:
        folder=results/f"{info['arm']}-{info['seed']}"
        receipt=folder/f'rung-{budget}.json';assert digest(receipt)==info['receipt_sha256']
        chosen=folder/f'selected-{budget}.pt';assert digest(chosen)==info['selected_sha256']
        if matched_step:chosen=folder/f'update-{matched_step}.pt'
        checkfile=out/(folder.name+'.json');probs=out/(folder.name+'.npz')
        if checkfile.exists():
            old=json.loads(checkfile.read_text())
            if digest(chosen)!=old['checkpoint_sha256'] or digest(probs)!=old['score_sha256']:raise ValueError(folder.name)
            continue
        started=time.perf_counter()
        model=Classifier(info['arm'])
        apply(model,torch.load(chosen,map_location='cpu',weights_only=True));model.to(device);model.eval()
        if device=='cuda':torch.cuda.synchronize()
        init_wall=time.perf_counter()-started
        kwargs={};timings={}
        with torch.inference_mode():
            for name,x in streams.items():
                stamp=time.perf_counter()
                kwargs[name]=torch.cat([model(batch.to(device)).cpu() for batch in x.split(48)]).numpy()
                timings[name]=time.perf_counter()-stamp
                assert kwargs[name].shape==(len(y),20) and np.isfinite(kwargs[name]).all()
        tmp=probs.with_suffix('.tmp')
        with tmp.open('wb') as h:np.savez_compressed(h,row=row,y=y,speaker=speaker,**kwargs)
        os.replace(tmp,probs)
        atomic_json(checkfile,dict(arm=info['arm'],seed=info['seed'],rung=budget,matched_step=matched_step,device=device,
                    checkpoint_sha256=digest(chosen),score_sha256=digest(probs),seal_sha256=digest(manifest),
                    input_setup_wall_s=common,model_restore_wall_s=init_wall,forward_wall_s=timings))
        print(folder.name,budget,matched_step,flush=True)
    atomic_json(out/'complete.json',{'seal':digest(manifest),'files':{f.name:digest(f) for f in sorted(out.glob('*.npz'))}})
if __name__=='__main__':
    p=argparse.ArgumentParser()
    for k in ('data','runs','out'):p.add_argument(k,type=Path)
    p.add_argument('rung',type=int);p.add_argument('--matched-step',type=int,default=0)
    p.add_argument('--device',choices=['cpu','cuda'],default='cpu')
    a=p.parse_args();confirm(a.data,a.runs,a.out,a.rung,a.matched_step,a.device)
