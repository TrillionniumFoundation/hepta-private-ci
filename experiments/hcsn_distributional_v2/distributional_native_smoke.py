"""Separate actual-owner/recovery integration of a trained distributional model.

This uses a small, explicitly non-fresh TRAIN/VAL engineering cohort.  It does
not inherit the frozen-v1 task-control quality result.  The task teacher is
refitted to this v2 model's own TRAIN prefixes without changing its weights.
"""

import argparse
from datetime import datetime, timezone
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
from types import SimpleNamespace

import numpy as np
import torch

from ..hcsn_free_boundary_v1.restore_native import restore
from ..hcsn_free_boundary_v1.training import load_weights
from .task_value_common import (PACKAGE, REPOSITORY, V1, read_json, write_json,
                                sha, load_state, state_identity)
from .task_value_data import fit_observation_model, load_observation_model
from .task_value_heads import Policy, make_solutions
from .task_value_native import run_stream, comparable_trajectory


class MyopicPolicy(Policy):
    """Same fitted observations, but omit later tasks from the decision value."""
    def __init__(self, solutions, edges):
        # The immutable driver journals its policy's tables at the actual queue
        # index. Repeat this ablation's single-task decision values along that
        # index so the logged G/C agree with the score actually sent to the owner.
        myopic = {price: SimpleNamespace(
            fire=np.broadcast_to(table.fire[1:2], table.fire.shape),
            read=np.broadcast_to(table.read[1:2], table.read.shape),
            future_after_reset=np.zeros_like(table.future_after_reset))
            for price, table in solutions.items()}
        super().__init__('tabular_myopic', myopic, edges)

    def score(self, prefix, state, ticks, tasks, price):
        prefix, state, ticks, tasks = np.broadcast_arrays(prefix, state, ticks, tasks)
        table = self.solutions[str(price)]
        score = table.read[1, ticks, prefix, state] - table.fire[1, ticks, prefix, state]
        return np.where((ticks == 0) | (prefix == 32), -1., score)


def verify(output):
    record = read_json(Path(output) / 'REGISTRATION.json')
    if record['schema'] != 'hcsn-trained-distributional-owner-registration.v1':
        raise ValueError('Unknown trained owner registration schema')
    for name, digest in record['files'].items():
        if sha(REPOSITORY / name) != digest:
            raise ValueError('Distributional owner registered input changed: ' + name)
    return record


def load_model(output):
    verify(output)
    from .model import build_model
    protocol = read_json(Path(output) / 'PROTOCOL.json')
    config = protocol['backbone_config']
    construction = {key: config[key] for key in ('name', 'input_dim', 'output_dim', 'width', 'depth', 'seed')}
    model = build_model(**construction).cpu().eval()
    if model.config != config:
        raise ValueError('Trained checkpoint configuration differs from runtime physical contract')
    checkpoint = REPOSITORY / protocol['backbone_checkpoint']
    load_weights(checkpoint, model)
    model.requires_grad_(False)
    return model


