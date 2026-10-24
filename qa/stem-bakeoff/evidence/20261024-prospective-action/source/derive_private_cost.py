"""Read-only cost derivation from the authenticated prospective preparation."""
import argparse
from collections import defaultdict
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys
import time

import numpy as np

SOURCE = Path('/workspace/scratch/f1f83ab8f2f0/hepta/qa/stem-bakeoff')
sys.path.insert(0, str(SOURCE))
from cell_learning_models import NumpyCellHead, canonical
from prospective_action_learning_run import verify_preparation

EXPECTED_REPORT = '77fac73c27874c1f4a81a574edd4c34054d437510d246fb8a3f5628c00f97e00'
EXPECTED_SEAL = 'aef77ab22412c73a7c31da6aa5d2b6340d9c13363904a59b32d468089eb5a725'
MODES = ('linear', 'gated', 'residual')
PREDICTION_SCALARS = ('alpha', 'prior_positive', 'mixture_weight', 'training_log_odds')
VALIDATOR_NUMERIC = PREDICTION_SCALARS + ('prior_strength', 'effective_training_prior',
                                        'group_weighted_class_mass', 'prior')


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def stats(values):
    return {'count': len(values), 'minimum': min(values), 'maximum': max(values), 'sum': sum(values)}


def derive(root, output):
    began, cpu = time.perf_counter_ns(), time.process_time_ns()
    root, output = Path(root).resolve(), Path(output).resolve()
    if output.is_relative_to(root) or output.exists():
        raise ValueError('new output outside the immutable preparation required')
    pins = {root/'report.json': EXPECTED_REPORT, root/'seal.json': EXPECTED_SEAL,
            Path(__file__).resolve(): sha(__file__)}
    if any(sha(p) != value for p, value in pins.items()):
        raise ValueError('unexpected preparation pin')
    report = verify_preparation(root)
    seal = json.loads((root/'seal.json').read_bytes())
    for path, entry in seal['files'].items():
        pins[root/path] = entry['sha256']
    groups, condition_reports, baseline_runs = defaultdict(list), [], []
    all_sources, selected_sources, selected_groups = {}, set(), set()
    development_sources, development_groups = set(), set()
    role_sources, role_groups = defaultdict(set), defaultdict(set)
    contexts_by_condition = {}
    all_paths, all_cal_records, frozen_bytes, child_seal_bytes, child_plan_bytes = [], [], 0, 0, 0
    for condition in report['conditions']:
        child = Path(condition['prepared_dir'])
        frozen = json.loads((child/'frozen.json').read_bytes())
        plan, runs = frozen['plan'], frozen['runs']
        width = plan['width']
        contexts_by_condition[condition['name']] = plan['contexts']
        for role, context in plan['contexts'].items():
            development_sources.update(context['source_ids'])
            development_groups.update(context['group_ids'])
            role_sources[role].update(context['source_ids'])
            role_groups[role].update(context['group_ids'])
        for name, digest in plan['code_sha256'].items():
            path = SOURCE/name
            if path in pins and pins[path] != digest:
                raise ValueError('conflicting source pin')
            pins[path] = digest
        frozen_bytes += (child/'frozen.json').stat().st_size
        child_seal_bytes += (child/'seal.json').stat().st_size
        child_plan_bytes += (child/'plan.json').stat().st_size
        paths, local_sources, local_groups, gradient_draws = [], set(), set(), []
        for run in runs:
            key = {'condition': condition['name'], 'seed': run['seed'], 'budget': run['budget']}
            paths.extend(run['search_paths'])
            if sum(p['optimizer_steps'] for p in run['search_paths']) != run['all_search_optimizer_steps']:
                raise ValueError('optimizer aggregation differs')
            if sum(p['executed_dense_matmul_flops'] for p in run['search_paths']) != run['all_search_matmul_flops']:
                raise ValueError('matrix FLOP aggregation differs')
            local_sources.update(run['training_source_ids'])
            local_groups.update(run['training_group_ids'])
            gradient_draws.append({**key, 'rows': run['training_rows'], 'independent_groups': run['training_groups'],
                                   'class_counts': run['training_class_counts']})
            for mode in MODES:
                arm = run['arms'][mode]
                directory = child/arm['artifact']
                head = NumpyCellHead.load(directory, condition['feature_identity'])
                manifest = json.loads((directory/'manifest.json').read_bytes())
                arrays = {k: {'dtype': str(a.dtype), 'shape': list(a.shape), 'scalars': int(a.size),
                              'bytes': int(a.nbytes)} for k, a in head.params.items()}
                count, raw_bytes = sum(v['scalars'] for v in arrays.values()), sum(v['bytes'] for v in arrays.values())
                if (count != arm['trainable_parameters'] or raw_bytes != arm['training']['parameter_bytes']
                        or head.digest() != arm['tensor_sha256'] or manifest['normalization'] != 'l2_times_sqrt_width'):
                    raise ValueError('saved array, manifest or declared parameter count differs')
                fit = arm['calibration']
                if fit['stored_prediction_scalars'] != 4:
                    raise ValueError('prediction-state contract changed')
                numeric_count = sum(np.asarray(fit[k]).size for k in VALIDATOR_NUMERIC)
                if numeric_count != 11 or not all(np.asarray(fit[k]).dtype.kind in 'fiu' for k in VALIDATOR_NUMERIC):
                    raise ValueError('validator numeric-state contract changed')
                groups[(width, mode)].append({'condition': condition['name'], 'key': run['directory'],
                    'arrays': arrays, 'parameters': count, 'parameter_bytes': raw_bytes,
                    'weights_npz_bytes': (directory/'weights.npz').stat().st_size,
                    'manifest_json_bytes': (directory/'manifest.json').stat().st_size,
                    'embedded_calibration_json_value_bytes': len(canonical(fit)),
                    'optimizer_state_bytes': arm['training']['optimizer_state_bytes'],
                    'gradient_bytes': arm['training']['gradient_bytes'],
                    'checkpoint_buffer_bytes': arm['training']['checkpoint_buffer_bytes']})
                all_cal_records.append(fit)
            bankdir = child/run['directory']
            rows = json.loads((bankdir/'baseline_rows.json').read_bytes())
            with np.load(bankdir/'baseline.npz', allow_pickle=False) as bank:
                if set(bank.files) != {'features', 'labels'} or bank['features'].dtype != np.float32 or bank['labels'].dtype != np.int64:
                    raise ValueError('unexpected baseline-bank dtype or arrays')
                bank_arrays = {k: {'dtype': str(bank[k].dtype), 'shape': list(bank[k].shape),
                                   'bytes': int(bank[k].nbytes)} for k in bank.files}
            if [r['source_id'] for r in rows] != run['training_source_ids']:
                raise ValueError('baseline bank source order differs')
            for row in rows:
                old = all_sources.setdefault(row['source_id'], row)
                if old != row:
                    raise ValueError('one source identity has inconsistent public content')
            baseline_runs.append({**key, 'arrays': bank_arrays,
                'npz_bytes': (bankdir/'baseline.npz').stat().st_size,
                'public_source_json_bytes': (bankdir/'baseline_rows.json').stat().st_size,
                'source_text_utf8_bytes': sum(len(r['text'].encode()) for r in rows),
                'retained_state_as_reported': run['baseline_retained_state']})
        all_paths.extend(paths)
        selected_sources.update(local_sources)
        selected_groups.update(local_groups)
        pools = plan['labelled_pools']
        condition_reports.append({'name': condition['name'], 'feature_identity': condition['feature_identity'],
            'input_bindings': plan['input_bindings'], 'width': width, 'task_id': plan['task_id'],
            'family_id': plan['family_id'], 'repeated_runs': len(runs), 'saved_learned_heads': 3*len(runs),
            'labelled_pools': pools, 'all_role_counts_from_sealed_preparation': condition['counts']['by_role'],
            'all_project_counts_from_sealed_preparation': condition['counts']['by_project'],
            'distinct_usable_development_labels': sum(p['rows'] for p in pools.values()),
            'distinct_usable_development_groups': sum(p['groups'] for p in pools.values()),
            'selected_gradient_source_union': len(local_sources), 'selected_gradient_group_union': len(local_groups),
            'gradient_draws': gradient_draws, 'unavailable': frozen['unavailable'],
            'search_paths': len(paths), 'optimizer_steps': sum(p['optimizer_steps'] for p in paths),
            'example_updates': sum(p['example_updates'] for p in paths),
            'dense_matmul_flops': sum(p['executed_dense_matmul_flops'] for p in paths),
            'estimated_elementwise_flops': sum(p['estimated_elementwise_flops'] for p in paths),
            'search_path_wall_ns': sum(p['wall_ns'] for p in paths),
            'search_path_cpu_ns': sum(p['cpu_ns'] for p in paths),
            'inclusive_preparation_wall_ns': frozen['wall_ns'], 'inclusive_preparation_cpu_ns': frozen['cpu_ns']})
    head_table = []
    for (width, mode), records in sorted(groups.items()):
        first = records[0]
        if any(r['arrays'] != first['arrays'] for r in records):
            raise ValueError('same-shape head inventory is not uniform')
        head_table.append({'width': width, 'mode': mode, 'rank': 4 if mode == 'residual' else None,
            'head_count': len(records), 'arrays': first['arrays'], 'trainable_parameters_per_head': first['parameters'],
            'fp64_parameter_bytes_per_head': first['parameter_bytes'],
            **{key: stats([r[key] for r in records]) for key in ('weights_npz_bytes', 'manifest_json_bytes',
                'embedded_calibration_json_value_bytes', 'optimizer_state_bytes', 'gradient_bytes', 'checkpoint_buffer_bytes')}})
    files = list(seal['files'].values()) + [{'bytes': (root/'seal.json').stat().st_size}]
    nheads = sum(len(v) for v in groups.values())
    head_npz = sum(r['weights_npz_bytes'] for rs in groups.values() for r in rs)
    head_manifests = sum(r['manifest_json_bytes'] for rs in groups.values() for r in rs)
    baseline_npz = sum(r['npz_bytes'] for r in baseline_runs)
    baseline_json = sum(r['public_source_json_bytes'] for r in baseline_runs)
    partition = {'head_compressed_npz': head_npz, 'head_manifests': head_manifests,
        'shared_per_run_baseline_npz': baseline_npz, 'shared_per_run_source_json': baseline_json,
        'child_frozen_reports_including_embedded_calibrators': frozen_bytes, 'child_plans': child_plan_bytes,
        'child_seals': child_seal_bytes,
        'global_plan_report_seal': sum((root/f).stat().st_size for f in ('plan.json', 'report.json', 'seal.json'))}
    total_bytes = sum(f['bytes'] for f in files)
    if sum(partition.values()) != total_bytes or (len(all_paths), nheads) != (162, 81):
        raise ValueError('artifact partition or frozen study count differs')
    for name, contexts in contexts_by_condition.items():
        for role, context in contexts.items():
            native = contexts_by_condition['granite_clean_field770'][role]
            if not set(context['source_ids']) <= set(native['source_ids']) or not set(context['group_ids']) <= set(native['group_ids']):
                raise ValueError('identifier-pool subset claim differs')
    if (sum(map(len, role_sources.values())) != len(development_sources)
            or sum(map(len, role_groups.values())) != len(development_groups)):
        raise ValueError('development roles overlap')
    result = {'schema': 'hepta.prospective-private-cost-supplement.v1', 'created_at': datetime.now(timezone.utc).isoformat(),
        'derivation': 'read actual saved arrays, manifests and authenticated preparation records; no fit, prediction or outcome scoring',
        'quality_qualified': False, 'preparation_root': str(root),
        'preparation_report_sha256': EXPECTED_REPORT, 'preparation_seal_sha256': EXPECTED_SEAL,
        'helper_path': str(Path(__file__).resolve()), 'helper_sha256': sha(__file__),
        'units': {'logical_task_definitions': 1, 'task_families': 1, 'feature_conditions': 3,
            'gradient_budgets': [8, 32, 64], 'fixed_seeds': [7, 17, 29], 'repeated_runs': 27,
            'retained_learned_heads': nheads, 'hyperparameter_search_paths': len(all_paths),
            'independent_tasks_are_not_runs_seeds_or_heads': True},
        'head_table': head_table, 'trainable_parameters_all_saved_heads': sum(r['parameters'] for rs in groups.values() for r in rs),
        'fp64_trainable_tensor_bytes_all_saved_heads': sum(r['parameter_bytes'] for rs in groups.values() for r in rs),
        'normalization': {'method': 'stateless per-row L2 * sqrt(width)', 'persisted_scalars_per_head': 0,
            'persisted_arrays_per_head': 0, 'learned_training_mean_or_scale': False,
            'runtime_conversion': 'FP32 source features are converted to FP64; input normalization work/buffers are not persistent model state'},
        'calibration': {'prediction_float64_scalars': list(PREDICTION_SCALARS), 'prediction_scalars_per_head': 4,
            'prediction_packed_fp64_equivalent_bytes_per_head': 32,
            'validator_numeric_fields_including_prediction_state': list(VALIDATOR_NUMERIC)+['calibration_groups'],
            'validator_float64_equivalent_scalars': 11, 'validator_int64_equivalent_scalars': 1,
            'validator_packed_numeric_equivalent_bytes_per_head': 96,
            'additional_required_metadata': ['schema', 'mode', 'bindings: feature/predictor/calibration-context SHA256'],
            'actual_storage': 'full diagnostic calibration object embedded in each arm of child frozen.json; no separate calibration tensor file',
            'packed_bytes_are_not_measured_python_heap_or_serialized_bytes': True,
            'learned_head_embedded_canonical_json_value_bytes': stats([len(canonical(f)) for f in all_cal_records]),
            'embedded_json_bytes_already_in_frozen_reports_do_not_add_again': True,
            'all_arms_have_private_calibrators_except_prior_fit_reused_once_per_condition': True},
        'baseline_retention': {'sharing': 'one saved bank and public source-row file per seed/budget run, shared by exact/BM25/dense-nearest/prototype; not copied per learned head',
            'saved_banks': len(baseline_runs), 'bank_input_features': 'FP32', 'bank_labels': 'int64',
            'prototype_scalars_per_run': '2 * feature width; non-gradient fitted state reconstructed from shared bank',
            'runtime_component_sizes': 'copied from preparation; lexical+numeric reachable-state estimates can double-count shared Python metadata and are not measured RSS',
            'rows': baseline_runs, 'summed_source_text_utf8_bytes': sum(r['source_text_utf8_bytes'] for r in baseline_runs),
            'unique_selected_source_rows': len(all_sources),
            'unique_selected_source_utf8_bytes': sum(len(r['text'].encode()) for r in all_sources.values())},
        'serialized_preparation': {'files': len(files), 'bytes': total_bytes, 'disjoint_byte_partition': partition,
            'compression_means_npz_bytes_differ_from_raw_tensor_bytes': True,
            'source_feature_owners_and_global_feature_archives_not_inside_this_private_preparation_total': True},
        'training_compute': {'actual_optimizer_steps_all_paths': sum(p['optimizer_steps'] for p in all_paths),
            'example_updates_all_paths': sum(p['example_updates'] for p in all_paths),
            'selected_checkpoint_steps_all_paths': sum(p['selected_checkpoint_step'] for p in all_paths),
            'discarded_updates_all_paths': sum(p['discarded_updates_after_selected'] for p in all_paths),
            'executed_dense_matmul_flops_all_paths': sum(p['executed_dense_matmul_flops'] for p in all_paths),
            'estimated_elementwise_flops_all_paths': sum(p['estimated_elementwise_flops'] for p in all_paths),
            'flop_scope': 'two scalar operations per multiply-add for executed train forward/backward products, tuning checkpoint forwards and selected-head final training forward; excludes calibration/inference forwards, Encoder work, lexical work, normalization, I/O and transcendental cost',
            'elementwise_count_is_formula_estimate_not_measured_total_flops': True,
            'adam_state_bytes_per_path': '2 * raw parameter bytes; discarded after fitting, not in saved weights',
            'gradient_and_checkpoint_bytes_per_path': 'one raw parameter-sized buffer each',
            'reported_persistent_tensor_bytes_per_path': '5 * raw parameter bytes + FP64 normalized train/tuning inputs; excludes Python heap, transient arrays, other simultaneously retained candidates and process RSS',
            'common_parameter_ceiling': 100000, 'equal_ceiling_or_steps_do_not_imply_equal_cost': True,
            'global_preparation_wall_ns': report['wall_ns'], 'global_preparation_cpu_ns': report['cpu_ns'],
            'global_wall_cpu_include_nested_paths_do_not_add_nested_timers_again': True},
        'label_budget': {'conditions': condition_reports,
            'scope': '8/32/64 distinct-bug gradient examples are selected using the whole available labelled TRAIN pool; tuning and calibration use separate full eligible pools, each bug total weight1',
            'same_source_labels_reused_across_conditions_seeds_budgets_not_new_annotations': True,
            'unique_development_usable_label_union': len(development_sources),
            'unique_development_usable_bug_union': len(development_groups),
            'union_rationale': 'both identifier usable pools are subsets of Granite: train313/77 + tuning130/32 + calibration152/44',
            'selected_gradient_union_sources': len(selected_sources), 'selected_gradient_union_groups': len(selected_groups),
            'holdout_counts_copied_from_preparation_availability_metadata_only': True,
            'holdout_labels_supplied_to_train_tune_cal_fit_functions': False,
            'unknown_outcomes_are_not_negative_labels': True},
        'verification': {'all81_saved_head_arrays_loaded_and_digest_checked': True,
            'all27_bank_arrays_and_source_orders_read': True, 'strict_global_preparation_verified_before_and_after': True}}
    verify_preparation(root)
    if any(sha(p) != digest for p, digest in pins.items()):
        raise ValueError('input or numerical source mutated during read-only derivation')
    result['verification']['bound_source_sha256'] = {str(p): d for p, d in pins.items() if p.parent == SOURCE}
    result['derivation_cost'] = {'wall_ns': time.perf_counter_ns()-began, 'cpu_ns': time.process_time_ns()-cpu,
                                 'not_included_in_training_timings': True}
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open('xb') as stream:
        stream.write(canonical(result)+b'\n')
    print(json.dumps({'path': str(output), 'sha256': sha(output), 'bytes': output.stat().st_size,
                      'heads': nheads, 'head_table': [{k: r[k] for k in ('width','mode','head_count','trainable_parameters_per_head','fp64_parameter_bytes_per_head')} for r in head_table],
                      'serialized_preparation': result['serialized_preparation'], 'derivation_cost': result['derivation_cost']}))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--preparation', required=True)
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    derive(args.preparation, args.output)
