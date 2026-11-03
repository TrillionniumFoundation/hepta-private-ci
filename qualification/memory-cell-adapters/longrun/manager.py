"""Preregistered 64-cycle serial maintenance driver; source truth stays here."""

import argparse
import copy
import hashlib
import json
import os
from pathlib import Path
import resource
import shutil
import sqlite3
import subprocess
import sys
import time

import torch

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))
from owner import Owner, create
from reader import MeasuredCell, canonical_features, database_guard
from runtime_contract import canonical
from tensor_cell import TensorCell


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def save(path, data):
    raw = canonical(data)
    Path(path).write_bytes(raw)
    return {'sha256': sha(raw), 'bytes': len(raw)}


def identity(path):
    raw = Path(path).read_bytes()
    return {'sha256': sha(raw), 'bytes': len(raw)}


def file_bytes(path):
    return sum(p.stat().st_size for p in Path(path).rglob('*') if p.is_file())


def policy(seed, stage, entity):
    return [2+(5*stage+3*entity+seed % 7) % 12, 1+(stage+entity) % 7, 8+(3*stage+entity) % 8]


def active_rows(state):
    keys = ('kind', 'index', 'source_id', 'version', 'value')
    return [{k: row[k] for k in keys} for row in state if row['active']]


def snapshot(source, destination):
    with sqlite3.connect(source) as src, sqlite3.connect(destination) as dst:
        src.backup(dst)


def command(executable, script, frame, stem):
    raw = canonical(frame)
    save(stem.with_suffix('.request.json'), frame)
    began, before = time.monotonic_ns(), resource.getrusage(resource.RUSAGE_CHILDREN)
    timed_out = False
    with subprocess.Popen([executable, '-I', '-B', str(script)], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                          stderr=subprocess.PIPE, env={**os.environ, 'OMP_NUM_THREADS': '1', 'MKL_NUM_THREADS': '1', 'PYTHONDONTWRITEBYTECODE': '1'}) as child:
        pid = child.pid
        try:
            stdout, stderr = child.communicate(raw, timeout=180)
        except subprocess.TimeoutExpired:
            timed_out = True
            child.kill()
            stdout, stderr = child.communicate()
    ended, after = time.monotonic_ns(), resource.getrusage(resource.RUSAGE_CHILDREN)
    stem.with_suffix('.stdout').write_bytes(stdout)
    stem.with_suffix('.stderr').write_bytes(stderr)
    receipt = {'pid': pid, 'script': script.name, 'started_ns': began, 'exited_ns': ended, 'exit_code': child.returncode,
               'timed_out': timed_out, 'wall_ns': ended-began,
               'cpu_seconds': after.ru_utime+after.ru_stime-before.ru_utime-before.ru_stime,
               'kernel_input_blocks': after.ru_inblock-before.ru_inblock, 'kernel_output_blocks': after.ru_oublock-before.ru_oublock,
               'request': {'bytes': len(raw), 'sha256': sha(raw)},
               'stdout': {'bytes': len(stdout), 'sha256': sha(stdout)}, 'stderr': {'bytes': len(stderr), 'sha256': sha(stderr)}}
    try:
        parsed = json.loads(stdout)
    except (ValueError, UnicodeError):
        parsed = {'error': 'child emitted no valid JSON'}
    receipt['passed'] = child.returncode == 0 and not timed_out and not parsed.get('error')
    receipt['reported_peak_rss_kib'] = parsed.get('peak_rss_kib')
    save(stem.with_suffix('.process.json'), receipt)
    return parsed, receipt


