"""Join sealed paired endpoints to one external objective receipt, then fit.

Verifier acceptance is diagnostic, never a utility label. Every registered pair
must terminate before any scores are released. Failed/unknown work cannot be
silently dropped or converted to complete cost. This is provenance linkage, not
signed owner authentication or a guarantee of counterfactual state sufficiency.
"""
from __future__ import annotations

import argparse
from dataclasses import asdict
from pathlib import Path

from matrix_materials import file_sha256, strict_json
from next_round_matrix import _digest
from paired_capture import PROFILE, read_task, sync_directory, validate_capture
from paired_critic import _number, fit_critic, bind_capture
from paired_execution import _integer, _sha
from work_record import validate_work_record

OBSERVER_SCHEMA = 'hepta.ndu.paired-objective-observations.v1'


def read_pair(root, registration, index, expected_id):
    _sha(expected_id, 'retained paired terminal')
    root = Path(root) / 'pairs' / f'{index:05d}'
    if root.is_symlink() or (root / 'FAILED_CAPTURE.json').exists():
        raise ValueError('failed or linked capture publication')
    for name in ('STARTED.json', 'pair.json', 'TERMINAL.json'):
        if (root / name).is_symlink() or not (root / name).is_file():
            raise ValueError('unfinished pair is unresolved, not a zero-utility failure')
    seal = strict_json(root / 'TERMINAL.json')
    if (not isinstance(seal, dict) or set(seal) != {'schema', 'capture_id', 'pair_id', 'sealed_at_ns', 'files', 'terminal_id'}
            or seal['schema'] != 'hepta.ndu.paired-terminal.v1'
            or seal['capture_id'] != registration['capture_id']
            or seal['pair_id'] != registration['protocol']['pairs'][index]['pair_id']
            or not isinstance(seal['files'], dict) or set(seal['files']) != {'STARTED.json', 'pair.json'}
            or seal['terminal_id'] != expected_id
            or _digest({k: v for k, v in seal.items() if k != 'terminal_id'}) != expected_id):
        raise ValueError('terminal identity or file inventory changed')
    for name, sha in seal['files'].items():
        _sha(sha, 'sealed file hash')
        if file_sha256(root / name) != sha:
            raise ValueError('sealed paired trajectory bytes changed')
    record, started = strict_json(root / 'pair.json'), strict_json(root / 'STARTED.json')
    boundary, p = registration['boundaries'][index], registration['protocol']
    if (record.get('schema') != 'hepta.ndu.captured-pair.v1' or record.get('capture_id') != registration['capture_id']
            or record.get('protocol_id') != p['protocol_id'] or record.get('pair_id') != seal['pair_id']
            or record.get('boundary_sha256') != _digest(boundary)
            or record.get('stop_candidate') != boundary['candidate']
            or record.get('source_files_sha256') != registration['source_files_sha256']
            or any(record.get(k) is not False for k in ('utility_labels_loaded', 'owner_authenticity_verified', 'production_authorized'))):
        raise ValueError('captured boundary/profile differs from registration')
    for key in ('decision_at_ns', 'duration_ns', 'finished_at_ns'):
        _integer(record.get(key), key, 1)
    _integer(seal['sealed_at_ns'], 'seal time', 1)
    if not p['registered_at_ns'] <= record['decision_at_ns'] < record['decision_at_ns'] + record['duration_ns'] <= record['finished_at_ns'] <= seal['sealed_at_ns'] < p['cutoff_ns']:
        raise ValueError('invalid segment and publication chronology')
    if started != dict(capture_id=registration['capture_id'], pair_id=seal['pair_id'],
                       started_at_ns=record['decision_at_ns'], boundary_sha256=_digest(boundary)):
        raise ValueError('started claim differs from terminal')
    execution = record['execution']
    if (execution.get('schema') != 'hepta.stem.paired-segment-execution.v1'
            or execution.get('capture_id') != registration['capture_id']
            or execution.get('task_sha256') != _digest(asdict(read_task(boundary['task'])))
            or execution.get('value_profile') != PROFILE
            or any(execution.get(k) is not False for k in ('independent_success_established', 'utility_labels_loaded', 'production_authorized'))):
        raise ValueError('pair did not use the registered single-segment execution path')
    _integer(execution.get('calls'), 'callback count', 1)
    _integer(execution.get('elapsed_ns'), 'execution elapsed time')
    if execution['elapsed_ns'] > record['duration_ns']:
        raise ValueError('segment duration omits observed execution time')
    trace = execution.get('trace')
    if not isinstance(trace, list) or not 1 <= len(trace) <= 2 or execution['calls'] != len(trace):
        raise ValueError('exact attempted callback denominator required')
    for i, row in enumerate(trace):
        if not isinstance(row, dict):
            raise ValueError('typed callback trace required')
        _integer(row.get('call'), 'callback index', 1)
        _integer(row.get('elapsed_ns'), 'callback elapsed time')
        if row.get('kind') != ('propose', 'verify')[i] or row.get('call') != i + 1 or row.get('status') not in ('completed', 'failed'):
            raise ValueError('critic/filter or invalid callback trace in paired capture')
    done = execution['status'] in ('depth_exhausted', 'verifier_accepted_not_independent_eval')
    observed = execution['work_observation']
    validate_work_record(observed, expected_policy=registration['meter_policy'])
    expected_status = 'completed' if done else ('timed_out' if observed['stopped'] == 'wall_time_budget' else 'failed')
    if record.get('status') != expected_status:
        raise ValueError('terminal status contradicts actual callback execution')
    if done:
        if (len(trace) != 2 or any(r['status'] != 'completed' for r in trace)
                or observed['stopped'] is not None or record['continue_candidate'] != execution['candidate']
                or trace[0].get('output_digest') != _digest(record['continue_candidate'])):
            raise ValueError('completed continuation lacks a complete callback pair')
    elif record.get('continue_candidate') is not None:
        raise ValueError('failed continuation cannot contain a delivered candidate')
    return record, seal


