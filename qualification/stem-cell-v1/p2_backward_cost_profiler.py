"""Independent re-execution of P2 trained Top-1 under bounded CPU ATen profiler.

This sidecar does not rewrite original P2 or its Top-1 receipt, change weights,
read heldout labels, or authorize promotion. PyTorch profiler's FLOP annotations
are INCOMPLETE (often omit nonlinearities, optimizer and some backward ops).
"""
from __future__ import annotations

import argparse
import json
import math
import resource
import sys
import time
from pathlib import Path

import torch
from torch.profiler import ProfilerActivity, profile

import p1_real_granite_cohort as p1
import p2_real_cell_split as p2
import p2_train_sparse_equal_compute as trained

SCHEMA = 'hepta.p2.one-active-cpu-backward-operator-profile.v1'
REGISTERED_ARMS = trained.ARMS
OBSERVABLE_MATMUL = ('aten::mm', 'aten::addmm', 'aten::bmm')
MAX_OPERATOR_TYPES = 256
MAX_FL0PS = 10**14


def need(ok, message):
    if not ok:
        raise ValueError(message)


def source_lock(training, blind, previous, original, backend, *, real):
    p1.verify_material(training, blind)
    need(type(real) is bool and isinstance(previous, dict) and isinstance(original, dict),
         'complete pinned predecessor receipt and explicit real-profile bit required')
    def seal(d):
        return d.get('report_sha256') == trained.digest({k:v for k,v in d.items() if k!='report_sha256'})
    need(seal(previous) and seal(original), 'changed sealed original training or P2 source')
    source_model_sha, count = p1.backend_digest(backend)
    need(original.get('frozen_model_weights_sha256') == source_model_sha
         and previous.get('original_model_weights_sha256') == source_model_sha
         and previous.get('original_p2_report_sha256') == original['report_sha256']
         and previous.get('model_parameter_count') == count
         and original.get('public_panel_sha256') == previous.get('source_panel_sha256') == p1.PANEL_SHA
         and original.get('model_revision') == previous.get('model_revision') == p1.GRANITE_REVISION
         and previous.get('source_cohorts_are_chronological') is False
         and previous.get('exact_backward_flops_matched') is False
         and previous.get('authority') == original.get('authority') == 'DENY_ALL',
         'mismatched model, panel, original P2 lineage, or unauthorized existing claim')
    need(previous.get('pretrained_weight_execution_claimed') is real
         and original.get('frozen_pretrained_source_execution_claimed') is real,
         'cannot relabel fixture as a real pretrained model')
    if real:
        need(count >= 90_000_000 and getattr(backend, 'revision', None) == p1.GRANITE_REVISION
             and getattr(backend, 'model_id', None) == p1.GRANITE_MODEL
             and getattr(backend, 'device', None) == 'cpu',
             'only pinned real Granite97 owner can attest pretrained weights')
    return source_model_sha, count


