"""Independent final execution/qualification accounting; report-only, no native calls."""

import argparse
from datetime import datetime, timezone
import gzip
import json
from pathlib import Path
import time
import traceback

import numpy as np

from . import review_feedback_evidence as e


def training_cost(root, seed, review):
    path = root / 'feedback_prepared' / f'seed_{seed}'
    receipt = e.read_json(path / 'TRAINING_RECEIPT.json')
    model = e.read_json(path / 'MODELS.json')
    with gzip.open(path / 'TRAINING_ROWS.json.gz', 'rt') as stream:
        rows = json.load(stream)
    review.require(set(rows) == {'train', 'development'} and receipt['seed'] == seed
        and not receipt['prior_confirmation_used'] and receipt['model_sha256'] == e.file_hash(path / 'MODELS.json')
        and receipt['model_document_sha256'] == e.digest(model), 'training', 'frozen training receipt/model binding')
    calls = ticks = ipc = forecasts = 0
    for split, file, count in (('train', 'TRAIN.npz', receipt['train_rows']), ('development', 'DEVELOPMENT.npz', receipt['development_rows'])):
        data = e.arrays(path / file)
        review.require(len(rows[split]) == len(data['ids']) == count and data['split'] == split
            and [r['case'] for r in rows[split]] == data['ids'].tolist(), 'training', 'unique complete supervised split')
        for row in rows[split]:
            review.require(len(row['stages']) == 2, 'training', 'complete supervised two-stage paths')
            for stage in row['stages']:
                forecasts += 1
                native = stage['runtime']['native']
                review.require(native['native_binary_sha256'] == model['native_binary_sha256']
                    and native['original_neuron_runtime'] and native['typed_model_port'] and native['authority'] == 'DENY_ALL',
                    'training', 'actual typed training execution')
                calls += 1; ticks += 1; ipc += native['subprocess_roundtrip_ns']
                review.require(set(stage['native']) == set(model['heads']) == {'numeric', 'analytic', 'history', 'zero', 'reset'},
                               'training', 'same available shared observations and five fitted heads')
                for arm, channels in stage['native'].items():
                    review.require(len(channels) == (0 if arm == 'history' else 3), 'training', 'matched sparse feature channels')
                    for channel in channels:
                        review.require(channel['original_sparse_tick_calls'] == len(channel['ticks']) == 2
                            and channel['native_binary_sha256'] == model['native_binary_sha256'], 'training', 'actual native training pair')
                        calls += 1; ticks += len(channel['ticks']); ipc += channel['subprocess_roundtrip_ns']
    review.require(receipt['native'] == {'requests': calls, 'ticks': ticks, 'roundtrip_ns': ipc}
        and forecasts == 2 * (receipt['train_rows'] + receipt['development_rows']), 'accounting', 'all training native requests/ticks/IPC')
    fits = candidates = iterations = 0
    for arm, head in receipt['heads'].items():
        table = head['candidates']
        review.require(len(table) == 15 and sorted(set(x['l2'] for x in table)) == [.001, .01, .1]
            and head['parameter_l2_change'] > 0 and head['selected_weights_sha256'] == e.digest(model['heads'][arm]['weights']),
            'training', 'real optimized and frozen selected parameters')
        for strength in (.001, .01, .1):
            group = [x for x in table if x['l2'] == strength]
            review.require(len(group) == 5 and all(x['weights'] == group[0]['weights'] and x['steps'] == 600 for x in group)
                and sorted(x['offset'] for x in group) == [-.1, -.05, 0.0, .05, .1], 'training', 'offset selection reuses one actual fit')
            fits += 1; iterations += group[0]['steps']
        candidates += len(table)
    return {'seed': seed, 'train_rows': receipt['train_rows'], 'development_rows': receipt['development_rows'],
        'forecasts': forecasts, 'native_requests': calls, 'native_ticks': ticks, 'native_roundtrip_ns': ipc,
        'wall_ns': receipt['wall_ns'], 'cpu_ns': receipt['cpu_ns'], 'distinct_gradient_fits': fits,
        'gradient_iterations': iterations, 'development_selection_candidates': candidates,
        'training_receipt_sha256': e.file_hash(path / 'TRAINING_RECEIPT.json'),
        'training_rows_sha256': e.file_hash(path / 'TRAINING_ROWS.json.gz')}


