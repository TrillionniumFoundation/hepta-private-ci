"""Execute frozen P1 CPU-matched pilot and create-only raw evidence.

Run as `python -m experiments.hcsn_p1_regime.run_regime_trial OUTFILE`.
No arbitrary changes to the protocol via CLI. Actual CPU and all raw predictions
are persisted; exact replay is not promised under variable CPU timing.
"""
import base64
import gzip
import hashlib
import json
import os
from pathlib import Path
import platform
import sys
from .independent_regime_trial import (Refuse, exact_signflip_p,
                                        make_data, score, train, warmup_runtime)
import numpy as np
import scipy
import torch

ROOT=Path(__file__).parent

def _write_create_only(path: Path,blob: bytes):
    fd=os.open(str(path),os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600)
    try:
        with os.fdopen(fd,'wb') as f:
            f.write(blob);f.flush();os.fsync(f.fileno())
    except BaseException:
        try:path.unlink()
        except FileNotFoundError:pass
        raise


def execute():
    frozen=(ROOT/'PROTOCOL_20261031.json').read_bytes()
    P=json.loads(frozen)
    if (P['seeds']!=list(range(501,509)) or P['model_trainable_parameters']!=609
            or P['process_cpu_training_and_features_seconds_per_arm']!=2.0
            or P['base_head_sha']!='042af0017b08f4316949cf9ba450ecd5e63350b3'):
        raise Refuse('unrecognized frozen trial contract')
    bootstrap_cpu_seconds=warmup_runtime()  # shared runtime initialization, never arm credit
    rows=[]
    for seed in P['seeds']:
        train_obs,train_y=make_data(seed+10000,P['train_examples_per_seed'])
        iid_obs,iid_y=make_data(seed+20000,P['iid_examples_per_seed'])
        ood_obs,ood_y=make_data(seed+30000,P['ood_examples_per_seed'],ood=True)
        item={'seed':seed,'train_event_rate':float(np.mean(train_y)),
              'iid_event_rate':float(np.mean(iid_y)), 'ood_event_rate':float(np.mean(ood_y)),
              'iid_labels':iid_y.tolist(),'ood_labels':ood_y.tolist(),'arms':{}}
        for arm in P['arms']:
            model,training=train(seed,arm,train_obs,train_y,
                budget_seconds=P['process_cpu_training_and_features_seconds_per_arm'])
            iid=score(model,iid_obs,iid_y,arm)
            ood=score(model,ood_obs,ood_y,arm)
            item['arms'][arm]={'training':training,'iid':iid,'ood':ood}
        rows.append(item)
        print(f"seed={seed} ordinary OOD={item['arms']['ordinary']['ood']['brier']:.6f} mechanism OOD={item['arms']['call_put_margin_risk']['ood']['brier']:.6f}",flush=True)
    differences=[row['arms']['ordinary']['ood']['brier']-row['arms']['call_put_margin_risk']['ood']['brier'] for row in rows]
    iid_differences=[row['arms']['ordinary']['iid']['brier']-row['arms']['call_put_margin_risk']['iid']['brier'] for row in rows]
    training_cpu=[row['arms'][arm]['training']['training_and_feature_cpu_seconds']
                  for row in rows for arm in P['arms']]
    raw={'schema':'hcsn-p1-regime-raw-v1','protocol_sha256':hashlib.sha256(frozen).hexdigest(),
         'environment':{'python':sys.version,'platform':platform.platform(),
            'shared_runtime_bootstrap_cpu_seconds':bootstrap_cpu_seconds,
            'numpy':np.__version__,'scipy':scipy.__version__,'torch':torch.__version__,
            'torch_threads':torch.get_num_threads()},'rows':rows}
    raw_blob=(json.dumps(raw,sort_keys=True,separators=(',',':'),allow_nan=False)+'\n').encode()
    summary={'schema':'hcsn-p1-regime-summary-v1','protocol_sha256':hashlib.sha256(frozen).hexdigest(),
             'raw_sha256':hashlib.sha256(raw_blob).hexdigest(),'n_seeds':len(rows),
             'ood_brier_improvement_per_seed':differences,'iid_brier_improvement_per_seed':iid_differences,
             'mean_ood_brier_improvement':float(np.mean(differences)),
             'mean_iid_brier_improvement':float(np.mean(iid_differences)),
             'exact_two_sided_signflip_p_ood':exact_signflip_p(differences),
             'min_training_cpu_seconds':min(training_cpu),'max_training_cpu_seconds':max(training_cpu),
             'mean_training_cpu_seconds':float(np.mean(training_cpu)),
             'model_parameters':P['model_trainable_parameters'],
             'same_observed_inputs':True,'same_anchor_slope':True,'genuine_markov_risk_state':True,
             'risk_feature_independent_information':False,
             'exploratory_screen_passed':(float(np.mean(differences))>=.01
                and exact_signflip_p(differences)<=.05 and float(np.mean(iid_differences))>=-.01),
             'p1_closed':False,'p0_p6_closed':False,'production_activation':False,
             'limitations':['synthetic independent switching-GBM task, not coupled financial HX',
                            'features deterministic in ordinary baseline inputs',
                            'CPU only, no Joules/GPU; no claim of hardware/energy equivalence',
                            'CPU-time-based loops are not bitwise deterministic across hosts']}
    return raw_blob,(json.dumps(summary,indent=2,sort_keys=True,allow_nan=False)+'\n').encode()


def main():
    if len(sys.argv)!=2:
        raise SystemExit('usage: python -m experiments.hcsn_p1_regime.run_regime_trial OUTPUT_PREFIX')
    prefix=Path(sys.argv[1])
    if prefix.with_suffix('.json').exists() or prefix.with_suffix('.json.gz.b64').exists():
        raise Refuse('create-only evidence destination already exists')
    raw,summ=execute()
    compress=base64.b64encode(gzip.compress(raw,mtime=0))+b'\n'
    # Create raw before summary: summary is publication commit marker.
    _write_create_only(prefix.with_suffix('.json.gz.b64'),compress)
    _write_create_only(prefix.with_suffix('.json'),summ)
    print(summ.decode())

if __name__=='__main__':main()
