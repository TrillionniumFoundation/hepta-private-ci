"""Measured, separately registered finite-task value study and native execution."""

import argparse
from datetime import datetime, timezone
import os
from pathlib import Path
import subprocess
import sys
import time

from .task_value_common import PACKAGE, REPOSITORY, V1, BACKBONE_RUN, sha, read_json, write_json


PROTOCOL = {
    'schema': 'hcsn-v2-regenerative-task-protocol.v1', 'study_id': 'task_value001',
    'base_commit': 'caa94dc53f8b8b721ee00076ce060d44a98d7a4f',
    'status_at_registration': 'no new task head training or fresh-cohort inference',
    'queue_tasks': 3, 'deadline_ticks': 48, 'maximum_reads_per_task': 32,
    'refractory_ticks': 2, 'discount_per_tick': 1.,
    'reward': 'Actual correctness at each FIRE minus price times every actual READ; later tasks score separately',
    'fire_and_reset': 'FIRE terminates the current native owner and iterator; if >2 ticks remain and queue nonempty, consume 2 quiet ticks and reset neural state for the next image',
    'clock': 'READ consumes 1 model-clock tick; quiet ticks are simulated task time, not wall-clock sleep; actual CPU billed separately',
    'first_read': 'Mandatory only when starting a task; fitted fresh value must be positive for all registered prices and available deadlines',
    'prices': [.001, .005, .02],
    'data': {'train': 'all original 1024 TRAIN images', 'validation': 'all original 256 VAL images; 85 shuffled three-image streams, last unused image disclosed',
             'fresh_test': 'reproduce old 640 test prefixes, then source episodes 640:1024; 384 new images',
             'new_test_streams': 128, 'test_queue_permutation_seed': 73013,
             'validation_queue_permutation_seed': 73012,
             'prior_exclusions': 'all original train/val/test source IDs and all native003 128 source IDs',
             'old_validation_reused': True, 'future_task_independence': 'Approximate independent restart assumption; deterministic permutation without replacement, no hidden future-label input'},
    'observation_model': {'confidence_bins': 4, 'confidence_quantum': .0001,
                          'quantile_fit': 'TRAIN only, separately for each observed prefix',
                          'transition_reward_fit': 'TRAIN-only empirical transitions/correctness, shrinkage pseudocount5',
                          'exact_belief_process': False},
    'head_inputs': ['prefix/32', 'confidence_bin/3', 'remaining_ticks/48', 'remaining_tasks/3', 'price/.02'],
    'head_architecture': 'Identical Linear(5,8),tanh,Linear(8,2); all66 parameters active in both score differences',
    'head_intervention': 'Value target/objective vs ordinary action distillation; not a pure architecture/channel-count comparison',
    'value_loss': 'MSE(predicted [G,C],teacher [G,C]) +25*MSE(predicted C-G,teacher C-G)',
    'ordinary_loss': 'Cross entropy of two ordinary logits against teacher Q24(tanh(C-G))>0 READ action; ties FIRE',
    'teacher': 'Finite Bellman table fitted from actual TRAIN prefix correctness/next-confidence distribution and actual public read cost; includes future tasks after reset',
    'head_seed': 34001, 'learning_rates': [.003, .01], 'updates': 256,
    'batch_size': 128, 'checkpoints': [64, 128, 256], 'optimizer': 'Adam, default betas, clip norm2',
    'pairing': 'Same initialization, complete minibatch sequence, input bank, candidate and checkpoint counts',
    'budget': 'Equal updates/search opportunities for the2 learned heads; not equalCPU. Record full measured costs.',
    'selection': 'Maximum actual VAL stream reward, macro average across prices; ties earlier checkpoint then smaller LR',
    'baselines': ['tabular_bellman', 'validation_schedule', 'validation_risk'],
    'schedule_candidates': 'prefix1/2/4/8/16/32, each fixed or deadline-balanced; select perprice on VAL',
    'risk_candidates': 'confidence_bin threshold0/1/2/3/4, each fixed or deadline-balanced; select perprice on VAL',
    'primary_ordinary_reference': 'VAL macro-best among ordinary_action_head, validation_schedule, validation_risk; locked before new test',
    'counterfactual': 'All128 shuffled new streams; full-prefix cache computation fully charged; logical paid reads do not imply compute savings',
    'native_streams': 16,
    'native_subset': 'First16 of the registered new queue permutation, all3 prices and all5 policies; actual step/owner/STOP/RESET, no extra postSTOP observations',
    'native_invariants': 'Original fixed binary, width5/topk1/20percent limit, DENY_ALL. KEEP iff Q24(tanh(score))>0; forced STOP at local maximum or global deadline.',
    'cache_native_parity': 'Audit and retain any mismatches; never combine cache scores with actual native costs as if they were one execution',
    'recovery': 'A declared fixed8 engineering fixture on firstnewstream: active state after1read and mid-refractory after1quiettick; suspend and resume in different Python processes, compare full semantic trajectory to uninterrupted fixture',
    'statistics': 'Descriptive stream-level paired means and1999-resample nominal bootstrap intervals; macro over3 prices before resampling; no new significance/superiority gate',
    'bootstrap_seed': 73015,
    'cost': {'measure': 'wait4 complete childCPU including waited native descendants; nested details not added again',
             'lifetimes_streams': [1000, 10000, 100000], 'utility_per_cpu_second': [0., .0001, .001, .01],
             'fixed_backbone': 'Charge historical complete search cost46.474767CPU under alternative deployment scenarios; no new backbone training',
             'scope': 'Measured research costs and assumption-based amortization reported separately; no energy claim'},
    'interpretation': 'Task-layer owner value contract, not a theorem that each neural pressure boundary optimizes classification or a claim that frozenv1 execution demonstrates v2 content superiority',
    'failure_policy': 'Keep failed processes/logs; source changes afterregistration require a new study identity; no fresh-test-driven selection changes'}


