"""Independent report-only review of the frozen feedback runtime qualification.

Reads original records and archives. It never generates histories, invokes the
native executable, changes science files, or repeats interruption experiments.
"""

import argparse
from datetime import datetime, timezone
import gzip
import json
import math
from pathlib import Path
import time
import traceback

import numpy as np

from . import review_feedback_evidence as e


def public_history(data, index, second=False):
    initial = float(data['initial_output'][index])
    result = {'initial': initial, 'residuals': [float(data['self_evaluation'][index]) - initial],
              'variances': [float(data['sensor_variance'][index])],
              **{key: float(data[key][index]) for key in ('repair_cost', 'wait_cost', 'wait_variance')}}
    if second:
        result['residuals'].append(float(data['wait_evaluation'][index]) - initial)
        result['variances'].append(result['wait_variance'])
    return result


def qualification_checks(n):
    result = ['actual reopened receiver', 'original native qualification', 'head probability mass',
              'analytic CDF numerical reference'] * (2 * n)
    result += ['stale CAS rejected before native', 'changed duplicate rejected before native',
        'rollback rejected before native', 'corruption rejected before native',
        'after_pending fails closed', 'after_pending expected native call count',
        'after_native fails closed', 'after_native expected native call count',
        'lost acknowledgement duplicate has no new tick', 'fresh process duplicate exact',
        'fresh process continuation one native tick', 'propagation silence is not terminal neutral']
    return result


