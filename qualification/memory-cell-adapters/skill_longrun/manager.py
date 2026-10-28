"""Fixed 64-cycle skill maintenance; only the manager owns source truth."""

import argparse
import copy
import json
import os
from pathlib import Path
import shutil
import sqlite3
import sys
import time

import torch

HERE = Path(__file__).resolve().parent
ADAPTER = HERE.parent
sys.path.insert(0, str(HERE))
from common import (GROUPS, active_rows, canonical, command, executions, file_bytes,
                    identity, save, sha, skill_rows, snapshot, validate_cell, validate_program)
from owner_read import guard
from reader import canonical_features
from targets import mutate
from tensor_cell import CellConfig, OutputSpec, TensorCell


def score(report, state, changed):
    quality, execution_quality = {}, {}
    for arm in ('parameter', 'exact_sql'):
        rows = {r['workflow']: r for a in report.get('arms', []) if a['arm'] == arm for r in a['rows']}
        groups = {name: {'correct': 0, 'count': 0} for name in GROUPS}
        execution_groups = copy.deepcopy(groups)
        for source in state:
            observed = rows.get(source['index'], {})
            result = observed.get('result', {})
            expected_status = 'read' if source['active'] else 'revoked'
            program_okay = (result.get('status') == expected_status and
                            result.get('value') == (source['value'] if source['active'] else None))
            execution_okay = (result.get('status') == expected_status and
                              observed.get('executions') == (executions(source['value']) if source['active'] else []))
            names = ['active' if source['active'] else 'revoked']
            if source['active']:
                names.append('changed' if source['index'] in changed else 'retention')
            for group in names:
                groups[group]['count'] += 1
                groups[group]['correct'] += int(program_okay)
                execution_groups[group]['count'] += 1
                execution_groups[group]['correct'] += int(execution_okay)
        quality[arm], execution_quality[arm] = groups, execution_groups
    return quality, execution_quality


def aggregate(records, key):
    counts = {arm: {group: {'correct': 0, 'count': 0} for group in GROUPS}
              for arm in ('parameter', 'exact_sql')}
    for record in records:
        for arm, groups in record[key].items():
            for group, result in groups.items():
                for name, count in result.items():
                    counts[arm][group][name] += count
    return counts


