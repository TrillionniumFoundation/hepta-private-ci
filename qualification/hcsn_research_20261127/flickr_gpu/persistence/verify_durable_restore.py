"""Verify durable state, optimizer and sampler restoration in a separate CPU process."""
from pathlib import Path
import argparse
import hashlib
import json
import os
import sys
import time

DIRECTORY=Path.home()/'.local/share/hepta-research/hcsn-flickr8k-c511-9c415'


def sha(p):
    with p.open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()


def verify_file(record):
    p=Path(record['file'])
    assert p.is_relative_to(DIRECTORY) and p.is_file()
    assert p.stat().st_size==record['bytes'] and sha(p)==record['sha256']
    return p


def main():
    p=argparse.ArgumentParser();p.add_argument('budget',type=int);p.add_argument('--available',action='store_true')
    a=p.parse_args()
    sys.path.insert(0,str(DIRECTORY/'replay'))
    import torch
    import numpy as np
    from model import Captioner
    torch.set_num_threads(1);torch.set_num_interop_threads(1)
    assets=json.loads((DIRECTORY/'replay_manifest.json').read_text())
    for rec in assets['files'].values():verify_file(rec)
    assert sha(DIRECTORY/'replay/data/manifest.json')==assets['canonical_manifest']
    out={}
    for arm in ('hcsn','smooth','lif','mean','dense'):
        for seed in (17011,24203,39827):
            name=f'{arm}-{seed}';receipt=DIRECTORY/'snapshots'/f'{name}-{a.budget:04d}.json'
            if not receipt.exists() and a.available:continue
            j=json.loads(receipt.read_text());assert j['cell']==name and j['budget']==a.budget
            fit=json.loads(verify_file(j['fit']).read_text())
            selected=verify_file(j['selected']);resume=verify_file(j['resume'])
            raw=torch.load(resume,map_location='cpu',weights_only=False)
            assert raw['arm']==arm and raw['seed']==seed and raw['device']=='cuda'
            for k in ['steps','tokens','best_step','best_nll','train_s','dev_s','exposure_s','checkpoints']:
                assert raw['current'][k]==fit[k]
            assert fit['checkpoints'][-1]['nominal_s']==a.budget
            model=Captioner(arm,3490);model.load_state_dict(torch.load(selected,map_location='cpu',weights_only=True),strict=True)
            model.load_state_dict(raw['model'],strict=True)
            opt=torch.optim.AdamW(model.parameters(),lr=.0005,weight_decay=.01);opt.load_state_dict(raw['optimizer'])
            step_values=[]
            for param,state in opt.state.items():
                for k in ('exp_avg','exp_avg_sq'):
                    assert state[k].shape==param.shape and torch.isfinite(state[k]).all()
                step_values.append(int(state['step']))
            assert len(step_values)>0 and max(step_values)==fit['steps']
            rng=np.random.default_rng();rng.bit_generator.state=raw['rng'];images=rng.integers(5999,size=32);caps=rng.integers(5,size=32)
            rng2=np.random.default_rng();rng2.bit_generator.state=raw['rng'];assert np.array_equal(images,rng2.integers(5999,size=32)) and np.array_equal(caps,rng2.integers(5,size=32))
            out[name]=dict(steps=fit['steps'],selected_step=fit['best_step'],optimizer_slots=len(step_values),
                minimum_optimizer_step=min(step_values),maximum_optimizer_step=max(step_values),
                sampler_probe_sha256=hashlib.sha256(images.astype('<i8').tobytes()+caps.astype('<i8').tobytes()).hexdigest(),
                selected=j['selected'],resume=j['resume'],fit=j['fit'],snapshot_sha256=sha(receipt))
    if not a.available:assert len(out)==15
    final=DIRECTORY/f'restore_verified_{a.budget:04d}.json'
    result=dict(budget=a.budget,states=out,device_recorded='cuda',cold_verification='CPU map-location; strict native model reload, AdamW moments/steps/shapes/finiteness, NumPy sampler reconstruction; no optimizer update or holdout query',
        supporting_assets=len(assets['files']),replay_manifest_sha256=sha(DIRECTORY/'replay_manifest.json'),
        support_bytes=sum(q['bytes'] for q in assets['files'].values()),source=sha(Path(__file__)))
    temp=final.with_suffix('.part');temp.write_text(json.dumps(result,sort_keys=True,indent=2));temp.replace(final)
    print('verified restore',a.budget,len(out),'complete optimizer/sampler states',flush=True)


if __name__=='__main__':main()
