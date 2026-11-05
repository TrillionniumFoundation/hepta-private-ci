#!/usr/bin/env python3
"""Read-only aggregation of bound, already-recorded training probabilities.

Run on Pocket4 with standard Python only. Raw rows, IDs and probabilities never
leave this process. This program does not import the training modules or Torch.
"""
import datetime
import hashlib
import importlib.util
import json
import math
from pathlib import Path
import resource
import sys
import time

sys.dont_write_bytecode = True
HELPER = Path('/home/alex/.local/state/hepta-wsp/20261105-fullencoder-db06eb2f/head_probe_helpers.py')
HELPER_SHA = 'dee2de37754edbebdc2c80b7ff1796ae8575d7e6d58c70ed4cd8267362f34f6c'
SOURCES = {
    'resident_train.py': 'cfea96538a918048fa76e6e117f08e932968aca9cf0ef93f4139031bd2bb745d',
    'resident_price_calibration_v3.py': '623e2e871644d6f68efaba91e331150da0a453b557155aec4665b21b28dd0a96',
    'resident_price_input.py': '6f0f08807f00270da381e7fbc0add6f48d19636528de23382556e2c58f396d62',
    'resident_price_calibration.py': 'e4a83db996d36c5079691c6dc273de8097f58264f8b1b6c7f1361f49fa421bf1',
    'resident_price_baselines.py': 'e6b3938326db59804fe794034c6e632c823c91788c16c51710538c8bb687d06e',
}
RAW_PROFILE = 'LEGACY_RAW_CAUSAL_QUOTES_V1'
REPORTED_TOLERANCE = 1e-6


def require(ok, reason):
    if not ok:
        raise ValueError(reason)


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()


def aggregate(receipts, targets):
    ce, brier, hits, errors = [], [], 0, []
    for row in receipts:
        probabilities = row['raw_probs']
        require(isinstance(probabilities, list) and len(probabilities) == 7 and
                all(type(p) in (int, float) and math.isfinite(p) and 0 <= p <= 1 for p in probabilities),
                'RECORDED_PROBABILITY_DOMAIN')
        mass_error = abs(math.fsum(probabilities) - 1)
        require(mass_error <= 1e-5, 'RECORDED_PROBABILITY_NORMALIZATION')
        target = targets[row['training_row_id']]
        require(probabilities[target] > 0, 'ZERO_TRUE_CLASS_PROBABILITY')
        ce.append(-math.log(probabilities[target]))
        brier.append(math.fsum((p - int(index == target)) ** 2
                              for index, p in enumerate(probabilities)))
        hits += int(max(range(7), key=lambda index: probabilities[index]) == target)
        errors.append(mass_error)
    return {'mean_nll_from_stored_raw_probabilities': math.fsum(ce) / len(receipts),
            'mean_multiclass_brier': math.fsum(brier) / len(receipts),
            'hits_argmax_first_index_tie_break': hits,
            'max_probability_sum_error': max(errors)}


