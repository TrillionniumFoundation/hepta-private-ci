"""Two authentic owner decisions, actual public feedback, and later private audit."""

import argparse
import copy
import json
import math
from pathlib import Path
import time

import numpy as np
import torch

from ...abc_recovery.runtime import initialize, transition, public_frame, public_digest
from ...abc_followup.native.forecast import Q
from ...closure_20261025.native.run import Native, recovery, rejected
from ...v6.data import render_tokens
from ...v6.observer import observe_tensors, read_bundle, write_bundle
from ...v7.data import make_batch
from ...v7.evaluation import load_reward
from ...v7.snapshot import Snapshot
from ...v7.sources import load_roles
from ..h2_sources import load_registered
from .common import ALLOCATION, ASSETS, MODEL, OBSERVER, SENSOR, SHARED, qualified_dependencies, sha, write
from .encoder import PublicEncoder, projected_moments
from .model_package import descriptor
from .observation import observe_public
from .qualification import ACTIONS, ID_VIEWS, calibrated, probabilities


POLICIES = ('ndu', 'correctness')


def negatives(native, request):
    checks = []
    for name, key, value in [('generation', 'generation', 2), ('weights', 'weights_sha256', '0' * 64),
                             ('objective', 'objective_digest', '0' * 64), ('future_target', 'target', [9, 9])]:
        changed = copy.deepcopy(request); changed[key] = value
        checks.append(rejected(native, name, changed))
    for name in ('candidate_set', 'shared_prefix', 'action_flags', 'feature_width', 'shared_hidden', 'invalid_horizon', 'H1_without_outcome'):
        changed = copy.deepcopy(request)
        if name == 'candidate_set': changed['candidates'].pop()
        elif name == 'shared_prefix': changed['candidates'][1]['features'][0] += 1
        elif name == 'action_flags': changed['candidates'][0]['features'][4] = Q * 3
        elif name == 'feature_width': changed['candidates'][0]['features'].append(0)
        elif name == 'shared_hidden': changed['candidates'][1]['features'][7] += 1
        else:
            for candidate in changed['candidates']: candidate['features'][6] = (3 if name == 'invalid_horizon' else 1) * Q
        checks.append(rejected(native, name, changed))
    return checks


def outcome_negatives(native, command, receipt, output):
    checks = []
    for name, key, value in [('decision_binding', 'decision_digest', '0' * 64), ('receipt_hash', 'receipt_sha256', '0' * 64)]:
        changed = copy.deepcopy(command); changed[key] = value
        checks.append(rejected(native, name, changed))
    for name in ('observer', 'causal_time', 'media_hash', 'utility_bound', 'episode', 'remaining', 'private_truth'):
        changed_receipt = copy.deepcopy(receipt)
        if name == 'observer': changed_receipt['observer_sha256'] = '0' * 64
        elif name == 'causal_time': changed_receipt['generation_started_ns'] = changed_receipt['decision_received_ns']
        elif name == 'media_hash': changed_receipt['media_sha256']['image'] = '0' * 64
        elif name == 'utility_bound': changed_receipt['utility_q32'] = 2 ** 32 + 1
        elif name == 'episode': changed_receipt['episode_id'] += '.wrong'
        elif name == 'remaining': changed_receipt['after_remaining'] = 3
        else: changed_receipt['private_truth_utility_supplied'] = True
        path = output / f'negative-{name}.json'; write(path, changed_receipt)
        changed = copy.deepcopy(command); changed.update(receipt_path=str(path), receipt_sha256=sha(path))
        checks.append(rejected(native, name, changed))
    return checks