def prepare(output):
    output = Path(output)
    model = load_model(output)
    with np.load(V1 / 'data/study001/mnist.npz', allow_pickle=False) as archive:
        x = torch.from_numpy(np.array(archive['train_x'][:64], copy=True))
        dt = torch.from_numpy(np.array(archive['train_dt'][:64], copy=True))
        labels = np.array(archive['train_y'][:64, -1], copy=True)
    confidence, predictions = [], []
    clock = time.process_time()
    with torch.no_grad():
        for first in range(0, len(x), 16):
            state, batch_c, batch_p = None, [], []
            for prefix in range(32):
                logits, state, _ = model.step(x[first:first + 16, prefix], dt[first:first + 16, prefix], state)
                batch_c.append(logits.softmax(-1).amax(-1).numpy())
                batch_p.append(logits.argmax(-1).numpy())
            confidence.append(np.stack(batch_c, 1))
            predictions.append(np.stack(batch_p, 1))
    confidence, predictions = map(np.concatenate, (confidence, predictions))
    with (output / 'train_trace.npz').open('xb') as handle:
        np.savez_compressed(handle, confidence=confidence, prediction=predictions,
                            labels=labels, correct=predictions == labels[:, None])
    trace_cpu = time.process_time() - clock
    model, _ = fit_observation_model(output / 'train_trace.npz', output)
    solutions = make_solutions(model, [.001, .005, .02])
    minimum_fresh = {p: float(s.fresh[1:, 1:].min()) for p, s in solutions.items()}
    if min(minimum_fresh.values()) <= 0:
        raise ValueError('Optional fresh-task decline disagrees with mandatory first READ contract')
    write_json(output / 'TEACHER_LOCK.json', {
        'files': {name: sha(output / name) for name in ('train_trace.npz', 'observation_model.npz', 'OBSERVATION_MODEL.json')},
        'fit_images': 64, 'fit_split': 'TRAIN', 'actual_model_observations': 64 * 32,
        'train_trace_parent_cpu_seconds': trace_cpu,
        'fresh_task_values_at_h48': {p: s.fresh[3, 48] for p, s in solutions.items()},
        'minimum_fresh_value_all_positive_deadlines_and_queue_sizes': minimum_fresh,
        'mandatory_first_read_matches_positive_teacher_fresh_value': True,
        'validation_or_test_labels_used_for_fit': False})


def inputs(output):
    output = Path(output)
    verify(output)
    lock = read_json(output / 'TEACHER_LOCK.json')
    for name, digest in lock['files'].items():
        if sha(output / name) != digest:
            raise ValueError('Distributional task teacher changed')
    observation, edges = load_observation_model(output / 'observation_model.npz')
    solutions = make_solutions(observation, [.001, .005, .02])
    with np.load(V1 / 'data/study001/mnist.npz', allow_pickle=False) as archive:
        x = torch.from_numpy(np.array(archive['val_x'][:6], copy=True))
        dt = torch.from_numpy(np.array(archive['val_dt'][:6], copy=True))
        labels = np.array(archive['val_y'][:6, -1], copy=True)
    ids = read_json(V1 / 'data/study001/mnist.json')['splits']['val']['image_source_ids'][:6]
    queues = np.random.default_rng(83011).permutation(6).reshape(2, 3)
    identity = {'scope': 'distributional v2 engineering TRAIN64/VAL6; not fresh-test quality',
                'protocol_sha256': sha(output / 'PROTOCOL.json'),
                'registration_sha256': sha(output / 'REGISTRATION.json'),
                'teacher_lock_sha256': sha(output / 'TEACHER_LOCK.json')}
    return solutions, edges, x, dt, labels, ids, queues, identity


