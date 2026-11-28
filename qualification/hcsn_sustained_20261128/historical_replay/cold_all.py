"""Independently score every immutable historical checkpoint, opening held data only after the original terminal."""
import ctypes
import hashlib
import json
import os
from pathlib import Path
import select
import sys
import time
import numpy as np
import torch

HERE=Path.home()/'.local/share/hepta-research'
BASE=HERE/'hcsn-sustained-1140569'
OUT=BASE/'run'
SRC=HERE/'hcsn-cremad-e0bf-20261127'
SNAP=HERE/'hcsn-9de7-sustained-history'/'objects'
DEST=HERE/'hcsn-9de7-cold-history'
CODE='69e8cf12bcfcd414175250405ac08286901457377d76c1ad28f08d33a775dbc1'
ARMS=('literal','smooth','lif','sdpa')
SEEDS=(137,311,557)
GATES=('update16','update128','time20','time240','time1000','time3150')


def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()
def read(path):return json.loads(path.read_text())
def write(path,data):
    temp=path.with_suffix('.pending')
    temp.write_text(json.dumps(data,indent=2,allow_nan=False)+'\n')
    os.replace(temp,path)


def wait_for_terminal():
    f=OUT/'terminal.json'
    if f.is_file():return
    lib=ctypes.CDLL(None,use_errno=True)
    fd=lib.inotify_init1(os.O_CLOEXEC)
    if fd<0:raise OSError(ctypes.get_errno(),'inotify')
    if lib.inotify_add_watch(fd,os.fsencode(OUT),0x8|0x80|0x100)<0:
        raise OSError(ctypes.get_errno(),'inotify_add_watch')
    while not f.is_file():
        select.select([fd],[],[]);os.read(fd,65536)
    os.close(fd)


def basic(scores,y):
    a=scores.astype(np.float64)
    m=a.max(1)
    loss=np.log(np.exp(a-m[:,None]).sum(1))+m-a[np.arange(len(y)),y]
    hits=np.argmax(a,axis=1)==y
    return dict(nll=float(loss.mean()),top1=float(hits.mean())),loss,hits


def score(data,split,final=False):
    from encoder import AVText
    from study import inference
    rows=data.dev if split=='dev' else data.test
    truth=data.y[rows].numpy();ids=data.names[rows]
    cache=DEST/split;cache.mkdir(exist_ok=True)
    recs={};selection=read(OUT/'seal.json') if final else {}
    term=read(OUT/'terminal.json') if final else {}
    for arm in ARMS:
        for seed in SEEDS:
            key=f'{arm}-{seed}'
            history=read(OUT/key/'progress.json')['history']
            if final:assert set(GATES)==set(x for z in history for x in z['tags'])
            model=AVText(arm,96,seed,data.words,SRC/'src/law4.npz')
            best=selection.get(key,{}).get('best',{}).get('file')
            for z in history:
                name=z['file'];digest=z['sha256']
                stable=SNAP/(digest+'.pt')
                if not stable.exists():
                    # Early development snapshot can coincide with the archive linking a new item.
                    stable=OUT/key/name
                if sha(stable)!=digest:raise ValueError(('immutable weight mismatch',key,name))
                stem=f'{key}-{Path(name).stem}';file=cache/(stem+'.npz');receipt=cache/(stem+'.json')
                if not receipt.exists():
                    model.load_state_dict(torch.load(stable,map_location='cpu',weights_only=True))
                    mat=inference(model,data,rows).numpy()
                    temp=file.with_suffix('.tmp')
                    with temp.open('wb') as fout:np.savez_compressed(fout,ids=ids,y=truth,scores=mat)
                    os.replace(temp,file)
                    summ,_,_=basic(mat,truth)
                    details=dict(weight_sha256=digest,score_sha256=sha(file),metrics=summ,
                                 arm=arm,seed=seed,tags=z['tags'],steps=z['steps'],training_s=z['optimization_wall'])
                    write(receipt,details)
                rec=read(receipt)
                assert rec['weight_sha256']==digest and rec['score_sha256']==sha(file)
                with np.load(file,allow_pickle=False) as est:
                    assert np.array_equal(est['ids'],ids) and np.array_equal(est['y'],truth)
                    mat=est['scores']
                summ,_,_=basic(mat,truth)
                assert rec['metrics']==summ
                if split=='dev':
                    assert abs(summ['nll']-z['development_nll'])<3e-6
                    assert abs(summ['top1']-z['development_top1'])<1e-7
                if split=='held' and name==best:
                    with np.load(OUT/key/'cold.npz',allow_pickle=False) as orig:
                        assert np.array_equal(orig['scores'],mat)
                if split=='held':
                    for gate,orig in selection[key]['gates'].items():
                        if orig and orig['file']==name:
                            expected=term['cells'][key]['gates'][gate]['cold']
                            assert abs(summ['nll']-expected['nll'])<3e-6
                            assert abs(summ['top1']-expected['top1'])<1e-7
                recs[stem]=dict(**rec,file=file.name)
    return recs


def compare(data,held):
    y=data.y[data.test].numpy();actors=data.actors[data.test];people=np.unique(actors)
    count=np.asarray([(actors==p).sum() for p in people])
    rng=np.random.default_rng(595575);indices=rng.integers(len(people),size=(4000,len(people)))
    vs={}
    for tag in GATES:
        values={}
        for key,r in held.items():
            if tag not in r['tags']:continue
            with np.load(DEST/'held'/r['file'],allow_pickle=False) as a:
                _,loss,hit=basic(a['scores'],y)
            values[r['arm'],r['seed']]=[loss,hit.astype(np.float64)]
        assert len(values)==12
        for arm in ('smooth','lif','sdpa'):
            for idx,metric in enumerate(('nll','accuracy')):
                delta=np.mean([values['literal',seed][idx]-values[arm,seed][idx] for seed in SEEDS],axis=0)
                sums=np.array([delta[actors==p].sum() for p in people])
                boot=sums[indices].sum(1)/count[indices].sum(1)
                vs[f'{tag}:{arm}:{metric}']=[float(delta.mean()),*np.quantile(boot,[.025,.975]).tolist()]
    return vs


def main():
    os.umask(0o077);DEST.mkdir(exist_ok=True)
    assert sha(BASE/'study.py')==CODE
    sys.path.insert(0,str(BASE));sys.path.insert(0,str(SRC/'src'))
    from study import Data,HASHES
    for rel,digest in HASHES.items():assert sha(SRC/rel)==digest
    torch.set_num_threads(1);torch.set_num_interop_threads(1)
    data=Data(SRC)
    current=score(data,'dev')
    write(DEST/'development-current.json',dict(utc=time.time(),n=len(current),stored_score_values=len(current)*len(data.dev)*72,scores=current))
    print('verified original development history',len(current),flush=True)
    wait_for_terminal()
    dev=score(data,'dev',True);held=score(data,'held',True)
    assert dev.keys()==held.keys()
    terminal=dict(original_source_sha256=CODE,original_seal_sha256=sha(OUT/'seal.json'),
                  original_terminal_sha256=sha(OUT/'terminal.json'),weights=len(held),seeds=SEEDS,
                  clips=len(data.test),held_gallery_scores=len(held)*len(data.test)*72,
                  dev_gallery_scores=len(dev)*len(data.dev)*72,dev=dev,held=held,
                  paired_fixed_gate_comparisons=compare(data,held))
    write(DEST/'terminal-all.json',terminal)
    print('verified complete existing historical series',len(held),sha(DEST/'terminal-all.json'),flush=True)
if __name__=='__main__':main()