def profile_arm(initial, x, y, heldout, cutoff, arm, original_arm):
    """Physically replay old 40-step SGD and derive an operator-only receipt."""
    need(arm in REGISTERED_ARMS and isinstance(original_arm, dict)
         and original_arm.get('arm') == arm, 'complete original trained arm required')
    cpu_start = time.process_time_ns()
    wall_start = time.perf_counter_ns()
    with profile(activities=[ProfilerActivity.CPU], with_flops=True,
                 profile_memory=True, record_shapes=False) as observer:
        replay = trained.train_arm(initial, x, y, heldout, mode=arm, cutoff=cutoff)
    elapsed_cpu = max(1, time.process_time_ns()-cpu_start)
    elapsed_wall = max(1, time.perf_counter_ns()-wall_start)
    need(replay['final_weights_sha256'] == original_arm['final_weights_sha256'],
         'profile changed original trained FP32 weights; no valid paired profiler claim')
    need(replay['split_proposed'] is original_arm['split_proposed']
         and replay['train_updates'] == original_arm['train_updates']
         and replay['train_physical_selected_expert_rows'] == original_arm['train_physical_selected_expert_rows']
         and replay['heldout_selected_expert_ids'] == original_arm['heldout_selected_expert_ids'],
         'profile reexecuted different routing/learning census')
    error = max(abs(a-b) for r,s in zip(replay['heldout_logits'], original_arm['heldout_logits'], strict=True)
                for a,b in zip(r,s,strict=True))
    need(error <= 1e-6, 'profile cannot reproduce exact original label-blind logits')
    events = observer.key_averages()
    need(0 < len(events) <= MAX_OPERATOR_TYPES, 'bounded Torch physical operator inventory required')
    census = {}
    for event in events:
        name = event.key
        count, flops = int(event.count), int(event.flops)
        cpu_us = float(event.self_cpu_time_total)
        need(type(name) is str and 1 <= len(name) <= 180 and name not in census
             and count > 0 and 0 <= flops <= MAX_FL0PS
             and math.isfinite(cpu_us) and cpu_us >= 0,
             'invalid physical operator/count/FLOP/time receipt')
        census[name] = {'calls':count, 'partial_estimated_flops':flops,
                        'self_cpu_time_us':cpu_us}
    need('aten::mm' in census and 'aten::index_select' in census,
         'Torch profiler failed to observe actual selected expert matmul')
    if arm != 'frozen_single':
        need('autograd::engine::evaluate_function: MmBackward0' in census
             and ('aten::_foreach_add_' in census or 'aten::add_' in census),
             'Torch profiler failed to observe actual backward and optimizer')
    estimate = sum(z['partial_estimated_flops'] for z in census.values())
    covered_cpu_us = sum(z['self_cpu_time_us'] for z in census.values()
                         if z['partial_estimated_flops']>0)
    whole_cpu_us = sum(z['self_cpu_time_us'] for z in census.values())
    route_calls = sum(census.get(key, {}).get('calls',0)
                      for key in ('aten::ge','aten::nonzero','aten::index_select','aten::index_copy'))
    autograd_nodes = sum(z['calls'] for name,z in census.items()
                         if name.startswith('autograd::engine::evaluate_function:'))
    if arm!='frozen_single':
        need(autograd_nodes >= 40, 'no physically observed 40-step reverse autograd work')
    need(estimate > 0 and whole_cpu_us > 0 and 0 <= covered_cpu_us <= whole_cpu_us + 1e-4,
         'missing partial arithmetic and CPU kernel cost measurement')
    return {
        'arm': arm,
        'original_final_weights_sha256': original_arm['final_weights_sha256'],
        'original_result_logits_max_abs': float(error),
        'train_updates': replay['train_updates'],
        'train_examples_exposed': replay['train_examples_exposed'],
        'train_selected_expert_forward_rows': replay['train_physical_selected_expert_rows'],
        'train_head_batch_calls': replay['training_head_batch_calls'],
        'migration_fp32_copy_bytes': replay['migration_copied_fp32_bytes'],
        'split_parity_extra_forward_rows': replay['split_parity_actual_head_forward_rows'],
        'registered_expert_forward_linear_mac': replay['train_forward_linear_mac'],
        'observer_cpu_process_ns': elapsed_cpu,
        'observer_wall_ns': elapsed_wall,
        'registered_aten_flops_partial_only': int(estimate),
        'registered_aten_self_cpu_us': float(whole_cpu_us),
        'registered_flop_covered_self_cpu_us': float(covered_cpu_us),
        'recorded_route_kernel_calls': route_calls,
        'recorded_autograd_function_nodes': autograd_nodes,
        'recorded_operator_types': len(census),
        'operator_census': census,
        'training_cpu_ns_original_uninstrumented': original_arm['train_cpu_ns'],
        'training_wall_ns_original_uninstrumented': original_arm['train_wall_ns'],
        'operator_flops_equal_total_backward_flops': False,
        'instrumented_wall_is_production_latency': False,
        'training_timing_is_order_randomized': False,
    }