def assemble_pairs(root, *, expected_capture_id, observer_path, expected_observer_sha256):
    """No callbacks or model loads. Raw observer digest follows every fitted row."""
    root = Path(root)
    registration = strict_json(root / 'REGISTRATION.json')
    validate_capture(registration, expected_capture_id)
    _sha(expected_observer_sha256, 'external objective receipt')
    if file_sha256(observer_path) != expected_observer_sha256:
        raise ValueError('objective receipt differs from retained bytes')
    observer = strict_json(observer_path)
    p = registration['protocol']
    keys = {'schema', 'capture_id', 'protocol_id', 'objective_sha256', 'observer_sha256', 'created_at_ns', 'terminal_ids', 'rows'}
    if (not isinstance(observer, dict) or set(observer) != keys or observer['schema'] != OBSERVER_SCHEMA
            or observer['capture_id'] != expected_capture_id
            or any(observer.get(k) != p[k] for k in ('protocol_id', 'objective_sha256', 'observer_sha256'))
            or not isinstance(observer['terminal_ids'], list) or len(observer['terminal_ids']) != len(p['pairs'])
            or not isinstance(observer['rows'], list) or len(observer['rows']) != len(p['pairs'])):
        raise ValueError('complete common paired objective receipt required')
    _integer(observer['created_at_ns'], 'objective receipt time', 1)
    records = [read_pair(root, registration, i, identity) for i, identity in enumerate(observer['terminal_ids'])]
    latest = max(seal['sealed_at_ns'] for _, seal in records)
    rows = []
    for pair, (record, _), labels in zip(p['pairs'], records, observer['rows'], strict=True):
        if (not isinstance(labels, dict) or set(labels) != {'pair_id', 'stop_candidate_sha256', 'continue_candidate_sha256',
                                                           'stop_utility', 'continue_utility', 'observed_at_ns'}
                or labels['pair_id'] != pair['pair_id']
                or labels['stop_candidate_sha256'] != _digest(record['stop_candidate'])
                or labels['continue_candidate_sha256'] != _digest(record['continue_candidate'])):
            raise ValueError('paired scores do not name the actual sealed endpoints')
        _integer(labels['observed_at_ns'], 'objective observation time', 1)
        if not latest <= labels['observed_at_ns'] <= observer['created_at_ns'] <= p['cutoff_ns']:
            raise ValueError('all paired outputs must seal before either endpoint is scored')
        for key in ('stop_utility', 'continue_utility'):
            _number(labels[key], key, 0., 1.)
        if record['status'] != 'completed' and labels['continue_utility'] != 0:
            raise ValueError('failed continuation must retain fail-closed utility and its costs')
        rows.append(dict(pair_id=pair['pair_id'], protocol_id=p['protocol_id'],
                         decision_at_ns=record['decision_at_ns'], observed_at_ns=labels['observed_at_ns'],
                         stop_utility=labels['stop_utility'], continue_utility=labels['continue_utility'],
                         status=record['status'], duration_ns=record['duration_ns'],
                         formula_work=record['execution']['work_observation']['phase_flops']['search'],
                         outcome_receipt_sha256=expected_observer_sha256))
    # Re-read external pins; no claim of hostile change-and-restore protection.
    for i, identity in enumerate(observer['terminal_ids']):
        read_pair(root, registration, i, identity)
    validate_capture(strict_json(root / 'REGISTRATION.json'), expected_capture_id)
    if file_sha256(observer_path) != expected_observer_sha256:
        raise ValueError('objective receipt changed during export')
    from aten_work import PROFILE as base_profile
    return p, rows, dict(capture_id=expected_capture_id, observer_receipt_sha256=expected_observer_sha256,
                         arithmetic_profile=registration['meter_policy'].get('arithmetic_profile', base_profile),
                         source_inventory_sha256=_digest(registration['source_files_sha256']),
                         terminal_ids=observer['terminal_ids'], pairs=len(rows),
                         incomplete_cost_pairs=[r['pair_id'] for r in rows if r['formula_work'] is None],
                         owner_authenticity_verified=False, final_efficacy_established=False)


