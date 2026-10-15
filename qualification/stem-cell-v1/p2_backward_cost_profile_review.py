"""Independent numeric review of a Torch CPU operator-census sidecar.

No producer, PyTorch, model-loading, or train-time profiler is imported here.
Original human labels are opened only at this *separate* reviewing stage. A
self-reported operator trace is NOT externally signed hardware attestation.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path

import p2_train_sparse_equal_compute_review as original_review

SCHEMA='hepta.p2.one-active-cpu-backward-operator-profile.v1'
SCORE='hepta.p2.one-active-operator-cost-independent-review.v1'
ARMS=('frozen_single','single_active','fixed_top1','adaptive_top1')
FIELDS={'schema','authority','production_promotion_permitted','original_p2_sha256',
        'original_trained_top1_sha256','original_panel_sha256','model_weights_sha256',
        'model_parameter_count','model_revision','pretrained_model_loaded_in_profile_job',
        'original_model_load_is_incremental_cost','physical_encoder_forward_calls_in_profile_job',
        'encoder_cpu_ns_in_profile_job','encoder_wall_ns_in_profile_job',
        'original_heldout_source_inventory','original_train_rows','original_blind_rows',
        'same_stem_and_training_data_as_original','profiled_arms','profiler_is_independently_attested',
        'source_model_publisher_signed','complete_backward_flops_verified',
        'equal_total_training_compute_verified','whole_request_p99_verified','energy_usage_verified',
        'future_source_family_generalization_verified','model_winner_selected',
        'observed_process_peak_rss_bytes','report_sha256'}
ARM_FIELDS={'arm','original_final_weights_sha256','original_result_logits_max_abs',
            'train_updates','train_examples_exposed','train_selected_expert_forward_rows',
            'train_head_batch_calls','migration_fp32_copy_bytes','split_parity_extra_forward_rows',
            'registered_expert_forward_linear_mac','observer_cpu_process_ns',
            'observer_wall_ns','registered_aten_flops_partial_only',
            'registered_aten_self_cpu_us','registered_flop_covered_self_cpu_us',
            'recorded_route_kernel_calls','recorded_autograd_function_nodes',
            'recorded_operator_types','operator_census',
            'training_cpu_ns_original_uninstrumented',
            'training_wall_ns_original_uninstrumented',
            'operator_flops_equal_total_backward_flops',
            'instrumented_wall_is_production_latency',
            'training_timing_is_order_randomized'}
FALSE_FLAGS=('profiler_is_independently_attested','source_model_publisher_signed',
             'complete_backward_flops_verified','equal_total_training_compute_verified',
             'whole_request_p99_verified','energy_usage_verified',
             'future_source_family_generalization_verified','model_winner_selected',
             'production_promotion_permitted')


def need(ok,msg):
    if not ok:raise ValueError(msg)


def digest(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':'),
                ensure_ascii=False,allow_nan=False).encode('utf8')).hexdigest()


def read(path):
    import os,stat
    path=Path(path)
    fd=os.open(path,os.O_RDONLY|getattr(os,'O_NOFOLLOW',0)|getattr(os,'O_NONBLOCK',0))
    try:
        a=os.fstat(fd)
        need(stat.S_ISREG(a.st_mode) and 10<a.st_size<3_000_000,'bounded regular cost journal only')
        with os.fdopen(fd,'rb',closefd=False) as f:content=f.read(3_000_001)
        b=os.fstat(fd)
        need((a.st_dev,a.st_ino,a.st_mtime_ns,a.st_size)==(b.st_dev,b.st_ino,b.st_mtime_ns,b.st_size)
             and len(content)==a.st_size,'cost report changed during reading')
    finally:os.close(fd)
    def unique(pairs):
        result={}
        for k,v in pairs:
            need(k not in result,'duplicate JSON key in physical cost receipt')
            result[k]=v
        return result
    return json.loads(content,object_pairs_hook=unique,
                      parse_constant=lambda _:(_ for _ in ()).throw(ValueError('nonfinite JSON number')))


def _positive_int(x):
    return type(x) is int and 0 < x < 10**16


def _nonnegative_int(x):
    return type(x) is int and 0 <= x < 10**16


def _nonnegative_float(x):
    return type(x) in (float,int) and 0 <= x < 10**16 and math.isfinite(x)


def review(original_panel, train, blind, gold, old_p2, old_trained, trace):
    """Reject unsupported tensor/work equality even after a self-rehash."""
    parent_score=original_review.review(original_panel,train,blind,gold,old_p2,old_trained)
    need(parent_score['production_promotion_permitted'] is False,
         'P2 independent reviewer unexpectedly granted promotion')
    need(type(trace) is dict and set(trace)==FIELDS and trace['schema']==SCHEMA
         and trace['report_sha256']==digest({k:v for k,v in trace.items() if k!='report_sha256'})
         and trace['authority']=='DENY_ALL',
         'source-bound, completely sealed operator profile required')
    need(all(trace[k] is False for k in FALSE_FLAGS)
         and trace['same_stem_and_training_data_as_original'] is True,
         'unsupported verified-compute, real-world quality, or serving authority')
    need(trace['original_p2_sha256']==old_p2['report_sha256']
         and trace['original_trained_top1_sha256']==old_trained['report_sha256']
         and trace['original_panel_sha256']==old_trained['source_panel_sha256']
         and trace['model_weights_sha256']==old_trained['original_model_weights_sha256']
         and trace['model_revision']==old_trained['model_revision']
         and trace['model_parameter_count']==old_trained['model_parameter_count']
         and trace['pretrained_model_loaded_in_profile_job'] is old_trained['pretrained_weight_execution_claimed']
         and trace['original_model_load_is_incremental_cost'] is trace['pretrained_model_loaded_in_profile_job']
         and trace['physical_encoder_forward_calls_in_profile_job']==224
         and trace['original_train_rows']==128 and trace['original_blind_rows']==96
         and trace['original_heldout_source_inventory']==old_trained['source_heldout_cases'],
         'cost trace changed original frozen Stem/source/model/train identity')
    need(_positive_int(trace['encoder_cpu_ns_in_profile_job'])
         and _positive_int(trace['encoder_wall_ns_in_profile_job'])
         and _positive_int(trace['observed_process_peak_rss_bytes']),
         'model encoding, RSS and newly rerun forward costs must be nonzero')
    arms=trace['profiled_arms']
    need(type(arms) is dict and set(arms)==set(ARMS),'complete unfiltered paired four-arm cost census required')
    results={};counted={}
    for name in ARMS:
        a=arms[name];prior=old_trained['compared_arms'][name]
        need(type(a) is dict and set(a)==ARM_FIELDS and a['arm']==name
             and a['original_final_weights_sha256']==prior['final_weights_sha256']
             and _nonnegative_float(a['original_result_logits_max_abs'])
             and a['original_result_logits_max_abs']<=1e-6
             and a['train_updates']==prior['train_updates']
             and a['train_examples_exposed']==prior['train_examples_exposed']
             and a['train_selected_expert_forward_rows']==prior['train_physical_selected_expert_rows']
             and a['train_head_batch_calls']==prior['training_head_batch_calls']
             and a['migration_fp32_copy_bytes']==prior['migration_copied_fp32_bytes']
             and a['split_parity_extra_forward_rows']==prior['split_parity_actual_head_forward_rows']
             and a['registered_expert_forward_linear_mac']==prior['train_forward_linear_mac']
             and a['training_cpu_ns_original_uninstrumented']==prior['train_cpu_ns']
             and a['training_wall_ns_original_uninstrumented']==prior['train_wall_ns']
             and a['operator_flops_equal_total_backward_flops'] is False
             and a['instrumented_wall_is_production_latency'] is False
             and a['training_timing_is_order_randomized'] is False,
             'operator profile changed original learned parameters, route, or data budget')
        for col in ('observer_cpu_process_ns','observer_wall_ns','registered_aten_flops_partial_only',
                    'recorded_operator_types'):
            need(_positive_int(a[col]),'physical CPU operator duration / partial FLOPs missing')
        for col in ('recorded_route_kernel_calls','recorded_autograd_function_nodes'):
            need(_nonnegative_int(a[col]),'invalid route or autograd function census')
        for col in ('registered_aten_self_cpu_us','registered_flop_covered_self_cpu_us'):
            need(_nonnegative_float(a[col]),'nonfinite self CPU operator timing')
        need(a['registered_aten_self_cpu_us']>0
             and a['registered_flop_covered_self_cpu_us'] <= a['registered_aten_self_cpu_us']+1e-3,
             'unsupported complete CPU attribution claim')
        op=a['operator_census']
        need(type(op) is dict and 5 <= len(op) <= 256 and len(op)==a['recorded_operator_types'],
             'physical profiler op rows incomplete')
        need('aten::mm' in op and 'aten::index_select' in op,
             'not actually physically profiling selected Head matmuls')
        if name!='frozen_single':
            need('autograd::engine::evaluate_function: MmBackward0' in op
                 and ('aten::_foreach_add_' in op or 'aten::add_' in op)
                 and a['recorded_autograd_function_nodes']>=40,
                 'missing physically profiled backward and optimizer updates')
        else:
            need(a['recorded_autograd_function_nodes']==0,'frozen Head cannot backpropagate')
        sum_flops=0;sum_us=0.;covered_us=0.;sum_autograd=0
        for key,metric in op.items():
            need(type(key) is str and 1 <= len(key) <= 180
                 and type(metric) is dict and set(metric)=={
                   'calls','partial_estimated_flops','self_cpu_time_us'}
                 and _positive_int(metric['calls'])
                 and _nonnegative_int(metric['partial_estimated_flops'])
                 and _nonnegative_float(metric['self_cpu_time_us']),
                 'malformed or invented ATen operator rows')
            sum_flops+=metric['partial_estimated_flops'];sum_us+=metric['self_cpu_time_us']
            if metric['partial_estimated_flops']:covered_us+=metric['self_cpu_time_us']
            if key.startswith('autograd::engine::evaluate_function:'):sum_autograd+=metric['calls']
        expected_routes=sum(op.get(k,{}).get('calls',0)
                            for k in ('aten::ge','aten::nonzero','aten::index_select','aten::index_copy'))
        need(sum_flops==a['registered_aten_flops_partial_only']
             and abs(sum_us-a['registered_aten_self_cpu_us']) <= max(1e-3,1e-8*sum_us)
             and abs(covered_us-a['registered_flop_covered_self_cpu_us']) <= max(1e-3,1e-8*covered_us)
             and sum_autograd==a['recorded_autograd_function_nodes']
             and expected_routes==a['recorded_route_kernel_calls'],
             'resealed operator accounting is arithmetically inconsistent')
        need(sum_flops >= 2*a['registered_expert_forward_linear_mac'],
             'matmul profiler did not observe even the registered training forward work')
        results[name]={
            'prelabel_replay_model_byte_identity':True,
            'registered_partial_cpu_profiler_flops':sum_flops,
            'observed_selected_head_forward_rows':sum(a['train_selected_expert_forward_rows']),
            'backward_autograd_function_events':sum_autograd,
            'recorded_router_or_index_ops':expected_routes,
            'instrumented_wall_ns':a['observer_wall_ns'],
            'instrumented_process_cpu_ns':a['observer_cpu_process_ns'],
            'cost_flop_annotation_time_fraction':covered_us/sum_us,
            'cost_total_forward_backward_verified':False,
            'complete_total_compute_matched':False,
        }
    baseline=results['single_active']
    for arm,r in results.items():
        r['partial_aten_flop_ratio_vs_single_active']=r['registered_partial_cpu_profiler_flops']/baseline['registered_partial_cpu_profiler_flops']
        r['instrumented_wall_ratio_vs_single_active_descriptive_only']=r['instrumented_wall_ns']/baseline['instrumented_wall_ns']
    return {
        'schema':SCORE,
        'cost_profile_source_sha256':trace['report_sha256'],
        'original_independent_score_source_sha256':parent_score['report_sha256'] if 'report_sha256' in parent_score else old_trained['report_sha256'],
        'source_case_count':96,'train_source_count':128,
        'observed_model_encode_forward_count':224,
        'arms':results,
        'all_accuracy_and_brier_rescored_from_original_human_labels':True,
        'previous_p2_training_quality_claims_unchanged':True,
        'source_groups_are_not_prospective':True,
        'producer_cpu_profile_is_not_independent_hardware_attestation':True,
        'profilers_report_partial_flops_only':True,
        'same_forward_expert_rows_is_not_full_equal_training_compute':True,
        'complete_cost_and_energy_certified':False,
        'production_promotion_permitted':False,
        'authority':'DENY_ALL',
    }


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    for k in ('original-panel','train-material','blind-material','owner-labels',
              'original-p2-report','original-trained-top1-report','cost-report','output'):
        parser.add_argument('--'+k,required=True)
    args=parser.parse_args()
    out=Path(args.output)
    need(not out.exists(),'create-only independent cost review required')
    output=review(read(args.original_panel),read(args.train_material),read(args.blind_material),
                  read(args.owner_labels),read(args.original_p2_report),
                  read(args.original_trained_top1_report),read(args.cost_report))
    with out.open('x',encoding='utf-8') as f:
        json.dump(output,f,sort_keys=True,allow_nan=False)
        f.write('\n')

if __name__=='__main__':main()
