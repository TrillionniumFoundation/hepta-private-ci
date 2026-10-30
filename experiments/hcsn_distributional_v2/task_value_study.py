"""Fit and evaluate the separately registered regenerative classification task."""

from pathlib import Path
import time

import numpy as np
import torch

from ..hcsn_free_boundary_v1.restore_native import restore
from .task_value_common import (V1, BACKBONE_RUN, BACKBONE_SHA, read_json, write_json,
                                sha, load_backbone, verify_registration, verify_selection)
from .task_value_data import (trace_split, fit_observation_model, load_observation_model,
                              load_trace)
from .task_value_heads import (FAMILIES, make_solutions, train_heads, select_ordinary,
                               load_policies, validation_score, cached_rollouts, Policy)
from .task_value_native import run_stream, comparable_trajectory


def fit(output):
    output = Path(output)
    verify_registration(output)
    protocol = read_json(output / 'PROTOCOL.json')
    model = load_backbone()
    traces = output / 'traces'
    traces.mkdir(exist_ok=False)
    trace_receipts = {split: trace_split(model, split, traces) for split in ('train', 'val')}
    teacher = output / 'teacher'
    teacher.mkdir(exist_ok=False)
    clock = time.process_time()
    observation_model, edges = fit_observation_model(traces / 'train.npz', teacher)
    fit_cpu = time.process_time() - clock
    clock = time.process_time()
    solutions = make_solutions(observation_model, protocol['prices'])
    for price, solution in solutions.items():
        with (teacher / ('price_' + price + '.npz')).open('xb') as handle:
            np.savez_compressed(handle, value=solution.value, fire=solution.fire,
                read=solution.read, fresh=solution.fresh, future=solution.future_after_reset)
    solve_cpu = time.process_time() - clock
    if any(np.any(s.fresh[1:, 1:] <= 0) for s in solutions.values()):
        raise AssertionError('Registered real-data prices must permit every fresh task start')
    validation = load_trace(traces / 'val.npz')
    head_dir = output / 'heads'
    head_dir.mkdir(exist_ok=False)
    clock = time.process_time()
    heads = train_heads(head_dir, protocol, solutions, edges, validation)
    head_cpu = time.process_time() - clock
    clock = time.process_time()
    ordinary = select_ordinary(head_dir, solutions, edges, validation, protocol['prices'])
    ordinary_cpu = time.process_time() - clock
    policies = load_policies(head_dir, solutions, edges)
    validations = {name: validation_score(policy, validation, protocol['prices'])
                   for name, policy in policies.items()}
    ordinary_families = ('ordinary_action_head', 'validation_schedule', 'validation_risk')
    best_ordinary = max(ordinary_families, key=lambda name: (
        validations[name]['macro_utility'], -ordinary_families.index(name)))
    summary = {'status': 'completed', 'trace_receipts': trace_receipts,
               'observation_model_fit_parent_cpu_seconds': fit_cpu,
               'teacher_solve_and_save_parent_cpu_seconds': solve_cpu,
               'head_training_parent_cpu_seconds': head_cpu,
               'ordinary_selection_parent_cpu_seconds': ordinary_cpu,
               'head_study': heads, 'ordinary_study': ordinary,
               'validation_scores': validations, 'best_ordinary_family': best_ordinary,
               'backbone_sha256': BACKBONE_SHA,
               'backbone_historical_complete_cpu_seconds': read_json(BACKBONE_RUN / 'EXECUTION.json')['child_cpu_seconds'],
               'new_backbone_training': False, 'fresh_test_accessed': False,
               'scope': 'Matched architecture/input/updates; target/objective intervention. No equal-CPU or neuron-architecture superiority claim.'}
    write_json(output / 'TRAINING_SUMMARY.json', summary)
    locked = [output / 'TRAINING_SUMMARY.json']
    locked.extend(path for folder in (traces, teacher, head_dir) for path in folder.rglob('*') if path.is_file())
    verify_registration(output)
    write_json(output / 'SELECTION_LOCK.json', {
        'files': {str(path.relative_to(output)): sha(path) for path in sorted(locked)},
        'both_lrs_and_all_candidates_completed': True, 'fresh_test_accessed': False,
        'best_ordinary_family': best_ordinary})
    print({'phase': 'fit', 'best_ordinary_validation': best_ordinary,
           'validation_macro_utility': {name: row['macro_utility'] for name, row in validations.items()}}, flush=True)


