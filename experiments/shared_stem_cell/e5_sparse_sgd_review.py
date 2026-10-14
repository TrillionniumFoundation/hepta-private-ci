#!/usr/bin/env python3
"""Independent descriptive reviewer for 24 separate local synthetic CPU SGD runs.

This is source/report consistency only; no real Encoder, NDU, target Worker or
cryptographic physical-run attestation is established.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import statistics
from pathlib import Path

SCALES=(64,256,1024,4096)
SEEDS=(20261014,20261015,20261016)
MODES=('packed','modules')
SCHEMA='hepta.e5.sparse-packed-sgd-cpu.v1'

class Invalid(ValueError):
    pass


def checked_number(v):
    if type(v) not in (float,int) or not math.isfinite(v) or v <= 0:
        raise Invalid('missing, nonpositive or nonfinite physical cost')
    return float(v)


def checked_sha(v):
    if type(v) is not str or len(v)!=64 or v=='0'*64 or any(c not in '0123456789abcdef' for c in v):
        raise Invalid('invalid output SHA')
    return v


def evaluate(records):
    if type(records) is not dict or set(records)!={str(n) for n in SCALES}:
        raise Invalid('missing four scale studies')
    result={}
    for n in SCALES:
        cases=records[str(n)]
        if type(cases) is not dict or set(cases)!={str(seed) for seed in SEEDS}:
            raise Invalid('missing repeat cohort')
        acceleration=[];rss_diff=[];observations=[]
        for seed in SEEDS:
            pair=cases[str(seed)]
            if type(pair) is not dict or set(pair)!=set(MODES):
                raise Invalid('missing paired mode')
            a=pair['packed'];b=pair['modules']
            for mode,r in pair.items():
                if type(r) is not dict or r.get('schema')!=SCHEMA or r.get('mode')!=mode:
                    raise Invalid('mode/schema drift')
                if r.get('authority')!='DENY_ALL' or r.get('production_promotion_permitted') is not False:
                    raise Invalid('model owner authority forged')
                if (r.get('pretrained_encoder_executed') is not False or
                    r.get('production_worker_executed') is not False or
                    r.get('synthetic_labels_and_features') is not True or
                    r.get('independent_ndu_verified') is not False or
                    r.get('p99_end_to_end_latency_verified') is not False or
                    r.get('measured_energy_joules') is not None):
                    raise Invalid('unapproved model/host/utility claim')
                active=max(8,n//10)
                if (r.get('requested_logical_cells')!=n or r.get('active_cell_count')!=active or
                    r.get('inactive_cell_count')!=n-active or r.get('seed')!=seed or
                    r.get('optimizer')!='torch.optim.SGD' or r.get('optimizer_steps_per_active_cell')!=3 or
                    r.get('learning_rate')!=.01 or r.get('physical_feature_buffer_count')!=1 or
                    r.get('observed_resident_head_parameters')!=n*9744):
                    raise Invalid('resource/model/training comparison drift')
                for key in ('measured_initialization_ms','measured_sgd_wall_ms',
                            'measured_end_to_end_process_wall_ms','measured_process_cpu_ms',
                            'measured_peak_rss_bytes','measured_current_rss_bytes'):
                    checked_number(r.get(key))
                if r['measured_peak_rss_bytes'] < n*9744*4:
                    raise Invalid('reported RSS smaller than resident FP32 Head weights')
                if r['measured_end_to_end_process_wall_ms']+1e-5<r['measured_sgd_wall_ms']:
                    raise Invalid('impossible wall clock accounting')
                if (r.get('dormant_weights_unchanged') is not True or
                        checked_sha(r.get('dormant_bank_sha256_before')) != checked_sha(r.get('dormant_bank_sha256_after'))):
                    raise Invalid('dormant learning isolation unverified')
                if checked_sha(r.get('initial_active_weights_sha256'))==checked_sha(r.get('final_active_weights_sha256')):
                    raise Invalid('learning claimed without updated weights')
                checked_sha(r.get('active_cell_index_sha256'))
                checked_sha(r.get('prediction_logits_sha256'))
                losses=r.get('training_loss_by_step_sum')
                if type(losses) is not list or len(losses)!=3:
                    raise Invalid('training loss trajectory missing')
                if any(checked_number(x)>1000000 for x in losses):
                    raise Invalid('unbounded synthetic loss')
                if abs(losses[-1]/active-checked_number(r.get('last_step_training_loss_per_cell')))>1e-5:
                    raise Invalid('loss normalization inconsistent')
            for field in ('active_cell_index_sha256','initial_active_weights_sha256'):
                if a[field]!=b[field]:
                    raise Invalid('unequal seeded weights or active Cell set')
            if any(abs(x-y)>max(1e-5,1e-5*abs(y)) for x,y in zip(
                  a['training_loss_by_step_sum'],b['training_loss_by_step_sum'])):
                raise Invalid('paired SGD numerics disagree beyond tolerance')
            ratio=checked_number(b['measured_sgd_wall_ms'])/checked_number(a['measured_sgd_wall_ms'])
            delta=(b['measured_peak_rss_bytes']-a['measured_peak_rss_bytes'])/(1024**2)
            acceleration.append(ratio);rss_diff.append(delta)
            observations.append({'seed':seed,'packed_train_ms':a['measured_sgd_wall_ms'],
                                 'module_train_ms':b['measured_sgd_wall_ms'],
                                 'paired_speed_ratio':ratio,
                                 'packed_peak_rss_mib':a['measured_peak_rss_bytes']/2**20,
                                 'module_peak_rss_mib':b['measured_peak_rss_bytes']/2**20,
                                 'rss_saving_mib':delta})
        result[str(n)]={'active_cells':max(8,n//10),
                        'median_paired_train_speed_ratio':statistics.median(acceleration),
                        'speed_ratios_by_seed':acceleration,
                        'median_paired_rss_saving_mib':statistics.median(rss_diff),
                        'rss_savings_by_seed_mib':rss_diff,'observations':observations}
    return {'schema':'hepta.e5.sparse-sgd-observation-review.v1',
            'scales':result,'completed_os_process_records_declared':24,
            'experimental_observations_from_one_local_host':True,
            'actual_pretrained_encoder_verified':False,'native_worker_verified':False,
            'model_utility_or_ood_verified':False,'energy_or_gpu_verified':False,
            'statistical_resource_superiority_established':False,
            'production_promotion_permitted':False,'authority':'DENY_ALL'}


def _pairs(pairs):
    d={}
    for k,v in pairs:
        if k in d:raise Invalid('duplicate JSON key')
        d[k]=v
    return d


def read(path):
    raw=Path(path).read_bytes()
    if not 2<len(raw)<=16*1024*1024:
        raise Invalid('empty/oversized report')
    return json.loads(raw,object_pairs_hook=_pairs,
        parse_constant=lambda _:(_ for _ in ()).throw(Invalid('nonfinite JSON')))


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--receipts-root',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True)
    a=p.parse_args()
    if a.output.exists():raise FileExistsError('write-once report')
    records={}
    for n in SCALES:
        records[str(n)]={}
        for seed in SEEDS:
            records[str(n)][str(seed)]={}
            for mode in MODES:
                path=a.receipts_root/f'{n}-{mode}-{seed}.json'
                records[str(n)][str(seed)][mode]=read(path)
    result=evaluate(records)
    hashes=[]
    for n in SCALES:
        for seed in SEEDS:
            for mode in MODES:
                path=a.receipts_root/f'{n}-{mode}-{seed}.json'
                hashes.append((path.name,hashlib.sha256(path.read_bytes()).hexdigest()))
    result['raw_receipt_sha256s']=dict(hashes)
    with a.output.open('x',encoding='utf8') as f:
        json.dump(result,f,sort_keys=True,indent=2,allow_nan=False);f.write('\n')

if __name__=='__main__':main()
