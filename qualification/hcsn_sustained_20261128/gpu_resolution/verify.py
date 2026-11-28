"""Independently re-evaluate the raw CUDA numerical pairs and sampled timing ratios."""
import argparse
import hashlib
import json
from pathlib import Path
import statistics

import numpy as np


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def verify(path):
    report=json.loads((path/'scaling.json').read_text())
    raw_path=path/'checks.npz'
    assert report['terminal'] and report['raw_npz_sha256']==digest(raw_path)
    assert report['dot']==140 and 'T4' in report['device']
    checked=[]
    with np.load(raw_path,allow_pickle=False) as arrays:
        array_count=len(arrays.files)
        elements=sum(arrays[k].size for k in arrays.files)
        for pair in report['pairs']:
            if pair['status_dense']!='ok' or pair['status_fft']!='ok':
                checked.append({key:pair[key] for key in ('kind','dtype','k','status_dense','status_fft')})
                continue
            base=f"{pair['kind']}_{pair['dtype']}_{pair['k']}_"
            prefix=base+'dense__'
            names=sorted(k[len(prefix):] for k in arrays.files if k.startswith(prefix))
            assert names and names==sorted(k[len(base+'fft__'):] for k in arrays.files if k.startswith(base+'fft__'))
            stats={}
            for field in names:
                x=arrays[prefix+field].astype('float64')
                y=arrays[base+'fft__'+field].astype('float64')
                assert x.shape==y.shape and np.isfinite(x).all() and np.isfinite(y).all()
                peak=float(np.abs(x-y).max())
                norm=peak/(1+np.max(np.abs(x)))
                recorded=pair['comparison'][field]
                assert abs(peak-recorded['max_abs'])<1e-13
                assert abs(norm-recorded['scaled_max_abs'])<1e-13
                stats[field]=float(norm)
            if pair['kind']=='operator':
                for mode in ('dense','fft'):
                    flow=arrays[base+mode+'__flow']
                    mass=arrays[base+mode+'__mass']
                    balance=arrays[base+mode+'__balance']
                    assert (flow>=0).all() and (flow<=1).all() and (mass>=0).all()
                    if pair['numeric_pass']:
                        assert np.max(np.abs(flow+mass.sum(axis=-1)-1))<pair['acceptance_bound']
                    err=float(np.max(np.abs(balance-1)))
                    assert err==pair['comparison']['conservation_'+mode]['max_abs']
            arm_a=report['arms'][base+'dense'];arm_b=report['arms'][base+'fft']
            ratios={}
            for suffix,field in [('wall','wall_s'),('cuda_event','cuda_event_s')]:
                val=statistics.median(arm_a[field])/statistics.median(arm_b[field])
                if pair.get('numeric_pass'):
                    assert abs(val-pair['dense_over_fft_'+suffix])<1e-12
                ratios[suffix]=val
            checked.append(dict(kind=pair['kind'],dtype=pair['dtype'],atoms=pair['k'],numeric_pass=pair['numeric_pass'],
                                max_scaled_error=max(stats.values()),recomputed_ratios=ratios))
    return dict(source_sha256=digest(path/'scaling.json'),raw_sha256=digest(raw_path),arrays_checked=array_count,array_elements_checked=elements,pairs=checked)


if __name__=='__main__':
    p=argparse.ArgumentParser()
    p.add_argument('--directory',type=Path,default=Path(__file__).resolve().parent)
    args=p.parse_args()
    obj=verify(args.directory)
    (args.directory/'independent.json').write_text(json.dumps(obj,indent=2)+'\n')