def controller_bundle(output):
    output = Path(output)
    verify_selection(output)
    protocol = read_json(output / 'PROTOCOL.json')
    observation, edges = load_observation_model(output / 'teacher/observation_model.npz')
    solutions = make_solutions(observation, protocol['prices'])
    for price, solution in solutions.items():
        with np.load(output / 'teacher' / ('price_' + price + '.npz'), allow_pickle=False) as stored:
            for key, value in {'value': solution.value, 'fire': solution.fire, 'read': solution.read,
                               'fresh': solution.fresh, 'future': solution.future_after_reset}.items():
                if not np.array_equal(stored[key], value, equal_nan=True):
                    raise AssertionError('Teacher changed on independent re-solve')
    return protocol, solutions, edges, load_policies(output / 'heads', solutions, edges)


def heldout_inputs(output):
    output = Path(output)
    registration = verify_selection(output)
    data = output / 'data/fresh_mnist.npz'
    metadata = read_json(data.with_suffix('.json'))
    if sha(data) != metadata['sha256']:
        raise ValueError('Fresh dataset hash changed immediately before heldout loading')
    with np.load(data, allow_pickle=False) as archive:
        x, dt, labels = (np.array(archive[key], copy=True) for key in ('x', 'dt', 'labels'))
    order = np.random.default_rng(73013).permutation(len(labels)).reshape(-1, 3)
    identity = {'dataset_sha256': metadata['sha256'], 'metadata_sha256': sha(data.with_suffix('.json')),
                'backbone_sha256': BACKBONE_SHA, 'selection_lock_sha256': sha(output / 'SELECTION_LOCK.json'),
                'registration_sha256': sha(output / 'REGISTRATION.json'),
                'protocol_sha256': sha(output / 'PROTOCOL.json')}
    return x, dt, labels, order, metadata['image_source_ids'], identity


