#!/usr/bin/env python3
"""Read-only cross-scale CPU synthetic fanout evidence review; not target-host E5.

Compares four separate OS-process observations per scale, never upgrades
reported local PyTorch counters into Worker/power/NDU attestations.
"""
from __future__ import annotations
import argparse, json, math
from pathlib import Path

SCALES=(64,256,1024,4096)
CASES=('shared_sgd','cloned_sgd','shared_inference','packed_inference')
class Invalid(ValueError): pass

def num(v,positive=True):
    if type(v) not in (float,int) or not math.isfinite(v) or v<(1e-300 if positive else 0):
        raise Invalid('missing, negative or nonfinite physical measurement')
    return float(v)

def examine(records):
    if not isinstance(records,dict) or set(records)!={str(n) for n in SCALES}:
        raise Invalid('all 64/256/1024/4096 real process reports required')
    rows={}
    for n in SCALES:
        raw=records[str(n)]
        if type(raw) is not dict or set(raw)!=set(CASES):
            raise Invalid('missing or extra local CPU arm')
        active=max(8,n//10)
        for arm,item in raw.items():
            if type(item) is not dict or item.get('authority')!='DENY_ALL' or item.get('production_promotion_permitted') is not False:
                raise Invalid('unsafe report status')
            if item.get('logical_cells')!=n or item.get('active_cells')!=active or item.get('seed')!=20261014:
                raise Invalid('unpaired Cell population, seed or active fraction')
            count=item.get('physical_cell_head_parameters') if arm!='packed_inference' else item.get('complete_head_parameters')
            if type(count) is not int or count!=n*9744:
                raise Invalid('fake or incomplete Head parameter inventory')
            rss=item.get('observed_process_lifetime_peak_rss_bytes') if arm!='packed_inference' else item.get('measured_peak_rss_bytes')
            num(rss)
            if item.get('hardware_energy_joules',None) is not None or item.get('power_or_gpu_evidence',None) is not None:
                raise Invalid('forged energy/power/host claim')
            if arm=='packed_inference':
                if (item.get('schema')!='hepta.e5.packed-physical-cpu-head-v1' or item.get('pretrained_encoder_executed') is not False or
                    item.get('production_worker_verified') is not False or item.get('p99_independently_qualified') is not False or
                    item.get('batch_repeats')!=20 or item.get('physical_head_weight_tensors')!=6 or
                    item.get('physical_input_feature_buffers')!=1):
                    raise Invalid('packed control or authority mismatch')
                num(item.get('per_cell_equivalent_loop_ms_mean'))
                if item.get('batch_forward_samples')!=20:raise Invalid('incomplete actual batch repetitions')
            else:
                if (item.get('schema')!='hepta.e5-local-cpu-head-fanout.v1' or item.get('actual_pretrained_encoder_forward') is not False or
                    item.get('production_worker_or_ndu_verified') is not False or item.get('real_pytorch_cpu_head_forward') is not True or
                    item.get('synthetic_input_and_labels') is not True or item.get('per_head_parameters')!=9744 or
                    item.get('synthetic_feature_producer_count')!=1):
                    raise Invalid('independent Head execution/control mismatch')
                steps=1 if arm.endswith('sgd') else 0
                repetitions=2 if steps else 20
                physical_buffers=active if arm=='cloned_sgd' else 1
                if (item.get('train_steps_per_active_cell')!=steps or item.get('serving_repeats')!=repetitions or
                    item.get('raw_sample_count')!=active*repetitions or item.get('heads_with_changed_weights')!=active*steps or
                    item.get('physical_feature_buffer_count')!=physical_buffers or
                    item.get('resident_feature_tensor_payload_bytes')!=physical_buffers*384*4):
                    raise Invalid('bad Head SGD/feature buffer evidence')
                num(item.get('measured_serving_loop_wall_ms'))
                num(item.get('measured_training_loop_wall_ms'),positive=False)
                if steps and item['measured_training_loop_wall_ms']<=0:
                    raise Invalid('train steps without observed time')
        sg=raw['shared_sgd'];cl=raw['cloned_sgd'];seq=raw['shared_inference'];packed=raw['packed_inference']
        if (sg['synthetic_feature_q24_sha256']!=cl['synthetic_feature_q24_sha256'] or
            sg['sampled_f32_prediction_sha256']!=cl['sampled_f32_prediction_sha256'] or
            sg['synthetic_feature_q24_sha256']!=seq['synthetic_feature_q24_sha256']):
            raise Invalid('input or network inference changed across shared and cloned control')
        module_average=num(seq['measured_serving_loop_wall_ms'])/(active*20)
        packed_average=num(packed['per_cell_equivalent_loop_ms_mean'])
        module_peak=seq['observed_process_lifetime_peak_rss_bytes']
        packed_peak=packed['measured_peak_rss_bytes']
        rows[str(n)]={'active_cells':active,'head_parameters':n*9744,'head_fp32_payload_bytes':n*9744*4,
                      'module_process_peak_rss_bytes':module_peak,'packed_process_peak_rss_bytes':packed_peak,
                      'observed_rss_difference_bytes':module_peak-packed_peak,
                      'module_mean_serving_loop_ms_per_active_cell':module_average,
                      'packed_mean_serving_loop_ms_per_active_cell':packed_average,
                      'observed_relative_loop_speed':module_average/packed_average,
                      'shared_physical_feature_buffers':sg['physical_feature_buffer_count'],
                      'cloned_physical_feature_buffers':cl['physical_feature_buffer_count'],
                      'sgd_heads_really_updated':sg['heads_with_changed_weights']}
    return {'schema':'hepta.e5-local-cpu-head-fanout-review.v1','scales':rows,
            'observed_local_cpu_math_not_inferred':True,
            'pretrained_encoder_executed':False,'target_production_worker_verified':False,
            'independent_energy_gpu_or_ndu_observed':False,'per_request_e2e_p99_qualified':False,
            'statistically_confirmed_resource_superiority':False,
            'production_promotion_permitted':False,'authority':'DENY_ALL'}

def main():
    p=argparse.ArgumentParser();p.add_argument('--receipts',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    a=p.parse_args()
    source=json.loads(a.receipts.read_text(encoding='utf8'))
    result=examine(source)
    with a.output.open('x',encoding='utf8') as f:json.dump(result,f,indent=2,sort_keys=True,allow_nan=False);f.write('\n')
if __name__=='__main__':main()
