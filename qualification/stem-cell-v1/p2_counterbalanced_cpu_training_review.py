"""Independent stdlib-only review of P2 balanced physical CPU re-training.

Does NOT import torch, the timer/producer, or any model loader. It reopens the
original material and all original human labels after sealing. Clock samples
remain self-observed, not independently signed hardware measurements.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import random
import statistics
from pathlib import Path

import p2_backward_cost_profile_review as previous_review

SCHEMA='hepta.p2.counterbalanced-uninstrumented-training-cost.v1'
REVIEW='hepta.p2.counterbalanced-cpu-independent-review.v1'
ARMS=('frozen_single','single_active','fixed_top1','adaptive_top1')
RND=(8,16,24,32)
FIELDS={'schema','authority','production_promotion_permitted','original_p2_sha256',
        'original_trained_top1_sha256','source_panel_sha256','model_revision',
        'model_weights_sha256','model_parameter_count','pretrained_model_loaded_in_this_job',
        'model_load_is_extra_replay_cost','model_load_ms_observed_by_backend',
        'physical_encoder_calls_in_this_job','encoder_cpu_ns','encoder_wall_ns',
        'original_train_rows','original_blind_rows','original_source_inventory',
        'control_arm','crossover_seed','measured_rounds','crossover_orders',
        'warmup_trials','measured_trials','warmup_runs_counted_as_work',
        'operator_profiler_disabled_for_timing',
        'all_four_arms_train_and_score_recomputed_every_round',
        'time_traces_are_not_independently_attested','retrospective_public_source_not_future',
        'exact_total_flops_matched','target_worker_end_to_end_certified',
        'p99_requests_independently_sampled','model_winner_selected',
        'CPU_run_not_energy_or_serving_measurement','process_peak_rss_bytes',
        'receipt_sha256'}
TRIAL={'arm','measured_total_cpu_ns','measured_total_wall_ns',
       'internally_measured_train_cpu_ns','internally_measured_train_wall_ns',
       'internally_measured_heldout_cpu_ns','internally_measured_heldout_wall_ns',
       'original_final_weights_sha256','original_heldout_logits_max_abs',
       'train_updates','training_selected_expert_rows','training_head_batch_calls',
       'split_parity_extra_forward_rows','migration_copied_fp32_bytes'}


def must(ok,why):
    if not ok:raise ValueError(why)


def digest(x):
    return hashlib.sha256(json.dumps(x,sort_keys=True,separators=(',',':'),
                        ensure_ascii=False,allow_nan=False).encode('utf8')).hexdigest()


def order(seed,rounds):
    must(type(seed) is int and 1<=seed<2**31 and type(rounds) is int and rounds in RND,
         'predeclared balanced round design required')
    names=list(ARMS)
    random.Random(seed).shuffle(names)
    base=(0,1,3,2)
    four=[tuple(names[(v+i)%4] for v in base) for i in range(4)]
    eight=four+[tuple(reversed(row)) for row in four]
    return [list(eight[i%8]) for i in range(rounds)]


def _nint(x):return type(x) is int and 0 <= x < 10**17

def _pint(x):return type(x) is int and 0 < x < 10**17

def _float(x):return type(x) in (int,float) and math.isfinite(x) and 0<=x<1e17


def check_trial(row, old, arm, *, measured):
    must(type(row) is dict and set(row)==(TRIAL|({'round','position'} if measured else set()))
         and row['arm']==arm, 'complete original Head timing observation required')
    must(row['original_final_weights_sha256']==old['final_weights_sha256']
         and _float(row['original_heldout_logits_max_abs'])
         and row['original_heldout_logits_max_abs']<=1e-6
         and row['train_updates']==old['train_updates']
         and row['training_selected_expert_rows']==old['train_physical_selected_expert_rows']
         and row['training_head_batch_calls']==old['training_head_batch_calls']
         and row['split_parity_extra_forward_rows']==old['split_parity_actual_head_forward_rows']
         and row['migration_copied_fp32_bytes']==old['migration_copied_fp32_bytes'],
         'cost comparison changed original trained model, selected rows or split work')
    for key in ('measured_total_cpu_ns','measured_total_wall_ns',
                'internally_measured_train_cpu_ns','internally_measured_train_wall_ns',
                'internally_measured_heldout_cpu_ns','internally_measured_heldout_wall_ns'):
        must(_pint(row[key]), 'missing actual timed whole-arm and stage CPU/wall clocks')
    for time_axis in ('cpu','wall'):
        total=row[f'measured_total_{time_axis}_ns']
        train=row[f'internally_measured_train_{time_axis}_ns']
        held=row[f'internally_measured_heldout_{time_axis}_ns']
        must(total >= train and total >= held and total >= train+held,
             'whole-arm timing failed to cover original train and heldout stages')
    return True


def review(panel, train, blind, labels, original_p2, original_trained, original_profile, trace):
    old_score=previous_review.review(panel,train,blind,labels,original_p2,original_trained,original_profile)
    must(old_score['authority']=='DENY_ALL' and old_score['production_promotion_permitted'] is False,
         'original 96 owner labels and original profiled source must review successfully')
    must(type(trace) is dict and set(trace)==FIELDS and trace['schema']==SCHEMA
         and trace['receipt_sha256']==digest({k:v for k,v in trace.items() if k!='receipt_sha256'})
         and trace['authority']=='DENY_ALL',
         'immutable exact-schema source/cost receipt required')
    must(trace['original_p2_sha256']==original_p2['report_sha256']
         and trace['original_trained_top1_sha256']==original_trained['report_sha256']
         and trace['source_panel_sha256']==original_trained['source_panel_sha256']
         and trace['source_panel_sha256']==original_profile['original_panel_sha256']
         and trace['model_weights_sha256']==original_profile['model_weights_sha256']
         and trace['model_revision']==original_trained['model_revision']
         and trace['model_parameter_count']==original_trained['model_parameter_count']
         and trace['pretrained_model_loaded_in_this_job'] is original_trained['pretrained_weight_execution_claimed']
         and trace['model_load_is_extra_replay_cost'] is trace['pretrained_model_loaded_in_this_job']
         and trace['original_train_rows']==128 and trace['original_blind_rows']==96
         and trace['physical_encoder_calls_in_this_job']==224
         and trace['original_source_inventory']==original_trained['source_heldout_cases']
         and _pint(trace['encoder_cpu_ns']) and _pint(trace['encoder_wall_ns'])
         and _pint(trace['process_peak_rss_bytes']),
         'frozen original material/pretrained model source or real Encoder cost identity drift')
    if trace['pretrained_model_loaded_in_this_job']:
        must(_float(trace['model_load_ms_observed_by_backend'])
             and trace['model_load_ms_observed_by_backend']>0,
             'real model load cannot be free or missing')
    else:
        must(trace['model_load_ms_observed_by_backend'] is None,
             'synthetic mechanism may not assert real model load')
    must(trace['control_arm']=='single_active'
         and trace['warmup_runs_counted_as_work'] is True
         and trace['operator_profiler_disabled_for_timing'] is True
         and trace['all_four_arms_train_and_score_recomputed_every_round'] is True
         and trace['retrospective_public_source_not_future'] is True
         and trace['CPU_run_not_energy_or_serving_measurement'] is True
         and trace['time_traces_are_not_independently_attested'] is True,
         'false balanced/authorization/host-timing claim')
    for name in ('production_promotion_permitted','exact_total_flops_matched',
                 'target_worker_end_to_end_certified','p99_requests_independently_sampled',
                 'model_winner_selected'):
        must(trace[name] is False,'false equal-total-cost, future outcome or model promotion')
    r=trace['measured_rounds'];expected=order(trace['crossover_seed'],r)
    must(trace['crossover_orders']==expected,'rotations/permutations not as preregistered')
    warmups=trace['warmup_trials'];trials=trace['measured_trials']
    must(type(warmups) is list and len(warmups)==4 and type(trials) is list
         and len(trials)==4*r,'all cold/warmup and measured arm trials required')
    work={a:[] for a in ARMS};positions={a:[0]*4 for a in ARMS}
    for slot,arm in enumerate(ARMS):
        check_trial(warmups[slot],original_trained['compared_arms'][arm],arm,measured=False)
    for i,row in enumerate(trials):
        round_number=i//4;slot=i%4;arm=expected[round_number][slot]
        must(type(row) is dict and row.get('round')==round_number
             and row.get('position')==slot,'changing timed case order/position is forbidden')
        check_trial(row,original_trained['compared_arms'][arm],arm,measured=True)
        positions[arm][slot]+=1
        work[arm].append(row)
    must(all(n==r//4 for a in ARMS for n in positions[a]),
         'every arm must appear an equal number of times in every position')
    by_round={i:{a:None for a in ARMS} for i in range(r)}
    for row in trials:
        by_round[row['round']][row['arm']]=row
    result={}
    for arm in ARMS:
        paired_cpu=[];paired_wall=[]
        cpu=[];wall=[]
        for round_number in range(r):
            here=by_round[round_number][arm]
            ref=by_round[round_number]['single_active']
            paired_cpu.append(here['measured_total_cpu_ns']/ref['measured_total_cpu_ns'])
            paired_wall.append(here['measured_total_wall_ns']/ref['measured_total_wall_ns'])
            cpu.append(here['measured_total_cpu_ns'])
            wall.append(here['measured_total_wall_ns'])
        result[arm]=dict(rounds=r,balanced_position_histogram=positions[arm],
            median_paired_full_head_cpu_ratio_vs_single=statistics.median(paired_cpu),
            median_paired_full_head_wall_ratio_vs_single=statistics.median(paired_wall),
            median_cpu_ns=statistics.median(cpu),median_wall_ns=statistics.median(wall),
            observed_wall_min_ns=min(wall),observed_wall_max_ns=max(wall),
            slowest_case_excluded=False,cpu_profiler_used=False,
            equal_total_compute_verified=False,whole_worker_p99_verified=False)
    all_cpu=sum(row['measured_total_cpu_ns'] for row in warmups+trials)
    all_wall=sum(row['measured_total_wall_ns'] for row in warmups+trials)
    must(all_cpu>0 and all_wall>0,'lifecycle/head cost cannot be zero')
    return dict(schema=REVIEW,source_trace_sha256=trace['receipt_sha256'],
        original_model_sha256=trace['model_weights_sha256'],
        original_human_label_score_recomputed=True,
        original_accuracy_did_not_change=True,
        observations=len(trials),warmup_training_runs_paid=len(warmups),
        physical_training_forward_cases_from_complete_census=sum(
           sum(row['training_selected_expert_rows']) for row in trials),
        complete_cpu_sum_ns_including_warmup=all_cpu,
        complete_wall_sum_ns_including_warmup=all_wall,
        additional_encoder_forward_calls=trace['physical_encoder_calls_in_this_job'],
        original_224_source_features_recomputed=True,
        per_arm=result,retrospective_repeated_cpu_trials_not_independent_test_cases=True,
        operator_profiler_disabled=True,complete_backward_flops_verified=False,
        equal_full_lifecycle_compute_verified=False,
        signed_target_hardware_timings_verified=False,model_winner_selected=False,
        production_promotion_permitted=False,authority='DENY_ALL')


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    for field in ('original-panel','train-material','blind-material','owner-labels',
                  'original-p2-report','original-trained-top1-report','original-backward-cost-report',
                  'counterbalanced-cost-report','output'):
        ap.add_argument('--'+field,required=True)
    args=ap.parse_args()
    outfile=Path(args.output)
    must(not outfile.exists(),'independent source cost result is create-only')
    from p2_backward_cost_profile_review import read
    z=review(read(args.original_panel),read(args.train_material),read(args.blind_material),
          read(args.owner_labels),read(args.original_p2_report),
          read(args.original_trained_top1_report),read(args.original_backward_cost_report),
          read(args.counterbalanced_cost_report))
    with outfile.open('x',encoding='utf8') as f:
        json.dump(z,f,sort_keys=True,allow_nan=False);f.write('\n')


if __name__=='__main__':main()
