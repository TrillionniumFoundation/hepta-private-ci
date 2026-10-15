"""Counterbalanced CPU re-training of source-locked Top-1 alternatives.

Physical full-run wall/CPU timing of exact *original* train_arm, no profiler.
An 8-round balanced randomized Williams-like crossover removes fixed arm-position
confounding, but not scheduler drift, causal performance variance or target-host
costs. This is research-only and CANNOT authorize a model/Cell Split.
"""
from __future__ import annotations

import argparse
import math
import random
import resource
import sys
import time
from pathlib import Path

import torch

import p1_real_granite_cohort as p1
import p2_real_cell_split as p2
import p2_train_sparse_equal_compute as trained
import p2_backward_cost_profiler as prior

SCHEMA = 'hepta.p2.counterbalanced-uninstrumented-training-cost.v1'
ARMS = trained.ARMS
ROUNDS_ALLOWED = (8, 16, 24, 32)
TOL = 1e-6


def need(condition, reason):
    if not condition:
        raise ValueError(reason)


def order_for_rounds(seed, rounds):
    """Balanced four-arm crossover: each arm every position twice per 8 rounds.

    The base sequence [0,1,3,2] uses four cyclic translations, then the
    reversed set. A seeded arm-name permutation is frozen before any timing.
    """
    need(type(seed) is int and 1 <= seed < 2**31 and type(rounds) is int
         and rounds in ROUNDS_ALLOWED, 'preregistered crossover seed and multiple-of-eight rounds required')
    names = list(ARMS)
    random.Random(seed).shuffle(names)
    base = (0, 1, 3, 2)
    four = [tuple(names[(v + i) % 4] for v in base) for i in range(4)]
    eight = four + [tuple(reversed(row)) for row in four]
    schedule = [list(eight[i % 8]) for i in range(rounds)]
    need(all(set(row) == set(ARMS) for row in schedule), 'crossover arm inventory changed')
    return schedule


def _replay(original, arm, result):
    need(result['final_weights_sha256'] == original['final_weights_sha256']
         and result['initial_weights_sha256'] == original['initial_weights_sha256']
         and result['split_proposed'] is original['split_proposed']
         and result['train_updates'] == original['train_updates']
         and result['train_examples_exposed'] == original['train_examples_exposed']
         and result['train_physical_selected_expert_rows'] == original['train_physical_selected_expert_rows']
         and result['heldout_selected_expert_ids'] == original['heldout_selected_expert_ids']
         and result['migration_copied_fp32_bytes'] == original['migration_copied_fp32_bytes']
         and result['training_head_batch_calls'] == original['training_head_batch_calls'],
         f'{arm}: original matched optimizer, route or physically resident weights changed')
    need(len(result['heldout_logits']) == len(original['heldout_logits']) == 96,
         'all original 96 heldout tasks must replay')
    error = max(abs(a-b) for x,y in zip(result['heldout_logits'], original['heldout_logits'], strict=True)
                for a,b in zip(x,y,strict=True))
    need(error <= TOL, 'trained original logits cannot be numerically replayed')
    return float(error)


def _time_retrain(initial, x, y, heldout, cutoff, arm, old):
    # No torch.profiler, no hardware benchmark substitution or inference cache.
    bcpu = time.process_time_ns()
    bwall = time.perf_counter_ns()
    observed = trained.train_arm(initial, x, y, heldout, mode=arm, cutoff=cutoff)
    cpu = max(1, time.process_time_ns() - bcpu)
    wall = max(1, time.perf_counter_ns() - bwall)
    error = _replay(old, arm, observed)
    need(cpu >= observed['train_cpu_ns'] and wall >= observed['train_wall_ns']
         and cpu >= observed['heldout_cpu_ns'] and wall >= observed['heldout_wall_ns'],
         'total measured CPU/wall cannot be smaller than any included stage')
    return dict(arm=arm, measured_total_cpu_ns=cpu, measured_total_wall_ns=wall,
                internally_measured_train_cpu_ns=observed['train_cpu_ns'],
                internally_measured_train_wall_ns=observed['train_wall_ns'],
                internally_measured_heldout_cpu_ns=observed['heldout_cpu_ns'],
                internally_measured_heldout_wall_ns=observed['heldout_wall_ns'],
                original_final_weights_sha256=observed['final_weights_sha256'],
                original_heldout_logits_max_abs=error,
                train_updates=observed['train_updates'],
                training_selected_expert_rows=observed['train_physical_selected_expert_rows'],
                training_head_batch_calls=observed['training_head_batch_calls'],
                split_parity_extra_forward_rows=observed['split_parity_actual_head_forward_rows'],
                migration_copied_fp32_bytes=observed['migration_copied_fp32_bytes'])


