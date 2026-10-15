"""Research-only CPU-budget-frozen, real one-active Top-1 training frontier.

This is NOT exact equal FLOPs: choose integer steps from paid, training-only
CPU calibrations *before* evaluating label-blind original heldout predictions.
All benchmark-calibration runs, Encoder loads and every updated Head are paid.
The scientific intervention trades additional baseline data exposure against
router compute and preserves unfavorable outcomes. Never production-authorizing.
"""
from __future__ import annotations

import argparse
import copy
import math
import random
import resource
import sys
import time
from pathlib import Path

import torch
from torch.nn import functional as F

import p1_real_granite_cohort as p1
import p2_real_cell_split as p2
import p2_train_sparse_equal_compute as prev
import p2_backward_cost_profiler as ancestor

SCHEMA='hepta.p2.training-cpu-budget-frontier.v1'
ARMS=prev.ARMS
LEARNED=prev.MATCHED
CAL_ROUNDS=8
BASE_STEPS=40
MIN_STEPS=20
MAX_STEPS=40
TOL=1e-6


def need(value, explanation):
    if not value:raise ValueError(explanation)


def orders(seed, rounds=CAL_ROUNDS):
    """4 arms; each arm occupies each sequential position twice."""
    need(type(seed) is int and 1<=seed<2**31 and rounds==CAL_ROUNDS,
         'fixed train-only CPU calibration schedule required')
    names=list(ARMS)
    random.Random(seed).shuffle(names)
    square=[tuple(names[(x+i)%4] for x in (0,1,3,2)) for i in range(4)]
    return [list(r) for r in square+[tuple(reversed(x)) for x in square]]