def execute(training, blind, backend, original_p2, earlier_trained, *, real=False):
    """Re-encode 224 frozen inputs, then replay training; no heldout label read."""
    torch.set_num_threads(1)
    initial_sha, count = source_lock(training, blind, earlier_trained, original_p2,backend,real=real)
    counter = {'calls':0,'model_encode_wall_ns':0}
    encoder_begin_cpu = time.process_time_ns()
    encoder_begin_wall = time.perf_counter_ns()
    vectors = {}
    for record in training['rows']+blind['rows']:
        vectors[record['case_id']] = p1.encode(backend,record,call_stats=counter)
    encoding_cpu = max(1,time.process_time_ns()-encoder_begin_cpu)
    encoding_wall = max(1,time.perf_counter_ns()-encoder_begin_wall)
    need(counter['calls']==224 and len(vectors)==224,
         'new profiler run must pay all 224 original frozen Encoder forwards')
    q24 = {r['case_id']:[int(round(float(z)*(1<<24))) for z in vectors[r['case_id']]]
           for r in blind['rows']}
    need(q24 == earlier_trained['source_features_q24'] == original_p2['source_features_q24'],
         'newly encoded model features not byte-identical to original training inputs')
    x = torch.stack([vectors[r['case_id']] for r in training['rows']])
    y = torch.tensor([r['label'] for r in training['rows']],dtype=torch.long)
    heldout = torch.stack([vectors[r['case_id']] for r in blind['rows']])
    cutoff=float(torch.median(x[:,0]))
    need(cutoff==earlier_trained['train_cutoff_feature0_median']==original_p2['cutoff_feature0_train_median'],
         'new routing threshold not the train-only registered original')
    seed=earlier_trained['seed']
    base=p2.TwoHeads(seed)
    need(p2.shape_hash(dict(base.named_parameters()))==earlier_trained['original_frozen_two_head_initial_sha256'],
         'profile did not reuse original trained Head initial weights')
    # Fixed order to preserve exact original results. Profiler overhead, cache,
    # and temperature make per-arm wall comparisons descriptive only.
    arms={k:profile_arm(base,x,y,heldout,cutoff,k,earlier_trained['compared_arms'][k])
          for k in REGISTERED_ARMS}
    after,count2=p1.backend_digest(backend)
    need((after,count2)==(initial_sha,count),'frozen original Stem modified by profiling')
    out={
        'schema':SCHEMA, 'authority':'DENY_ALL',
        'production_promotion_permitted':False,
        'original_p2_sha256': original_p2['report_sha256'],
        'original_trained_top1_sha256': earlier_trained['report_sha256'],
        'original_panel_sha256':p1.PANEL_SHA,
        'model_weights_sha256':initial_sha,
        'model_parameter_count':count,
        'model_revision':p1.GRANITE_REVISION,
        'pretrained_model_loaded_in_profile_job':real,
        'original_model_load_is_incremental_cost':real,
        'physical_encoder_forward_calls_in_profile_job':counter['calls'],
        'encoder_cpu_ns_in_profile_job':encoding_cpu,
        'encoder_wall_ns_in_profile_job':encoding_wall,
        'original_heldout_source_inventory':earlier_trained['source_heldout_cases'],
        'original_train_rows':128,'original_blind_rows':96,
        'same_stem_and_training_data_as_original':True,
        'profiled_arms':arms,
        'profiler_is_independently_attested':False,
        'source_model_publisher_signed':False,
        'complete_backward_flops_verified':False,
        'equal_total_training_compute_verified':False,
        'whole_request_p99_verified':False,
        'energy_usage_verified':False,
        'future_source_family_generalization_verified':False,
        'model_winner_selected':False,
        'observed_process_peak_rss_bytes':resource.getrusage(resource.RUSAGE_SELF).ru_maxrss*1024,
    }
    out['report_sha256']=trained.digest(out)
    return out


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    for field in ('train-material','blind-material','compact-source','original-p2-report',
                  'original-trained-top1-report','output'):
        ap.add_argument('--'+field,required=True)
    args=ap.parse_args()
    need(not Path(args.output).exists(),'immutable create-only cost profile file required')
    t=p1.read_json(args.train_material)
    b=p1.read_json(args.blind_material)
    old=p1.read_json(args.original_p2_report)
    learned=p1.read_json(args.original_trained_top1_report)
    sys.path.insert(0,str(Path(args.compact_source)/'qualification/neuron-stem'))
    from compact_stem_trial import FrozenCompactStem
    backend=FrozenCompactStem(p1.GRANITE_MODEL,p1.GRANITE_REVISION,device='cpu',max_tokens=512)
    receipt=execute(t,b,backend,old,learned,real=True)
    p1.write_exclusive(args.output,receipt)

if __name__=='__main__':main()