def measure(output, key, command):
    output = Path(output)
    log = output / (key + '.log')
    receipt = output / (key + '_EXECUTION.json')
    if receipt.exists() or log.exists():
        raise FileExistsError('Refusing to overwrite an executed phase: ' + key)
    environment = os.environ.copy()
    for name in ('OMP_NUM_THREADS', 'MKL_NUM_THREADS', 'OPENBLAS_NUM_THREADS', 'NUMEXPR_NUM_THREADS'):
        environment[name] = '1'
    environment['PYTHONDONTWRITEBYTECODE'] = '1'
    start = time.perf_counter()
    with log.open('x') as out:
        process = subprocess.Popen(command, stdout=out, stderr=subprocess.STDOUT, env=environment)
        _, status, usage = os.wait4(process.pid, 0)
        process.returncode = os.waitstatus_to_exitcode(status)
    result = {'command': command, 'exit_code': process.returncode,
              'complete_child_cpu_seconds': usage.ru_utime + usage.ru_stime,
              'child_user_cpu_seconds': usage.ru_utime, 'child_system_cpu_seconds': usage.ru_stime,
              'child_peak_rss_kib_linux': usage.ru_maxrss, 'wall_seconds': time.perf_counter() - start,
              'log_sha256': sha(log), 'measurement': 'Linux wait4; imports and waited native descendants included',
              'thread_counts': {name: environment[name] for name in (
                  'OMP_NUM_THREADS', 'MKL_NUM_THREADS', 'OPENBLAS_NUM_THREADS', 'NUMEXPR_NUM_THREADS')}}
    write_json(receipt, result)
    print({'phase': key, 'exit_code': process.returncode,
           'complete_child_cpu_seconds': result['complete_child_cpu_seconds']}, flush=True)
    if process.returncode:
        raise RuntimeError('Failed phase preserved at ' + str(log))
    return result