def preflight(checkpoint, encoder, database, features, entities, expected):
    began = time.monotonic_ns()
    model = MeasuredCell(TensorCell.load(checkpoint, encoder).eval())
    owner = Owner(str(database), {'semantic': model}, features)
    try:
        audit = database_guard(owner, False)
        rows = [{'entity': i, 'result': owner.execute({'role': 'semantic', 'entity': i, 'workflow': None})} for i in entities]
        owner.stop()
        before = dict(owner.reads)
        stopped = owner.execute({'role': 'semantic', 'entity': 0, 'workflow': None})
        passed = (all(r['result']['status'] == expected for r in rows) and model.calls == 0
                  and owner.reads == before and stopped['status'] == 'owner_stopped' and owner.reads['explicit_values'] == 0)
        return {'passed': passed, 'expected_status': expected, 'rows': rows, 'model_reads': model.snapshot(),
                'parameter_sha256': model.cell.parameter_digest(), 'sql_audit': audit, 'reads': dict(owner.reads),
                'wall_ns': time.monotonic_ns()-began, 'target_blind_manager_claimed': False}
    finally:
        owner.close()


def score(report, state, changed):
    scored = {}
    for arm in ('parameter', 'exact_sql'):
        rows = {r['entity']: r['result'] for a in report.get('arms', []) if a['arm'] == arm for r in a['rows']}
        groups = {name: {'correct': 0, 'count': 0} for name in ('active', 'retention', 'changed', 'revoked')}
        for source in state:
            result = rows.get(source['index'], {})
            okay = result.get('status') == ('read' if source['active'] else 'revoked')
            okay &= result.get('value') == (source['value'] if source['active'] else None)
            names = ['active' if source['active'] else 'revoked']
            if source['active']:
                names.append('changed' if source['index'] in changed else 'retention')
            for name in names:
                groups[name]['count'] += 1
                groups[name]['correct'] += int(okay)
        scored[arm] = groups
    return scored


def storage(state, database, checkpoint, seed_root, encoder_bytes, canonical_bytes):
    return {'current_checkpoint_bytes': file_bytes(checkpoint),
            'retained_checkpoint_bytes': sum(file_bytes(p) for p in seed_root.glob('stage-*/**/checkpoint') if p.is_dir()),
            'source_sqlite_bytes': Path(database).stat().st_size,
            'active_source_payload_json_bytes': len(canonical([r['value'] for r in state if r['active']])),
            'all_source_payload_json_bytes': len(canonical([r['value'] for r in state])),
            'source_version_record_json_bytes': len(canonical(state)), 'shared_encoder_reference_bytes': encoder_bytes,
            'canonical_feature_file_bytes': canonical_bytes,
            'shared_encoder_is_not_copied_or_rerun': True}


def ensure_space(output, seed, stage):
    while shutil.disk_usage(output).free < 20*1024*1024:
        save(output/'PAUSED.json', {'seed': seed, 'stage': stage, 'free_bytes': shutil.disk_usage(output).free,
                                   'reason': 'below preregistered 20 MiB minimum', 'evidence_deleted': False})
        print(json.dumps({'paused_low_space': True, 'seed': seed, 'stage': stage}), flush=True)
        time.sleep(5)