def run(args):
    began, own_cpu = time.monotonic_ns(), time.process_time_ns()
    torch.set_num_threads(1)
    torch.use_deterministic_algorithms(True)
    protocol_path = HERE/'LONGRUN_PROTOCOL.json'
    protocol_raw = protocol_path.read_bytes()
    protocol_sha = sha(protocol_raw)
    if (HERE/'LONGRUN_PROTOCOL.sha256').read_text().strip() != protocol_sha:
        raise ValueError('protocol SHA does not match')
    protocol = json.loads(protocol_raw)
    if protocol['seeds'] != [731, 732, 733] or protocol['cycles_per_seed'] != 64:
        raise ValueError('registered full skill horizon required')
    original = args.initial_study.resolve()
    if original != Path(protocol['initial_study']):
        raise ValueError('initial-study namespace differs from protocol')
    training = json.loads((original/'models/TRAINING.json').read_bytes())
    historical = json.loads((original/'training.process.json').read_bytes())
    if historical['exit_code'] != 0 or historical['pid'] != training['pid'] or historical['timed_out']:
        raise ValueError('original training was not a successful completed process')
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    if (output/'FREEZE.json').exists() or (output/'inputs').exists():
        raise ValueError('existing experiment cannot be overwritten or silently resumed')
    inputs = output/'inputs'
    inputs.mkdir()
    for name in ('sources.json', 'canonical.npz', 'development-encoder.json', 'training.process.json'):
        shutil.copyfile(original/name, inputs/name)
    shutil.copyfile(original/'models/TRAINING.json', inputs/'TRAINING.json')
    encoder_reference = json.loads((inputs/'development-encoder.json').read_bytes())
    encoder = training['encoder_sha']
    if encoder != encoder_reference['base_encoder_sha']:
        raise ValueError('encoder identity differs from initial training')
    features, feature_identity = canonical_features(inputs/'canonical.npz')
    source_keys = ('kind', 'index', 'source_id', 'version', 'value')
    declared = [{k: row[k] for k in source_keys} for row in json.loads((inputs/'sources.json').read_bytes())
                if row['kind'] == 'skill']
    if [row['index'] for row in declared] != list(range(8)):
        raise ValueError('eight initial skill sources required')
    for row in declared:
        validate_program(row['value'])
    for seed in protocol['seeds']:
        shutil.copytree(original/'models'/f'seed-{seed}'/'skill', inputs/f'seed-{seed}')
        database_name = f'read-seed-{seed}-event-0.sqlite'
        shutil.copyfile(original/database_name, inputs/database_name)
        if active_rows(skill_rows(inputs/database_name)) != declared:
            raise ValueError('initial SQLite skill sources differ from declared source bytes')
        cell = TensorCell.load(inputs/f'seed-{seed}', encoder)
        validate_cell(cell)
        if cell.config.seed != seed or cell.source_ids != {r['source_id'] for r in declared}:
            raise ValueError('initial fitted cell seed or source support differs')
        config = CellConfig(f'skill-untrained-{seed}', input_dim=cell.config.input_dim, rank=cell.config.rank,
                            outputs=tuple(OutputSpec(s.name, s.kind, s.size, s.weight) for s in cell.config.outputs), seed=seed)
        untrained = TensorCell(config, encoder)
        validate_cell(untrained)
        untrained.save(inputs/f'untrained-seed-{seed}')
    monitor_root = ADAPTER.parent/'memory-cell-v9'/'learning'
    source_files = sorted(set([*HERE.glob('*.py'), protocol_path, HERE/'LONGRUN_PROTOCOL.sha256',
        *[ADAPTER/name for name in ('owner.py', 'reader.py', 'routing.py', 'tensor_cell.py', 'runtime_contract.py')],
        ADAPTER/'longrun/ci_run.py', ADAPTER/'evidence/formal-01/restore.py',
        *[monitor_root/name for name in ('resource_monitor.py', 'resource_samples.py', 'resource_cleanup.py')]]))
    frozen = {str(path): identity(path) for path in source_files}
    save(output/'FREEZE.json', {'schema': 'hepta.memory.adapter-longrun-freeze.v1', 'scope': 'skill',
        'protocol_sha256': protocol_sha, 'created_ns': time.monotonic_ns(), 'source_files': frozen,
        'initial_training_receipt': identity(original/'models/TRAINING.json'), 'initial_training_pid': training['pid'],
        'initial_trainer_exited_ns_historical_clock': historical['exited_ns'],
        'historical_clock_compared_to_runner': False,
        'input_files': {str(path.relative_to(inputs)): identity(path) for path in sorted(inputs.rglob('*')) if path.is_file()},
        'held_or_main_result_opened': False, 'reader_targets_supplied': False, 'native_runtime_executed': False})
    phases, cycles, initial_records, processes, failures = [], [], [], [], []

    def read(checkpoint, database, stem):
        request = {'checkpoint': str(checkpoint), 'encoder_sha': encoder, 'database': str(database),
                   'canonical_features_path': str(inputs/'canonical.npz'), 'protocol_sha256': protocol_sha}
        report, process = command(args.python, HERE/'owner_read.py', request, stem)
        processes.append(process)
        if not process['passed']:
            failures.append({'phase': str(stem.relative_to(output)), 'kind': 'read', 'process': process})
        return report, process

    for seed in protocol['seeds']:
        seed_root = output/f'seed-{seed}'
        seed_root.mkdir()
        database = seed_root/'owner.sqlite'
        snapshot(inputs/f'read-seed-{seed}-event-0.sqlite', database)
        state = skill_rows(database)
        checkpoint = inputs/f'seed-{seed}'
        initial_database = seed_root/'initial-sources.sqlite'
        snapshot(database, initial_database)
        initial, initial_process = read(checkpoint, initial_database, seed_root/'initial-read')
        quality, execution_quality = score(initial, state, [])
        initial_records.append({'seed': seed, 'quality': quality, 'execution_quality': execution_quality, 'process': initial_process})
        pending = None
        for stage in range(1, 65):
            if shutil.disk_usage(output).free < 20*1024*1024:
                save(output/'LOW_SPACE.json', {'seed': seed, 'stage': stage, 'free_bytes': shutil.disk_usage(output).free,
                    'reason': 'below preregistered 20 MiB minimum', 'evidence_deleted': False})
                raise OSError('insufficient space; evidence retained and run aborted')
            stage_began = time.monotonic_ns()
            stage_root = seed_root/f'stage-{stage:03d}'
            stage_root.mkdir()
            changed = sorted({stage % 8} | ({pending} if pending is not None else set()))
            for workflow in changed:
                state[workflow] = mutate(state[workflow], seed, stage)
            with sqlite3.connect(database) as db:
                for workflow in changed:
                    row = state[workflow]
                    db.execute("UPDATE sources SET identity=?,version=?,active=1,payload=? WHERE kind='skill' AND idx=?",
                               (row['source_id'], row['version'], json.dumps(row['value']), workflow))
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
                        db.execute("UPDATE sources SET active=0 WHERE kind='skill' AND idx=?", (deleted,))
                    pending = deleted
                phase_database = phase_root/'sources.sqlite'
                snapshot(database, phase_database)
                if skill_rows(phase_database) != state:
                    raise ValueError('source snapshot does not match current authored skill state')
                save(phase_root/'source-state.json', state)
                probe = guard(checkpoint, encoder, phase_database, features,
                              [deleted] if mode == 'rebuild' else changed,
                              'revoked' if mode == 'rebuild' else 'stale_source')
                save(phase_root/'preflight.json', probe)
                if not probe['passed']:
                    failures.append({'seed': seed, 'stage': stage, 'mode': mode, 'kind': 'preflight'})
                source_path = phase_root/'active-train-sources.json'
                save(source_path, active_rows(state))
                next_checkpoint = phase_root/'checkpoint'
                request = {'mode': mode, 'checkpoint': str(checkpoint), 'initial_checkpoint': str(inputs/f'untrained-seed-{seed}'),
                           'output': str(next_checkpoint), 'canonical_features_path': str(inputs/'canonical.npz'),
                           'source_rows_path': str(source_path), 'database': str(phase_database),
                           'encoder_sha': encoder, 'seed': seed, 'stage': stage,
                           'protocol_path': str(protocol_path), 'protocol_sha256': protocol_sha}
                fitted, fit_process = command(args.python, HERE/'fit_worker.py', request, phase_root/'fit')
                processes.append(fit_process)
                if fit_process['passed']:
                    checkpoint = next_checkpoint
                else:
                    failures.append({'seed': seed, 'stage': stage, 'mode': mode, 'kind': 'fit', 'process': fit_process})
                report, read_process = read(checkpoint, phase_database, phase_root/'read')
                causal = read_process['started_ns'] > fit_process['exited_ns'] and read_process['pid'] != fit_process['pid']
                if not causal:
                    failures.append({'seed': seed, 'stage': stage, 'mode': mode, 'kind': 'process-order'})
                quality, execution_quality = score(report, state, changed)
                record = {'seed': seed, 'stage': stage, 'mode': mode, 'changed_workflows': changed,
                    'reentered_workflow': reentered, 'deleted_workflow': deleted,
                    'preflight_passed': probe['passed'], 'trainer_passed': fit_process['passed'],
                    'reader_passed': read_process['passed'], 'fresh_reader_after_trainer_exit': causal,
                    'quality': quality, 'execution_quality': execution_quality,
                    'model': {'parameter_sha256': report.get('parameter_sha256'), 'checkpoint': str(checkpoint.relative_to(output))},
                    'fit_wall_ns': fit_process['wall_ns'], 'fit_cpu_seconds': fit_process['cpu_seconds'],
                    'read_process_wall_ns': read_process['wall_ns'], 'read_process_cpu_seconds': read_process['cpu_seconds'],
                    'baseline_and_parameter_read_wall_ns': {a['arm']: a['read_wall_ns'] for a in report.get('arms', [])},
                    'storage': {'current_checkpoint_bytes': file_bytes(checkpoint), 'source_sqlite_bytes': phase_database.stat().st_size,
                        'active_source_payload_json_bytes': len(canonical([r['value'] for r in state if r['active']])),
                        'all_source_payload_json_bytes': len(canonical([r['value'] for r in state])),
                        'source_version_record_json_bytes': len(canonical(state)),
                        'shared_encoder_reference_bytes': encoder_reference['base_bytes'],
                        'canonical_feature_file_bytes': feature_identity['bytes']}}
                save(phase_root/'RESULT.json', record)
                current_phases.append(record)
                phases.append(record)
            final = current_phases[-1]
            cycle = {'seed': seed, 'stage': stage, 'phase_count': len(current_phases),
                     'quality': final['quality'], 'execution_quality': final['execution_quality'],
                     'final_model': final['model'], 'wall_ns': time.monotonic_ns()-stage_began,
                     'phase_paths': [f"seed-{seed}/stage-{stage:03d}/{p['mode']}/RESULT.json" for p in current_phases]}
            save(stage_root/'CYCLE.json', cycle)
            cycles.append(cycle)
            if stage % 8 == 0:
                print(json.dumps({'seed': seed, 'stage': stage, 'completed_cycles': len(cycles), 'failures': len(failures),
                    'final_quality': final['quality']['parameter'], 'execution_quality': final['execution_quality']['parameter']}), flush=True)
    if {str(path): identity(path) for path in source_files} != frozen:
        failures.append({'kind': 'source-changed-after-freeze'})
    all_quality = [groups for record in [*initial_records, *phases] for key in ('quality', 'execution_quality')
                   for groups in record[key].values()]
    summary = {'schema': 'hepta.memory.adapter-skill-longrun-result.v1', 'scope': 'skill', 'protocol_sha256': protocol_sha,
        'seeds': protocol['seeds'], 'cycles_per_seed': 64, 'completed_cycles': len(cycles), 'phase_count': len(phases),
        'update_fits_attempted': sum(p['mode'] == 'update' for p in phases),
        'rebuild_fits_attempted': sum(p['mode'] == 'rebuild' for p in phases), 'failures': failures,
        'initial_quality': initial_records, 'final_cycle_aggregate': aggregate(cycles, 'quality'),
        'final_cycle_execution_aggregate': aggregate(cycles, 'execution_quality'),
        'all_phase_aggregate': aggregate(phases, 'quality'), 'all_phase_execution_aggregate': aggregate(phases, 'execution_quality'),
        'quality_all_correct': all(c['correct'] == c['count'] for groups in all_quality for c in groups.values()),
        'all_preflight_passed': all(p['preflight_passed'] for p in phases),
        'all_readers_after_trainer_exit': all(p['fresh_reader_after_trainer_exit'] for p in phases),
        'all_steps_retained': len(cycles) == 192 and len(phases) == 216,
        'cost': {'driver_wall_ns_before_summary': time.monotonic_ns()-began,
            'driver_own_cpu_ns_before_summary': time.process_time_ns()-own_cpu,
            'children_cpu_seconds_including_failures': sum(p['cpu_seconds'] for p in processes),
            'children_wall_ns_including_failures': sum(p['wall_ns'] for p in processes),
            'training_children_cpu_seconds': sum(p['cpu_seconds'] for p in processes if p['script'] == 'fit_worker.py'),
            'reader_children_cpu_seconds': sum(p['cpu_seconds'] for p in processes if p['script'] == 'owner_read.py'),
            'kernel_output_blocks_children': sum(p['kernel_output_blocks'] for p in processes),
            'current_output_regular_bytes_before_summary': file_bytes(output),
            'initial_checkpoint_copies_bytes': sum(file_bytes(inputs/f'seed-{seed}') for seed in protocol['seeds']),
            'untrained_checkpoint_bytes': sum(file_bytes(inputs/f'untrained-seed-{seed}') for seed in protocol['seeds']),
            'retained_fitted_checkpoint_bytes': sum(file_bytes(p) for p in output.glob('seed-*/stage-*/*/checkpoint') if p.is_dir()),
            'retained_sample_schedule_bytes': sum(p.stat().st_size for p in output.rglob('sample-schedule.i64')),
            'current_source_sqlite_bytes': sum(p.stat().st_size for p in output.glob('seed-*/owner.sqlite')),
            'historical_source_sqlite_snapshot_bytes': sum(p.stat().st_size for p in output.rglob('sources.sqlite')),
            'initial_source_sqlite_snapshot_bytes': sum(p.stat().st_size for p in output.glob('seed-*/initial-sources.sqlite')),
            'retained_explicit_source_json_bytes': sum(p.stat().st_size for p in output.rglob('*sources.json')) +
                sum(p.stat().st_size for p in output.rglob('source-state.json')),
            'shared_encoder_reference_bytes': encoder_reference['base_bytes'], 'canonical_features_bytes': feature_identity['bytes'],
            'peak_and_integral_authority': 'outer resource.json; independent child maxima are not summed'},
        'native_runtime_executed': False, 'held_inputs_opened': False, 'actual_public_programs_executed': True,
        'interpretation': protocol['cost_interpretation']}
    save(output/'RESULT.json', summary)
    save(output/'CYCLES.json', cycles)
    save(output/'PROCESSES.json', processes)
    print(json.dumps({'complete': True, 'cycles': len(cycles), 'phases': len(phases), 'failures': len(failures),
                      'quality_all_correct': summary['quality_all_correct'], 'result': str(output/'RESULT.json')}), flush=True)
    return 0 if summary['all_steps_retained'] and not failures else 1


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--python', default=sys.executable)
    parser.add_argument('--initial-study', type=Path, default=Path('/workspace/scratch/76e2020e4b36/memory-adapter-formal-01'))
    args = parser.parse_args()
    try:
        raise SystemExit(run(args))
    except Exception as error:
        args.output.mkdir(parents=True, exist_ok=True)
        save(args.output/'FAILED.json', {'error': f'{type(error).__name__}: {error}', 'pid': os.getpid()})
        raise