def scope_review(root, seed, review):
    root = Path(root)
    began, cpu = time.perf_counter_ns(), time.process_time_ns()
    frozen = e.verify_freeze(root, review)
    protocol = e.read_json(e.PROJECT / 'PROTOCOL.json')['runtime']
    index = e.read_json(root / 'RUNTIME_INDEX.json')
    entries = [x for x in index['scopes'] if x['seed'] == seed]
    review.require(len(entries) == 1 and index['phase'] == 'runtime' and index['source_commit'] == frozen['source_commit'],
                   'identity', 'immutable completed registered runtime scope')
    entry = entries[0]
    scope = root / 'runtime_confirmation' / f'seed_{seed}'
    review.require({str(p.relative_to(root)) for p in scope.rglob('*') if p.is_file()} == set(entry['files_sha256']),
                   'identity', 'exact completed artifact inventory')
    for name, sha in entry['files_sha256'].items():
        review.require(e.file_hash(root / name) == sha, 'identity', 'indexed file digest ' + name)
    qualification = e.read_json(scope / 'QUALIFICATION.json')
    model_path = root / 'feedback_prepared' / f'seed_{seed}' / 'MODELS.json'
    model = e.read_json(model_path)
    review.require(qualification['model_sha256'] == e.file_hash(model_path) == frozen['artifacts_sha256'][str(model_path.relative_to(root))]
        and qualification['runtime_source_sha256'] == frozen['sources_sha256'][str((e.PROJECT / 'runtime_feedback.py').relative_to(e.REPO))],
        'identity', 'same frozen model and runtime source as paid-action evaluation')
    n = protocol['unique_histories_per_seed']
    review.require(qualification['seed'] == seed and qualification['unique_histories'] == n and qualification['ordinary_forecasts'] == 2 * n
        and qualification['checks'] == qualification_checks(n) and qualification['passed'] and not qualification['development_only'],
        'qualification', 'all predeclared actual qualification checks retained')
    review.require(qualification['same_runtime_as_feedback_utility'] and qualification['source_or_density_retention_certificate'] is None
        and not qualification['production_promotion'] and not qualification['cross_owner_atomicity'], 'qualification', 'scope of claims')
    data = e.arrays(scope / 'PUBLIC.npz')
    required = {'initial_output', 'self_evaluation', 'wait_evaluation', 'sensor_variance', 'wait_variance',
                'repair_cost', 'wait_cost', 'ids', 'seed', 'split', 'law'}
    review.require(set(data) == required and data['split'] == 'runtime_confirmation'
        and data['seed'] == protocol['data_offset'] + seed, 'privacy', 'only target-free registered runtime data')
    ids = [f"feedback3:runtime_confirmation:{protocol['data_offset'] + seed}:{i}" for i in range(n)]
    review.require(data['ids'].tolist() == ids and len(set(ids)) == n, 'coverage', 'all unique histories; no duplicated first-four fixture')
    with gzip.open(scope / 'FORECASTS.json.gz', 'rt') as stream:
        forecasts = json.load(stream)
    review.require(set(forecasts) == {'ordinary', 'stress'} and len(forecasts['ordinary']) == 2 * n and len(forecasts['stress']) == 3,
                   'coverage', 'complete ordinary and stress records')
    ordinary, stress = forecasts['ordinary'], forecasts['stress']
    owners = e.archive_index(scope / 'owners.tar.gz', qualification['owners'], review, 'runtime_owners')
    chains, native_records = {}, []
    for i, case in enumerate(ids):
        previous, receipts = None, []
        for stage in range(2):
            row = ordinary[2 * i + stage]
            review.require(row['public'] == public_history(data, i, bool(stage)), 'privacy', 'exact acquired sensor history')
            e.runtime_receipt(row, [case, 'event'], model, previous, review)
            previous = row; receipts.append(row); native_records.append(row['native'])
        chains[row['subject']] = receipts
    for stage, row in enumerate(stress[:2]):
        review.require(row['public'] == public_history(data, 0), 'privacy', 'unchanged public history during propagation stress')
        e.runtime_receipt(row, [ids[0], 'stress'], model, stress[0] if stage else None, review)
        native_records.append(row['native'])
    review.require(stress[1]['packet']['counts'] == [0, 0] and stress[1]['packet']['observation_kind'] == 'propagation'
        and stress[1]['law'] == stress[0]['law'], 'semantics', 'zero communication counts do not mean neutral terminal outcome')
    chains[stress[0]['subject']] = stress[:2]
    row = stress[2]
    review.require(row['public'] == public_history(data, 0), 'privacy', 'lost acknowledgement public history')
    e.runtime_receipt(row, [ids[0], 'after_commit'], model, None, review)
    chains[row['subject']] = [row]; native_records.append(row['native'])
    recovery_records = []
    for sequence in (2, 3):
        job = e.read_json(scope / f'recovery_job_{sequence}.json')
        result = e.read_json(scope / f'recovery_{sequence}.json')
        review.require(job['identity'] == [ids[0], 'event'] and job['public'] == public_history(data, 0, True)
            and job['sequence'] == sequence and job['expected_model_sha256'] == e.file_hash(model_path)
            and job['expected_checkpoint'] == (e.ZERO if sequence == 2 else ordinary[1]['checkpoint_after'])
            and Path(job['root']).parts[-3:] == ('runtime_confirmation', f'seed_{seed}', 'owners'),
            'recovery', 'fresh-process request model/history/checkpoint binding')
        if sequence == 2:
            review.require(result['receipt'] == ordinary[1] and result['native_ticks'] == result['native_requests'] == 0
                and result['native_roundtrip_ns'] == 0, 'recovery', 'duplicate exact cached receipt, no tick/IPC')
        else:
            review.require(result['receipt']['public'] == ordinary[1]['public'], 'privacy', 'continuation identical information')
            e.runtime_receipt(result['receipt'], [ids[0], 'event'], model, ordinary[1], review)
            review.require(result['native_ticks'] == result['native_requests'] == 1
                and result['native_roundtrip_ns'] == result['receipt']['native']['subprocess_roundtrip_ns'], 'recovery', 'one continuation native call')
            review.require(result['receipt']['packet']['counts'] == [0, 0] and result['receipt']['law'] == ordinary[1]['law']
                and result['receipt']['packet']['observation_kind'] == 'propagation', 'semantics', 'fresh-process silent propagation law unchanged')
            chains[ordinary[1]['subject']].append(result['receipt'])
            native_records.append(result['receipt']['native'])
        recovery_records.append(result)
    for receipts in chains.values():
        e.owner_state(owners, receipts, review)
    actual_state_subjects = {name.split('/')[1] for name in owners['hashes'] if name.endswith('/state.json')}
    review.require(actual_state_subjects == set(chains) and len(chains) == n + 2, 'coverage', 'all committed owner states/witnesses')
    pending_records, pending_subjects = {}, set()
    config = {'mean_step': e.STEP, 'logvar_step': e.STEP, 'mode': 'error_feedback', 'maximum_count': 2147483647}
    public = public_history(data, 0)
    for failure in ('after_pending', 'after_native'):
        subject = e.digest([e.SCHEMA, [ids[0], failure], e.digest(model), config])
        pending_subjects.add(subject)
        stem = owners['prefix'] + subject + '/'
        envelope = owners['documents'][stem + 'pending.json']
        pending = envelope['document']
        review.require(set(envelope) == {'document', 'sha256'} and e.digest(pending) == envelope['sha256'], 'interruption', 'retained pending envelope integrity')
        base = ordinary[0]
        request = {key: base[key] for key in ('schema', 'model_sha256', 'public_sha256', 'source_sha256', 'sequence', 'time')}
        request['subject'] = subject
        expected = {'request_sha256': e.digest(request), 'packet': base['packet'], 'decoder': base['decoder']}
        review.require(all(pending[k] == value for k, value in expected.items())
            and set(pending) == set(expected) | ({'native'} if failure == 'after_native' else set()),
            'interruption', 'pending commit contents match only already acquired public forecast')
        review.require(stem + 'state.json' not in owners['hashes'] and stem + 'delivery.witness.json' not in owners['hashes'],
                       'interruption', 'interrupted adapter has no committed state/law delivery')
        paths = {name[len(stem):] for name in owners['hashes'] if name.startswith(stem)}
        expected_paths = {'owner.lock', 'pending.json'}
        if failure == 'after_native':
            native = pending['native']; native_records.append(native)
            expected_paths |= {'native/state.journal', 'native/anchor.witness'}
            review.require(native['sequence'] == 1 and native['checkpoint_before'] == e.ZERO and native['case'] == subject
                and native['native_binary_sha256'] == model['native_binary_sha256'] and native['recovered'] is False,
                'interruption', 'native committed exactly once before interrupted adapter')
            review.require(native['head']['parameters_q24_decoded'] == base['native']['head']['parameters_q24_decoded']
                and native['head']['probabilities_q24'] == base['native']['head']['probabilities_q24']
                and native['signals_q24'] == base['native']['signals_q24'], 'interruption', 'same independent verified Q24 head')
            review.close(native['head']['probabilities'], e.probability(*native['head']['parameters_q24_decoded']), 'cdf', 'interrupted native head', 3e-15)
            review.require(native['authority'] == 'DENY_ALL' and native['abstain'] and native['legacy_runtime_confidence_ppm'] == 0
                and not native['calibrated_success_probability'] and not native['native_owner_integration'], 'qualification', 'partial native commit cannot grant authority')
            review.require(owners['hashes'][stem + 'native/state.journal']['bytes'] == native['journal_bytes'] == 600
                and owners['hashes'][stem + 'native/anchor.witness']['bytes'] == native['witness_bytes'] == 224,
                'accounting', 'interrupted native durable bytes retained')
        review.require(paths == expected_paths, 'interruption', 'complete exact partial-state evidence')
        pending_records[failure] = {'subject': subject, 'native_ticks': int(failure == 'after_native'), 'committed_adapter_law': False}
    actual_pending = {name.split('/')[1] for name in owners['hashes'] if name.endswith('/pending.json')}
    all_subjects = {name.split('/')[1] for name in owners['hashes'] if name.count('/') > 1}
    review.require(actual_pending == pending_subjects and all_subjects == set(chains) | pending_subjects, 'coverage', 'all stress/ordinary owner subjects exhausted')
    in_process_records = ordinary + stress
    in_process_ticks = len(in_process_records) + 1
    in_process_ipc = sum(r['native']['subprocess_roundtrip_ns'] for r in in_process_records)
    in_process_ipc += owners['documents'][owners['prefix'] + pending_records['after_native']['subject'] + '/pending.json']['document']['native']['subprocess_roundtrip_ns']
    expected_in_process = {'native_requests': in_process_ticks, 'native_ticks': in_process_ticks, 'native_roundtrip_ns': in_process_ipc}
    review.require(qualification['in_process_cost'] == expected_in_process and in_process_ticks == 2 * n + 4,
                   'accounting', 'all successful/partial native work included')
    review.require(qualification['fresh_processes'] == 2 and qualification['recovery_native_ticks'] == 1
        and sum(x['native_ticks'] for x in recovery_records) == 1 and len(native_records) == 2 * n + 5,
        'accounting', 'full qualification including recovery and partial-native failure')
    native_ipc = sum(r['subprocess_roundtrip_ns'] for r in native_records)
    review.require(native_ipc == in_process_ipc + recovery_records[1]['native_roundtrip_ns'], 'accounting', 'runtime IPC conservation')
    native_pairs = [(x['case'], x['sequence']) for x in native_records]
    review.require(len(native_pairs) == len(set(native_pairs)), 'coverage', 'successful native calls not duplicated in accounting')
    probabilities = np.array([r['law']['probabilities'] for r in ordinary])
    e.verify_freeze(root, review)
    return {'schema': 'hepta.round3.independent-runtime-review.v1', 'passed': True, 'seed': seed,
        'source_commit': frozen['source_commit'], 'freeze_sha256': e.file_hash(root / 'FREEZE.json'),
        'indexed_files_sha256': entry['files_sha256'], 'reviewer_sha256': {p.name: e.file_hash(p) for p in (Path(__file__), Path(e.__file__))},
        'checks': dict(review.counts), 'total_checks': sum(review.counts.values()), 'maximum_absolute_errors': review.maximum,
        'registered_qualification_check_count': len(qualification['checks']), 'independent_unique_histories': n,
        'ordinary_forecasts': len(ordinary), 'all_archive_members_verified': len(owners['hashes']),
        'committed_owner_chains': len(chains), 'retained_partial_commits': pending_records,
        'fresh_processes': 2, 'duplicate_native_ticks': 0, 'continuation_native_ticks': 1,
        'successful_native_ticks_including_partial_commit': len(native_records),
        'actual_cost': {'native_requests': len(native_records), 'native_ticks': len(native_records),
            'native_roundtrip_ns': native_ipc, 'wall_ns': qualification['wall_ns'], 'cpu_ns': qualification['cpu_ns'],
            'owners_archive_bytes': qualification['owners']['bytes'], 'ordinary_logical_unit_events': sum(r['logical_unit_events'] for r in ordinary),
            'ordinary_packet_bytes': sum(r['packet_bytes'] for r in ordinary),
            'ordinary_native_journal_bytes_written': sum(r['native']['journal_bytes_written'] for r in ordinary)},
        'ordinary_forecasts_with_any_zero_probability': int(np.any(probabilities == 0, axis=1).sum()),
        'ordinary_zero_probabilities_by_category': np.count_nonzero(probabilities == 0, axis=0).tolist(),
        'qualification_limits': ['No additional native calls executed by this independent reviewer.',
            'Rejected-call occurrence follows frozen qualification source and retained check results; no independent syscall trace.',
            'Retained pending/native files directly demonstrate separate owners and non-atomic partial states.',
            'No production grant, calibrated success confidence, adversarial process isolation or density-retention certificate.'],
        'wall_ns': time.perf_counter_ns() - began, 'cpu_ns': time.process_time_ns() - cpu}


def main():
    parser = argparse.ArgumentParser(); parser.add_argument('--run-dir', required=True); parser.add_argument('--seed', type=int, required=True)
    args = parser.parse_args(); root = Path(args.run_dir); review = e.Review()
    try:
        report = scope_review(root, args.seed, review)
    except Exception:
        stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%f')
        e.write_new(root / 'reviews' / f'RUNTIME_REVIEW_FAILURE_{args.seed}_{stamp}.json',
            {'passed': False, 'seed': args.seed, 'traceback': traceback.format_exc(), 'checks': dict(review.counts),
             'reviewer_sha256': e.file_hash(__file__), 'scientific_files_modified': False})
        raise
    path = root / 'reviews' / f'RUNTIME_INDEPENDENT_{args.seed}.json'
    e.write_new(path, report)
    print(json.dumps({'passed': True, 'seed': args.seed, 'report': str(path), 'sha256': e.file_hash(path),
                      'checks': report['total_checks'], 'native_ticks_independently_accounted': report['actual_cost']['native_ticks']}, sort_keys=True), flush=True)


if __name__ == '__main__':
    main()