def run(args):
    began, own_cpu = time.monotonic_ns(), time.process_time_ns()
    torch.set_num_threads(1)
    protocol_path = HERE/'LONGRUN_PROTOCOL.json'
    protocol_raw = protocol_path.read_bytes()
    protocol_sha = sha(protocol_raw)
    if (HERE/'LONGRUN_PROTOCOL.sha256').read_text().strip() != protocol_sha:
        raise ValueError('preregistration SHA does not match')
    protocol = json.loads(protocol_raw)
    if protocol['seeds'] != [731, 732, 733] or protocol['cycles_per_seed'] != 64:
        raise ValueError('registered full horizon required')
    original = Path(protocol['initial_study'])
    training = json.loads((original/'models/TRAINING.json').read_bytes())
    process = json.loads((original/'training.process.json').read_bytes())
    if process['exit_code'] != 0 or process['pid'] != training['pid'] or process['timed_out']:
        raise ValueError('original trainer has not successfully exited')
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    if (output/'FREEZE.json').exists():
        raise ValueError('do not overwrite or silently resume an existing experiment')
    inputs = output/'inputs'
    inputs.mkdir()
    for name in ('sources.json', 'canonical.npz', 'development-encoder.json', 'training.process.json'):
        shutil.copyfile(original/name, inputs/name)
    encoder_reference = json.loads((inputs/'development-encoder.json').read_bytes())
    encoder = training['encoder_sha']
    if encoder != encoder_reference['base_encoder_sha']:
        raise ValueError('encoder identity differs from training')
    features, feature_id = canonical_features(inputs/'canonical.npz')
    sources = [r for r in json.loads((inputs/'sources.json').read_bytes()) if r['kind'] == 'semantic']
    if [r['index'] for r in sources] != list(range(8)):
        raise ValueError('initial semantic source inventory')
    for seed in protocol['seeds']:
        shutil.copytree(original/'models'/f'seed-{seed}'/'semantic', inputs/f'seed-{seed}')
    monitor_root = ROOT.parent/'memory-cell-v9'/'learning'
    source_files = [*HERE.glob('*.py'), protocol_path, ROOT/'owner.py', ROOT/'reader.py',
                    ROOT/'tensor_cell.py', ROOT/'runtime_contract.py',
                    *[monitor_root/name for name in ('resource_monitor.py', 'resource_samples.py', 'resource_cleanup.py')]]
    frozen = {str(p): identity(p) for p in source_files}
    freeze = {'schema': 'hepta.memory.adapter-longrun-freeze.v1', 'protocol_sha256': protocol_sha,
              'created_ns': time.monotonic_ns(), 'source_files': frozen,
              'initial_training_receipt': identity(original/'models/TRAINING.json'), 'initial_training_pid': training['pid'],
              'initial_trainer_exited_ns': process['exited_ns'], 'input_files': {str(p.relative_to(inputs)): identity(p) for p in inputs.rglob('*') if p.is_file()},
              'held_or_main_result_opened': False, 'reader_targets_supplied': False}
    save(output/'FREEZE.json', freeze)
    phase_records, stage_records, initial_records = [], [], []
    process_records, failures = [], []

    def read(checkpoint, database, stem):
        frame = {'checkpoint': str(checkpoint), 'encoder_sha': encoder, 'database': str(database),
                 'canonical_features_path': str(inputs/'canonical.npz'), 'protocol_sha256': protocol_sha}
        result, receipt = command(args.python, HERE/'owner_read.py', frame, stem)
        process_records.append(receipt)
        if not receipt['passed']:
            failures.append({'phase': str(stem.relative_to(output)), 'kind': 'read', 'process': receipt})
        return result, receipt

    for seed in protocol['seeds']:
        seed_root = output/f'seed-{seed}'
        seed_root.mkdir()
        state = [{**copy.deepcopy(r), 'active': True} for r in sources]
        database = seed_root/'owner.sqlite'
        create(database, sources)
        checkpoint = inputs/f'seed-{seed}'
        initial, initial_process = read(checkpoint, database, seed_root/'initial-read')
        initial_records.append({'seed': seed, 'quality': score(initial, state, []), 'process': initial_process})
        pending = None
        for stage in range(1, 65):
            ensure_space(output, seed, stage)
            stage_began = time.monotonic_ns()
            stage_root = seed_root/f'stage-{stage:03d}'
            stage_root.mkdir()
            changed = sorted({stage % 8} | ({pending} if pending is not None else set()))
            for entity in changed:
                row = state[entity]
                row.update(version=row['version']+1, active=True, value=policy(seed, stage, entity))
                row['source_id'] = sha(canonical(['hepta.adapter.longrun.source.v1', seed, entity, row['version'], stage]))
            with sqlite3.connect(database) as db:
                for entity in changed:
                    row = state[entity]
                    db.execute('UPDATE sources SET identity=?,version=?,active=1,payload=? WHERE kind=? AND idx=?',
                               (row['source_id'], row['version'], json.dumps(row['value']), 'semantic', entity))
            reentered, pending = pending, None
            current_phases = []
            for mode in (['update', 'rebuild'] if stage % 8 == 0 else ['update']):
                phase_root = stage_root/mode
                phase_root.mkdir()
                deleted = None
                if mode == 'rebuild':
                    deleted = (stage // 8) % 8
                    state[deleted]['active'] = False
                    with sqlite3.connect(database) as db:
                        db.execute("UPDATE sources SET active=0 WHERE kind='semantic' AND idx=?", (deleted,))
                    pending = deleted
                phase_database = phase_root/'sources.sqlite'
                snapshot(database, phase_database)
                save(phase_root/'source-state.json', state)
                probe = preflight(checkpoint, encoder, phase_database, features,
                                  [deleted] if mode == 'rebuild' else changed, 'revoked' if mode == 'rebuild' else 'stale_source')
                save(phase_root/'preflight.json', probe)
                if not probe['passed']:
                    failures.append({'seed': seed, 'stage': stage, 'mode': mode, 'kind': 'preflight'})
                source_path = phase_root/'active-train-sources.json'
                save(source_path, active_rows(state))
                next_checkpoint = phase_root/'checkpoint'
                request = {'mode': mode, 'checkpoint': str(checkpoint), 'initial_checkpoint': str(inputs/f'seed-{seed}'),
                           'output': str(next_checkpoint), 'canonical_features_path': str(inputs/'canonical.npz'),
                           'source_rows_path': str(source_path), 'encoder_sha': encoder, 'seed': seed, 'stage': stage,
                           'protocol_path': str(protocol_path), 'protocol_sha256': protocol_sha}
                fit, fit_process = command(args.python, HERE/'fit_worker.py', request, phase_root/'fit')
                process_records.append(fit_process)
                if fit_process['passed']:
                    checkpoint = next_checkpoint
                else:
                    failures.append({'seed': seed, 'stage': stage, 'mode': mode, 'kind': 'fit', 'process': fit_process})
                raw, read_process = read(checkpoint, phase_database, phase_root/'read')
                causal = read_process['started_ns'] > fit_process['exited_ns'] and read_process['pid'] != fit_process['pid']
                if not causal:
                    failures.append({'seed': seed, 'stage': stage, 'mode': mode, 'kind': 'process-order'})
                record = {'seed': seed, 'stage': stage, 'mode': mode, 'changed_entities': changed,
                          'reentered_entity': reentered, 'deleted_entity': deleted, 'preflight_passed': probe['passed'],
                          'trainer_passed': fit_process['passed'], 'reader_passed': read_process['passed'],
                          'fresh_reader_after_trainer_exit': causal, 'quality': score(raw, state, changed),
                          'model': {'parameter_sha256': raw.get('parameter_sha256'), 'checkpoint': str(checkpoint.relative_to(output))},
                          'fit_wall_ns': fit_process['wall_ns'], 'fit_cpu_seconds': fit_process['cpu_seconds'],
                          'read_process_wall_ns': read_process['wall_ns'], 'read_process_cpu_seconds': read_process['cpu_seconds'],
                          'baseline_and_parameter_read_wall_ns': {a['arm']: a['read_wall_ns'] for a in raw.get('arms', [])},
                          'storage': storage(state, phase_database, checkpoint, seed_root, encoder_reference['base_bytes'], feature_id['bytes'])}
                save(phase_root/'RESULT.json', record)
                current_phases.append(record)
                phase_records.append(record)
            final = current_phases[-1]
            stage_record = {'seed': seed, 'stage': stage, 'phase_count': len(current_phases), 'quality': final['quality'],
                            'final_model': final['model'], 'wall_ns': time.monotonic_ns()-stage_began,
                            'phase_paths': [f"seed-{seed}/stage-{stage:03d}/{p['mode']}/RESULT.json" for p in current_phases]}
            save(stage_root/'CYCLE.json', stage_record)
            stage_records.append(stage_record)
            if stage % 8 == 0:
                print(json.dumps({'seed': seed, 'stage': stage, 'completed_cycles': len(stage_records), 'failures': len(failures),
                                  'final_quality': final['quality']['parameter'], 'free_bytes': shutil.disk_usage(output).free}), flush=True)
    if {str(p): identity(p) for p in source_files} != frozen:
        failures.append({'kind': 'source-changed-after-freeze'})
    aggregate = {arm: {group: {'correct': 0, 'count': 0} for group in ('active', 'retention', 'changed', 'revoked')}
                 for arm in ('parameter', 'exact_sql')}
    for cycle in stage_records:
        for arm, groups in cycle['quality'].items():
            for group, counts in groups.items():
                for key, value in counts.items():
                    aggregate[arm][group][key] += value
    summary = {'schema': 'hepta.memory.adapter-longrun-result.v1', 'protocol_sha256': protocol_sha,
               'seeds': protocol['seeds'], 'cycles_per_seed': 64, 'completed_cycles': len(stage_records),
               'phase_count': len(phase_records), 'update_fits_attempted': sum(p['mode'] == 'update' for p in phase_records),
               'rebuild_fits_attempted': sum(p['mode'] == 'rebuild' for p in phase_records), 'failures': failures,
               'initial_quality': initial_records, 'final_cycle_aggregate': aggregate,
               'all_preflight_passed': all(p['preflight_passed'] for p in phase_records),
               'all_readers_after_trainer_exit': all(p['fresh_reader_after_trainer_exit'] for p in phase_records),
               'all_steps_retained': len(stage_records) == 192 and len(phase_records) == 216,
               'cost': {'driver_wall_ns_before_summary': time.monotonic_ns()-began,
                        'driver_own_cpu_ns_before_summary': time.process_time_ns()-own_cpu,
                        'children_cpu_seconds_including_failures': sum(p['cpu_seconds'] for p in process_records),
                        'children_wall_ns_including_failures': sum(p['wall_ns'] for p in process_records),
                        'training_children_cpu_seconds': sum(p['cpu_seconds'] for p in process_records if p['script'] == 'fit_worker.py'),
                        'reader_children_cpu_seconds': sum(p['cpu_seconds'] for p in process_records if p['script'] == 'owner_read.py'),
                        'kernel_output_blocks_children': sum(p['kernel_output_blocks'] for p in process_records),
                        'current_output_regular_bytes_before_summary': file_bytes(output),
                        'initial_checkpoint_copies_bytes': sum(file_bytes(inputs/f'seed-{seed}') for seed in protocol['seeds']),
                        'retained_fitted_checkpoint_bytes': sum(file_bytes(p) for p in output.glob('seed-*/stage-*/**/checkpoint') if p.is_dir()),
                        'current_source_sqlite_bytes': sum(p.stat().st_size for p in output.glob('seed-*/owner.sqlite')),
                        'historical_source_sqlite_snapshot_bytes': sum(p.stat().st_size for p in output.rglob('sources.sqlite')),
                        'retained_explicit_source_json_bytes': sum(p.stat().st_size for p in output.rglob('*sources.json')) +
                                                               sum(p.stat().st_size for p in output.rglob('source-state.json')),
                        'shared_encoder_reference_bytes': encoder_reference['base_bytes'],
                        'canonical_features_bytes': feature_id['bytes'],
                        'peak_and_integral_authority': 'outer resource.json; independent child maxima are not summed'},
               'native_runtime_executed': False, 'held_inputs_opened': False,
               'interpretation': protocol['cost_interpretation']}
    save(output/'RESULT.json', summary)
    save(output/'CYCLES.json', stage_records)
    print(json.dumps({'complete': True, 'cycles': len(stage_records), 'phases': len(phase_records), 'failures': len(failures),
                      'quality': aggregate, 'result': str(output/'RESULT.json')}), flush=True)
    return 0 if summary['all_steps_retained'] else 1


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--python', default=sys.executable)
    args = parser.parse_args()
    try:
        raise SystemExit(run(args))
    except Exception as error:
        args.output.mkdir(parents=True, exist_ok=True)
        save(args.output/'FAILED.json', {'error': f'{type(error).__name__}: {error}', 'pid': os.getpid()})
        raise
