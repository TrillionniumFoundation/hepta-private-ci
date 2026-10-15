"""Independent Torch-free evaluator of CPU-budget-frozen P2 Head learning.

It reopens owner labels only after original and new model outputs are sealed.
Cannot authenticate self-reported CPU time, model publisher signatures, exact
backward FLOPs, prospective source families, or training gradient execution.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import random
import statistics
from pathlib import Path

import numpy as np
import p2_train_sparse_equal_compute_review as oldreview
import p2_real_cell_split_review as original_review
import p2_counterbalanced_cpu_training_review as time_review

SCHEMA='hepta.p2.training-cpu-budget-frontier.v1'
SCORE='hepta.p2.training-cpu-budget-frontier-independent-score.v1'
ARMS=('frozen_single','single_active','fixed_top1','adaptive_top1')
CAL_ROUNDS=8
TOL=4e-5


def must(condition,msg):
    if not condition:raise ValueError(msg)


def sha(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':'),
                      ensure_ascii=False,allow_nan=False).encode('utf8')).hexdigest()


def _pint(v):return type(v) is int and 0<v<10**17

def _finite(v):return type(v) in (int,float) and math.isfinite(v) and 0<=v<1e18


def crossover(seed):
    must(type(seed) is int and 1<=seed<2**31,'invalid preregistered calibration seed')
    labels=list(ARMS);random.Random(seed).shuffle(labels)
    a=[tuple(labels[(x+i)%4] for x in (0,1,3,2)) for i in range(4)]
    return [list(s) for s in a+[tuple(reversed(r)) for r in a]]


def median_even(items):
    must(type(items) is list and len(items)==8 and all(_pint(v) for v in items),
         'exact eight positive training-only CPU pilots required')
    ss=sorted(items);return (ss[3]+ss[4])//2


def derive(ref,other):
    must(_pint(ref) and _pint(other),'bounded strictly positive CPU budgets')
    return int(max(20,min(40,2*(((40*ref)//other)//2))))


def review(panel,train,blind,owner,old,trained,profile,balanced,new):
    # Explicitly independently open and score ALL old P2 heads with owner labels,
    # prior physical operator study and the fully counterbalanced CPU source.
    base=time_review.review(panel,train,blind,owner,old,trained,profile,balanced)
    must(base['authority']=='DENY_ALL' and base['original_human_label_score_recomputed'] is True,
         'historical independent source owner and numerical score must first pass')
    must(type(new) is dict and new.get('schema')==SCHEMA
         and new.get('report_sha256')==sha({k:v for k,v in new.items() if k!='report_sha256'})
         and new.get('authority')=='DENY_ALL' and new.get('production_promotion_permitted') is False,
         'source-bound nonauthorizing budgeted experiment required')
    core={'schema','authority','production_promotion_permitted','original_p2_sha256',
          'original_trained_top1_sha256','original_counterbalanced_cpu_sha256',
          'source_panel_sha256','frozen_model_weights_sha256','model_revision',
          'model_parameter_count','pretrained_model_loaded_in_this_job',
          'model_load_cost_counted_separately','model_load_ms_observed_by_backend',
          'physical_encoder_calls_in_this_job','encoding_cpu_ns','encoding_wall_ns',
          'source_heldout_cases','source_features_q24','original_seed',
          'calibration_seed','pilot_rounds','pilot_orders','pilot_records',
          'calibrated_single_40_step_cpu_ns','steps_lower_bound','steps_upper_bound',
          'allocated_steps','calibration_runs_paid_in_lifecycle',
          'calibration_uses_training_labels_only','calibrated_cpu_budget_is_not_exact_matching',
          'total_backward_flops_equalized','future_task_quality_established',
          'blinded_labels_opened_during_training','test_cohorts_are_retrospective_not_future',
          'model_winner_selected','whole_worker_p99_verified','final_arms','process_peak_rss_bytes','report_sha256'}
    must(set(new)==core,'CPU-budgeted study missing/added unregistered critical fields')
    must(new['original_p2_sha256']==old['report_sha256']
         and new['original_trained_top1_sha256']==trained['report_sha256']
         and new['original_counterbalanced_cpu_sha256']==balanced['receipt_sha256']
         and new['source_panel_sha256']==trained['source_panel_sha256']==balanced['source_panel_sha256']
         and new['frozen_model_weights_sha256']==balanced['model_weights_sha256']==trained['original_model_weights_sha256']
         and new['model_revision']==trained['model_revision']
         and new['model_parameter_count']==trained['model_parameter_count']
         and new['pretrained_model_loaded_in_this_job'] is trained['pretrained_weight_execution_claimed']
         and new['model_load_cost_counted_separately'] is new['pretrained_model_loaded_in_this_job']
         and new['original_seed']==trained['seed'] and new['physical_encoder_calls_in_this_job']==224
         and _pint(new['encoding_cpu_ns']) and _pint(new['encoding_wall_ns'])
         and _pint(new['process_peak_rss_bytes']),
         'original pretrained model, 224 source encodings, or full material cost identity drift')
    if new['pretrained_model_loaded_in_this_job']:
        must(_finite(new['model_load_ms_observed_by_backend'])
             and new['model_load_ms_observed_by_backend']>0,'pretrained model load cannot be free')
    else:
        must(new['model_load_ms_observed_by_backend'] is None,'fixture must not falsely claim pretrained model load')
    for field in ('calibration_runs_paid_in_lifecycle','calibration_uses_training_labels_only',
                  'calibrated_cpu_budget_is_not_exact_matching','test_cohorts_are_retrospective_not_future'):
        must(new[field] is True,'invalid cost, data-selection or efficacy disclaimer')
    for field in ('total_backward_flops_equalized','future_task_quality_established',
                  'blinded_labels_opened_during_training','model_winner_selected','whole_worker_p99_verified'):
        must(new[field] is False,'unqualified cost or future-task effectiveness claim')
    must(new['source_heldout_cases']==trained['source_heldout_cases']
         and new['source_features_q24']==trained['source_features_q24']==old['source_features_q24'],
         'original frozen 96 source inputs and complete Q24 feature fingerprint changed')
    must(new['pilot_rounds']==CAL_ROUNDS and new['steps_lower_bound']==20
         and new['steps_upper_bound']==40 and new['pilot_orders']==crossover(new['calibration_seed']),
         'train-only balanced preregistered pilot schedule changed')
    trials=new['pilot_records']
    must(type(trials) is list and len(trials)==CAL_ROUNDS*4,
         'exact full 32 train-only CPU calibration studies required')
    observations={arm:[] for arm in ARMS};positions={arm:[0]*4 for arm in ARMS}
    for i,trial in enumerate(trials):
        rnd,pos=divmod(i,4)
        expected_arm=new['pilot_orders'][rnd][pos]
        original=trained['compared_arms'][expected_arm]
        must(type(trial) is dict and set(trial)=={
             'round','position','arm','full_40_step_training_cpu_ns','full_40_step_training_wall_ns',
             'final_weights_sha256','split_proposed','train_selected_head_rows',
             'migration_copied_fp32_bytes'}
             and trial['round']==rnd and trial['position']==pos and trial['arm']==expected_arm
             and _pint(trial['full_40_step_training_cpu_ns']) and _pint(trial['full_40_step_training_wall_ns'])
             and trial['final_weights_sha256']==original['final_weights_sha256']
             and trial['split_proposed'] is original['split_proposed']
             and trial['train_selected_head_rows']==original['train_physical_selected_expert_rows']
             and trial['migration_copied_fp32_bytes']==original['migration_copied_fp32_bytes'],
             'false original training pilot, weight or actual expense')
        observations[expected_arm].append(trial['full_40_step_training_cpu_ns']);positions[expected_arm][pos]+=1
    must(all(count==2 for a in ARMS for count in positions[a]),'calibration was not balanced across CPU order')
    ref=median_even(observations['single_active'])
    must(new['calibrated_single_40_step_cpu_ns']==ref,'reference trained Head CPU cannot be selected after scoring')
    scheduled={arm:(0 if arm=='frozen_single' else 40 if arm=='single_active'
                    else derive(ref,median_even(observations[arm]))) for arm in ARMS}
    must(new['allocated_steps']==scheduled,'trained Head budget differs from frozen prelabel CPU decision')
    arms=new['final_arms']
    must(type(arms) is dict and set(arms)==set(ARMS),'all Head architectures needed even if they perform badly')
    source_rows=blind['rows']
    x=np.array([[v/(1<<24) for v in new['source_features_q24'][r['case_id']]]
                for r in source_rows],dtype=np.float32)
    must(x.shape==(96,384) and bool(np.isfinite(x).all()),'full 96 original Q24 matrices required')
    from p1_real_granite_review import validate_original
    gold=validate_original(panel,train,blind,owner)
    must(type(gold) is list and len(gold)==96
         and all(type(row) is dict and row.get('case_id')==source_rows[i]['case_id']
                 and row.get('split')==source_rows[i]['split']
                 and type(row.get('label')) is int and row['label'] in (0,1)
                 for i,row in enumerate(gold)),
         'independent original publisher label order changed')
    targets=[row['label'] for row in gold]
    original_dormant=original_review.decode_weights(old['compared_arms']['frozen_no_change']['weights'])
    must(oldreview.original_weights_sha(original_dormant)==
         old['compared_arms']['frozen_no_change']['final_weights_sha256'],
         'original initial dormant Cell parameter bytes not source-bound')
    result={};all_paid_pilots=sum(r['full_40_step_training_cpu_ns'] for r in trials)
    for name in ARMS:
        record=arms[name];expected=trained['compared_arms'][name]
        keys={'arm','training_steps','old_steps','mixed_steps','train_exposures',
              'training_selected_expert_rows','training_head_batch_calls','initial_weights_sha256',
              'final_weights_sha256','model_parameter_count','active_head_parameters','split_proposed',
              'train_only_brier_excess','split_threshold','clone_parity_logits_max_abs',
              'migration_copied_fp32_bytes','parity_head_forward_rows','parity_head_batch_calls',
              'diagnostic_head_rows','diagnostic_head_batch_calls','train_cpu_ns','train_wall_ns',
              'training_loss_trace','heldout_selected_expert_ids','heldout_logits',
              'heldout_expert_rows','heldout_head_batch_calls','weights',
              'budget_selected_steps','training_cpu_ns_ratio_vs_calibrated_single_budget',
              'pilot_median_full_40_cpu_ns'}
        must(type(record) is dict and set(record)==keys and record['arm']==name
             and record['model_parameter_count']==14868 and record['active_head_parameters']==7434
             and record['initial_weights_sha256']==trained['original_frozen_two_head_initial_sha256']
             and record['budget_selected_steps']==scheduled[name]
             and record['pilot_median_full_40_cpu_ns']==median_even(observations[name])
             and _pint(record['train_cpu_ns']) and _pint(record['train_wall_ns'])
             and _finite(record['training_cpu_ns_ratio_vs_calibrated_single_budget'])
             and abs(record['training_cpu_ns_ratio_vs_calibrated_single_budget']-record['train_cpu_ns']/ref)<1e-8,
             'not exact original initialized Head and preregistered budget')
        nsteps=scheduled[name]
        must(record['training_steps']==nsteps and record['old_steps']==nsteps//2
             and record['mixed_steps']==nsteps//2,
             'budgeted source replay stage and optimizer updates differ')
        need_rows=64*nsteps//2+128*nsteps//2
        must(record['train_exposures']==need_rows and sum(record['training_selected_expert_rows'])==need_rows
             and sum(record['diagnostic_head_rows'])==128
             and sum(record['heldout_expert_rows'])==96
             and record['training_head_batch_calls']>=nsteps
             and record['training_head_batch_calls']<=2*nsteps
             and record['diagnostic_head_batch_calls']>=2
             and record['diagnostic_head_batch_calls']<=4
             and len(record['training_loss_trace'])==nsteps
             and all(type(v) is float and math.isfinite(v) for v in record['training_loss_trace']),
             'incomplete budgeted Head physical training, diagnostic or score rows')
        need_route=[int(r[0]/(1<<24)>=trained['train_cutoff_feature0_median'])
                    if (name=='fixed_top1' or (name=='adaptive_top1' and record['split_proposed']))
                    else 0 for r in (new['source_features_q24'][c['case_id']] for c in source_rows)]
        must(record['heldout_selected_expert_ids']==need_route,
             'fixed or train-only adaptive route changed on withheld feature')
        must(record['heldout_expert_rows']==[need_route.count(0),need_route.count(1)]
             and record['heldout_head_batch_calls']==len(set(need_route)),
             'physical exactly one expert per heldout case or batch-call census changed')
        decoded=original_review.decode_weights(record['weights'])
        if name in ('frozen_single','single_active') or (name=='adaptive_top1' and not record['split_proposed']):
            must(all(np.array_equal(arr[1], original_dormant[key][1]) for key,arr in decoded.items()),
                 'inactive trained or frozen Cell parameter bytes were secretly updated')
        must(oldreview.original_weights_sha(decoded)==record['final_weights_sha256'],
             'altered complete 14,868p FP32 learned weight bytes')
        pred,decoded2=oldreview.np_selected(x,record['weights'],need_route)
        recorded=np.asarray(record['heldout_logits'],dtype=np.float64)
        must(recorded.shape==(96,2) and bool(np.isfinite(recorded).all())
             and float(np.max(np.abs(pred-recorded)))<=TOL,
             'heldout logits do not physically match final learned Head tensors')
        if nsteps==40:
            must(record['final_weights_sha256']==expected['final_weights_sha256']
                 and float(np.max(np.abs(recorded-np.asarray(expected['heldout_logits']))))<=TOL,
                 'original 40-step baseline or router weights/results changed')
        if name=='fixed_top1':
            must(record['split_proposed'] is True,'fixed routed Head cannot disable routing')
        if name=='single_active':
            must(record['split_proposed'] is False,'single Head cannot silently activate split')
        if name=='frozen_single':
            must(record['split_proposed'] is False and record['initial_weights_sha256']==record['final_weights_sha256'],
                 'no-change frozen Head actually trained or split')
        if name=='adaptive_top1':
            must(record['split_proposed'] is (record['train_only_brier_excess']>0.03)
                 and record['migration_copied_fp32_bytes']==(7434*4 if record['split_proposed'] else 0)
                 and record['parity_head_forward_rows']==(8 if record['split_proposed'] else 0),
                 'adaptive fission trigger/migration cannot use heldout or free copying')
        else:
            must(record['migration_copied_fp32_bytes']==0 and record['parity_head_forward_rows']==0,
                 'unregistered fission/migration')
        score=[int((float(pred[i,1])>=float(pred[i,0]))==bool(targets[i])) for i in range(96)]
        probabilities=np.exp(pred-pred.max(axis=1,keepdims=True))
        probabilities=probabilities[:,1]/probabilities.sum(axis=1)
        result[name]=dict(test_correct=sum(score[32:]),test_total=64,
                          calibration_correct=sum(score[:32]),calibration_total=32,
                          test_brier=sum((float(probabilities[i])-targets[i])**2 for i in range(32,96))/64,
                          trained_steps=nsteps,training_exposure=need_rows,
                          train_cpu_ratio_vs_single_pilot=record['train_cpu_ns']/ref,
                          test_predictions_are_retrospective_not_future=True)
    return dict(schema=SCORE,original_cpu_review_has_no_authority=True,
                source_report_sha256=new['report_sha256'],model_weights_sha256=new['frozen_model_weights_sha256'],
                full_training_pilots_paid=len(trials),calibration_training_cpu_ns_sum=all_paid_pilots,
                budgeted_train_cpu_ns_sum=sum(arms[a]['train_cpu_ns'] for a in ARMS),
                original_heldout_labels_reopened_after_predictions=True,
                compare=dict(sorted(result.items())),
                predictor_backward_history_independently_authenticated=False,
                matched_exact_total_flops=False,equal_cpu_budget_exact=False,
                model_winner_selected=False,production_promotion_permitted=False,authority='DENY_ALL')


def main():
    pa=argparse.ArgumentParser(description=__doc__)
    for arg in ('original-panel','train-material','blind-material','owner-labels',
                'original-p2-report','original-trained-top1-report','original-backward-cost-report',
                'original-counterbalanced-cpu-report','budget-frontier-report','output'):
        pa.add_argument('--'+arg,required=True)
    args=pa.parse_args()
    dest=Path(args.output);must(not dest.exists(),'independent prelabel score artifact must be create-only')
    from p2_backward_cost_profile_review import read
    out=review(read(args.original_panel),read(args.train_material),read(args.blind_material),
               read(args.owner_labels),read(args.original_p2_report),
               read(args.original_trained_top1_report),read(args.original_backward_cost_report),
               read(args.original_counterbalanced_cpu_report),read(args.budget_frontier_report))
    with dest.open('x',encoding='utf8') as f:
        json.dump(out,f,sort_keys=True,allow_nan=False);f.write('\n')

if __name__=='__main__':main()