def evaluate(output):
    output = Path(output)
    protocol, solutions, edges, policies = controller_bundle(output)
    write_json(output / 'HELDOUT_ACCESS.json', {
        'selection_lock_verified_before_access': True, 'selection_lock_sha256': sha(output / 'SELECTION_LOCK.json'),
        'fresh_data_sha256': sha(output / 'data/fresh_mnist.npz'),
        'model_inference_started': False})
    model = load_backbone()
    trace_receipt = trace_split(model, 'test', output / 'traces', output / 'data/fresh_mnist.npz')
    test = load_trace(output / 'traces/test.npz')
    x, dt, labels, queues, image_ids, identity = heldout_inputs(output)
    evaluation = output / 'evaluation'
    evaluation.mkdir(exist_ok=False)
    cached, native, cache_rows, parity = {}, {}, {}, []
    binary, _ = restore(output / 'runtime/continuous_host')
    tensor_x, tensor_dt = torch.from_numpy(x), torch.from_numpy(dt)
    for price in protocol['prices']:
        price_dir = evaluation / ('price_' + str(price))
        price_dir.mkdir(exist_ok=False)
        cached[str(price)], native[str(price)], cache_rows[str(price)] = {}, {}, {}
        for family, policy in policies.items():
            clock = time.process_time()
            raw = cached_rollouts(policy, test, price, 73013)
            with (price_dir / (family + '_counterfactual.npz')).open('xb') as handle:
                np.savez_compressed(handle, **raw)
            cached[str(price)][family] = {'streams': len(raw['utility']),
                'mean_utility': float(raw['utility'].mean()), 'sd_utility': float(raw['utility'].std(ddof=1)),
                'mean_reads': float(raw['task_reads'].sum(1).mean()),
                'mean_correct': float(raw['task_correct'].sum(1).mean()),
                'mean_actual_later_correct': float(raw['actual_later_correct'].mean()),
                'mean_actual_later_net_reward': float(raw['actual_later_net_reward'].mean()),
                'mean_first_fire_predicted_future': float(raw['first_fire_predicted_future'].mean()),
                'counterfactual_parent_cpu_seconds': time.process_time() - clock}
            cache_rows[str(price)][family] = raw
            clock = time.process_time()
            records = []
            for stream in range(protocol['native_streams']):
                q = queues[stream]
                directory = price_dir / family / ('stream_' + str(stream))
                started = time.process_time()
                row = run_stream(model, policy, tensor_x[q], tensor_dt[q], labels[q],
                    [image_ids[index] for index in q], price=price, stream_number=stream,
                    directory=directory, binary=binary, identity=identity)
                parent_cpu = time.process_time() - started
                write_json(directory / 'STREAM_EXECUTION.json', {'parent_cpu_seconds': parent_cpu,
                    'native_child_cpu_seconds': row['native_child_cpu_seconds'],
                    'complete_stream_cpu_seconds': parent_cpu + row['native_child_cpu_seconds'],
                    'scope': 'Parent slice plus waited native children; nested in complete evaluator wait4 receipt'})
                records.append(row)
                actual_reads = np.zeros(3, dtype=int)
                actual_correct = np.zeros(3, dtype=int)
                for task in row['task_results']:
                    actual_reads[task['task_index']] = task['actual_reads']
                    actual_correct[task['task_index']] = task['correct']
                matched = np.array_equal(actual_reads, raw['task_reads'][stream]) and np.array_equal(
                    actual_correct, raw['task_correct'][stream])
                parity.append({'price': price, 'family': family, 'stream': stream, 'matched': bool(matched),
                               'actual_reads': actual_reads.tolist(), 'cached_reads': raw['task_reads'][stream].tolist(),
                               'actual_correct': actual_correct.tolist(), 'cached_correct': raw['task_correct'][stream].tolist()})
            parent_cpu = time.process_time() - clock
            child_cpu = sum(row['native_child_cpu_seconds'] for row in records)
            costs = [cost for row in records for cost in row['native_costs']]
            native[str(price)][family] = {'streams': len(records),
                'mean_utility': float(np.mean([row['utility'] for row in records])),
                'mean_reads': float(np.mean([row['actual_reads'] for row in records])),
                'mean_correct': float(np.mean([row['correct'] for row in records])),
                'mean_actual_later_correct': float(np.mean([row['later_task_correct'] for row in records])),
                'mean_actual_later_net_reward': float(np.mean([row['later_task_net_reward'] for row in records])),
                'actual_owner_processes': len(costs), 'parent_cpu_seconds': parent_cpu,
                'native_child_cpu_seconds': child_cpu,
                'complete_execution_cpu_per_stream': (parent_cpu + child_cpu) / len(records),
                'owner_ticks': sum(c['counters']['owner_ticks'] for c in costs),
                'native_kernel_calls': sum(c['counters']['total_native_kernel_calls'] for c in costs),
                'native_ndu_calls': sum(c['counters']['total_native_ndu_calls'] for c in costs),
                'intentional_post_stop_rejections': sum(c['counters']['native_errors'] for c in costs),
                'failed_native_processes': sum(c['exit_code'] != 0 for c in costs),
                'float_q24_disagreements': sum(row['float_q24_disagreements'] for row in records),
                'ledger': [{'stream': i, 'utility': row['utility'], 'actual_reads': row['actual_reads'],
                            'correct': row['correct'], 'later_correct': row['later_task_correct']}
                           for i, row in enumerate(records)]}
            print({'price': price, 'family': family, 'native_mean_utility': native[str(price)][family]['mean_utility'],
                   'counterfactual_mean_utility': cached[str(price)][family]['mean_utility']}, flush=True)
    reference = read_json(output / 'TRAINING_SUMMARY.json')['best_ordinary_family']
    macro = {family: np.stack([cache_rows[str(p)][family]['utility'] for p in protocol['prices']]).mean(0)
             for family in FAMILIES}
    rng = np.random.default_rng(73015)
    boot = rng.integers(0, len(queues), (1999, len(queues)))
    differences = {}
    for family in FAMILIES:
        delta = macro[family] - macro[reference]
        interval = np.quantile(delta[boot].mean(1), [.025, .975])
        differences[family] = {'mean_paired_difference': float(delta.mean()),
            'nominal_descriptive_bootstrap_interval': interval.tolist(),
            'resampling_unit': '3-task stream, averaged over all 3 public prices before resampling',
            'hypothesis_test_or_multiple_comparison_gate': False}
    result = {'status': 'completed', 'counterfactual': cached, 'actual_native': native,
              'cache_native_parity': {'cases': len(parity), 'mismatches': sum(not p['matched'] for p in parity),
                                     'records': parity},
              'best_ordinary_selected_on_validation': reference,
              'counterfactual_macro_paired_comparisons': differences,
              'fresh_trace_generation': trace_receipt, 'identity': identity,
              'statistical_unit': 'stream, not task or repeated price condition',
              'exact_binary_oracle': False, 'mnist_coarsened_markov_approximation': True,
              'native_and_counterfactual_results_are_separate': True}
    verify_selection(output)
    write_json(output / 'EVALUATION_SUMMARY.json', result)
    return result


