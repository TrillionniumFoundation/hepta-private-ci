"""Resume the infrastructure-interrupted fixed experiment without rerunning fits.

The original manager, workers, protocol and evidence remain unchanged. This
controller restores the exact interrupted source state, changes only the pending
fit's output path, then follows the same deterministic schedule and budgets.
"""

import argparse
import copy
import json
import os
from pathlib import Path
import resource
import shutil
import sqlite3
import sys
import time

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import manager as m


def tree_identity(root):
    rows = [(str(p.relative_to(root)), m.identity(p)) for p in sorted(root.rglob('*')) if p.is_file()]
    return {'sha256': m.sha(m.canonical(rows)), 'files': len(rows), 'bytes': sum(r[1]['bytes'] for r in rows)}


def sql_state(path):
    with sqlite3.connect(path) as db:
        rows = db.execute("SELECT idx,identity,version,active,payload FROM sources WHERE kind='semantic' ORDER BY idx").fetchall()
    return [{'index': r[0], 'source_id': r[1], 'version': r[2], 'active': bool(r[3]), 'value': json.loads(r[4])} for r in rows]


def run(args):
    began, cpu = time.monotonic_ns(), time.process_time_ns()
    m.torch.set_num_threads(1)
    plan_raw = (HERE/'RESUME_PLAN.json').read_bytes()
    plan = json.loads(plan_raw)
    old, output = Path(plan['old_output']), args.output.resolve()
    if output != Path(plan['resume_output']) or (output/'FREEZE.json').exists():
        raise ValueError('fresh registered resume output required')
    output.mkdir(exist_ok=True, parents=True)
    freeze = json.loads((old/'FREEZE.json').read_bytes())
    if any(m.identity(Path(p)) != expected for p, expected in freeze['source_files'].items()):
        raise ValueError('original frozen source changed before resume')
    protocol_sha = (HERE/'LONGRUN_PROTOCOL.sha256').read_text().strip()
    if protocol_sha != plan['original_protocol_sha256']:
        raise ValueError('original training protocol identity changed')
    if len(list(old.glob('seed-*/stage-*/CYCLE.json'))) != 79:
        raise ValueError('resume requires the verified original 79 complete cycles')
    old_tree = tree_identity(old)
    inputs = old/'inputs'
    encoder_info = json.loads((inputs/'development-encoder.json').read_bytes())
    encoder = encoder_info['base_encoder_sha']
    features, feature_id = m.canonical_features(inputs/'canonical.npz')
    initial_sources = [r for r in json.loads((inputs/'sources.json').read_bytes()) if r['kind'] == 'semantic']
    interrupted = old/'seed-732'/'stage-016'/'rebuild'
    pending_raw = (interrupted/'fit.request.json').read_bytes()
    pending_request = json.loads(pending_raw)
    state = json.loads((interrupted/'source-state.json').read_bytes())
    expected_state = [{k: row[k] for k in ('index', 'source_id', 'version', 'active', 'value')} for row in state]
    if sql_state(interrupted/'sources.sqlite') != expected_state or sql_state(old/'seed-732'/'owner.sqlite') != expected_state:
        raise ValueError('recovery source state differs from the frozen pending request')
    if (pending_request['seed'], pending_request['stage'], pending_request['mode']) != (732, 16, 'rebuild'):
        raise ValueError('wrong interrupted operation')
    if (interrupted/'checkpoint').exists() or (interrupted/'fit.process.json').exists():
        raise ValueError('pending fit may already be complete; refusing duplicate training')
    new_sources = {str(p): m.identity(p) for p in (HERE/'resume.py', HERE/'RESUME_PLAN.json')}
    new_freeze = {'schema': 'hepta.memory.adapter-longrun-resume-freeze.v1', 'created_ns': time.monotonic_ns(),
                  'protocol_sha256': protocol_sha, 'resume_plan_sha256': m.sha(plan_raw), 'source_files': new_sources,
                  'original_freeze': m.identity(old/'FREEZE.json'), 'original_tree_before_resume': old_tree,
                  'interruption_receipt': m.identity(old/'INFRA_INTERRUPTION.json'),
                  'pending_fit_request_sha256': m.sha(pending_raw), 'source_state_verified': True,
                  'fit_hyperparameters_changed': False, 'held_inputs_opened': False}
    m.save(output/'FREEZE.json', new_freeze)
    phases, cycles, processes, failures = [], [], [], []

    def read(checkpoint, database, stem):
        frame = {'checkpoint': str(checkpoint), 'encoder_sha': encoder, 'database': str(database),
                 'canonical_features_path': str(inputs/'canonical.npz'), 'protocol_sha256': protocol_sha}
        raw, receipt = m.command(args.python, HERE/'owner_read.py', frame, stem)
        processes.append(receipt)
        if not receipt['passed']:
            failures.append({'kind': 'read', 'path': str(stem), 'process': receipt})
        return raw, receipt

    def phase(seed, stage, mode, state, changed, reentered, deleted, database, checkpoint, seed_root, original=None):
        phase_root = seed_root/f'stage-{stage:03d}'/mode
        phase_root.mkdir(parents=True)
        phase_database = phase_root/'sources.sqlite'
        m.snapshot(database, phase_database)
        m.save(phase_root/'source-state.json', state)
        probe = m.preflight(checkpoint, encoder, phase_database, features,
                            [deleted] if mode == 'rebuild' else changed, 'revoked' if mode == 'rebuild' else 'stale_source')
        m.save(phase_root/'preflight.json', probe)
        if not probe['passed']:
            failures.append({'kind': 'preflight', 'seed': seed, 'stage': stage, 'mode': mode})
        source_path = phase_root/'active-train-sources.json'
        m.save(source_path, m.active_rows(state))
        next_checkpoint = phase_root/'checkpoint'
        frame = {'mode': mode, 'checkpoint': str(checkpoint), 'initial_checkpoint': str(inputs/f'seed-{seed}'),
                 'output': str(next_checkpoint), 'canonical_features_path': str(inputs/'canonical.npz'),
                 'source_rows_path': str(source_path), 'encoder_sha': encoder, 'seed': seed, 'stage': stage,
                 'protocol_path': str(HERE/'LONGRUN_PROTOCOL.json'), 'protocol_sha256': protocol_sha}
        if original is not None:
            frame = {**original, 'output': str(next_checkpoint)}
            changes = [key for key in frame if frame[key] != original[key]]
            if changes != ['output']:
                raise ValueError('resume changed more than the pending output path')
            m.save(phase_root/'REQUEST_RELOCATION.json', {'original_request_sha256': m.sha(pending_raw),
                     'new_request_sha256': m.sha(m.canonical(frame)), 'changed_fields': changes,
                     'old_output': original['output'], 'new_output': frame['output'], 'all_training_inputs_identical': True})
        fit, fit_process = m.command(args.python, HERE/'fit_worker.py', frame, phase_root/'fit')
        processes.append(fit_process)
        if fit_process['passed']:
            checkpoint = next_checkpoint
        else:
            failures.append({'kind': 'fit', 'seed': seed, 'stage': stage, 'mode': mode, 'process': fit_process})
        raw, read_process = read(checkpoint, phase_database, phase_root/'read')
        causal = read_process['started_ns'] > fit_process['exited_ns'] and read_process['pid'] != fit_process['pid']
        if not causal:
            failures.append({'kind': 'process-order', 'seed': seed, 'stage': stage, 'mode': mode})
        record = {'seed': seed, 'stage': stage, 'mode': mode, 'changed_entities': changed, 'reentered_entity': reentered,
                  'deleted_entity': deleted, 'preflight_passed': probe['passed'], 'trainer_passed': fit_process['passed'],
                  'reader_passed': read_process['passed'], 'fresh_reader_after_trainer_exit': causal,
                  'quality': m.score(raw, state, changed), 'model': {'parameter_sha256': raw.get('parameter_sha256'), 'checkpoint': str(checkpoint)},
                  'fit_wall_ns': fit_process['wall_ns'], 'fit_cpu_seconds': fit_process['cpu_seconds'],
                  'read_process_wall_ns': read_process['wall_ns'], 'read_process_cpu_seconds': read_process['cpu_seconds'],
                  'baseline_and_parameter_read_wall_ns': {a['arm']: a['read_wall_ns'] for a in raw.get('arms', [])},
                  'storage': m.storage(state, phase_database, checkpoint, seed_root, encoder_info['base_bytes'], feature_id['bytes']),
                  'resumes_interrupted_attempt': original is not None}
        m.save(phase_root/'RESULT.json', record)
        phases.append(record)
        return checkpoint, record

    def finish_cycle(seed, stage, record, paths, started):
        result = {'seed': seed, 'stage': stage, 'quality': record['quality'], 'final_model': record['model'],
                  'phase_count': len(paths), 'phase_paths': paths, 'wall_ns': time.monotonic_ns()-started,
                  'interrupted_cycle_wall_excludes_prior_segment': seed == 732 and stage == 16}
        m.save(output/f'seed-{seed}'/f'stage-{stage:03d}'/'CYCLE.json', result)
        cycles.append(result)
        if stage % 8 == 0:
            print(json.dumps({'seed': seed, 'stage': stage, 'combined_complete_cycles': 79+len(cycles),
                              'new_failures': len(failures), 'quality': record['quality']['parameter'],
                              'free_bytes': shutil.disk_usage(output).free}), flush=True)

    seed_root = output/'seed-732'
    seed_root.mkdir()
    database = seed_root/'owner.sqlite'
    m.snapshot(old/'seed-732'/'owner.sqlite', database)
    m.ensure_space(output, 732, 16)
    checkpoint = Path(pending_request['checkpoint'])
    started = time.monotonic_ns()
    update_record = json.loads((old/'seed-732'/'stage-016'/'update'/'RESULT.json').read_bytes())
    checkpoint, record = phase(732, 16, 'rebuild', state, update_record['changed_entities'],
                               update_record['reentered_entity'], 2, database, checkpoint, seed_root, original=pending_request)
    finish_cycle(732, 16, record, [str(old/'seed-732'/'stage-016'/'update'/'RESULT.json'),
                                  str(seed_root/'stage-016'/'rebuild'/'RESULT.json')], started)
    pending = 2
    for seed in (732, 733):
        if seed == 733:
            seed_root = output/f'seed-{seed}'
            seed_root.mkdir()
            state = [{**copy.deepcopy(row), 'active': True} for row in initial_sources]
            database = seed_root/'owner.sqlite'
            m.create(database, initial_sources)
            checkpoint = inputs/f'seed-{seed}'
            read(checkpoint, database, seed_root/'initial-read')
            pending = None
        for stage in range(17 if seed == 732 else 1, 65):
            m.ensure_space(output, seed, stage)
            started = time.monotonic_ns()
            changed = sorted({stage % 8} | ({pending} if pending is not None else set()))
            for entity in changed:
                row = state[entity]
                row.update(version=row['version']+1, active=True, value=m.policy(seed, stage, entity))
                row['source_id'] = m.sha(m.canonical(['hepta.adapter.longrun.source.v1', seed, entity, row['version'], stage]))
            with sqlite3.connect(database) as db:
                for entity in changed:
                    row = state[entity]
                    db.execute('UPDATE sources SET identity=?,version=?,active=1,payload=? WHERE kind=? AND idx=?',
                               (row['source_id'], row['version'], json.dumps(row['value']), 'semantic', entity))
            reentered, pending = pending, None
            paths = []
            for mode in (['update', 'rebuild'] if stage % 8 == 0 else ['update']):
                deleted = None
                if mode == 'rebuild':
                    deleted = (stage//8) % 8
                    state[deleted]['active'] = False
                    with sqlite3.connect(database) as db:
                        db.execute("UPDATE sources SET active=0 WHERE kind='semantic' AND idx=?", (deleted,))
                    pending = deleted
                checkpoint, record = phase(seed, stage, mode, state, changed, reentered, deleted, database, checkpoint, seed_root)
                paths.append(str(seed_root/f'stage-{stage:03d}'/mode/'RESULT.json'))
            finish_cycle(seed, stage, record, paths, started)
    if tree_identity(old) != old_tree:
        failures.append({'kind': 'original-evidence-changed-during-resume'})
    if any(m.identity(Path(p)) != expected for p, expected in freeze['source_files'].items()):
        failures.append({'kind': 'original-frozen-source-changed'})
    if any(m.identity(Path(p)) != expected for p, expected in new_sources.items()):
        failures.append({'kind': 'resume-source-changed-after-freeze'})
    all_cycles = [json.loads(p.read_bytes()) for p in old.glob('seed-*/stage-*/CYCLE.json')]+cycles
    all_phases = [json.loads(p.read_bytes()) for p in old.glob('seed-*/stage-*/*/RESULT.json')]+phases
    observed = {(row['seed'], row['stage']) for row in all_cycles}
    required = {(seed, stage) for seed in (731, 732, 733) for stage in range(1, 65)}
    if observed != required or len(all_cycles) != 192 or len(all_phases) != 216:
        raise ValueError('combined horizon or phase inventory incomplete')
    all_processes = [json.loads(p.read_bytes()) for p in old.rglob('*.process.json')]
    all_processes = [p for p in all_processes if p.get('script') in ('fit_worker.py', 'owner_read.py')]+processes
    aggregate = {arm: {g: {'correct': 0, 'count': 0} for g in ('active', 'retention', 'changed', 'revoked')}
                 for arm in ('parameter', 'exact_sql')}
    for cycle in all_cycles:
        for arm, groups in cycle['quality'].items():
            for group, counts in groups.items():
                for key, value in counts.items(): aggregate[arm][group][key] += value
    summary = {'schema': 'hepta.memory.adapter-longrun-combined-result.v1', 'protocol_sha256': protocol_sha,
               'completed_cycles': 192, 'cycles_per_seed': 64, 'seeds': [731, 732, 733], 'phase_count': 216,
               'completed_update_fits': sum(p['mode'] == 'update' for p in all_phases),
               'completed_rebuild_fits': sum(p['mode'] == 'rebuild' for p in all_phases),
               'completed_fit_steps': 216*600, 'completed_sample_presentations': 216*600*32,
               'infrastructure_interrupted_attempts': 1, 'interrupted_attempt_steps': None,
               'new_failures': failures, 'final_cycle_aggregate': aggregate,
               'all_preflight_passed': all(p['preflight_passed'] for p in all_phases),
               'all_trainers_and_readers_completed': all(p['trainer_passed'] and p['reader_passed'] for p in all_phases),
               'all_readers_after_trainer_exit': all(p['fresh_reader_after_trainer_exit'] for p in all_phases),
               'original_evidence_unchanged': tree_identity(old) == old_tree,
               'cost': {'completed_children_cpu_seconds': sum(p['cpu_seconds'] for p in all_processes),
                        'completed_children_wall_ns': sum(p['wall_ns'] for p in all_processes),
                        'training_children_cpu_seconds': sum(p['cpu_seconds'] for p in all_processes if p['script'] == 'fit_worker.py'),
                        'reader_children_cpu_seconds': sum(p['cpu_seconds'] for p in all_processes if p['script'] == 'owner_read.py'),
                        'interrupted_child_cpu_seconds': None, 'original_driver_final_cpu_seconds': None,
                        'resume_driver_own_cpu_ns': time.process_time_ns()-cpu,
                        'resume_driver_wall_ns_before_summary': time.monotonic_ns()-began,
                        'kernel_output_blocks_completed_children': sum(p['kernel_output_blocks'] for p in all_processes),
                        'source_sqlite_bytes_all_snapshots': sum(p.stat().st_size for root in (old, output) for p in root.rglob('*.sqlite')),
                        'fitted_checkpoint_bytes': sum(m.file_bytes(p) for root in (old, output) for p in root.glob('seed-*/stage-*/**/checkpoint') if p.is_dir()),
                        'initial_checkpoint_copies_bytes': sum(m.file_bytes(inputs/f'seed-{seed}') for seed in (731, 732, 733)),
                        'shared_encoder_reference_bytes': encoder_info['base_bytes'], 'canonical_features_bytes': feature_id['bytes'],
                        'output_regular_bytes_before_summary': m.file_bytes(old)+m.file_bytes(output),
                        'peak_and_integral_authority': 'run-01/RESOURCE_INTERRUPTED.json plus run-02-resume/resource.json; unknown tail and gap remain explicit',
                        'full_cost_exact': False},
               'native_runtime_executed': False, 'held_inputs_opened': False,
               'interpretation': json.loads((HERE/'LONGRUN_PROTOCOL.json').read_bytes())['cost_interpretation']}
    m.save(output/'RESULT.json', summary)
    m.save(output/'CYCLES.json', sorted(all_cycles, key=lambda r: (r['seed'], r['stage'])))
    print(json.dumps({'complete': True, 'cycles': 192, 'phases': 216, 'interrupted_attempts': 1,
                      'new_failures': len(failures), 'quality': aggregate}), flush=True)
    return 0


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--python', default=sys.executable)
    args = parser.parse_args()
    try:
        raise SystemExit(run(args))
    except Exception as error:
        args.output.mkdir(parents=True, exist_ok=True)
        m.save(args.output/'FAILED.json', {'error': f'{type(error).__name__}: {error}', 'pid': os.getpid()})
        raise