def preflight(output):
    import unittest
    import numpy as np
    import torch
    from .task_value import binary_observation_model, solve, literal_binary_reference, binary_rollouts
    from .task_value_tests import TaskValueTests
    from .task_value_execution_tests import ExecutionContractTests, fixture_law
    from .task_value_heads import Policy, make_solutions
    from .task_value_native import run_stream, TaskNativeSession
    from ..hcsn_free_boundary_v1.native_bridge import Signals, UPSTREAM
    from ..hcsn_free_boundary_v1.restore_native import restore

    suite = unittest.TestSuite([unittest.defaultTestLoader.loadTestsFromTestCase(cls)
                               for cls in (TaskValueTests, ExecutionContractTests)])
    result = unittest.TextTestRunner(stream=sys.stdout, verbosity=2).run(suite)
    if not result.wasSuccessful():
        raise AssertionError('Task value preflight tests failed')
    output = Path(output) / 'preflight'
    output.mkdir(exist_ok=False)
    rows = []
    for i, (price, refractory, discount) in enumerate(((.005, 0, 1.), (.02, 2, 1.), (.07, 4, .98))):
        model = binary_observation_model(10, .72)
        table = solve(model, horizon=18, tasks=3, price=price,
                      refractory=refractory, discount=discount)
        raw = binary_rollouts(table, samples=50000, seed=32010 + i, reliability=.72)
        with (output / ('binary_rollouts_' + str(i) + '.npz')).open('xb') as stream:
            np.savez_compressed(stream, **raw)
        expected = float(table.fresh[3, 18])
        mean = float(raw['utility'].mean())
        se = float(raw['utility'].std(ddof=1) / np.sqrt(len(raw['utility'])))
        if abs(mean - expected) / se > 4.5:
            raise AssertionError('Actual reward Monte Carlo does not agree with the exact oracle')
        small = solve(model, horizon=6, tasks=3, price=price,
                      refractory=refractory, discount=discount)
        reference = literal_binary_reference(horizon=6, tasks=3, price=price,
                        refractory=refractory, discount=discount, max_reads=10, reliability=.72)
        rows.append({'price': price, 'refractory': refractory, 'discount': discount,
                     'expected_total_reward': expected, 'mc_mean_reward': mean,
                     'mc_standard_error': se, 'absolute_z': abs(mean - expected) / se,
                     'actual_mean_later_correct': float(raw['later_task_correct'].mean()),
                     'literal_history_absolute_error': abs(small.fresh[3, 6] - reference),
                     'raw_sha256': sha(output / ('binary_rollouts_' + str(i) + '.npz'))})
    write_json(output / 'EXACT_ORACLE.json', {'tests': result.testsRun, 'all_passed': True, 'cases': rows})

    class FixtureBackbone:
        def step(self, x, dt, state=None):
            old = torch.zeros(len(x)) if state is None else state['count']
            state = {'count': old + 1}
            logits = torch.zeros((len(x), 10))
            logits[:, 0] = 2.
            return logits, state, {}

    edges = np.tile([.3, .6, .9], (33, 1))
    solutions = make_solutions(fixture_law(), [.001])
    policy = Policy('validation_schedule', solutions, edges,
                    settings={'0.001': {'prefix': 2, 'balanced': False}})
    binary, _ = restore(output / 'runtime/continuous_host')
    record = run_stream(FixtureBackbone(), policy, torch.zeros((3, 32, 64)), torch.ones((3, 32)),
        np.array([0, 1, 0]), ['fixture0', 'fixture1', 'fixture2'], price=.001,
        stream_number=0, directory=output / 'native_fixture', binary=binary,
        identity={'scope': 'explicit deterministic engineering fixture, not learned content evidence'})
    if (record['actual_reads'] != 6 or record['correct'] != 2 or record['quiet_ticks'] != 4
            or abs(record['utility'] - 1.994) > 1e-14 or record['later_task_correct'] != 1):
        raise AssertionError('Native task reset/reward/quiet accounting differs from independent fixture')
    print({'preflight_native_read_ticks': record['actual_reads'], 'actual_later_correct': 1}, flush=True)
    causal_table = solve(binary_observation_model(10, .72), horizon=18, tasks=3,
                         price=.005, refractory=2)
    causal = []
    objective = {'problem': 'exact noisy-binary-task queue', 'max_deadline': 18,
                 'max_tasks': 3, 'read_price': .005, 'refractory': 2, 'reliability': .72}
    for remaining in (1, 3):
        qfire = float(causal_table.fire[remaining, 3, 1, 11])
        qread = float(causal_table.read[remaining, 3, 1, 11])
        session = TaskNativeSession(output / ('future_causality_tasks_' + str(remaining)),
            binary=binary, family='exact_binary_future_causality',
            model_digest=UPSTREAM.digest(objective), objective=objective, case='same_observed_prefix', seed=0)
        row = session.tick(Signals(float(np.tanh(qread - qfire)), 0., 0., 0.),
            context={'observed_prefix': [1], 'remaining_ticks': 3, 'remaining_tasks': remaining,
                     'exact_fire_value': qfire, 'exact_read_value': qread,
                     'future_after_reset': float(causal_table.future_after_reset[remaining, 3])})
        terminal = session.verify_terminal() if session.terminal else None
        cost = session.close()
        causal.append({'remaining_tasks': remaining, 'row': row, 'terminal_probe': terminal, 'cost': cost})
    if [row['row']['native']['effective_action'] for row in causal] != ['keep', 'stop']:
        raise AssertionError('Actual owner did not consume the change in subsequent-task value')
    write_json(output / 'FUTURE_VALUE_CAUSALITY.json', {'same_observed_prefix': True,
        'remaining_queue_is_the_only_changed_public_state': True, 'records': causal,
        'scope': 'Exact binary task-value engineering fixture, separate from MNIST quality'})


