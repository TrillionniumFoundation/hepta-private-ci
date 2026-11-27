"""Describe actual receiver matrix changes using only the paid fit keys."""
import argparse
import json
from pathlib import Path

import numpy as np
from scipy.linalg import eigh
from fit import ARMS,BUDGETS,SEEDS,Cell,panel,sha,dump


if __name__=='__main__':
    a=argparse.ArgumentParser()
    for name in ['models','data','table','seal','out']:a.add_argument(name,type=Path)
    args=a.parse_args();booked=json.loads(args.seal.read_bytes());law=Cell(args.table);out={}
    for seed in SEEDS:
        pth=args.models/f'parent_{seed}.npz';assert sha(pth)==booked['fits'][pth.name]
        with np.load(pth) as z:p=dict(z)
        keys={}
        for part in ('old','new'):
            k,_,_=panel(args.data,part+'_cal',p,law,True)
            keys[part]=k.reshape(-1,k.shape[-1])
        cov={part:k.T@k/len(k) for part,k in keys.items()}
        eye=np.eye(len(cov['old']))
        vals=eigh(cov['new']+.001*eye,cov['old']+.05*np.trace(cov['old'])/len(eye)*eye,eigvals_only=True)[::-1]
        entries={}
        for arm in ARMS:
            for budget in BUDGETS:
                path=args.models/f'{arm}_{seed}_{budget}.npy'
                assert sha(path)==booked['fits'][path.name]
                delta=np.load(path)-p['W'];singular=np.linalg.svd(delta,compute_uv=False)
                rank=int(np.sum(singular>max(singular[0]*1e-10,1e-12)))
                if arm=='lora':assert rank<=3
                entries[f'{arm}_{budget}']={'changed':int(np.sum(delta!=0)),'rank':rank,
                    'frobenius_norm':float(np.linalg.norm(delta)),
                    'drive_rms_on_calibration':{part:float(np.mean((k@delta)**2)**.5) for part,k in keys.items()}}
        out[str(seed)]={'regularized_new_vs_old_eigenvalues':vals.tolist(),'write_site':entries}
    dump(args.out,out)