def run(args):
    torch.set_num_threads(1)
    output = args.output; output.mkdir(parents=True, exist_ok=False)
    package = json.loads(args.package.read_text())
    qualified_dependencies(package['predictor_path'], package['calibration_path'])
    export = json.loads(Path(package['weights_path']).read_text())
    predictor = json.loads(Path(package['predictor_path']).read_text())
    calibration = json.loads(Path(package['calibration_path']).read_text())
    registration = {'schema': 'hepta.next.native-h2-owner-access.v1', 'mode': args.mode,
                    'new_sources': args.mode == 'confirm', 'count': args.count,
                    'source_allocation_sha256': sha(ALLOCATION), 'binary_sha256': sha(args.binary),
                    'package_sha256': sha(args.package), 'protocol_sha256': sha(args.protocol) if args.protocol else None,
                    'views': 'one cycling ID view and both_missing per source', 'policies': POLICIES,
                    'order': 'cyclic policy rotation by source and view, fixed before outcomes',
                    'frozen_unix_ns': time.time_ns(), 'H2_root_and_all_reachable_H1_supported': True,
                    'rejection_score': {'utility': -1., 'joint_correct': False},
                    'null_action_is_rejection_not_successful_stop': True,
                    'online_feedback': 'public sensor caption legality and image/text agreement only',
                    'private_truth_scoring': 'after every native owner is closed; never passed to native',
                    'online_proxy_equals_global_NDU': False}
    write(output / 'registration.json', registration)
    start, cpu = time.perf_counter_ns(), time.process_time_ns()
    if args.mode == 'smoke':
        corpus = load_roles(SHARED / 'abc2-assets/mnist', SHARED / 'abc2-runs/source-recovery-001/source-manifest.json', roles=('train',))
        role, allocation = 'train', None
    else:
        if args.count != 128 or args.protocol is None:
            raise ValueError('The fixed 64-writer/128-pair independent protocol is required')
        frozen = json.loads(args.protocol.read_text())
        if frozen['binary_sha256'] != sha(args.binary) or frozen['package_sha256'] != sha(args.package):
            raise ValueError('Native binary or model package differs from prospective freeze')
        corpus = load_registered(ASSETS / 'qmnist', ALLOCATION, args.protocol, study='native_h2_execution')
        allocation = corpus.manifest
        role = 'next_native_h2_execution'
    model = Snapshot.load(MODEL, expected_file_sha256=sha(MODEL))._model
    encoder = PublicEncoder(Path(package['predictor_path']))
    # No private audit model is loaded while either owner is live.
    owners, descriptors, processes, statuses = {}, {}, {}, {}
    for policy in POLICIES:
        area = output / policy; area.mkdir()
        spec = descriptor(args.package, policy, 20 * args.count + 200, registration)
        descriptors[policy] = area / 'descriptor.json'; write(descriptors[policy], spec)
        owners[policy] = Native(args.binary, descriptors[policy], area / 'state', 'new', area / 'process-0.stderr')
        processes[policy] = [owners[policy].process.pid]; statuses[policy] = []
    rows, checks, recoveries = [], [], []
    pending_probe = {p: True for p in POLICIES}
    continuation_probe = {p: True for p in POLICIES}
    max_moment_error, max_teacher_error, max_probability_error = 0., 0., 0.
    with (output / 'public-rollouts.jsonl').open('x') as journal:
        for case in range(args.count):
            for view_index, view in enumerate((ID_VIEWS[case % 5], 'both_missing')):
                rotation = (case + view_index) % 2
                for policy in POLICIES[rotation:] + POLICIES[:rotation]:
                    began = time.perf_counter_ns()
                    work_ns, probe_ns = 0, 0
                    area, native = output / policy, owners[policy]
                    seed = 83360017 + case * 1009 + view_index * 1000000
                    batch = make_batch(corpus, role, 1, seed, view=view, offset=case)
                    episode = f'h2.case.{case}.{view_index}.{policy}'
                    writer = allocation['roles']['execution']['pair_writer_ids'][case] if allocation else case
                    steps, parent_outcome = [], None
                    with torch.inference_mode():
                        current = initialize(model, batch.observation, generator=torch.Generator().manual_seed(seed + 1000000))
                        work_ns += time.perf_counter_ns() - began
                        for step in range(2):
                            feature_begin = time.perf_counter_ns()
                            frame = public_frame(current)
                            inputs, teacher_moments, feature_work, hidden = encoder.encode(model, frame, batch.observation)
                            feature_ns = time.perf_counter_ns() - feature_begin; work_ns += feature_ns
                            spec = json.loads(descriptors[policy].read_text())
                            request = {'kind': 'decide', 'request_id': episode + f'.step{step}', 'episode_id': episode,
                                       'parent_outcome_digest': parent_outcome, 'generation': 1,
                                       'weights_sha256': spec['pins']['weights'], 'objective_digest': sha(descriptors[policy]),
                                       'prefix_digest': public_digest(frame),
                                       'candidates': [{'action': a, 'features': x} for a, x in zip(ACTIONS, inputs)]}
                            if case == 0 and view_index == 0 and step == 0:
                                probe_begin = time.perf_counter_ns()
                                checks += [{'policy': policy, **c} for c in negatives(native, request)]
                                probe_ns += time.perf_counter_ns() - probe_begin
                            if step == 1 and continuation_probe[policy]:
                                probe_begin = time.perf_counter_ns()
                                for name, key, value in [('H1_wrong_parent', 'parent_outcome_digest', '0' * 64),
                                                         ('H1_wrong_public_state', 'prefix_digest', '1' * 64),
                                                         ('H1_wrong_episode', 'episode_id', episode + '.other')]:
                                    changed = copy.deepcopy(request); changed[key] = value
                                    checks.append({'policy': policy, **rejected(native, name, changed)})
                                continuation_probe[policy] = False
                                probe_ns += time.perf_counter_ns() - probe_begin
                            prior = native.success({'kind': 'status'})
                            tick_begin = time.perf_counter_ns()
                            decision = native.success(request); received = time.time_ns()
                            decision_ns = time.perf_counter_ns() - tick_begin; work_ns += decision_ns
                            tag = f'{case:04d}-{view}-step{step}'
                            write(area / ('decision-' + tag + '.json'), {'request': request, 'response': decision, 'received_ns': received})
                            raw = probabilities(predictor, hidden, frame.remaining)
                            for i, (candidate, values) in enumerate(zip(decision['decision']['candidates'], inputs)):
                                if candidate['prior_modulator'] != prior['modulator']:
                                    raise ValueError('Future observation entered a current decision')
                                actual_moments = np.asarray(candidate['ndu_moments'], dtype=np.float64)
                                moment_error = float(np.max(np.abs(actual_moments - projected_moments(export, values))))
                                teacher_error = float(np.max(np.abs(actual_moments - teacher_moments)))
                                raw_error = float(np.max(np.abs(np.asarray(candidate['raw_probabilities'], dtype=np.float64) - raw)))
                                max_moment_error, max_teacher_error = max(max_moment_error, moment_error), max(max_teacher_error, teacher_error)
                                max_probability_error = max(max_probability_error, raw_error)
                                confidence = calibrated(calibration, [raw[i]], [view == 'both_missing'], [frame.remaining], [i])[0]
                                if (moment_error > 1e-10 or teacher_error > 3e-6 or raw_error > 1e-10
                                        or candidate['confidence_ppm'] != round(confidence * 1e6)):
                                    raise ValueError('Native teacher or actual qualified admission function differs')
                            action = decision['decision']['selected_action']
                            eligible = [i for i, candidate in enumerate(decision['decision']['candidates'])
                                        if candidate['admitted'] and not (frame.remaining == 1 and i == 1)]
                            teacher_choice = ACTIONS[min(eligible, key=lambda i: (teacher_moments[i], i))] if eligible else None
                            unmasked = [i for i in range(5) if not (frame.remaining == 1 and i == 1)]
                            unmasked_choice = ACTIONS[min(unmasked, key=lambda i: (teacher_moments[i], i))]
                            record = {'step': step, 'remaining': frame.remaining, 'action': action,
                                      'decision_digest': decision['decision_digest'], 'prefix_digest': public_digest(frame),
                                      'parent_outcome_digest': parent_outcome, 'feature_ns': feature_ns,
                                      'decision_ns': decision_ns, 'feature_work': feature_work,
                                      'decision_received_ns': received, 'prior_modulator': prior['modulator'],
                                      'teacher_on_same_admission_set': teacher_choice,
                                      'unmasked_teacher_choice': unmasked_choice,
                                      'admission_changed_teacher_choice': teacher_choice != unmasked_choice,
                                      'teacher_action_parity': teacher_choice == action if policy == 'ndu' else None,
                                      'selected_confidence_ppm': next((c['confidence_ppm'] for c in decision['decision']['candidates'] if c['action'] == action), None)}
                            if action is None:
                                record['rejected'] = True; steps.append(record); break
                            if pending_probe[policy]:
                                probe_begin = time.perf_counter_ns()
                                changed = copy.deepcopy(request); changed['request_id'] += '.pending'
                                checks.append({'policy': policy, **rejected(native, 'pending_blocks_decision', changed)})
                                before = native.interrupt(); statuses[policy].append(before)
                                native = Native(args.binary, descriptors[policy], area / 'state', 'resume', area / f'process-{len(processes[policy])}.stderr')
                                owners[policy] = native; processes[policy].append(native.process.pid)
                                if before['episodes'] != native.ready['status']['episodes']:
                                    raise ValueError('Pending episode changed on recovery')
                                recoveries.append({'policy': policy, **recovery(before, native.ready['status'], 'abrupt_pending_H2_decision')})
                                probe_ns += time.perf_counter_ns() - probe_begin
                            generation_begin, generated_ns = time.perf_counter_ns(), time.time_ns()
                            action_index = ACTIONS.index(action)
                            current = transition(model, current, action, generator=torch.Generator().manual_seed(
                                seed + 2000000 + (step * 5 + action_index) * 3000000))
                            media = write_bundle(area / 'media' / tag, render_tokens(current.tokens[0]), current.pixels[0])
                            reopened, caption, hashes = read_bundle(media)
                            if not torch.equal(reopened[0], current.pixels[0]) or caption != render_tokens(current.tokens[0]):
                                raise ValueError('Actual selected output failed round trip')
                            observed_public = observe_public(encoder.sensor, reopened, caption)
                            utility = observed_public['public_utility'] * 2 ** 32
                            receipt = {'request_id': request['request_id'], 'episode_id': episode,
                                       'decision_digest': decision['decision_digest'], 'action': action,
                                       'observer_sha256': sha(SENSOR), 'media': media, 'media_sha256': hashes,
                                       'decision_received_ns': received, 'generation_started_ns': generated_ns,
                                       'observed_ns': time.time_ns(), 'utility_q32': math.floor(utility + .5) if utility >= 0 else math.ceil(utility - .5),
                                       'public_observation': observed_public, 'private_truth_utility_supplied': False,
                                       'after_public_digest': public_digest(public_frame(current)),
                                       'after_remaining': current.remaining, 'done': current.done}
                            receipt_path = area / ('outcome-' + tag + '.json'); write(receipt_path, receipt)
                            command = {'kind': 'observe', 'request_id': request['request_id'],
                                       'decision_digest': decision['decision_digest'], 'selected_action': action,
                                       'receipt_path': str(receipt_path), 'receipt_sha256': sha(receipt_path)}
                            work_ns += time.perf_counter_ns() - generation_begin
                            if pending_probe[policy]:
                                probe_begin = time.perf_counter_ns()
                                checks += [{'policy': policy, **c} for c in outcome_negatives(native, command, receipt, area)]
                                probe_ns += time.perf_counter_ns() - probe_begin
                            observe_begin = time.perf_counter_ns(); outcome = native.success(command)
                            work_ns += time.perf_counter_ns() - observe_begin
                            if pending_probe[policy]:
                                probe_begin = time.perf_counter_ns()
                                checks.append({'policy': policy, **rejected(native, 'duplicate_outcome', command)})
                                pending_probe[policy] = False
                                probe_ns += time.perf_counter_ns() - probe_begin
                            parent_outcome = outcome['outcome_digest']
                            record.update(public_observation=observed_public, media=media, media_sha256=hashes,
                                          outcome_sha256=sha(receipt_path), outcome_digest=parent_outcome,
                                          generation_started_ns=generated_ns, next_modulator=outcome['status']['modulator'],
                                          after_public_digest=receipt['after_public_digest'],
                                          continuation_actions=int(action != 'stop'),
                                          actual_emission_calls=current.ledger[-1]['work'].get('emission_calls', 0))
                            steps.append(record)
                            if case == 0 and view_index == 0:
                                probe_begin = time.perf_counter_ns()
                                checks.append({'policy': policy, **rejected(native, 'duplicate_decision', request)})
                                probe_ns += time.perf_counter_ns() - probe_begin
                            if current.done: break
                            if continuation_probe[policy]:
                                probe_begin = time.perf_counter_ns()
                                before = native.close(); statuses[policy].append(before)
                                native = Native(args.binary, descriptors[policy], area / 'state', 'resume', area / f'process-{len(processes[policy])}.stderr')
                                owners[policy] = native; processes[policy].append(native.process.pid)
                                if before['episodes'] != native.ready['status']['episodes']:
                                    raise ValueError('Committed H2 continuation changed on recovery')
                                recoveries.append({'policy': policy, **recovery(before, native.ready['status'], 'graceful_observed_H2_before_H1')})
                                probe_ns += time.perf_counter_ns() - probe_begin
                    total_ns = time.perf_counter_ns() - began
                    row = {'pair': case, 'writer': writer, 'source_ids': batch.source_ids[0], 'view': view,
                           'policy': policy, 'seed': seed, 'steps': steps, 'request_ns': total_ns - probe_ns,
                           'scoped_execution_stage_ns': work_ns, 'diagnostic_probe_and_fault_ns': probe_ns,
                           'instrumented_wall_ns': total_ns,
                           'continuation_actions': sum(s.get('continuation_actions', 0) for s in steps),
                           'cost_excludes': 'exactly timed deliberate probes/recovery faults, final row serialization, and later private audit; present in complete child cost'}
                    rows.append(row); journal.write(json.dumps(row, sort_keys=True) + '\n'); journal.flush()
            if (case + 1) % 8 == 0:
                print(json.dumps({'pairs': case + 1, 'policy_episodes': len(rows)}), flush=True)
    for policy in POLICIES: statuses[policy].append(owners[policy].close())
    all_owners_closed_ns = time.time_ns()
    audit_begin = time.perf_counter_ns()
    observer, _ = load_reward(OBSERVER, sha(OBSERVER))
    with (output / 'rollouts.jsonl').open('x') as journal:
        for row in rows:
            batch = make_batch(corpus, role, 1, row['seed'], view=row['view'], offset=row['pair'])
            for step in row['steps']:
                if step['action'] is None: step['scores'] = {'utility': -1., 'joint_fact_correct': False}; continue
                pixels, caption, hashes = read_bundle(step['media'])
                if hashes != step['media_sha256']: raise ValueError('Actual output changed before private audit')
                step['scores'] = observe_tensors(observer, pixels, [caption], batch.target.pixels, batch.target.labels)[0]
                step['private_audited_ns'] = time.time_ns()
            row['scores'] = row['steps'][-1]['scores']
            row['private_truth_scoring_started_after_all_owners_closed'] = all_owners_closed_ns
            journal.write(json.dumps(row, sort_keys=True) + '\n')
    write(output / 'results.json', {'schema': 'hepta.next.native-h2-owner-results.v1', 'registration': registration,
          'source_pairs': args.count, 'actual_policy_episodes': len(rows),
          'actual_owner_decisions': sum(len(r['steps']) for r in rows),
          'actual_emitted_outputs': sum(s['action'] is not None for r in rows for s in r['steps']),
          'actual_continuation_actions': sum(r['continuation_actions'] for r in rows),
          'max_native_numpy_moment_error': max_moment_error, 'max_native_original_teacher_error': max_teacher_error,
          'max_native_correctness_raw_error': max_probability_error,
          'negative_cases': checks, 'recoveries': recoveries, 'process_ids': processes, 'process_status': statuses,
          'all_owners_closed_before_private_audit_ns': all_owners_closed_ns,
          'private_audit_wall_ns': time.perf_counter_ns() - audit_begin,
          'wall_ns': time.perf_counter_ns() - start, 'cpu_ns': time.process_time_ns() - cpu,
          'rollouts_sha256': sha(output / 'rollouts.jsonl'), 'new_sources_used_to_train': False,
          'online_feedback_uses_only_existing_public_sensor': True,
          'whole_agentd_daemon': False, 'production_authority': False})


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    for name in ('binary', 'package', 'output'): p.add_argument('--' + name, type=Path, required=True)
    p.add_argument('--mode', choices=('smoke', 'confirm'), default='smoke')
    p.add_argument('--count', type=int, default=16); p.add_argument('--protocol', type=Path)
    run(p.parse_args())
