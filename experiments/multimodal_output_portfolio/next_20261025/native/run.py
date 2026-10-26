"""Actual qualified native NDU choice, generation, observation and restart.

Three interleaved policies execute real requests: native NDU, the same newly
qualified head's correctness argmax, and the original legacy two-action owner.
Every policy has its own journals and physical feature/generation work. Future
innovations are sampled only after that policy's durable native decision.
"""

import argparse
import copy
import json
import math
from pathlib import Path
import time

import numpy as np
import torch

from ...abc_recovery.runtime import ACTIONS, initialize, transition, public_frame, public_digest
from ...abc_followup.native.forecast import Q, public_input, predict, groups, quantize
from ...closure_20261025.native.run import Native, recovery, rejected
from ...v6.data import render_tokens
from ...v6.observer import observe_tensors, read_bundle, write_bundle
from ...v7.data import make_batch
from ...v7.evaluation import load_reward
from ...v7.snapshot import Snapshot
from ...v7.sources import load_roles
from ..sources import load_registered
from .common import AREA, ALLOCATION, ASSETS, MODEL, NATIVE, OBSERVER, OLD_HEAD, SHARED, sha, write
from .encoder import PublicEncoder, projected_moments
from .model_package import descriptor, legacy_descriptor
from .qualification import calibrated, probabilities


POLICIES = ('ndu', 'correctness', 'legacy_correctness')
FLAGS = ((0, 0), (-Q, 0), (0, -Q), (Q, 0), (0, Q))
ID_VIEWS = ('clean', 'noise', 'occlusion', 'missing_trusted', 'conflict_untrusted')


def negatives(native, request):
    values = []
    for name, key, value in [('generation', 'generation', 2), ('weights', 'weights_sha256', '0' * 64),
                             ('objective', 'objective_digest', '0' * 64), ('future_field', 'target', [9, 9])]:
        changed = copy.deepcopy(request); changed[key] = value
        values.append(rejected(native, name, changed))
    for name in ('candidate_set', 'prefix_mismatch', 'action_flags', 'feature_width', 'value_prefix_mismatch', 'horizon'):
        changed = copy.deepcopy(request)
        if name == 'candidate_set': changed['candidates'].pop()
        elif name == 'prefix_mismatch': changed['candidates'][1]['features'][0] += 1
        elif name == 'action_flags': changed['candidates'][0]['features'][476] = Q * 3
        elif name == 'feature_width': changed['candidates'][0]['features'].append(0)
        elif name == 'value_prefix_mismatch': changed['candidates'][1]['features'][478] += 1
        else:
            for candidate in changed['candidates']: candidate['features'][510] = 2 * Q
        values.append(rejected(native, name, changed))
    return values


def outcome_negatives(native, command, observed, output):
    values = []
    for name, key, value in [('decision_binding', 'decision_digest', '0' * 64),
                             ('receipt_hash', 'receipt_sha256', '0' * 64)]:
        changed = copy.deepcopy(command); changed[key] = value
        values.append(rejected(native, name, changed))
    for name in ('observer', 'action', 'causal_time', 'media_hash', 'utility_bound'):
        value = copy.deepcopy(observed)
        if name == 'observer': value['observer_sha256'] = '0' * 64
        elif name == 'action': value['action'] = 'invalid_action'
        elif name == 'causal_time': value['generation_started_ns'] = value['decision_received_ns']
        elif name == 'media_hash': value['media_sha256']['image'] = '0' * 64
        else: value['utility_q32'] = 2 ** 32 + 1
        path = output / f'negative-{name}.json'; write(path, value)
        changed = copy.deepcopy(command); changed.update(receipt_path=str(path), receipt_sha256=sha(path))
        values.append(rejected(native, name, changed))
    return values