def allotted_steps(full_single_cpu_ns, candidate_cpu_ns):
    """Even 20..40 steps; estimation uses ONLY completed training CPU pilot."""
    need(type(full_single_cpu_ns) is int and type(candidate_cpu_ns) is int
         and 0<full_single_cpu_ns<10**14 and 0<candidate_cpu_ns<10**14,
         'nonzero bounded CPU calibration required')
    raw=(BASE_STEPS*full_single_cpu_ns)//candidate_cpu_ns
    return int(max(MIN_STEPS,min(MAX_STEPS,2*(raw//2))))


def train_one(initial,x,y,*,mode,cutoff,steps,heldout=None):
    """One real autograd Head per sample, train-only midstage fission decision.

    `heldout=None` throughout all calibration pilots. 20/20 old/mixed
    stages at 40 steps, or half/half when a measured CPU cap reduces updates.
    The original 40-step protocol exactly replays at steps=40.
    """
    need(mode in ARMS and type(steps) is int and steps%2==0 and 20<=steps<=40
         and x.shape==(128,384) and y.shape==(128,) and not x.requires_grad
         and x.dtype==torch.float32 and y.dtype==torch.long
         and type(cutoff) is float and math.isfinite(cutoff)
         and (heldout is None or (heldout.shape==(96,384) and heldout.dtype==torch.float32)),
         'bounded original train-only 128x384 and even training stages required')
    model=copy.deepcopy(initial)
    need(prev.resident(model)==14868,'equal total 14868-scalar physical Head resident slots required')
    initial_sha=p2.shape_hash(dict(model.named_parameters()))
    original_slot=prev.expert_bytes(model,1)
    optimizer=torch.optim.SGD(model.parameters(),lr=.15)
    split=(mode=='fixed_top1')
    updates=0;exposures=0;rows=[0,0];train_calls=0
    loss_trace=[];diagnostics=[0,0];diagnostic_calls=0
    start_cpu=time.process_time_ns();start_wall=time.perf_counter_ns()

    def one_batch(bx, by):
        nonlocal updates,exposures,train_calls
        optimizer.zero_grad(set_to_none=True)
        selected=prev.select_indices(bx,mode,cutoff=cutoff,split=split)
        logits,selected_counts,ncalls=prev.sparse_head(model,bx,selected=selected)
        loss=F.cross_entropy(logits,by)
        need(bool(torch.isfinite(loss)), 'finite physical train loss required')
        loss.backward()
        for selected_expert,nrows in enumerate(selected_counts):
            if nrows==0:
                for w in model.parameters():
                    need(w.grad is None or bool(torch.all(w.grad[selected_expert]==0)),
                         'inactive expert illegally received a gradient')
        optimizer.step()
        updates+=1;exposures+=len(bx);train_calls+=ncalls
        for e in range(2):rows[e]+=selected_counts[e]
        loss_trace.append(float(loss.detach()))

    old_steps=steps//2;new_steps=steps//2
    if mode!='frozen_single':
        for _ in range(old_steps):one_batch(x[:64],y[:64])
    with torch.no_grad():
        probs=[]
        for a,b in ((0,64),(64,128)):
            batch=x[a:b]
            who=prev.select_indices(batch,mode,cutoff=cutoff,split=split)
            scores,count,ncalls=prev.sparse_head(model,batch,selected=who)
            for e in range(2):diagnostics[e]+=count[e]
            diagnostic_calls+=ncalls
            probs.append(torch.softmax(scores,dim=1)[:,1])
        old=float(((probs[0]-y[:64].float())**2).mean())
        new=float(((probs[1]-y[64:].float())**2).mean())
    excess=new-old
    clone_max=0.0;copy_bytes=0;parity_rows=0;parity_calls=0
    if mode=='adaptive_top1' and excess>p2.SPLIT_THRESHOLD:
        with torch.no_grad():
            sample=x[:4]
            parent,a,ac=prev.sparse_head(model,sample,selected=torch.zeros(4,dtype=torch.long))
            for w in model.parameters():w[1].copy_(w[0])
            child,b,bc=prev.sparse_head(model,sample,selected=torch.ones(4,dtype=torch.long))
            clone_max=float((parent-child).abs().max())
            need(clone_max==0.,'parent-copy fission parity failed')
            parity_rows=sum(a)+sum(b);parity_calls=ac+bc;copy_bytes=7434*4
        split=True
    if mode!='frozen_single':
        for _ in range(new_steps):one_batch(x,y)
    train_cpu=max(1,time.process_time_ns()-start_cpu)
    train_wall=max(1,time.perf_counter_ns()-start_wall)
    sha=p2.shape_hash(dict(model.named_parameters()))
    need(sum(rows)==(0 if mode=='frozen_single' else old_steps*64+new_steps*128)
         and sum(diagnostics)==128
         and (mode=='frozen_single' or (updates==steps and sha!=initial_sha)),
         'frozen/updated physical Head training work census incomplete')
    if mode in ('frozen_single','single_active') or (mode=='adaptive_top1' and not split):
        need(prev.expert_bytes(model,1)==original_slot,'unselected Head mutated despite single-active training')
    result=dict(arm=mode,training_steps=updates,old_steps=old_steps if updates else 0,
                mixed_steps=new_steps if updates else 0,train_exposures=exposures,
                training_selected_expert_rows=rows,training_head_batch_calls=train_calls,
                initial_weights_sha256=initial_sha,final_weights_sha256=sha,
                model_parameter_count=prev.resident(model),active_head_parameters=7434,
                split_proposed=split,train_only_brier_excess=float(excess),
                split_threshold=p2.SPLIT_THRESHOLD,clone_parity_logits_max_abs=clone_max,
                migration_copied_fp32_bytes=copy_bytes,parity_head_forward_rows=parity_rows,
                parity_head_batch_calls=parity_calls,
                diagnostic_head_rows=diagnostics,diagnostic_head_batch_calls=diagnostic_calls,
                train_cpu_ns=train_cpu,train_wall_ns=train_wall,
                training_loss_trace=loss_trace)
    if heldout is not None:
        with torch.no_grad():
            chosen=prev.select_indices(heldout,mode,cutoff=cutoff,split=split)
            logits,heldout_counts,heldout_calls=prev.sparse_head(model,heldout,selected=chosen)
        result.update(heldout_selected_expert_ids=chosen.tolist(),
                      heldout_logits=logits.tolist(),
                      heldout_expert_rows=heldout_counts,heldout_head_batch_calls=heldout_calls,
                      weights=prev.trained_weights(model))
    return result


def median_three_or_eight(values):
    need(type(values) is list and len(values)==CAL_ROUNDS and all(type(v) is int and v>0 for v in values),
         'full preregistered 8-round train-only CPU calibration required')
    v=sorted(values)
    return (v[3]+v[4])//2


def execute(training,blind,backend,original_p2,original_trained,cpu_reference,*,real=False,
            seed=20261015):
    torch.set_num_threads(1)
    model_sha,param_count=ancestor.source_lock(training,blind,original_trained,original_p2,
                                               backend,real=real)
    need(cpu_reference['schema']=='hepta.p2.counterbalanced-uninstrumented-training-cost.v1'
         and cpu_reference['receipt_sha256']==prev.digest({k:v for k,v in cpu_reference.items() if k!='receipt_sha256'})
         and cpu_reference['model_weights_sha256']==model_sha
         and cpu_reference['original_trained_top1_sha256']==original_trained['report_sha256'],
         'original independent paired CPU provenance required, not outcome tuning')
    calls={'calls':0,'model_encode_wall_ns':0};begin_cpu=time.process_time_ns();begin_wall=time.perf_counter_ns()
    features={r['case_id']:p1.encode(backend,r,call_stats=calls)
              for r in training['rows']+blind['rows']}
    encode_cpu=max(1,time.process_time_ns()-begin_cpu)
    encode_wall=max(1,time.perf_counter_ns()-begin_wall)
    need(calls['calls']==len(features)==224,'additional 224 actual frozen model forwards required')
    feature_q24={r['case_id']:[int(round(float(v)*(1<<24))) for v in features[r['case_id']]]
                 for r in blind['rows']}
    need(feature_q24==original_p2['source_features_q24']==original_trained['source_features_q24'],
         'changed original heldout source features before budget calibration')
    x=torch.stack([features[r['case_id']] for r in training['rows']]);y=torch.tensor([r['label'] for r in training['rows']],dtype=torch.long)
    heldout=torch.stack([features[r['case_id']] for r in blind['rows']])
    cutoff=float(torch.median(x[:,0]));need(cutoff==original_trained['train_cutoff_feature0_median'],
                                           'changed original train-only cutoff')
    initial=p2.TwoHeads(original_trained['seed'])
    need(p2.shape_hash(dict(initial.named_parameters()))==original_trained['original_frozen_two_head_initial_sha256'],
         'original initial Head parameters did not replay')
    schedule=orders(seed)
    # Physical calibration uses train source/labels ONLY. Never call predict on heldout.
    pilots=[];calibration={arm:[] for arm in ARMS}
    for i,round_order in enumerate(schedule):
        for position,arm in enumerate(round_order):
            pilot=train_one(initial,x,y,mode=arm,cutoff=cutoff,steps=BASE_STEPS,heldout=None)
            expected=original_trained['compared_arms'][arm]
            need(pilot['final_weights_sha256']==expected['final_weights_sha256']
                 and pilot['split_proposed'] is expected['split_proposed']
                 and pilot['training_steps']==expected['train_updates'],
                 'calibration cannot mutate original exact trained control')
            pilots.append(dict(round=i,position=position,arm=arm,
                               full_40_step_training_cpu_ns=pilot['train_cpu_ns'],
                               full_40_step_training_wall_ns=pilot['train_wall_ns'],
                               final_weights_sha256=pilot['final_weights_sha256'],
                               split_proposed=pilot['split_proposed'],
                               train_selected_head_rows=pilot['training_selected_expert_rows'],
                               migration_copied_fp32_bytes=pilot['migration_copied_fp32_bytes']))
            calibration[arm].append(pilot['train_cpu_ns'])
    reference_ns=median_three_or_eight(calibration['single_active'])
    target={a:(0 if a=='frozen_single' else BASE_STEPS if a=='single_active'
               else allotted_steps(reference_ns,median_three_or_eight(calibration[a])))
            for a in ARMS}
    # A zero-step frozen control still exercises its 128 training-only diagnostic cases.
    final={};score_calls=0
    for arm in ARMS:
        out=train_one(initial,x,y,mode=arm,cutoff=cutoff,
                      steps=target[arm] or MIN_STEPS,heldout=heldout)
        expected=original_trained['compared_arms'][arm]
        if target[arm]==BASE_STEPS:
            need(out['final_weights_sha256']==expected['final_weights_sha256'] and
                 all(abs(a-b)<=TOL for xrow,yrow in zip(out['heldout_logits'],expected['heldout_logits'],strict=True)
                     for a,b in zip(xrow,yrow,strict=True)),
                 '40-step original learned or frozen P2 prediction drift')
        if arm=='frozen_single':need(out['training_steps']==0,'frozen budget control was updated')
        out['budget_selected_steps']=target[arm]
        out['training_cpu_ns_ratio_vs_calibrated_single_budget']=out['train_cpu_ns']/reference_ns
        out['pilot_median_full_40_cpu_ns']=median_three_or_eight(calibration[arm])
        final[arm]=out
        score_calls+=out['heldout_head_batch_calls']
    sha_end,n_after=p1.backend_digest(backend)
    need((sha_end,n_after)==(model_sha,param_count),'pretrained shared Stem mutated')
    report=dict(schema=SCHEMA,authority='DENY_ALL',production_promotion_permitted=False,
                original_p2_sha256=original_p2['report_sha256'],
                original_trained_top1_sha256=original_trained['report_sha256'],
                original_counterbalanced_cpu_sha256=cpu_reference['receipt_sha256'],
                source_panel_sha256=original_trained['source_panel_sha256'],
                frozen_model_weights_sha256=model_sha,model_revision=p1.GRANITE_REVISION,
                model_parameter_count=param_count,pretrained_model_loaded_in_this_job=real,
                model_load_cost_counted_separately=real,
                model_load_ms_observed_by_backend=(float(getattr(backend,'model_load_ms',0)) if real else None),
                physical_encoder_calls_in_this_job=calls['calls'],encoding_cpu_ns=encode_cpu,
                encoding_wall_ns=encode_wall,
                source_heldout_cases=original_trained['source_heldout_cases'],
                source_features_q24=feature_q24,
                original_seed=original_trained['seed'],calibration_seed=seed,
                pilot_rounds=CAL_ROUNDS,pilot_orders=schedule,
                pilot_records=pilots,calibrated_single_40_step_cpu_ns=reference_ns,
                steps_lower_bound=MIN_STEPS,steps_upper_bound=MAX_STEPS,
                allocated_steps=target,calibration_runs_paid_in_lifecycle=True,
                calibration_uses_training_labels_only=True,
                calibrated_cpu_budget_is_not_exact_matching=True,
                total_backward_flops_equalized=False,
                future_task_quality_established=False,
                blinded_labels_opened_during_training=False,
                test_cohorts_are_retrospective_not_future=True,
                model_winner_selected=False,
                whole_worker_p99_verified=False,
                final_arms=final,
                process_peak_rss_bytes=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss*1024)
    report['report_sha256']=prev.digest(report)
    return report


def main():
    pa=argparse.ArgumentParser(description=__doc__)
    for arg in ('train-material','blind-material','compact-source','original-p2-report',
                'original-trained-top1-report','original-counterbalanced-cpu-report','output'):
        pa.add_argument('--'+arg,required=True)
    pa.add_argument('--calibration-seed',type=int,default=20261015)
    args=pa.parse_args();need(not Path(args.output).exists(),'write-once source-bound CPU-budget result required')
    train=p1.read_json(args.train_material);blind=p1.read_json(args.blind_material)
    old=p1.read_json(args.original_p2_report);traced=p1.read_json(args.original_trained_top1_report)
    cpu=p1.read_json(args.original_counterbalanced_cpu_report)
    sys.path.insert(0,str(Path(args.compact_source)/'qualification/neuron-stem'))
    from compact_stem_trial import FrozenCompactStem
    backend=FrozenCompactStem(p1.GRANITE_MODEL,p1.GRANITE_REVISION,device='cpu',max_tokens=512)
    result=execute(train,blind,backend,old,traced,cpu,real=True,seed=args.calibration_seed)
    p1.write_exclusive(args.output,result)


if __name__=='__main__':main()