def evaluation(output):
    output = Path(output)
    solutions, edges, x, dt, labels, ids, queues, identity = inputs(output)
    model = load_model(output)
    binary, _ = restore(output / 'runtime/continuous_host')
    policies = {'tabular_bellman': Policy('tabular_bellman', solutions, edges),
                'tabular_myopic': MyopicPolicy(solutions, edges)}
    rows, executed = [], {}
    for price in (.001, .005, .02):
        for family, policy in policies.items():
            for stream, queue in enumerate(queues):
                started = time.process_time()
                directory = output / 'evaluation' / ('price_' + str(price)) / family / ('stream_' + str(stream))
                result = run_stream(model, policy, x[queue], dt[queue], labels[queue],
                    [ids[i] for i in queue], price=price, stream_number=stream,
                    directory=directory, binary=binary, identity=identity)
                executed[(price, family, stream)] = result
                rows.append({'price': price, 'family': family, 'stream': stream,
                    'result': str((directory / 'RESULT.json').relative_to(output)),
                    'result_sha256': sha(directory / 'RESULT.json'),
                    'actual_reads': result['actual_reads'], 'correct': result['correct'],
                    'later_correct': result['later_task_correct'], 'utility': result['utility'],
                    'parent_cpu_seconds': time.process_time() - started,
                    'native_child_cpu_seconds': result['native_child_cpu_seconds'],
                    'q24_disagreements': result['float_q24_disagreements'],
                    'actual_owner_processes': len(result['native_costs'])})
    pairs = []
    for price in (.001, .005, .02):
        for stream in range(len(queues)):
            full = executed[(price, 'tabular_bellman', stream)]
            myopic = executed[(price, 'tabular_myopic', stream)]
            a = [x for x in full['events'] if x['kind'] == 'read_and_decide']
            b = [x for x in myopic['events'] if x['kind'] == 'read_and_decide']
            first = None
            for x, y in zip(a, b):
                state_keys = ('task_index', 'prefix', 'clock', 'confidence', 'confidence_bin')
                if any(x[key] != y[key] for key in state_keys):
                    raise AssertionError('Paired trajectories diverged before their first policy-action difference')
                if x['action'] != y['action']:
                    first = {key: x[key] for key in state_keys}
                    first.update(full_action=x['action'], myopic_action=y['action'],
                                 full_score=x['score'], myopic_score=y['score'])
                    break
            if first is None and len(a) != len(b):
                raise AssertionError('Paired native executions differ without a recorded action divergence')
            pairs.append({'price': price, 'stream': stream, 'first_action_divergence': first,
                          'full_minus_myopic_actual_utility': full['utility'] - myopic['utility']})
    write_json(output / 'EVALUATION_SUMMARY.json', {
        'status': 'completed', 'registered_engineering_streams': 12, 'rows': rows,
        'causal_paired_action_comparison': pairs,
        'scope': 'Two non-fresh VAL streams; teacher-only future-value omission diagnostic, no population quality inference',
        'myopic_definition': 'Same trained v2 backbone, fitted P/r, current observation, deadline and price. Controller deliberately uses m=1 table; actual queue still has3 tasks.'})


def recovery(output, kind, resume):
    output = Path(output)
    solutions, edges, x, dt, labels, ids, queues, identity = inputs(output)
    identity['fixture'] = 'fixed8 distributional active/quiet recovery'
    model = load_model(output)
    binary, _ = restore(output / 'runtime/continuous_host')
    policy = Policy('validation_schedule', solutions, edges,
                    settings={'0.001': {'prefix': 8, 'balanced': False}})
    queue = queues[0]
    result = run_stream(model, policy, x[queue], dt[queue], labels[queue],
        [ids[i] for i in queue], price=.001, stream_number=0,
        directory=output / 'recovery' / kind, binary=binary, identity=identity,
        resume=resume, checkpoint_active=(0, 4) if kind == 'active' else None,
        checkpoint_quiet=kind == 'quiet')
    if kind != 'reference' and not resume and result['status'] != 'suspended':
        raise AssertionError('Distributional fixture did not suspend at its registered state')


