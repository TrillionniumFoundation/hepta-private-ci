"""A fresh process confirms one previously selected arm. No model selection."""
import argparse
import json
import time
from pathlib import Path

import numpy as np
from fit import ARMS,BUDGETS,SEEDS,Cell,encode,load_data,scores,sha,dump


if __name__=='__main__':
    ap=argparse.ArgumentParser()
    ap.add_argument('models',type=Path);ap.add_argument('data',type=Path);ap.add_argument('table',type=Path)
    ap.add_argument('out',type=Path);ap.add_argument('seal',type=Path)
    ap.add_argument('seed',type=int,choices=SEEDS);ap.add_argument('arm',choices=['keep',*ARMS]);ap.add_argument('budget',type=int)
    a=ap.parse_args();a.out.mkdir(exist_ok=True)
    cpu=time.process_time();wall=time.perf_counter()
    s=json.loads(a.seal.read_bytes())
    here=Path(__file__).resolve().parent
    assert all(sha(here/k)==v for k,v in s['code'].items())
    assert sha(a.table)==s['table'] and sha(a.data/'data.json')==s['data_manifest']
    path=a.models/f'parent_{a.seed}.npz'
    assert sha(path)==s['fits'][path.name]
    with np.load(path) as f:p=dict(f)
    if a.arm=='keep':
        assert a.budget==0;w=p['W']
    else:
        assert a.budget in BUDGETS
        wpath=a.models/f'{a.arm}_{a.seed}_{a.budget}.npy'
        assert sha(wpath)==s['fits'][wpath.name]
        w=np.load(wpath)
    assert w.shape==p['W'].shape==(12,12) and np.isfinite(w).all()
    d=json.loads((a.data/'data.json').read_bytes())
    out={};law=Cell(a.table)
    for split in ('new','old'):
        key=split+'_test'
        assert sha(a.data/(key+'.npz'))==d['parts'][key]['sha256']
        x,y,sp,n=load_data(a.data,key)
        k=encode(x,p,law);z,_=scores(k,w,p,law)
        assert np.isfinite(z).all() and z.shape==(len(y),10)
        for suffix,val in [('scores',z),('label',y),('speaker',sp),('record',n)]:out[split+'_'+suffix]=val
    file=a.out/f'{a.arm}_{a.seed}_{a.budget}.npz'
    np.savez_compressed(file,**out)
    dump(file.with_suffix('.json'),{'pred_sha256':sha(file),'parent_sha256':sha(path),'seat':w.shape,'changed_coefficients':int((p['W']!=w).sum()),'wall_seconds':time.perf_counter()-wall,'cpu_seconds':time.process_time()-cpu})
