"""Execute native decisions before real output generation and later observation."""

import argparse
import copy
import json
import math
import os
from pathlib import Path
import subprocess
import time

import numpy as np
import torch

from ...abc_recovery.runtime import initialize, transition, public_frame, public_digest
from ...abc_followup.native.forecast import ACTIONS, Q, public_input, predict, groups, quantize
from ...v6.data import render_tokens
from ...v6.observer import observe_tensors, read_bundle, write_bundle
from ...v7.data import make_batch
from ...v7.evaluation import load_reward
from ...v7.snapshot import Snapshot
from ...v7.sources import load_roles
from ..sources import load_registered
from .build import ROOT, sha


AREA = Path(__file__).parent
PRIOR = ROOT / 'hepta-ndu-recovery/experiments/multimodal_output_portfolio/abc_followup/native/PROTOCOL.json'
FROZEN = ROOT / 'abc4-native-runs/future-packet-001/packet.json'
VIEWS = ('clean', 'noise', 'occlusion', 'missing_trusted', 'conflict_untrusted', 'both_missing')
RECOVERY_KEYS = ('native_sequence', 'anchor', 'history_digest', 'objective_digest',
                 'modulator', 'pending', 'requests', 'outcomes')


def write(path, value):
    raw = json.dumps(value, indent=2, sort_keys=True, allow_nan=False).encode() + b'\n'
    with Path(path).open('xb') as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())


class Native:
    def __init__(self, binary, descriptor, state, mode, log):
        self.stderr = Path(log).open('xb')
        self.process = subprocess.Popen([str(binary), str(descriptor), sha(descriptor), str(state), mode],
                                        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=self.stderr,
                                        text=True, bufsize=1)
        line = self.process.stdout.readline()
        if not line:
            self.process.wait()
            self.stderr.close()
            raise RuntimeError(Path(log).read_text())
        self.ready = json.loads(line)

    def call(self, value):
        self.process.stdin.write(json.dumps(value, allow_nan=False) + '\n')
        self.process.stdin.flush()
        line = self.process.stdout.readline()
        if not line:
            raise RuntimeError('Native child stopped before its response')
        return json.loads(line)

    def success(self, value):
        result = self.call(value)
        if result['ok'] is not True:
            raise RuntimeError(result)
        return result['value']

    def close(self):
        status = self.success({'kind': 'shutdown'})
        self.process.stdin.close()
        if self.process.wait(timeout=20):
            raise RuntimeError('Native child failed during shutdown')
        self.stderr.close()
        return status

    def interrupt(self):
        status = self.success({'kind': 'status'})
        self.process.kill()
        if self.process.wait(timeout=20) != -9:
            raise RuntimeError('Expected explicit pending-state interruption')
        self.stderr.close()
        return status


def rejected(native, name, value):
    before = native.success({'kind': 'status'})
    result = native.call(value)
    after = native.success({'kind': 'status'})
    if result['ok'] or before != after:
        raise AssertionError(f'Rejected input changed the owner: {name}')
    return {'case': name, 'result': result, 'owner_state_unchanged': True}


def negative_inputs(native, request):
    variants = []
    for name, key, value in [('generation', 'generation', 2), ('weights', 'weights_sha256', '0' * 64),
                             ('objective', 'objective_digest', '0' * 64), ('future_field', 'target', [9, 9])]:
        changed = copy.deepcopy(request)
        changed[key] = value
        variants.append((name, changed))
    for name in ('candidate_set', 'prefix_mismatch', 'action_bits', 'feature_width'):
        changed = copy.deepcopy(request)
        if name == 'candidate_set':
            changed['candidates'].pop()
        elif name == 'prefix_mismatch':
            changed['candidates'][1]['features'][0] += 1
        elif name == 'action_bits':
            changed['candidates'][0]['features'][476] = 0
        else:
            changed['candidates'][0]['features'].append(0)
        variants.append((name, changed))
    return [rejected(native, name, value) for name, value in variants]