def run(output, backbone_run):
    output, backbone_run = Path(output).resolve(), Path(backbone_run).resolve()
    output.mkdir(parents=True, exist_ok=False)
    execution, summary, trained_identity = (read_json(backbone_run / name) for name in
                                            ('EXECUTION.json', 'summary.json', 'IDENTITY.json'))
    if (execution.get('returncode') != 0 or summary['status'] != 'completed'
            or trained_identity['status'] != 'completed'):
        raise ValueError('Use only a fully completed trained distributional checkpoint')
    config = summary['selected_model_config']
    expected_job = {'task': 'mnist', 'model': 'distribution_free_dual', 'seed': config['seed']}
    if trained_identity['job'] != expected_job or execution['job'] != expected_job:
        raise ValueError('Trained checkpoint must be the declared completed MNIST distributional job')
    if (config['name'] != expected_job['model'] or config['input_dim'] != 64
            or config['output_dim'] != 10 or config['width'] != 32 or config['depth'] != 1
            or summary['request']['model'] != config['name']
            or summary['request']['seed'] != config['seed']):
        raise ValueError('Trained model configuration does not match this registered engineering task')
    seed = config['seed']
    checkpoint = backbone_run / 'selected.npz'
    if summary['selection']['selected_checkpoint_sha256'] != sha(checkpoint):
        raise ValueError('Selected checkpoint differs from the completed training selection')
    content_registration = backbone_run.parents[1] / 'REGISTRATION.json'
    if read_json(content_registration)['protocol_sha256'] != trained_identity['protocol_sha256']:
        raise ValueError('Training worker and registered campaign protocol differ')
    training_files = trained_identity['source_files_sha256']
    for name, digest in training_files.items():
        if sha(REPOSITORY / name) != digest:
            raise ValueError('Trained source dependency differs from current runtime: ' + name)
    data_sha = sha(V1 / 'data/study001/mnist.npz')
    if (trained_identity['dataset_sha256'] != data_sha
            or summary['selection']['dataset_sha256'] != data_sha):
        raise ValueError('Trained MNIST data identity differs from integration data')
    write_json(output / 'PROTOCOL.json', {
        'schema': 'hcsn-trained-distributional-native-engineering.v1',
        'study_id': output.name, 'fit_train_images': 64, 'validation_images': 6,
        'queue_tasks': 3, 'queue_seed': 83011, 'deadline_ticks': 48, 'task_refractory_ticks': 2,
        'prices': [.001, .005, .02], 'policies': ['tabular_bellman', 'tabular_myopic'],
        'backbone_checkpoint': str(checkpoint.relative_to(REPOSITORY)),
        'backbone_checkpoint_sha256': sha(checkpoint), 'backbone_seed': seed,
        'backbone_config': config,
        'backbone_content_protocol_sha256': trained_identity['protocol_sha256'],
        'backbone_training_complete_cpu_seconds': execution.get('child_total_cpu_seconds'),
        'fresh_test_quality_claim': False,
        'controller': 'Refit the same4-bin transition/correctness task model on thisv2 TRAIN64; no new content/head parameter fitting',
        'output_semantics': 'Real-valued task gap from a quantized confidence state. It is piecewise constant in confidence, not a claim of an everywhere-smooth task policy.',
        'active_recovery': 'after4 actual reads with nonempty retained distribution; new Python process',
        'quiet_recovery': 'after first FIRE and1 of2 task-level quiet ticks; new Python process',
        'selection': 'No policy/threshold/hyperparameter selection on theseVAL outcomes; engineering comparison only'})
    files = [Path(__file__), PACKAGE / 'model.py', PACKAGE / 'distribution_kernel.py',
             *[PACKAGE / name for name in ('task_value.py', 'task_value_common.py', 'task_value_data.py',
                      'task_value_heads.py', 'task_value_native.py')],
             *[backbone_run / name for name in ('EXECUTION.json', 'summary.json', 'selected.npz', 'IDENTITY.json')],
             content_registration, V1 / 'native_vendor/MANIFEST.json', V1 / 'native_vendor/adapter.py',
             V1 / 'data/study001/mnist.npz', V1 / 'data/study001/mnist.json', output / 'PROTOCOL.json']
    registered_files = dict(training_files)
    registered_files.update({str(path.relative_to(REPOSITORY)): sha(path) for path in files})
    snapshot = output / 'registered_source'
    snapshot.mkdir()
    shutil.copy2(__file__, snapshot / Path(__file__).name)
    registered_files[str((snapshot / Path(__file__).name).relative_to(REPOSITORY))] = sha(__file__)
    write_json(output / 'REGISTRATION.json', {
        'schema': 'hcsn-trained-distributional-owner-registration.v1',
        'created_utc': datetime.now(timezone.utc).isoformat(), 'files': registered_files,
        'v2_teacher_or_native_inference_performed': False})
    receipts = {}
    commands = [sys.executable, '-m', 'experiments.hcsn_distributional_v2.distributional_native_smoke',
                '--output', str(output), '--backbone-run', str(backbone_run)]
    phases = [('prepare', ['--worker', 'prepare']), ('evaluate', ['--worker', 'evaluate'])]
    for kind in ('reference', 'active', 'quiet'):
        phases.append(('recovery_' + kind, ['--worker', 'recovery', '--kind', kind]))
        if kind != 'reference':
            phases.append(('resume_' + kind, ['--worker', 'recovery', '--kind', kind, '--resume']))
    for key, arguments in phases:
        log = output / (key + '.log')
        started = time.perf_counter()
        with log.open('x') as handle:
            process = subprocess.Popen(commands + arguments, stdout=handle, stderr=subprocess.STDOUT)
            _, status, usage = os.wait4(process.pid, 0)
            process.returncode = os.waitstatus_to_exitcode(status)
        row = {'command': commands + arguments, 'exit_code': process.returncode,
               'complete_child_cpu_seconds': usage.ru_utime + usage.ru_stime,
               'wall_seconds': time.perf_counter() - started, 'peak_rss_kib_linux': usage.ru_maxrss,
               'stdout_sha256': sha(log), 'measurement': 'wait4 includes imports and waited native descendants'}
        write_json(output / (key + '_EXECUTION.json'), row)
        receipts[key] = row
        if process.returncode:
            raise RuntimeError('Distributional owner integration failure retained: ' + str(log))
    reference = read_json(output / 'recovery/reference/RESULT.json')
    checks = {}
    for kind in ('active', 'quiet'):
        restored = read_json(output / 'recovery' / kind / 'RESULT.json')
        if comparable_trajectory(reference) != comparable_trajectory(restored):
            raise AssertionError('Trained distributional fresh-process replay differs')
        if not restored['resumptions'][0]['different_python_process']:
            raise AssertionError('Expected a new Python interpreter')
        checks[kind] = restored['resumptions'][0]
    state = load_state(output / 'recovery/active/STATE.npz')
    distribution_checks = []
    for layer in state['layers']:
        probability = layer['probability'].numpy()
        if not np.isfinite(probability).all() or np.any(probability < -1e-6):
            raise AssertionError('Checkpoint distribution invalid')
        mass_error = float(np.max(np.abs(probability.sum(-1) - 1)))
        phase_mass = float(probability[..., 8:].sum())
        if probability.shape != (1, 8, 10) or mass_error > 1e-5 or phase_mass <= 0:
            raise AssertionError('Checkpoint must retain normalized active and nonempty refractory phases')
        distribution_checks.append({'shape': list(probability.shape),
            'maximum_mass_error': mass_error, 'refractory_phase_mass': phase_mass,
            'state_identity': state_identity(state)})
    evaluation_summary = read_json(output / 'EVALUATION_SUMMARY.json')
    rows = evaluation_summary['rows']
    native_summary = {'streams': len(rows), 'paid_reads': 0, 'native_processes': 0,
                      'owner_ticks': 0, 'actual_kernel_calls': 0, 'actual_ndu_calls': 0,
                      'intentional_post_stop_rejections': 0, 'float_q24_disagreements': 0,
                      'paired_streams_with_action_difference': sum(
                          pair['first_action_divergence'] is not None
                          for pair in evaluation_summary['causal_paired_action_comparison'])}
    for row in rows:
        path = output / row['result']
        if sha(path) != row['result_sha256']:
            raise ValueError('Executed stream result changed before audit')
        executed = read_json(path)
        native_summary['paid_reads'] += executed['actual_reads']
        native_summary['float_q24_disagreements'] += executed['float_q24_disagreements']
        native_summary['native_processes'] += len(executed['native_costs'])
        native_summary['intentional_post_stop_rejections'] += sum(
            task['terminal_probe']['passed'] for task in executed['task_results'])
        for cost in executed['native_costs']:
            if cost['exit_code'] != 0:
                raise AssertionError('Native process did not exit cleanly')
            for key in ('owner_ticks', 'actual_kernel_calls', 'actual_ndu_calls'):
                native_summary[key] += cost['counters'][key]
    if len({native_summary[key] for key in ('paid_reads', 'owner_ticks', 'actual_kernel_calls', 'actual_ndu_calls')}) != 1:
        raise AssertionError('Actual read/owner/kernel/NDU counts differ')
    result = {'status': 'completed', 'phases': receipts, 'recovery': checks,
              'active_distribution_state': distribution_checks, 'evaluation_native_audit': native_summary,
              'complete_measured_phase_cpu_seconds': sum(x['complete_child_cpu_seconds'] for x in receipts.values()),
              'coordinator_whole_self_cpu_seconds_through_audit': time.process_time(),
              'new_v2_content_training': False, 'scope': 'Actual execution and recovery engineering;6 reusedVAL images, not a quality/generalization result'}
    verify(output)
    write_json(output / 'COMPLETE.json', result)
    text = ['# Trained distributional model: actual owner and fresh-process recovery', '',
        'This separately registered engineering study uses the selected v2 distributional MNIST model. Its own first64 TRAIN traces fit the task-value observation model; six original VAL images form two three-task streams. These are explicitly reused TRAIN/VAL data, not a fresh-test quality cohort.', '',
        'Both full finite-queue task values and a same-observation myopic value ablation feed real-valued scores to the actual native owner. The latter deliberately omits later tasks from its decision table while the executed queue still has three tasks. The confidence-state map is quantized/piecewise constant; no global differentiability claim is made for this external task controller.', '',
        '| Price | Policy | Stream | Actual reads | Correct tasks | Actual later correct | Utility |',
        '| --- | --- | ---: | ---: | ---: | ---: | ---: |']
    for row in rows:
        text.append(f'| {row["price"]} | {row["family"]} | {row["stream"]} | {row["actual_reads"]} | {row["correct"]} | {row["later_correct"]} | {row["utility"]:.6f} |')
    text += ['', 'Active and mid-quiet checkpoints were resumed in different Python processes. All subsequent neural outputs, actual actions, native checkpoints, final neural state and task reward matched the uninterrupted fixed8 engineering fixture. The active snapshot preserves the full distribution and refractory phases; it does not collapse to a pressure mean.', '',
        f'Measured worker CPU, including native descendants: **{result["complete_measured_phase_cpu_seconds"]:.6f} s**. Coordinator self CPU is separately retained. Existing content training is identified and not billed as new training in this engineering run. Runtime and reward rows here do not replace the larger frozen-v1 task-control panel.', '',
        'See PROTOCOL.json, REGISTRATION.json, TEACHER_LOCK.json, EVALUATION_SUMMARY.json and COMPLETE.json for hashes, assumptions and scope. Every owner journal, explicit STOP rejection, checkpoint and execution receipt is retained.', '']
    with (output / 'REPORT.md').open('x') as handle:
        handle.write('\n'.join(text))
    print({'status': 'completed', 'output': str(output), 'phase_cpu': result['complete_measured_phase_cpu_seconds']}, flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--backbone-run', type=Path, required=True)
    parser.add_argument('--worker', choices=('prepare', 'evaluate', 'recovery'))
    parser.add_argument('--kind', choices=('reference', 'active', 'quiet'))
    parser.add_argument('--resume', action='store_true')
    args = parser.parse_args()
    torch.set_num_threads(1)
    if args.worker == 'prepare':
        prepare(args.output)
    elif args.worker == 'evaluate':
        evaluation(args.output)
    elif args.worker == 'recovery':
        recovery(args.output, args.kind, args.resume)
    else:
        completed, failure = False, None
        try:
            run(args.output, args.backbone_run)
            completed = True
        except Exception as error:
            failure = {'type': type(error).__name__, 'message': str(error)}
            raise
        finally:
            if args.output.is_dir():
                write_json(args.output / 'COORDINATOR_EXECUTION.json', {
                    'status': 'completed' if completed else 'failed', 'failure': failure,
                    'whole_self_cpu_seconds_through_cutoff': time.process_time(),
                    'pid': os.getpid(),
                    'scope': 'Whole coordinator self CPU including imports, registration, audit and report; add complete measured phases once, never their nested native child costs again'})
