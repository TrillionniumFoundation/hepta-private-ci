"""Seal all training outputs, then score each arm in a fresh scoring process."""
import time
ENTRY=time.perf_counter();ENTRY_CPU=time.process_time()
import argparse
import json
from pathlib import Path
import numpy as np
from model import ARMS,FP_ARMS,SEEDS,RUNGS,Cell,fp_readout_features,sha,prep,predict,raw_features,read_batches


def dump(path,obj):
    path.write_text(json.dumps(obj,indent=1,sort_keys=True,allow_nan=False)+'\n')


def sources():
    home=Path(__file__).resolve().parent
    paths=[home/s for s in ('PROTOCOL.md','FP_PROTOCOL.md','forward_projection.py','model.py','train.py','gradcheck.py','cold.py','verify.py')]
    paths.append(home.parent/'hcsn_independent_audiomnist_20261127'/'receiver.py')
    return {p.name:sha(p) for p in paths}


def seal(a):
    if a.seal.exists():raise FileExistsError(a.seal)
    fits={}
    for arm in ARMS+FP_ARMS:
        for seed in SEEDS:
            train_path=a.models/f'{arm}_{seed}.json'
            history=json.loads(train_path.read_bytes());fits[train_path.name]=sha(train_path)
            for r in RUNGS:
                chosen=history['selected'][str(r)]
                if chosen is None:continue
                assert chosen['fit_cpu']<=r
                p=a.models/f'{arm}_{seed}_{r}.npz'
                assert sha(p)==chosen['sha256'];fits[p.name]=sha(p)
    dump(a.seal,{'archive':sha(a.archive),'law':sha(a.law),'fits':fits,'code':sources(),'gradcheck':sha(a.models/'gradcheck.json'),'confirmation':'pending'})
    print('sealed',len(fits),sha(a.seal),flush=True)


def score(a):
    sealed=json.loads(a.seal.read_bytes());assert sealed['code']==sources()
    assert sha(a.archive)==sealed['archive'] and sha(a.law)==sealed['law']
    x,y,b,ids=read_batches(a.archive,(8,9,10))
    law=Cell(a.law) if a.arm in ('forward','bp','hybrid_bp','frozen','fp_hcsn','fp_shuffle') else None
    a.out.mkdir(exist_ok=True,parents=True);scores={'y':y,'batch':b,'feature_id':ids}
    read_wall=time.perf_counter()-ENTRY;read_cpu=time.process_time()-ENTRY_CPU
    rows={}
    for r in RUNGS:
        p=a.models/f'{a.arm}_{a.seed}_{r}.npz'
        if p.name not in sealed['fits']:continue
        started=time.perf_counter();cpu=time.process_time();assert sha(p)==sealed['fits'][p.name]
        with np.load(p) as weights:
            t=prep(x,weights)
            if a.arm in FP_ARMS:z=fp_readout_features(t,weights,a.arm,law)@weights['w3']
            elif law is None:z=raw_features(t,a.arm,weights)@weights['w3']
            else:z=predict(t,weights,law)
        assert z.shape==(len(y),6) and np.isfinite(z).all()
        scores['r'+str(r)]=z.astype(np.float64);rows[r]={'model_load_and_prediction_wall':time.perf_counter()-started,'model_load_and_prediction_cpu':time.process_time()-cpu}
    file=a.out/f'{a.arm}_{a.seed}.npz';np.savez_compressed(file,**scores)
    dump(file.with_suffix('.json'),{'source_and_start_wall':read_wall,'source_and_start_cpu':read_cpu,'per_rung':rows,'seal_sha256':sha(a.seal),'pred_sha256':sha(file),'scoring_complete_wall':time.perf_counter()-ENTRY,'scoring_complete_cpu':time.process_time()-ENTRY_CPU})
    print(a.arm,a.seed,len(rows),flush=True)


def main():
    p=argparse.ArgumentParser()
    p.add_argument('command',choices=('seal','score'))
    for k in ('models','archive','law','seal','out'):p.add_argument(k,type=Path)
    p.add_argument('arm',nargs='?',choices=ARMS+FP_ARMS);p.add_argument('seed',nargs='?',type=int,choices=SEEDS)
    a=p.parse_args();(seal if a.command=='seal' else score)(a)


if __name__=='__main__':main()