def aggregate(root, review):
    from collections import Counter
    root = Path(root)
    began, cpu = time.perf_counter_ns(), time.process_time_ns()
    frozen = e.verify_freeze(root, review)
    seeds = e.read_json(e.PROJECT / 'PROTOCOL.json')['feedback']['seeds']
    feedback_cost = e.read_json(root / 'FEEDBACK_EXECUTION_COSTS.json')
    runtime_cost = e.read_json(root / 'RUNTIME_EXECUTION_COSTS.json')
    runtime_results = e.read_json(root / 'RUNTIME_RESULTS.json')
    accounting = e.read_json(root / 'FEEDBACK_RUNTIME_ACCOUNTING.json')
    statistics = e.read_json(root / 'FEEDBACK_STATISTICS_EXECUTION.json')
    feedback_index, runtime_index = [e.read_json(root / name) for name in ('FEEDBACK_INDEX.json', 'RUNTIME_INDEX.json')]
    for document in (feedback_cost, runtime_cost, runtime_results, accounting, feedback_index, runtime_index):
        review.require(document['complete'] and document['source_commit'] == frozen['source_commit'], 'identity', 'complete source-bound report')
    expected_reports = {'FEEDBACK_EXECUTION_COSTS.json', 'RUNTIME_EXECUTION_COSTS.json', 'RUNTIME_RESULTS.json', 'FEEDBACK_RESULTS.json'}
    review.require(set(accounting['reports']) == expected_reports and accounting['aggregator_sha256']
        == e.file_hash(Path(__file__).with_name('aggregate_feedback_runtime_costs.py')), 'identity', 'reported cost aggregation code')
    for name, sha in accounting['reports'].items():
        review.require(e.file_hash(root / name) == sha, 'identity', 'final report digest')
    review.require(statistics['results_sha256'] == e.file_hash(root / 'FEEDBACK_RESULTS.json') and statistics['native_calls'] == 0
        and statistics['frozen_source_and_model_binding'] and statistics['source_commit'] == frozen['source_commit'], 'identity', 'statistics execution binding')
    training, summaries, audits, runtime_scopes, native_records, qualifiers = [], [], [], [], [], []
    prior_review_bindings = {}
    for seed in seeds:
        measured = training_cost(root, seed, review)
        training.append(measured)
        prepared = root / 'feedback_prepared' / f'seed_{seed}'
        tr = e.read_json(prepared / 'TRAINING_RECEIPT.json')
        scope = root / 'feedback_confirmation' / f'seed_{seed}'
        summary, audit = [e.read_json(scope / name) for name in ('SUMMARY.json', 'AUDIT.json')]
        summaries.append(summary); audits.append(audit)
        fr_path = root / 'reviews' / f'FEEDBACK_INDEPENDENT_{seed}.json'
        rr_path = root / 'reviews' / f'RUNTIME_INDEPENDENT_{seed}.json'
        fr, rr = e.read_json(fr_path), e.read_json(rr_path)
        for path, doc in ((fr_path, fr), (rr_path, rr)):
            review.require(doc['passed'] and doc['seed'] == seed and doc['freeze_sha256'] == e.file_hash(root / 'FREEZE.json'),
                           'identity', 'completed independent per-scope evidence')
            prior_review_bindings[str(path.relative_to(root))] = e.file_hash(path)
            for name, sha in doc['indexed_files_sha256'].items():
                review.require(e.file_hash(root / name) == sha, 'identity', 'original reviewed scope still immutable')
        row = next(x for x in feedback_cost['scopes'] if x['seed'] == seed)
        expected = {'seed': seed, 'summary': str((scope / 'SUMMARY.json').relative_to(root)),
            'audit': str((scope / 'AUDIT.json').relative_to(root)), 'training_receipt': str((prepared / 'TRAINING_RECEIPT.json').relative_to(root)),
            'training_wall_ns': measured['wall_ns'], 'training_parent_cpu_ns': measured['cpu_ns'],
            'training_native': {'requests': measured['native_requests'], 'ticks': measured['native_ticks'], 'roundtrip_ns': measured['native_roundtrip_ns']},
            'policy_worker_wall_ns': summary['wall_ns'], 'policy_worker_cpu_ns': summary['cpu_ns'],
            'policy_native_requests': fr['actual_cost']['native_requests'], 'policy_native_ticks': fr['actual_cost']['native_ticks'],
            'policy_native_roundtrip_ns': fr['actual_cost']['native_roundtrip_ns'], 'audit_wall_ns': audit['wall_ns'],
            'audit_native': audit['replay_cost'], 'typed_ticks_replayed': audit['typed_ticks_replayed'],
            'sparse_ticks_replayed': audit['sparse_ticks_replayed']}
        review.require(row == expected, 'accounting', 'exact per-seed feedback accounting')
        scope = root / 'runtime_confirmation' / f'seed_{seed}'
        qualification = e.read_json(scope / 'QUALIFICATION.json'); qualifiers.append(qualification)
        with gzip.open(scope / 'FORECASTS.json.gz', 'rt') as stream:
            forecasts = json.load(stream)
        native = [r['native'] for r in forecasts['ordinary'] + forecasts['stress']]
        continuation = e.read_json(scope / 'recovery_3.json')
        duplicate = e.read_json(scope / 'recovery_2.json')
        review.require(duplicate['native_ticks'] == duplicate['native_requests'] == duplicate['native_roundtrip_ns'] == 0,
                       'accounting', 'cached duplicate contributes no new execution cost')
        native.append(continuation['receipt']['native'])
        owners = e.archive_index(scope / 'owners.tar.gz', qualification['owners'], review, 'runtime_owners')
        pending = [v['document']['native'] for name, v in owners['documents'].items()
                   if name.endswith('/pending.json') and 'native' in v['document']]
        review.require(len(pending) == 1, 'accounting', 'one retained partial native commit included')
        native.extend(pending)
        unique = {(r['case'], r['checkpoint_after']) for r in native}
        review.require(len(unique) == len(native) == rr['actual_cost']['native_ticks'] == 69, 'accounting', 'all successful calls counted once')
        review.require(sum(r['subprocess_roundtrip_ns'] for r in native) == rr['actual_cost']['native_roundtrip_ns'], 'accounting', 'independent native IPC receipt sum')
        native_records.extend(native)
        expected = {'seed': seed, 'passed': qualification['passed'], 'qualification': str((scope / 'QUALIFICATION.json').relative_to(root)),
            'qualification_sha256': e.file_hash(scope / 'QUALIFICATION.json'), 'checks': len(qualification['checks']),
            'unique_histories': rr['independent_unique_histories'], 'ordinary_forecasts': rr['ordinary_forecasts'],
            'fresh_processes': rr['fresh_processes'], 'in_process_native_ticks': qualification['in_process_cost']['native_ticks'],
            'recovery_native_ticks': rr['continuation_native_ticks'], 'native_ticks': len(native),
            'native_roundtrip_ns': sum(r['subprocess_roundtrip_ns'] for r in native),
            'qualification_wall_ns': qualification['wall_ns'], 'qualification_parent_cpu_ns': qualification['cpu_ns'],
            'owner_archive_bytes': qualification['owners']['bytes'], 'owner_archive_files': rr['all_archive_members_verified']}
        runtime_scopes.append(expected)
    review.require(runtime_results['scopes'] == runtime_cost['scopes'] == runtime_scopes, 'accounting', 'complete exact runtime scope table')
    def exact(document, fields, kind):
        for key, expected in fields.items():
            review.require(document[key] == expected, kind, key)
    exact(feedback_cost, {'seed_count': len(seeds), 'unique_confirmation_trajectories': 1920, 'all_formal_episodes': 17280,
        'successful_training': {'wall_ns_sum': sum(t['wall_ns'] for t in training), 'parent_cpu_ns_sum': sum(t['cpu_ns'] for t in training),
            'native': {'requests': sum(t['native_requests'] for t in training), 'ticks': sum(t['native_ticks'] for t in training),
                       'roundtrip_ns': sum(t['native_roundtrip_ns'] for t in training)}, 'includes_train_development_actual_readbacks_and_archiving': True},
        'policy_workers_nested_in_confirmation_phase': {key: sum(s[key] for s in summaries)
            for key in ('wall_ns', 'cpu_ns', 'native_requests', 'native_ticks', 'native_roundtrip_ns')},
        'native_audit_nested_in_confirmation_phase': {'wall_ns_sum': sum(a['wall_ns'] for a in audits), 'isolated_parent_cpu_ns': None,
            **{key: sum(a['replay_cost'][key] for a in audits) for key in ('native_requests', 'native_ticks', 'native_roundtrip_ns')},
            'typed_ticks': sum(a['typed_ticks_replayed'] for a in audits), 'sparse_ticks': sum(a['sparse_ticks_replayed'] for a in audits)},
        'statistics_after_confirmation_phase': statistics,
        'confirmation_owner_compressed_bytes': sum(s['owners']['bytes'] for s in summaries),
        'audit_native_compressed_bytes': sum(a['native_replay_archive']['bytes'] for a in audits)}, 'accounting')
    transport_keys = ('observations', 'deliveries', 'files', 'archive_bytes', 'archive_ns')
    train_transports = []
    for seed in seeds:
        tr = e.read_json(root / 'feedback_prepared' / f'seed_{seed}' / 'TRAINING_RECEIPT.json')
        train_transports.extend(tr[split + '_archive']['readbacks'] for split in ('train', 'development'))
    exact(feedback_cost, {'training_transport': {key: sum(t[key] for t in train_transports) for key in transport_keys},
        'confirmation_transport': {key: sum(s['readbacks'][key] for s in summaries) for key in transport_keys},
        'covered_successful_native_requests': sum(t['native_requests'] for t in training) + sum(s['native_requests'] for s in summaries) + sum(a['replay_cost']['native_requests'] for a in audits),
        'covered_successful_native_ticks': sum(t['native_ticks'] for t in training) + sum(s['native_ticks'] for s in summaries) + sum(a['replay_cost']['native_ticks'] for a in audits)}, 'accounting')
    exact(feedback_cost['confirmation_phase'], {'wall_ns': feedback_index['wall_ns'], 'controller_parent_cpu_ns': feedback_index['parent_cpu_ns']}, 'accounting')
    failed = feedback_cost['failed_development_training_attempt']
    failure_path = root / failed['receipt']; failure_descriptor = e.read_json(failure_path)
    failure_archive = e.archive_index(root / failure_descriptor['path'], failure_descriptor, review, 'retained_failed_training')
    review.require(failed['wall_ns'] is None and failed['parent_cpu_ns'] is None and failed['all_native_requests_or_ticks'] is None,
                   'limitations', 'unknown failed-attempt totals remain unknown')
    check_counts = Counter(name for q in qualifiers for name in q['checks'])
    ordinary_cdf_errors = []
    for seed in seeds:
        with gzip.open(root / 'runtime_confirmation' / f'seed_{seed}' / 'FORECASTS.json.gz', 'rt') as stream:
            ordinary_cdf_errors.extend(r['native_cdf_error'] for r in json.load(stream)['ordinary'])
    exact(runtime_results, {'passed': all(q['passed'] for q in qualifiers), 'seed_count': len(seeds),
        'unique_histories': sum(q['unique_histories'] for q in qualifiers), 'ordinary_forecasts': sum(q['ordinary_forecasts'] for q in qualifiers),
        'checks': sum(len(q['checks']) for q in qualifiers), 'check_counts': dict(check_counts),
        'fresh_processes': 10, 'in_process_native_ticks': 340, 'recovery_native_ticks': 5,
        'native_ticks': len(native_records), 'successful_native_requests': len(native_records),
        'cached_duplicate_recovery_new_native_ticks': 0, 'maximum_ordinary_cdf_absolute_error': max(ordinary_cdf_errors),
        'all_runtime_permission_confidences_zero': all(r['legacy_runtime_confidence_ppm'] == 0 for r in native_records),
        'all_native_abstain': all(r['abstain'] for r in native_records), 'same_runtime_as_feedback_utility': True,
        'source_or_density_retention_certificate': None, 'production_promotion': False, 'cross_owner_atomicity': False,
        'runtime_source_sha256': e.file_hash(e.PROJECT / 'runtime_feedback.py')}, 'runtime_summary')
    exact(runtime_cost, {'phase_wall_ns': runtime_index['wall_ns'], 'phase_controller_parent_cpu_ns': runtime_index['parent_cpu_ns'],
        'qualification_wall_ns_sum_nested_in_phase': sum(q['wall_ns'] for q in qualifiers),
        'qualification_parent_cpu_ns_sum_nested_in_phase': sum(q['cpu_ns'] for q in qualifiers),
        'successful_native_requests': len(native_records), 'successful_native_ticks': len(native_records),
        'native_subprocess_roundtrip_ns_nested': sum(r['subprocess_roundtrip_ns'] for r in native_records),
        'native_typed_tick_wall_ns_nested': sum(r['typed_tick_wall_ns'] for r in native_records),
        'native_head_execution_micros_nested': sum(r['head_execution_micros'] for r in native_records),
        'native_reported_journal_bytes_written': sum(r['journal_bytes_written'] for r in native_records),
        'maximum_sampled_native_process_resident_bytes': max(r['process_resident_bytes'] for r in native_records),
        'owner_compressed_archive_bytes': sum(q['owners']['bytes'] for q in qualifiers),
        'owner_archived_files': sum(q['owners']['verified_files'] for q in qualifiers), 'fresh_processes': 10}, 'accounting')
    review.require(all(value is None for value in feedback_cost['unmeasured'].values())
        and all(value is None for value in runtime_cost['unmeasured'].values()), 'limitations', 'unmeasured energy/I/O/dollars/child CPU not fabricated')
    expected_ticks = feedback_cost['covered_successful_native_ticks'] + len(native_records)
    review.require(accounting['covered_successful_native_ticks_all_listed_nonoverlapping_phases'] == expected_ticks == 379611
        and accounting['not_a_full_failed_attempt_or_energy_or_monetary_cost_total'], 'accounting', 'disjoint successful phase counts only')
    e.verify_freeze(root, review)
    return {'schema': 'hepta.round3.independent-feedback-runtime-accounting-review.v1', 'passed': True,
        'source_commit': frozen['source_commit'], 'freeze_sha256': e.file_hash(root / 'FREEZE.json'),
        'reviewer_sha256': {p.name: e.file_hash(p) for p in (Path(__file__), Path(e.__file__))},
        'input_reports_sha256': {name: e.file_hash(root / name) for name in sorted(expected_reports | {'FEEDBACK_RUNTIME_ACCOUNTING.json', 'FEEDBACK_STATISTICS_EXECUTION.json', 'FEEDBACK_TRAINING_OPERATIONAL_EVENT.json'})},
        'independent_scope_reports_sha256': prior_review_bindings, 'checks': dict(review.counts),
        'total_checks': sum(review.counts.values()), 'maximum_absolute_errors': review.maximum,
        'training_from_all_actual_native_records': training,
        'training_forecasts': sum(x['forecasts'] for x in training), 'training_native_ticks': sum(x['native_ticks'] for x in training),
        'trained_gradient_fits': sum(x['distinct_gradient_fits'] for x in training),
        'actual_gradient_iterations': sum(x['gradient_iterations'] for x in training),
        'development_selection_candidates': sum(x['development_selection_candidates'] for x in training),
        'runtime_unique_histories': runtime_results['unique_histories'], 'runtime_ordinary_forecasts': runtime_results['ordinary_forecasts'],
        'runtime_native_requests': len(native_records), 'runtime_actual_native_ipc_ns': sum(r['subprocess_roundtrip_ns'] for r in native_records),
        'runtime_native_reported_journal_bytes_written': sum(r['journal_bytes_written'] for r in native_records),
        'all_listed_nonoverlapping_successful_native_ticks': expected_ticks,
        'retained_failed_training_archive_sha256': failure_descriptor['sha256'],
        'retained_failed_training_archive_members_independently_verified': len(failure_archive['hashes']),
        'source_or_density_retention_certificate': None, 'cross_owner_atomicity': False, 'production_promotion': False,
        'limitations': ['No native re-execution; all sums independently rederived from recorded calls and durable evidence.',
            'Covered counts exclude unknown failed prefreeze training counters; all partial bytes verified and preserved.',
            'Wall/CPU/native/archive durations are nested scopes, not additive elapsed time.',
            'Qualification rejection occurrence is evidenced by frozen executable logic and check receipts, not an independent syscall trace.',
            'Training archive containers were freeze-hashed; current full member/PNG review targets confirmation, runtime and retained failed-attempt archives.',
            'No full child CPU, energy, monetary or hardware write-amplification measurement.'],
        'wall_ns': time.perf_counter_ns() - began, 'cpu_ns': time.process_time_ns() - cpu}


def main():
    parser = argparse.ArgumentParser(); parser.add_argument('--run-dir', required=True)
    args = parser.parse_args(); root = Path(args.run_dir); review = e.Review()
    try:
        report = aggregate(root, review)
    except Exception:
        stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%f')
        e.write_new(root / 'reviews' / f'FEEDBACK_RUNTIME_ACCOUNTING_REVIEW_FAILURE_{stamp}.json',
            {'passed': False, 'traceback': traceback.format_exc(), 'checks': dict(review.counts),
             'reviewer_sha256': e.file_hash(__file__), 'scientific_files_modified': False})
        raise
    output = root / 'reviews' / 'FEEDBACK_RUNTIME_ACCOUNTING_INDEPENDENT.json'
    e.write_new(output, report)
    print(json.dumps({'passed': True, 'path': str(output), 'sha256': e.file_hash(output), 'checks': report['total_checks'],
                      'native_ticks_independently_accounted': report['all_listed_nonoverlapping_successful_native_ticks']}, sort_keys=True), flush=True)


if __name__ == '__main__':
    main()