def run(args):
    torch.set_num_threads(1)
    output = args.output; output.mkdir(parents=True, exist_ok=False)
    package = json.loads(args.package.read_text())
    export = json.loads(Path(package['weights_path']).read_text())
    new_predictor = json.loads(Path(package['predictor_path']).read_text())
    new_calibration = json.loads(Path(package['calibration_path']).read_text())
    registration = {'schema': 'hepta.next.native-owner-access.v1', 'mode': args.mode,
                    'new_sources': args.mode == 'confirm', 'count': args.count,
                    'source_allocation_sha256': sha(ALLOCATION), 'binary_sha256': sha(args.binary),
                    'package_sha256': sha(args.package), 'protocol_sha256': sha(args.protocol) if args.protocol else None,
                    'views': 'one cycling ID view and both_missing per source', 'policies': POLICIES,
                    'order': 'cyclic rotation by source and view, fixed before outcomes',
                    'frozen_unix_ns': time.time_ns(), 'H1_only': True,
                    'rejection_score': {'utility': -1., 'joint_correct': False},
                    'null_action_is_rejection_not_successful_stop': True}
    write(output / 'registration.json', registration)
    start, cpu = time.perf_counter_ns(), time.process_time_ns()
    if args.mode == 'smoke':
        corpus = load_roles(SHARED / 'abc2-assets/mnist', SHARED / 'abc2-runs/source-recovery-001/source-manifest.json', roles=('train',))
        role = 'train'
    else:
        if args.count != 96 or args.protocol is None:
            raise ValueError('The exact new 96-pair protocol is required')
        frozen = json.loads(args.protocol.read_text())
        if frozen['binary_sha256'] != sha(args.binary) or frozen['package_sha256'] != sha(args.package):
            raise ValueError('Native binary or model package differs from prospective freeze')
        corpus = load_registered(ASSETS / 'qmnist', ALLOCATION, args.protocol, study='native')
        role = 'next_native'
    model = Snapshot.load(MODEL, expected_file_sha256=sha(MODEL))._model
    observer, _ = load_reward(OBSERVER, sha(OBSERVER))
    encoder = PublicEncoder()
    legacy_weights = json.loads((OLD_HEAD / 'weights.json').read_text())
    legacy_calibration = json.loads((OLD_HEAD / 'calibration.json').read_text())
    owners, descriptors, binary, processes, statuses = {}, {}, {}, {}, {}
    for policy in POLICIES:
        area = output / policy; area.mkdir()
        legacy = policy == 'legacy_correctness'
        spec = (legacy_descriptor(4 * args.count + 16, registration) if legacy else
                descriptor(args.package, policy, 10 * args.count + 40, registration))
        descriptors[policy] = area / 'descriptor.json'; write(descriptors[policy], spec)
        binary[policy] = NATIVE / 'raw_evidence/native/build-004/hepta-native-online' if legacy else args.binary
        owners[policy] = Native(binary[policy], descriptors[policy], area / 'state', 'new', area / 'process-0.stderr')
        processes[policy] = [owners[policy].process.pid]; statuses[policy] = []
    rows, checks, recoveries = [], [], []
    first_outcome = {p: True for p in POLICIES}
    max_moment_error, max_teacher_error = 0., 0.
    with (output / 'rollouts.jsonl').open('x') as journal:
        for case in range(args.count):
            for view_index, view in enumerate((ID_VIEWS[case % 5], 'both_missing')):
                rotation = (case + view_index) % 3
                for policy in POLICIES[rotation:] + POLICIES[:rotation]:
                    began = time.perf_counter_ns()
                    work_ns = 0
                    area = output / policy
                    legacy = policy == 'legacy_correctness'
                    native = owners[policy]
                    seed = 8360017 + case * 1009 + view_index * 1000000
                    batch = make_batch(corpus, role, 1, seed, view=view, offset=case)
                    with torch.inference_mode():
                        rng = torch.Generator().manual_seed(seed + 1000000)
                        prefix = initialize(model, batch.observation, generator=rng)
                        prefix = transition(model, prefix, 'refine_image', generator=rng)
                        frame = public_frame(prefix)
                        feature_begin = time.perf_counter_ns()
                        if legacy:
                            actions = ('refine_text', 'couple')
                            inputs = [public_input(model, frame, batch.observation, a)[0].tolist() for a in actions]
                            original_moments = None; feature_work = {}
                        else:
                            encoded, original_moments, feature_work, _ = encoder.encode(model, frame, batch.observation)
                            actions = ACTIONS
                            inputs = []
                            for flag in FLAGS:
                                value = encoded[0].copy(); value[476:478] = flag; inputs.append(value)
                        feature_ns = time.perf_counter_ns() - feature_begin
                        work_ns += time.perf_counter_ns() - began
                        spec = json.loads(descriptors[policy].read_text())
                        request = {'kind': 'decide', 'request_id': f'next.case.{case}.{view_index}.{policy}',
                                   'generation': 1, 'weights_sha256': spec['pins']['weights'],
                                   'objective_digest': sha(descriptors[policy]), 'prefix_digest': public_digest(frame),
                                   'candidates': [{'action': a, 'features': x} for a, x in zip(actions, inputs)]}
                        if case == 0 and view_index == 0 and not legacy:
                            checks += [{'policy': policy, **c} for c in negatives(native, request)]
                        prior = native.success({'kind': 'status'})
                        tick_begin = time.perf_counter_ns()
                        decision = native.success(request); received = time.time_ns()
                        decision_ns = time.perf_counter_ns() - tick_begin; work_ns += decision_ns
                        tag = f'{case:04d}-{view}'
                        write(area / ('decision-' + tag + '.json'), {'request': request, 'response': decision, 'received_ns': received})
                        for index, (candidate, values) in enumerate(zip(decision['decision']['candidates'], inputs)):
                            if candidate['prior_modulator'] != prior['modulator']:
                                raise ValueError('A future NDU outcome entered a current decision')
                            if legacy:
                                x = np.asarray([values], dtype=np.float64) / Q
                                forecast, raw = predict(legacy_weights, x)
                                probability = legacy_calibration['probabilities'][int(groups(x, raw, legacy_calibration['cuts'])[0])]
                                expected = quantize(np.column_stack(([probability], forecast)))[0].tolist()
                                if [candidate['probability_q24'], *candidate['forecast_q24']] != expected:
                                    raise ValueError('Legacy actual native model differs from frozen Python model')
                            else:
                                expected = projected_moments(export, values)
                                error = float(np.max(np.abs(np.asarray(candidate['ndu_moments'], dtype=np.float64) - expected)))
                                teacher_error = float(np.max(np.abs(np.asarray(candidate['ndu_moments'], dtype=np.float64) - original_moments)))
                                max_moment_error = max(max_moment_error, error)
                                max_teacher_error = max(max_teacher_error, teacher_error)
                                if error > 1e-10 or teacher_error > 3e-6:
                                    raise ValueError('Actual native NDU layer exceeds frozen numerical tolerance')
                                raw = probabilities(new_predictor, np.asarray(values[478:510]) / Q)
                                absent = view == 'both_missing'
                                p = calibrated(new_calibration, np.asarray([raw[index]]), np.asarray([absent]))[0]
                                if candidate['confidence_ppm'] != round(p * 1e6):
                                    raise ValueError('Native calibrated confidence differs from verified function')
                        action = decision['decision']['selected_action']
                        teacher_choice = None
                        if policy == 'ndu':
                            eligible = [i for i, c in enumerate(decision['decision']['candidates'])
                                        if c['admitted'] and i != 1]
                            if eligible:
                                teacher_choice = ACTIONS[min(eligible, key=lambda i: (original_moments[i], i))]
                        row = {'pair': case, 'source_ids': batch.source_ids[0], 'view': view, 'policy': policy,
                               'action': action, 'decision_digest': decision['decision_digest'],
                               'initial_public_digest': public_digest(frame), 'feature_ns': feature_ns,
                               'decision_ns': decision_ns, 'feature_work': feature_work,
                               'decision_received_ns': received, 'prior_modulator': prior['modulator'],
                               'original_teacher_choice_on_same_admission_set': teacher_choice,
                               'original_teacher_action_parity': None if policy != 'ndu' else teacher_choice == action,
                               'selected_confidence_ppm': next((c['confidence_ppm'] for c in decision['decision']['candidates'] if c['action'] == action), None)}
                        if action is not None:
                            if first_outcome[policy]:
                                changed = copy.deepcopy(request); changed['request_id'] += '.pending'
                                checks.append({'policy': policy, **rejected(native, 'pending_blocks_decision', changed)})
                                before = native.interrupt(); statuses[policy].append(before)
                                native = Native(binary[policy], descriptors[policy], area / 'state', 'resume', area / f'process-{len(processes[policy])}.stderr')
                                owners[policy] = native; processes[policy].append(native.process.pid)
                                recoveries.append({'policy': policy, **recovery(before, native.ready['status'], 'abrupt_pending_decision')})
                            generate_begin = time.perf_counter_ns(); generated_ns = time.time_ns()
                            action_index = ACTIONS.index(action)
                            future = transition(model, prefix, action, generator=torch.Generator().manual_seed(seed + 2000000 + action_index * 3000000))
                            media = write_bundle(area / 'media' / tag, render_tokens(future.tokens[0]), future.pixels[0])
                            reopened, caption, hashes = read_bundle(media)
                            if not torch.equal(reopened[0], future.pixels[0]) or caption != render_tokens(future.tokens[0]):
                                raise ValueError('Actual selected output failed round-trip')
                            score = observe_tensors(observer, reopened, [caption], batch.target.pixels, batch.target.labels)[0]
                            utility = score['utility'] * 2 ** 32
                            observed = {'request_id': request['request_id'], 'decision_digest': decision['decision_digest'],
                                        'action': action, 'observer_sha256': sha(OBSERVER), 'media': media, 'media_sha256': hashes,
                                        'decision_received_ns': received, 'generation_started_ns': generated_ns,
                                        'observed_ns': time.time_ns(), 'utility_q32': math.floor(utility + .5) if utility >= 0 else math.ceil(utility - .5),
                                        'scores': score, 'source_ids': batch.source_ids[0]}
                            receipt = area / ('outcome-' + tag + '.json'); write(receipt, observed)
                            command = {'kind': 'observe', 'request_id': request['request_id'],
                                       'decision_digest': decision['decision_digest'], 'selected_action': action,
                                       'receipt_path': str(receipt), 'receipt_sha256': sha(receipt)}
                            work_ns += time.perf_counter_ns() - generate_begin
                            if first_outcome[policy]:
                                checks += [{'policy': policy, **c} for c in outcome_negatives(native, command, observed, area)]
                            observe_begin = time.perf_counter_ns(); outcome = native.success(command)
                            work_ns += time.perf_counter_ns() - observe_begin
                            if first_outcome[policy]:
                                checks.append({'policy': policy, **rejected(native, 'duplicate_outcome', command)})
                                first_outcome[policy] = False
                            row.update(scores=score, media_sha256=hashes, outcome_sha256=sha(receipt),
                                       generation_started_ns=generated_ns, next_modulator=outcome['status']['modulator'],
                                       continuation_generations=int(action != 'stop'))
                        else:
                            row.update(scores={'utility': -1., 'joint_fact_correct': False}, continuation_generations=0)
                        if case == 0 and view_index == 0:
                            checks.append({'policy': policy, **rejected(native, 'duplicate_decision', request)})
                        row.update(request_ns=work_ns, instrumented_wall_ns=time.perf_counter_ns() - began,
                                   cost_excludes='deliberate rejection probes and forced process-recovery faults; separately present in whole-process cost')
                        rows.append(row); journal.write(json.dumps(row, sort_keys=True) + '\n'); journal.flush()
            if case + 1 == args.count // 2:
                for policy in POLICIES:
                    before = owners[policy].close(); statuses[policy].append(before)
                    area = output / policy
                    owners[policy] = Native(binary[policy], descriptors[policy], area / 'state', 'resume', area / f'process-{len(processes[policy])}.stderr')
                    processes[policy].append(owners[policy].process.pid)
                    recoveries.append({'policy': policy, **recovery(before, owners[policy].ready['status'], 'graceful_committed_outcomes')})
            if (case + 1) % 8 == 0:
                print(json.dumps({'pairs': case + 1, 'requests': len(rows)}), flush=True)
    for policy in POLICIES:
        statuses[policy].append(owners[policy].close())
    write(output / 'results.json', {'schema': 'hepta.next.native-owner-results.v1', 'registration': registration,
          'source_pairs': args.count, 'actual_policy_requests': len(rows),
          'actual_emitted_outputs': sum(r['action'] is not None for r in rows),
          'actual_continuation_generations': sum(r['continuation_generations'] for r in rows),
          'max_native_numpy_moment_error': max_moment_error, 'max_native_original_teacher_error': max_teacher_error,
          'negative_cases': checks, 'recoveries': recoveries, 'process_ids': processes, 'process_status': statuses,
          'wall_ns': time.perf_counter_ns() - start, 'cpu_ns': time.process_time_ns() - cpu,
          'rollouts_sha256': sha(output / 'rollouts.jsonl'), 'new_sources_used_to_train': False,
          'whole_agentd_daemon': False, 'production_authority': False})


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('binary', 'package', 'output'):
        parser.add_argument('--' + name, type=Path, required=True)
    parser.add_argument('--mode', choices=('smoke', 'confirm'), default='smoke')
    parser.add_argument('--count', type=int, default=16)
    parser.add_argument('--protocol', type=Path)
    run(parser.parse_args())