def recovery_worker(output, kind, resume=False):
    output = Path(output)
    _, solutions, edges, _ = controller_bundle(output)
    x, dt, labels, queues, ids, identity = heldout_inputs(output)
    identity['fixture'] = 'fixed8 task-driver recovery, not a selected policy performance claim'
    q = queues[0]
    policy = Policy('validation_schedule', solutions, edges,
                    settings={'0.001': {'prefix': 8, 'balanced': False}})
    model = load_backbone()
    binary, _ = restore(output / 'runtime/continuous_host')
    result = run_stream(model, policy, torch.from_numpy(x[q]), torch.from_numpy(dt[q]), labels[q],
        [ids[index] for index in q], price=.001, stream_number=0,
        directory=output / 'recovery' / kind, binary=binary, identity=identity, resume=resume,
        checkpoint_active=(0, 1) if kind == 'active' else None,
        checkpoint_quiet=kind == 'quiet')
    if kind != 'reference' and not resume and result['status'] != 'suspended':
        raise AssertionError('Registered recovery fixture did not suspend')
    print({'recovery_kind': kind, 'resume': resume, 'status': result['status']}, flush=True)
    return result


def audit_recovery(output):
    output = Path(output)
    reference = read_json(output / 'recovery/reference/RESULT.json')
    results = {}
    for kind in ('active', 'quiet'):
        restored = read_json(output / 'recovery' / kind / 'RESULT.json')
        if comparable_trajectory(restored) != comparable_trajectory(reference):
            raise AssertionError('Fresh-process restored task trajectory differs: ' + kind)
        if len(restored['resumptions']) != 1 or not restored['resumptions'][0]['different_python_process']:
            raise AssertionError('Recovery did not use a fresh Python process')
        results[kind] = {'semantic_trajectory_identical': True,
                         'checkpoint': restored['resumptions'][0],
                         'reads': restored['actual_reads'], 'quiet_ticks': restored['quiet_ticks'],
                         'correct': restored['correct'], 'utility': restored['utility']}
    write_json(output / 'RECOVERY_AUDIT.json', results)
    return results
