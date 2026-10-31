"""Research-only crash-resumable, create-only, parallel process-CPU paired study.

Parallelism is across independent seed processes, never inside a paired arm.
A separate process CPU clock per worker prevents concurrent workers from
consuming each other's measured budget. All raw per-example predictions are
atomically sealed per seed, then summarized without overwriting old receipts.
"""
import base64
from concurrent.futures import ProcessPoolExecutor, as_completed
import gzip
import hashlib
import json
import os
from pathlib import Path
import platform
import sys

import numpy as np
import scipy
import torch

from .independent_regime_trial import Refuse, exact_signflip_p, make_data, score, train, warmup_runtime
from .run_regime_trial import ROOT, _write_create_only


def _sha(raw):return hashlib.sha256(raw).hexdigest()


def _worker(seed, p, seal):
    bootstrap_cpu=warmup_runtime()
    train_obs,train_y=make_data(seed+10000,p['train_examples_per_seed'])
    iid_obs,iid_y=make_data(seed+20000,p['iid_examples_per_seed'])
    ood_obs,ood_y=make_data(seed+30000,p['ood_examples_per_seed'],ood=True)
    record={'seed':seed,'protocol_sha256':seal,'shared_runtime_bootstrap_cpu_seconds':bootstrap_cpu,
            'train_event_rate':float(np.mean(train_y)),'iid_event_rate':float(np.mean(iid_y)),
            'ood_event_rate':float(np.mean(ood_y)),
            'iid_labels':iid_y.tolist(),'ood_labels':ood_y.tolist(),'arms':{}}
    for arm in p['arms']:
        model,receipt=train(seed,arm,train_obs,train_y,budget_seconds=p['process_cpu_training_and_features_seconds_per_arm'])
        record['arms'][arm]={'training':receipt,'iid':score(model,iid_obs,iid_y,arm),
                             'ood':score(model,ood_obs,ood_y,arm)}
    return record


def _receipt_bytes(record):
    return (json.dumps(record,sort_keys=True,separators=(',',':'),allow_nan=False)+'\n').encode()


def run(prefix):
    protocol=(ROOT/'PROTOCOL_20261031.json').read_bytes()
    p=json.loads(protocol)
    seal=_sha(protocol)
    if (p['base_head_sha']!='042af0017b08f4316949cf9ba450ecd5e63350b3'
        or p['process_cpu_training_and_features_seconds_per_arm']!=2.0
        or p['seeds']!=list(range(501,509)) or p['model_trainable_parameters']!=609):
        raise Refuse('frozen protocol mutated')
    root=Path(str(prefix)+'_receipts')
    root.mkdir(mode=0o700,parents=False,exist_ok=True)
    pending=[]
    for seed in p['seeds']:
        if not (root/f'{seed}.json').exists():pending.append(seed)
    if pending:
        with ProcessPoolExecutor(max_workers=4) as pool:
            futures={pool.submit(_worker,seed,p,seal):seed for seed in pending}
            for f in as_completed(futures):
                seed=futures[f]
                record=f.result()
                if record['seed']!=seed or record['protocol_sha256']!=seal:
                    raise Refuse('worker/protocol identity mismatch')
                _write_create_only(root/f'{seed}.json',_receipt_bytes(record))
                print(f"sealed seed {seed} to create-only receipt",flush=True)
    rows=[]; file_seals={}
    for seed in p['seeds']:
        path=root/f'{seed}.json'
        blob=path.read_bytes()
        item=json.loads(blob)
        if item['seed']!=seed or item['protocol_sha256']!=seal or len(item['iid_labels'])!=768 or len(item['ood_labels'])!=768:
            raise Refuse('corrupt or wrong seed receipt; do not overwrite')
        if set(item['arms'])!=set(p['arms']):raise Refuse('incomplete arm receipt')
        for arm in p['arms']:
            for split in ('iid','ood'):
                pr=item['arms'][arm][split]['prediction']
                if len(pr)!=768 or not all(0<=v<=1 for v in pr):raise Refuse('bad prediction receipt')
            if item['arms'][arm]['training']['parameters']!=609:raise Refuse('wrong model budget')
        rows.append(item);file_seals[str(seed)]=_sha(blob)
    diffs=[v['arms']['ordinary']['ood']['brier']-v['arms']['call_put_margin_risk']['ood']['brier'] for v in rows]
    iddiff=[v['arms']['ordinary']['iid']['brier']-v['arms']['call_put_margin_risk']['iid']['brier'] for v in rows]
    cpus=[v['arms'][arm]['training']['training_and_feature_cpu_seconds'] for v in rows for arm in p['arms']]
    raw={'schema':'hcsn-p1-markov-evolving-raw-v2','protocol_sha256':seal,'per_seed_receipt_sha256':file_seals,
         'environment':{'python':sys.version,'platform':platform.platform(),
                        'numpy':np.__version__,'scipy':scipy.__version__,'torch':torch.__version__},
         'rows':rows}
    raw_blob=_receipt_bytes(raw)
    mean=float(np.mean(diffs));idi=float(np.mean(iddiff));sig=exact_signflip_p(diffs)
    summary={'schema':'hcsn-p1-markov-evolving-summary-v2','protocol_sha256':seal,
       'raw_sha256':_sha(raw_blob),'n_seeds':len(rows),'per_seed_receipt_sha256':file_seals,
       'ood_brier_improvement_per_seed':diffs,'iid_brier_improvement_per_seed':iddiff,
       'mean_ood_brier_improvement':mean,'mean_iid_brier_improvement':idi,
       'exact_two_sided_signflip_p_ood':sig,'min_training_cpu_seconds':min(cpus),
       'max_training_cpu_seconds':max(cpus),'mean_training_cpu_seconds':float(np.mean(cpus)),
       'cpu_budgets_matched':max(cpus)-min(cpus)<0.1,'trainable_parameters_each':609,
       'exploratory_screen_passed':mean>=.01 and sig<=.05 and idi>=-.01,
       'same_observed_information':True,'independent_new_information_from_feature':False,
       'p1_closed':False,'p0_p6_closed':False,'production_activation':False,
       'limits':['synthetic piecewise Markov GBM, not original HX','no GPU/energy/real tasks',
                 'per-seed model weights and CPU timing may vary slightly on replay']}
    compressed=base64.b64encode(gzip.compress(raw_blob,mtime=0))+b'\n'
    _write_create_only(Path(str(prefix)+'.json.gz.b64'),compressed)
    _write_create_only(Path(str(prefix)+'.json'),_receipt_bytes(summary))
    return summary

if __name__=='__main__':
    if len(sys.argv)!=2:raise SystemExit('usage: python -m experiments.hcsn_p1_regime.run_parallel_regime_trial output_prefix')
    print(json.dumps(run(sys.argv[1]),indent=2),flush=True)