def register(output):
    output = Path(output).resolve()
    output.relative_to(REPOSITORY)
    files = list(PACKAGE.glob('task_value*.py'))
    snapshot = output / 'registered_source'
    snapshot.mkdir(exist_ok=False)
    snapshot_map = {}
    for path in files:
        destination = snapshot / path.name
        with destination.open('xb') as handle:
            handle.write(path.read_bytes())
        snapshot_map[str(path.relative_to(REPOSITORY))] = {
            'snapshot': str(destination.relative_to(output)), 'sha256': sha(destination)}
    write_json(output / 'REGISTERED_SOURCE.json', snapshot_map)
    files.extend(V1.glob('*.py'))
    files.extend((V1 / 'native_vendor').glob('*'))
    files.extend((V1.with_name('continuous_spiking_network')).glob('*.py'))
    files.extend([BACKBONE_RUN / name for name in ('selected.npz', 'summary.json', 'EXECUTION.json')])
    files.extend([V1 / name for name in ('data/study001/mnist.npz', 'data/study001/mnist.json',
                  'data/study001/SOURCES.json', 'data/native003/fresh_mnist.npz', 'data/native003/fresh_mnist.json')])
    files.extend([output / name for name in ('PROTOCOL.json', 'data/fresh_mnist.npz', 'data/fresh_mnist.json')])
    for prior in read_json(output / 'PROTOCOL.json').get('prior_attempts', []):
        files.append(REPOSITORY / prior['receipt'])
    identities = {str(path.relative_to(REPOSITORY)): sha(path) for path in sorted(set(files)) if path.is_file()}
    write_json(output / 'REGISTRATION.json', {'schema': 'hcsn-v2-task-registry.v1',
        'created_utc': datetime.now(timezone.utc).isoformat(), 'files': identities,
        'fresh_test_inference_performed': False, 'head_training_performed': False,
        'preflight_passed': True, 'independence_scope': 'New384 image IDs; original VAL and fixed backbone reused'})


def run(output, raw_root, prior_attempts=()):
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    prior_records = []
    for directory in prior_attempts:
        receipt = Path(directory).resolve() / 'CAMPAIGN_EXECUTION.json'
        row = read_json(receipt)
        prior_records.append({'receipt': str(receipt.relative_to(REPOSITORY)),
                              'sha256': sha(receipt), 'exit_code': row['exit_code'],
                              'complete_child_cpu_seconds': row['complete_child_cpu_seconds']})
    write_json(output / 'PROTOCOL.json', {**PROTOCOL, 'study_id': output.name, 'prior_attempts': prior_records})
    commands = [sys.executable, '-m', 'experiments.hcsn_distributional_v2.task_value_run',
                '--output', str(output), '--raw-root', str(raw_root)]
    self_start = time.process_time()
    receipts = {}
    for phase in ('prepare', 'preflight'):
        receipts[phase] = measure(output, phase, commands + ['--worker', phase])
    register(output)
    for phase in ('fit', 'evaluate'):
        receipts[phase] = measure(output, phase, commands + ['--worker', phase])
    for kind in ('reference', 'active', 'quiet'):
        receipts['recovery_' + kind] = measure(output, 'recovery_' + kind,
            commands + ['--worker', 'recovery', '--kind', kind])
        if kind != 'reference':
            receipts['resume_' + kind] = measure(output, 'resume_' + kind,
                commands + ['--worker', 'recovery', '--kind', kind, '--resume'])
    from .task_value_study import audit_recovery
    audit_recovery(output)
    write_json(output / 'COMPLETE.json', {'status': 'completed', 'phases': receipts,
        'complete_measured_child_cpu_seconds': sum(row['complete_child_cpu_seconds'] for row in receipts.values()),
        'coordinator_self_cpu_seconds_before_report': time.process_time() - self_start,
        'scope': 'Disjoint measured phase processes; native descendants are nested and not added again',
        'registry_sha256': sha(output / 'REGISTRATION.json'), 'selection_lock_sha256': sha(output / 'SELECTION_LOCK.json')})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--raw-root', type=Path, required=True)
    parser.add_argument('--worker', choices=('prepare', 'preflight', 'fit', 'evaluate', 'recovery'))
    parser.add_argument('--kind', choices=('reference', 'active', 'quiet'))
    parser.add_argument('--resume', action='store_true')
    parser.add_argument('--prior-attempt', action='append', type=Path, default=[])
    args = parser.parse_args()
    if args.worker == 'prepare':
        from .task_value_data import prepare_fresh
        prepare_fresh(args.raw_root, args.output / 'data')
    elif args.worker == 'preflight':
        preflight(args.output)
    elif args.worker in ('fit', 'evaluate', 'recovery'):
        import torch
        from .task_value_study import fit, evaluate, recovery_worker
        torch.set_num_threads(1)
        if args.worker == 'fit':
            fit(args.output)
        elif args.worker == 'evaluate':
            evaluate(args.output)
        else:
            recovery_worker(args.output, args.kind, args.resume)
    else:
        run(args.output, args.raw_root, args.prior_attempt)


if __name__ == '__main__':
    main()