def negative_outcomes(native, command, observed, output):
    cases = []
    for name, key, value in [('outcome_binding', 'decision_digest', '0' * 64),
                             ('outcome_hash', 'receipt_sha256', '0' * 64)]:
        changed = copy.deepcopy(command)
        changed[key] = value
        cases.append(rejected(native, name, changed))
    for name in ('observer', 'outcome_action', 'causal_time', 'observed_time', 'media_hash', 'utility_bound'):
        value = copy.deepcopy(observed)
        if name == 'observer':
            value['observer_sha256'] = '0' * 64
        elif name == 'outcome_action':
            value['action'] = 'refine_image'
        elif name == 'causal_time':
            value['generation_started_ns'] = value['decision_received_ns']
        elif name == 'observed_time':
            value['observed_ns'] = value['generation_started_ns']
        elif name == 'media_hash':
            value['media_sha256']['image'] = '0' * 64
        else:
            value['utility_q32'] = 2 ** 32 + 1
        path = output / f'negative-{name}.json'
        write(path, value)
        changed = copy.deepcopy(command)
        changed.update(receipt_path=str(path), receipt_sha256=sha(path))
        cases.append(rejected(native, name, changed))
    return cases


def recovery(before, after, kind):
    if any(before[k] != after[k] for k in RECOVERY_KEYS):
        raise AssertionError('Restart did not restore exact owner/NDU/controller state')
    return {'kind': kind, 'before': {k: before[k] for k in RECOVERY_KEYS},
            'after': {k: after[k] for k in RECOVERY_KEYS}}