def execute(training, blind, backend, original_p2, earlier_trained, *, real=False,
            rounds=8, crossover_seed=20261015):
    """Source-locked re-encoding, warmups, counterbalanced full 40-step reruns.

    Do not pass any withheld evaluation labels. Claims of external source or
    public model identity still require original independently owned evidence.
    """
    order = order_for_rounds(crossover_seed, rounds)
    torch.set_num_threads(1)
    model_sha, nmodel = prior.source_lock(training, blind, earlier_trained,
                                          original_p2, backend, real=real)
    calls = {'calls':0, 'model_encode_wall_ns':0}
    tcpu = time.process_time_ns(); twall = time.perf_counter_ns()
    features = {r['case_id']:p1.encode(backend,r,call_stats=calls)
                for r in training['rows'] + blind['rows']}
    encode_cpu = max(1,time.process_time_ns()-tcpu)
    encode_wall = max(1,time.perf_counter_ns()-twall)
    need(calls['calls'] == len(features) == 224,
         'new independent CPU benchmark must pay all 224 original model forwards')
    source_q24 = {r['case_id']:[int(round(float(v)*(1<<24))) for v in features[r['case_id']]]
                  for r in blind['rows']}
    need(source_q24 == earlier_trained['source_features_q24'] == original_p2['source_features_q24'],
         'benchmark did not recreate original frozen pre-label heldout feature bytes')
    x = torch.stack([features[r['case_id']] for r in training['rows']])
    y = torch.tensor([r['label'] for r in training['rows']], dtype=torch.long)
    heldout = torch.stack([features[r['case_id']] for r in blind['rows']])
    cutoff = float(torch.median(x[:,0]))
    need(cutoff == original_p2['cutoff_feature0_train_median']
         == earlier_trained['train_cutoff_feature0_median'],
         'benchmark changed train-only Router threshold')
    initial = p2.TwoHeads(earlier_trained['seed'])
    need(p2.shape_hash(dict(initial.named_parameters()))
         == earlier_trained['original_frozen_two_head_initial_sha256'],
         'benchmark initial identical Head control not restored')
    # Warmup runs are NOT discarded as cost. They are charged separately and
    # excluded only from steady-state descriptive paired wall summaries.
    warmups = []
    for arm in ARMS:
        warmups.append(_time_retrain(initial,x,y,heldout,cutoff,arm,
                      earlier_trained['compared_arms'][arm]))
    measurements = []
    for round_number, arm_order in enumerate(order):
        for position, arm in enumerate(arm_order):
            timed = _time_retrain(initial,x,y,heldout,cutoff,arm,
                         earlier_trained['compared_arms'][arm])
            measurements.append(dict(round=round_number, position=position, **timed))
    last_sha, count2 = p1.backend_digest(backend)
    need((last_sha,count2)==(model_sha,nmodel),
         'frozen shared Stem weights mutated across timed replays')
    need(len(warmups)==4 and len(measurements)==rounds*4,
         'missing timed CPU trials')
    out = dict(schema=SCHEMA,authority='DENY_ALL',production_promotion_permitted=False,
        original_p2_sha256=original_p2['report_sha256'],
        original_trained_top1_sha256=earlier_trained['report_sha256'],
        source_panel_sha256=p1.PANEL_SHA, model_revision=p1.GRANITE_REVISION,
        model_weights_sha256=model_sha,model_parameter_count=nmodel,
        pretrained_model_loaded_in_this_job=real,
        model_load_is_extra_replay_cost=real,
        model_load_ms_observed_by_backend=(float(getattr(backend,'model_load_ms',0)) if real else None),
        physical_encoder_calls_in_this_job=calls['calls'],
        encoder_cpu_ns=encode_cpu,encoder_wall_ns=encode_wall,
        original_train_rows=128,original_blind_rows=96,
        original_source_inventory=earlier_trained['source_heldout_cases'],
        control_arm=ARMS[1], crossover_seed=crossover_seed, measured_rounds=rounds,
        crossover_orders=order,warmup_trials=warmups,measured_trials=measurements,
        warmup_runs_counted_as_work=True,operator_profiler_disabled_for_timing=True,
        all_four_arms_train_and_score_recomputed_every_round=True,
        time_traces_are_not_independently_attested=True,
        retrospective_public_source_not_future=True,
        exact_total_flops_matched=False,target_worker_end_to_end_certified=False,
        p99_requests_independently_sampled=False,model_winner_selected=False,
        CPU_run_not_energy_or_serving_measurement=True,
        process_peak_rss_bytes=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss*1024)
    out['receipt_sha256']=trained.digest(out)
    return out


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    for field in ('train-material','blind-material','compact-source','original-p2-report',
                  'original-trained-top1-report','output'):
        ap.add_argument('--'+field,required=True)
    ap.add_argument('--rounds',type=int,default=8)
    ap.add_argument('--crossover-seed',type=int,default=20261015)
    args=ap.parse_args()
    need(not Path(args.output).exists(),'create-only CPU crossover receipt required')
    tr=p1.read_json(args.train_material); ev=p1.read_json(args.blind_material)
    old=p1.read_json(args.original_p2_report)
    parent=p1.read_json(args.original_trained_top1_report)
    sys.path.insert(0,str(Path(args.compact_source)/'qualification/neuron-stem'))
    from compact_stem_trial import FrozenCompactStem
    model=FrozenCompactStem(p1.GRANITE_MODEL,p1.GRANITE_REVISION,device='cpu',max_tokens=512)
    trace=execute(tr,ev,model,old,parent,real=True,rounds=args.rounds,crossover_seed=args.crossover_seed)
    p1.write_exclusive(args.output,trace)


if __name__=='__main__':
    main()