def audit():
    began, cpu = time.monotonic(), time.process_time()
    resource.setrlimit(resource.RLIMIT_CPU, (5, 6))
    resource.setrlimit(resource.RLIMIT_AS, (192 * 1024**2, 192 * 1024**2))
    result = {'schema': 'hepta.wsp.bound_training_metric_audit.v1',
              'started_utc': datetime.datetime.now(datetime.timezone.utc).isoformat(),
              'status': 'STARTED', 'source_receipts_only': True,
              'new_training_executed': False, 'new_model_forwards': 0,
              'evaluator_started': False, 'production_modified': False,
              'raw_row_ids_exported': False, 'raw_probabilities_exported': False,
              'training_only': True, 'held_out': False, 'future_value_proven': False,
              'labels_independently_checked_against_dataset': False,
              'reported_metric_absolute_tolerance': REPORTED_TOLERANCE}
    try:
        require(sha(HELPER.read_bytes()) == HELPER_SHA, 'HELPER_IDENTITY')
        spec = importlib.util.spec_from_file_location('bound_metric_helper', HELPER)
        helper = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(helper)
        config, job, binding = helper.bound_live()
        source_root = Path(config['runtime_directory']) / 'learn/laya_cell'
        before_sources = {name: sha(helper.read(source_root / name, 65536)) for name in SOURCES}
        require(before_sources == SOURCES, 'METRIC_SOURCE_IDENTITY')
        candidate_path = Path(job['output_directory']) / 'candidate.json'
        parent_path = Path(job['parent_directory']) / 'candidate.json'
        candidate_raw, parent_raw = helper.read(candidate_path, 524288), helper.read(parent_path, 524288)
        candidate, parent = helper.unique_json(candidate_raw), helper.unique_json(parent_raw)
        require(candidate['candidate_id'] == helper.EXPECTED['candidate_id'] ==
                sha(canonical({k: v for k, v in candidate.items() if k != 'candidate_id'})),
                'CANDIDATE_CONTENT_ID')
        require(parent['candidate_id'] == candidate['parent_id'] ==
                sha(canonical({k: v for k, v in parent.items() if k != 'candidate_id'})),
                'PARENT_CONTENT_ID')
        require(sha(parent_raw) == job['parent_manifest_sha256'], 'PARENT_JOB_BINDING')
        require(candidate['base_id'] == parent['base_id'] == helper.EXPECTED['base_id'], 'BASE_ID_BINDING')
        for record, directory, expected in (
                (candidate, job['output_directory'], helper.EXPECTED['adapter_sha256']),
                (parent, job['parent_directory'], helper.EXPECTED['parent_adapter_sha256'])):
            require(sha(helper.read(Path(directory) / 'adapter.safetensors', 1048576)) ==
                    record['adapter_sha256'] == expected, 'ADAPTER_BINDING')
        child_rows = candidate['final_price_raw_forward_receipts']
        parent_rows = candidate['parent_price_forward_receipts']
        measurement = candidate['measurement']
        require(len(child_rows) == len(parent_rows) == measurement['rows'] == 32 and
                measurement['training_only'] is True, 'TRAINING_POPULATION_SIZE')
        children = {row['training_row_id']: row for row in child_rows}
        parents = {row['training_row_id']: row for row in parent_rows}
        require(len(children) == len(parents) == 32 and set(children) == set(parents) ==
                set(job['training_row_ids']) == set(candidate['row_accounting']['measurement_row_ids']),
                'TRAINING_POPULATION_IDENTITY')
        targets = {identity: row['target_class'] for identity, row in children.items()}
        require(all(type(target) is int and 0 <= target < 7 for target in targets.values()), 'TARGET_DOMAIN')
        require(candidate['price_input_profile'] == candidate['parent_price_input_profile'] == RAW_PROFILE and
                all(row['price_input_profile'] == RAW_PROFILE for row in child_rows + parent_rows),
                'RAW_INPUT_SCOPE_REQUIRED')
        require(all(children[identity]['price_input_id'] == parents[identity]['price_input_id']
                    for identity in children), 'PARENT_CHILD_INPUT_IDENTITY')
        require(candidate['price_calibration']['real_target_class_counts'] ==
                [sum(target == k for target in targets.values()) for k in range(7)],
                'RECORDED_LABEL_COUNT_CONSISTENCY')
        result['identity'] = {'candidate_id': candidate['candidate_id'], 'parent_id': parent['candidate_id'],
                              'candidate_manifest_sha256': sha(candidate_raw), 'parent_manifest_sha256': sha(parent_raw),
                              'base_id': candidate['base_id'], 'adapter_sha256': candidate['adapter_sha256'],
                              'parent_adapter_sha256': parent['adapter_sha256'], 'binding': binding,
                              'source_sha256': before_sources, 'helper_sha256': HELPER_SHA}
        result['population'] = {'rows': 32, 'classes': 7, 'unique_ids_verified': True,
                                'same_parent_child_row_set_and_input_ids': True,
                                'raw_price_input_profile': RAW_PROFILE,
                                'labels_source': 'BOUND_FINAL_PRICE_RAW_FORWARD_RECEIPTS'}
        metrics = {'parent': aggregate(parent_rows, targets), 'candidate': aggregate(child_rows, targets)}
        uniform = {'mean_nll': math.log(7), 'mean_multiclass_brier': 6 / 7,
                   'parameters_edited': 0, 'training_steps': 0, 'model_forwards': 0,
                   'source': 'EXACT_SEVEN_CLASS_UNIFORM_DISTRIBUTION_MATH'}
        result['independently_reaggregated_raw_metrics'] = metrics
        result['uniform_zero_edit_control'] = uniform
        reported = {'parent': {'ce': measurement['parent_ce'], 'brier': measurement['parent_brier']},
                    'candidate': {'ce': measurement['candidate_ce'], 'brier': measurement['candidate_brier']}}
        consistent = True
        for name in ('parent', 'candidate'):
            report = reported[name]
            report['ce_minus_reaggregated_nll'] = report['ce'] - metrics[name]['mean_nll_from_stored_raw_probabilities']
            report['brier_minus_reaggregated'] = report['brier'] - metrics[name]['mean_multiclass_brier']
            report['within_declared_absolute_tolerance'] = (
                abs(report['ce_minus_reaggregated_nll']) <= REPORTED_TOLERANCE and
                abs(report['brier_minus_reaggregated']) <= REPORTED_TOLERANCE)
            consistent = consistent and report['within_declared_absolute_tolerance']
        result['reported_training_measurement_comparison'] = reported
        result['raw_metric_difference_vs_uniform'] = {
            name: {'nll_minus_uniform': metric['mean_nll_from_stored_raw_probabilities'] - uniform['mean_nll'],
                   'brier_minus_uniform': metric['mean_multiclass_brier'] - uniform['mean_multiclass_brier']}
            for name, metric in metrics.items()}
        result['candidate_minus_parent_raw_metrics'] = {
            'nll': metrics['candidate']['mean_nll_from_stored_raw_probabilities'] -
                   metrics['parent']['mean_nll_from_stored_raw_probabilities'],
            'brier': metrics['candidate']['mean_multiclass_brier'] - metrics['parent']['mean_multiclass_brier']}
        recorded_calibration = candidate['price_calibration_training_measurement']
        scalar_fields = ('training_only', 'held_out', 'future_value_proven', 'rows',
                         'additional_independent_rows', 'model_weight', 'exact_prior_fallback', 'fit_objective')
        calibration = {key: recorded_calibration[key] for key in scalar_fields if key in recorded_calibration}
        calibration['models'] = {
            name: {key: values[key] for key in ('mean_brier', 'mean_nll', 'hits') if key in values}
            for name, values in recorded_calibration['models'].items()
            if name in ('raw_child', 'calibrated_child', 'train_prior', 'uniform')}
        require(calibration['training_only'] is True and calibration['held_out'] is False and
                calibration['future_value_proven'] is False and calibration['rows'] == 32,
                'RECORDED_CALIBRATION_SCOPE')
        result['recorded_calibration_aggregate_not_independently_recomputed'] = calibration
        result['recorded_calibration_output_profile'] = candidate['price_output_profile']
        require(helper.bound_live()[2] == binding, 'LIVE_BINDING_CHANGED')
        require(helper.read(candidate_path, 524288) == candidate_raw and
                helper.read(parent_path, 524288) == parent_raw, 'MANIFEST_CHANGED')
        require({name: sha(helper.read(source_root / name, 65536)) for name in SOURCES} == before_sources,
                'METRIC_SOURCE_CHANGED')
        require('torch' not in sys.modules, 'TORCH_IMPORTED')
        result.update(status='PASS_RECORDED_RAW_METRIC_AUDIT' if consistent else 'REPORTED_METRIC_MISMATCH_PRESERVED',
                      source_and_live_binding_unchanged=True, raw_metric_reaggregation_consistent=consistent,
                      calibrated_metrics_independently_recomputed=False,
                      uniform_comparison_scope='SAME_32_TRAINING_ROWS_ONLY_NOT_OUT_OF_SAMPLE_OR_PNL',
                      arithmetic_note='Stored float32 softmax probabilities are scored in Python float64; original CE used float32 cross_entropy logits.')
    except Exception as error:
        code = str(error)
        result.update(status='FAILED_PRESERVED', failure_type=type(error).__name__,
                      failure_code=code if code.isupper() and code.replace('_', '').isalnum() and len(code) < 100
                      else 'REDACTED_EXCEPTION')
    result['cost'] = {'wall_seconds': time.monotonic() - began, 'cpu_seconds': time.process_time() - cpu,
                      'peak_rss_bytes': resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024}
    result['finished_utc'] = datetime.datetime.now(datetime.timezone.utc).isoformat()
    print(json.dumps(result, sort_keys=True, allow_nan=False))
    return 0 if result['status'] == 'PASS_RECORDED_RAW_METRIC_AUDIT' else 2


if __name__ == '__main__':
    raise SystemExit(audit())
