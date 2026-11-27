"""Seal all SHD contender states before official labels can enter a scoring process."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import resource
import numpy as np
from scipy.special import ndtr
from common import sha,record,usage,SEEDS,score_batches

def roster():
    return [(g,k,s) for g,fams in [('construct',('ridge','physical','smooth','random','shuffled')),('bp',('physical','conv','english')),('edit',('keep','direct','shuffle','lora','adam'))] for k in fams for s in (SEEDS if g!='construct' or k in ('random','shuffled') else SEEDS[:1])]


def seal(root):
    states={}
    for g,k,s in roster():
        d=root/'fits'/g/f'{k}-{s}';state=d/'selected.npz';fit=d/'fit.json'
        rec=json.loads(fit.read_text());assert rec['checkpoint']==sha(state)
        assert json.loads((d/'supervised.json').read_text())['exit_code']==0
        assert rec['test_label_access'] is False
        if g=='edit':
            parent=root/'fits/bp'/f'english-{s}'/'selected.npz'
            assert rec['parent']==sha(parent)
            with np.load(state) as a,np.load(parent) as b:
                assert set(a.files)==set(b.files)
                for par in a:
                    if par!='w2':assert np.array_equal(a[par],b[par])
                changed=int((a['w2']!=b['w2']).sum());assert changed==rec['hidden_changed']
        states[f'{g}/{k}-{s}']=dict(model=sha(state),fit=sha(fit),source=rec.get('arm'))
    dev={}
    for g,arm in [('construct','ridge'),('bp','conv'),('bp','physical')]:
        keys=[k for k in states if k.startswith(f'{g}/{arm}-')]
        dev[g+'/'+arm]=float(np.mean([json.loads((root/'fits'/k/'fit.json').read_text())['best']['dev']['speaker_acc'] for k in keys]))
    pkg=Path(__file__).parent
    sources={f.name:sha(f) for f in sorted(pkg.iterdir()) if f.suffix in ('.md','.py')}
    dest=root/'seal.json'
    contents=dict(models=states,source=sources,dev_criterion=dev,chosen_cmp=max(dev,key=dev.get),
                  preparatory_arrays=json.loads((root/'data/prepare.json').read_text())['arrays'])
    if dest.exists(): assert contents==json.loads(dest.read_text())
    else:record(dest,contents)
    print("seal",sha(dest),len(states),contents['chosen_cmp'],flush=True)


def conv_pred(x,state):
    for prefix in ('c1','c2'):
        w=state[prefix+'.weight'];b=state[prefix+'.bias']
        padded=np.pad(x,((0,0),(1,1),(0,0)))
        a=sum(padded[:,j:j+x.shape[1],:]@w[:,:,j].T for j in range(3))+b
        x=a*ndtr(a)
    return x.reshape(len(x),6,2,-1).mean(2).reshape(len(x),-1)@state['out.weight'].T+state['out.bias']


def cold(root,source,model):
    import h5py
    manifest=json.loads((root/'seal.json').read_text())
    assert set(manifest['models'])=={f'{g}/{k}-{s}' for g,k,s in roster()}
    info=manifest['models'][model]
    checkpoint=root/'fits'/model/'selected.npz';assert sha(checkpoint)==info['model']
    with np.load(checkpoint) as a: state=dict(a)
    x=(np.load(root/'data/x_test.npy')-state['center'])/state['scale']
    people=np.load(root/'data/people_test.npy')
    with h5py.File(source/'shd_test.h5') as f: y=f['labels'][:].astype('i8')
    table=dict(np.load(root/'data/law.npz'))
    if state['kind'].item()=='conv':
        scores=np.concatenate([conv_pred(x[i:i+96],state) for i in range(0,len(x),96)])
    else:scores=score_batches(x,state,table)
    assert scores.shape==(len(x),10 if model.startswith(('bp/english-','edit/')) else 20)
    assert np.isfinite(scores).all()
    d=root/'test'/model;d.mkdir(parents=True,exist_ok=True);out=d/'scores.npz'
    np.savez_compressed(out,logits=scores,y=y,people=people,record=np.arange(len(y)),temperature=state['temperature'])
    record(d/'receipt.json',dict(model=model,checkpoint=info['model'],seal=sha(root/'seal.json'),
           predictions=sha(out),n=len(x),**usage()))


def invoke(root,source):
    seal(root)
    for g,k,s in roster():
        name=f'{g}/{k}-{s}';target=root/'test'/name
        if (target/'clock.json').exists() and json.loads((target/'clock.json').read_text())['exit']==0:continue
        cmd=[sys.executable,__file__,'--action','one','--root',str(root),'--source',str(source),'--model',name]
        start=time.perf_counter()
        sub=subprocess.run(cmd)
        receipt=dict(wall_s=time.perf_counter()-start,exit=sub.returncode)
        target.mkdir(parents=True,exist_ok=True);record(target/'clock.json',receipt)
        if sub.returncode:raise SystemExit(sub.returncode)
        print(name,receipt['wall_s'],flush=True)


if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('--action',choices=('seal','one','all'),required=True)
    ap.add_argument('--root',type=Path,required=True);ap.add_argument('--source',type=Path);ap.add_argument('--model')
    a=ap.parse_args()
    if a.action=='seal':seal(a.root)
    elif a.action=='all':invoke(a.root,a.source)
    else:cold(a.root,a.source,a.model)