def run(args):
    torch.set_num_threads(1)
    output = args.output
    output.mkdir(parents=True, exist_ok=False)
    old = json.loads(PRIOR.read_text())
    packet = json.loads(FROZEN.read_text())
    paths = {k: Path(v) for k, v in old['paths'].items()}
    for name, digest in old['input_sha256'].items():
        if sha(paths[name]) != digest:
            raise ValueError(f'Frozen upstream input changed: {name}')
    if args.mode == 'fresh':
        if args.protocol is None or args.allocation is None or args.count != 64:
            raise ValueError('Fresh native study requires frozen protocol and exact 64-pair allocation')
        frozen = json.loads(args.protocol.read_text())
        if (frozen['binary_sha256'] != sha(args.binary) or frozen['pair_count'] != args.count
                or frozen['views'] != list(VIEWS) or frozen['seed_base'] != 361117):
            raise ValueError('Fresh execution differs from the frozen study')
    role = 'train' if args.mode == 'smoke' else 'closure_native'
    registration = {'purpose': 'causal-owner-mechanism-development', 'source_role': 'train',
                    'pair_start': 0, 'pair_count': args.count, 'views': VIEWS,
                    'new_independent_source_pairs': 0, 'code_sha256': {p.name: sha(p) for p in AREA.glob('*') if p.is_file()},
                    'binary_sha256': sha(args.binary), 'frozen_ns': time.time_ns(),
                    'selection': 'maximum frozen correctness probability among actual admitted actions; refine_text breaks ties',
                    'online_carrier': 'one correctness reference plus 32 predicted coordinates; no observed future supplied',
                    'production_authority': False, 'new_policy_calibration_claim': False}
    registration.update(purpose='causal-owner-mechanism-' + args.mode, source_role=role,
                        new_independent_source_pairs=0 if args.mode == 'smoke' else args.count,
                        protocol_sha256=None if args.protocol is None else sha(args.protocol),
                        source_allocation_sha256=None if args.allocation is None else sha(args.allocation))
    descriptor = {'schema': 'hepta.closure.native-online.v1', 'pins': packet['pins'],
                  'weights_path': packet['weights_path'], 'calibration_path': packet['calibration_path'],
                  'verification_path': packet['verification_path'], 'observer_path': str(paths['observer']),
                  'observer_sha256': old['input_sha256']['observer'], 'max_native_ticks': 2 * (args.count + 8),
                  'registration': registration}
    descriptor_path = output / 'descriptor.json'
    write(descriptor_path, descriptor)
    # Registration is durable before opening even these already-used source pixels.
    began, cpu = time.monotonic_ns(), time.process_time_ns()
    corpus = (load_roles(paths['cache'], paths['manifest'], roles=('train',)) if args.mode == 'smoke'
              else load_registered(paths['cache'], paths['manifest'], args.allocation, 'native', args.protocol))
    generator = Snapshot.load(paths['model'], expected_file_sha256=old['input_sha256']['model'])._model
    observer, _ = load_reward(paths['observer'], old['input_sha256']['observer'])
    weights = json.loads(Path(packet['weights_path']).read_text())
    calibration = json.loads(Path(packet['calibration_path']).read_text())
    native = Native(args.binary, descriptor_path, output / 'state', 'new', output / 'native-0.stderr')
    process_ids = [native.process.pid]
    rows, negatives, recoveries, process_status = [], [], [], []
    tested_outcome = False
    journal = (output / 'rollouts.jsonl').open('x')
    for index in range(args.count):
        view = VIEWS[index % len(VIEWS)]
        seed = 361117 + index
        batch = make_batch(corpus, role, 1, seed, view=view, offset=index)
        with torch.inference_mode():
            rng = torch.Generator().manual_seed(seed + 1000000)
            prefix = initialize(generator, batch.observation, generator=rng)
            prefix = transition(generator, prefix, 'refine_image', generator=rng)
            frame = public_frame(prefix)
            inputs = [public_input(generator, frame, batch.observation, a)[0].tolist() for a in ACTIONS]
            request = {'kind': 'decide', 'request_id': f'closure.case.{index}', 'generation': 1,
                       'weights_sha256': packet['pins']['weights'], 'objective_digest': sha(descriptor_path),
                       'prefix_digest': public_digest(frame),
                       'candidates': [{'action': a, 'features': x} for a, x in zip(ACTIONS, inputs)]}
            if index == 0:
                negatives += negative_inputs(native, request)
            previous = native.success({'kind': 'status'})
            decision = native.success(request)
            received = time.time_ns()
            write(output / f'decision-{index:04d}.json', {'request': request, 'response': decision, 'received_ns': received})
            for candidate, x in zip(decision['decision']['candidates'], inputs):
                x = np.asarray([x], dtype=np.float64) / Q
                forecast, raw = predict(weights, x)
                p = calibration['probabilities'][int(groups(x, raw, calibration['cuts'])[0])]
                expected = quantize(np.column_stack(([p], forecast)))[0].tolist()
                if [candidate['probability_q24'], *candidate['forecast_q24']] != expected:
                    raise AssertionError('Original Python forecast/calibration differs from actual Rust execution')
                if candidate['prior_modulator'] != previous['modulator']:
                    raise AssertionError('Decision used an uncommitted NDU future')
            action = decision['decision']['selected_action']
            row = {'index': index, 'view': view, 'source_ids': batch.source_ids[0],
                   'decision_digest': decision['decision_digest'], 'action': action,
                   'decision_received_ns': received, 'prior_modulator': previous['modulator']}
            if action is not None:
                if not tested_outcome:
                    pending_request = copy.deepcopy(request)
                    pending_request['request_id'] += '.pending-conflict'
                    negatives.append(rejected(native, 'pending_blocks_decision', pending_request))
                    negatives.append(rejected(native, 'pending_blocks_shutdown', {'kind': 'shutdown'}))
                    before = native.interrupt(); process_status.append(before)
                    native = Native(args.binary, descriptor_path, output / 'state', 'resume',
                                    output / f'native-{len(process_ids)}.stderr')
                    process_ids.append(native.process.pid)
                    recoveries.append(recovery(before, native.ready['status'], 'abrupt_pending_decision'))
                generation_started = time.time_ns()
                future = transition(generator, prefix, action, generator=torch.Generator().manual_seed(seed + 9000000))
                media = write_bundle(output / 'media' / f'{index:04d}', render_tokens(future.tokens[0]), future.pixels[0])
                reopened, caption, hashes = read_bundle(media)
                if not torch.equal(reopened[0], future.pixels[0]) or caption != render_tokens(future.tokens[0]):
                    raise AssertionError('Persisted output differs from actual generation')
                score = observe_tensors(observer, reopened, [caption], batch.target.pixels, batch.target.labels)[0]
                value = score['utility'] * 2 ** 32
                observed = {'request_id': request['request_id'], 'decision_digest': decision['decision_digest'],
                            'action': action, 'observer_sha256': old['input_sha256']['observer'], 'media': media,
                            'media_sha256': hashes, 'decision_received_ns': received,
                            'generation_started_ns': generation_started, 'observed_ns': time.time_ns(),
                            'utility_q32': math.floor(value + .5) if value >= 0 else math.ceil(value - .5),
                            'scores': score, 'source_ids': batch.source_ids[0]}
                receipt = output / f'outcome-{index:04d}.json'
                write(receipt, observed)
                outcome_command = {'kind': 'observe', 'request_id': request['request_id'],
                                   'decision_digest': decision['decision_digest'], 'selected_action': action,
                                   'receipt_path': str(receipt), 'receipt_sha256': sha(receipt)}
                if not tested_outcome:
                    negatives += negative_outcomes(native, outcome_command, observed, output)
                outcome = native.success(outcome_command)
                if not tested_outcome:
                    negatives.append(rejected(native, 'duplicate_outcome', outcome_command))
                    tested_outcome = True
                row.update(scores=score, media_sha256=hashes, generation_started_ns=generation_started,
                           observed_ns=observed['observed_ns'], outcome_sha256=sha(receipt),
                           next_modulator=outcome['status']['modulator'])
            else:
                row['generation_calls'] = 0
            duplicate = native.call(request)
            if duplicate['ok']:
                raise AssertionError('Repeated native decision accepted')
            if index == 0:
                negatives.append({'case': 'duplicate_decision', 'result': duplicate})
            rows.append(row)
            journal.write(json.dumps(row, sort_keys=True) + '\n'); journal.flush(); os.fsync(journal.fileno())
            if index + 1 == args.count // 2:
                before = native.close(); process_status.append(before)
                native = Native(args.binary, descriptor_path, output / 'state', 'resume',
                                output / f'native-{len(process_ids)}.stderr')
                process_ids.append(native.process.pid)
                recoveries.append(recovery(before, native.ready['status'], 'graceful_committed_outcomes'))
        if (index + 1) % 8 == 0:
            print(json.dumps({'completed': index + 1, 'emitted': sum(r['action'] is not None for r in rows)}), flush=True)
    journal.close()
    process_status.append(native.close())
    summary = {'schema': 'hepta.closure.native-online-results.v1', 'registration': registration,
               'descriptor_sha256': sha(descriptor_path), 'source_pairs': len(rows),
               'actual_output_generations': sum(r['action'] is not None for r in rows),
               'abstained_without_generation': sum(r['action'] is None for r in rows),
               'correctness_action_scope': list(ACTIONS), 'negative_cases': negatives,
               'recoveries': recoveries, 'process_ids': process_ids, 'process_status': process_status,
               'wall_ns': time.monotonic_ns() - began, 'python_cpu_ns': time.process_time_ns() - cpu,
               'raw_rollouts_sha256': sha(output / 'rollouts.jsonl'), 'raw_controller_log_sha256': sha(output / 'state/control.jsonl'),
               'all_decisions_precede_generation': all(r.get('generation_started_ns', r['decision_received_ns'] + 1) > r['decision_received_ns'] for r in rows),
               'production_authority': False, 'complete_agentd_daemon': False,
               'new_calibration_or_independent_policy_efficacy_claim': False}
    write(output / 'results.json', summary)
    print(json.dumps({k: summary[k] for k in ('source_pairs', 'actual_output_generations', 'abstained_without_generation', 'wall_ns')}))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--binary', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--count', type=int, default=12)
    parser.add_argument('--mode', choices=('smoke', 'fresh'), default='smoke')
    parser.add_argument('--protocol', type=Path)
    parser.add_argument('--allocation', type=Path)
    run(parser.parse_args())