def fit_collected(protocol, rows, lineage):
    """Fit unfiltered normalized rows; bind measured units to runtime consumption."""
    dataset_id = _digest(rows)
    artifact, work = fit_critic(protocol, rows, expected_protocol_id=protocol['protocol_id'],
                                expected_dataset_sha256=dataset_id)
    if (lineage['pairs'] != len(rows) or len(lineage['terminal_ids']) != len(rows)
            or any(r['outcome_receipt_sha256'] != lineage['observer_receipt_sha256'] for r in rows)):
        raise ValueError('captured row denominator or common observation linkage changed')
    binding = {k: lineage[k] for k in ('capture_id', 'observer_receipt_sha256', 'arithmetic_profile', 'source_inventory_sha256')}
    binding.update(protocol_id=protocol['protocol_id'], dataset_sha256=dataset_id,
                   terminal_inventory_sha256=_digest(lineage['terminal_ids']))
    return bind_capture(artifact, binding), work


def main():
    from matrix_runtime import write_json_exclusive
    parser = argparse.ArgumentParser(description=__doc__)
    for key in ('capture-dir', 'capture-id', 'observer', 'observer-sha256', 'output'):
        parser.add_argument('--' + key, required=True)
    args = parser.parse_args()
    root = Path(args.output); root.mkdir(exist_ok=False)
    try:
        p, rows, lineage = assemble_pairs(args.capture_dir, expected_capture_id=args.capture_id,
                                          observer_path=args.observer, expected_observer_sha256=args.observer_sha256)
        # Retain all normalized rows before fitting; incomplete or over-budget
        # pairs will cause fit_critic to reject the entire release, not filtering.
        write_json_exclusive(root / 'paired-rows.json', rows)
        write_json_exclusive(root / 'lineage.json', lineage)
        artifact, work = fit_collected(p, rows, lineage)
        write_json_exclusive(root / 'critic.json', artifact)
        write_json_exclusive(root / 'fit-work.json', work)
        write_json_exclusive(root / 'COMMITTED.json', dict(artifact_id=artifact['artifact_id'],
                             files={n: file_sha256(root / n) for n in ('paired-rows.json', 'lineage.json', 'critic.json', 'fit-work.json')}))
        sync_directory(root)
    except Exception as exc:
        write_json_exclusive(root / 'FAILED.json', dict(error_type=type(exc).__name__, production_authorized=False))
        sync_directory(root)
        raise


if __name__ == '__main__':
    main()
