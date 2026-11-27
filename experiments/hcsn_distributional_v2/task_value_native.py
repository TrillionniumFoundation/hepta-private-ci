"""Actual native READ/FIRE/RESET loops, with a finite queue and deadline.

The task clock counts observation and refractory ticks, not wall-clock seconds.
Actual model/controller/native CPU is measured separately.  A stopped task's
tensor iterator is never advanced; a fresh task gets a new native owner and a
reset neural state.  The v1 native binary and authority are unchanged.
"""

import math
from pathlib import Path
import time

import numpy as np
import torch

from ..hcsn_free_boundary_v1.native_bridge import MANIFEST, NativeSession, Signals, UPSTREAM
from .task_value_common import (read_json, write_json, sha, save_state,
                                load_state, state_identity)
from .task_value_heads import confidence_state


OBJECTIVE = {'name': 'finite-queue-regenerative-paid-classification-v2',
             'correct_reward': 1., 'read_cost': 'every actual READ, including the first',
             'deadline_ticks': 48, 'tasks': 3, 'refractory_ticks': 2,
             'fire': 'actual classification score, terminal owner STOP, possible next independent task',
             'quiet': 'two model-clock ticks with zero model, observation or owner ticks',
             'discount_per_tick': 1.}


class TaskNativeSession(NativeSession):
    def __init__(self, root, *, binary, family, model_digest, case, seed, resume=False, objective=None):
        self.root, self.case, self.seed = Path(root), case, seed
        self.policy = family
        kernel = {'width': 5, 'top_k': 1, 'temporal_decay_q24': 0,
                  'activity_decay_q24': 0, 'target_activity_q24': 0,
                  'threshold_rate_q24': 0, 'threshold_min_q24': 0,
                  'threshold_max_q24': 0, 'eligibility_decay_q24': 0}
        self.profile = UPSTREAM.make_profile(
            ['task_value_or_ordinary_continue_gap'],
            [[1, 0, 0, 0], [-1, 0, 0, 0], [0] * 4, [0] * 4, [0] * 4],
            [0, 0, -4, -4, -4], [[1, -1, 0, 0, 0], [0] * 5, [0] * 5], [0, -8, 0],
            source_model_digest=model_digest, objective_digest=UPSTREAM.digest(OBJECTIVE if objective is None else objective),
            arm_id='regenerative-task-' + family, kernel=kernel, maximum_ticks=512)
        path, self.profile_digest = UPSTREAM.save_profile(self.root / 'profiles', self.profile)
        self.bridge = UPSTREAM.NativeBridge(binary, self.root,
                                            expected_binary_sha256=MANIFEST['binary_sha256'])
        identity = self.bridge.identity
        if (identity['source_commit'] != MANIFEST['native_base_commit']
                or identity['source_manifest_digest'] != MANIFEST['source_manifest_sha256']
                or identity['owner_authority'] != 'DENY_ALL'):
            self.bridge.close()
            raise ValueError('Native source identity or authority changed')
        self.bridge.load_profile(path, self.profile_digest)
        self.open_receipt = self.bridge.open(case, seed, self.profile_digest, resume=resume)
        self.terminal = bool(self.open_receipt['status']['terminal'])
        self.events = []


def run_stream(backbone, policy, task_x, task_dt, labels, source_ids, *, price,
               stream_number, directory, binary, identity, resume=False,
               checkpoint_active=None, checkpoint_quiet=False):
    """Consume exactly the observations authorized by actual owner decisions.

    A suspended run closes its native child and stores the full controller and
    numeric neural state.  Calling with resume=True can happen in a fresh Python
    process.  This generic function accepts v1 or v2 `.step`-compatible models.
    """
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    if (directory / 'RESULT.json').exists():
        raise FileExistsError('Refusing to replace an executed stream')
    if tuple(task_x.shape[:2]) != (3, 32) or task_dt.shape != (3, 32):
        raise ValueError('Registered stream shape must contain three 32-prefix tasks')
    context_identity = {'input': identity, 'source_ids': list(source_ids), 'price': price,
                        'family': policy.family, 'stream_number': stream_number,
                        'objective': OBJECTIVE}
    digest = UPSTREAM.digest(context_identity)
    native = None
    if resume:
        record = read_json(directory / 'SUSPENDED.json')
        if record['context_identity'] != context_identity:
            raise ValueError('Resume inputs or policy differ from the checkpoint')
        if sha(directory / 'STATE.npz') != record['state_sha256']:
            raise ValueError('Neural checkpoint bytes changed')
        state = load_state(directory / 'STATE.npz')
        if state_identity(state) != record['state_identity']:
            raise ValueError('Neural checkpoint state identity changed on decoding')
        driver = record['driver']
        driver['resumptions'].append({'fresh_process_pid': __import__('os').getpid(),
                                     'checkpoint_writer_pid': record['writer_pid'],
                                     'different_python_process': __import__('os').getpid() != record['writer_pid'],
                                     'mode': driver['mode'], 'quiet_ticks_remaining': driver['quiet_remaining'],
                                     'task_index': driver['task_index'], 'prefix': driver['prefix'],
                                     'deadline_ticks_remaining': driver['ticks']})
    else:
        if (directory / 'SUSPENDED.json').exists():
            raise FileExistsError('Existing suspended stream requires explicit resume')
        state = None
        driver = {'task_index': 0, 'prefix': 0, 'ticks': 48, 'quiet_remaining': 0,
                  'mode': 'active', 'events': [], 'task_results': [], 'native_costs': [],
                  'model_cpu_seconds': 0., 'policy_cpu_seconds': 0., 'actual_reads': 0,
                  'quiet_ticks': 0, 'resumptions': [], 'float_q24_disagreements': 0,
                  'zero_q24_ties': 0}

    def suspend():
        nonlocal native
        if native is not None:
            driver['native_costs'].append(native.close())
            native = None
        state_sha = save_state(directory / 'STATE.npz', state)
        write_json(directory / 'SUSPENDED.json', {
            'schema': 'hcsn-v2-task-driver-checkpoint.v1', 'context_identity': context_identity,
            'driver': driver, 'state_sha256': state_sha, 'state_identity': state_identity(state),
            'writer_pid': __import__('os').getpid()})
        return {'status': 'suspended', 'mode': driver['mode'], 'prefix': driver['prefix'],
                'task_index': driver['task_index'], 'quiet_remaining': driver['quiet_remaining']}

    try:
        while driver['task_index'] < 3:
            if driver['mode'] == 'quiet':
                if driver['quiet_remaining'] <= 0:
                    driver['mode'] = 'active'
                    continue
                driver['quiet_remaining'] -= 1
                driver['ticks'] -= 1
                driver['quiet_ticks'] += 1
                driver['events'].append({'kind': 'refractory_tick', 'clock': 48 - driver['ticks'],
                                         'quiet_remaining': driver['quiet_remaining'],
                                         'model_steps': 0, 'owner_ticks': 0})
                if checkpoint_quiet and not resume and driver['quiet_remaining'] > 0:
                    return suspend()
                continue
            task, prefix, ticks = (driver[key] for key in ('task_index', 'prefix', 'ticks'))
            if ticks <= 0:
                break
            if native is None:
                native = TaskNativeSession(directory / ('owner_task' + str(task)), binary=binary,
                    family=policy.family, model_digest=digest,
                    case='stream' + str(stream_number) + '-task' + str(task),
                    seed=stream_number * 3 + task, resume=(prefix > 0))
                if native.terminal:
                    raise ValueError('An active task cannot resume a terminal owner')
            clock = time.process_time()
            with torch.no_grad():
                logits, state, _ = backbone.step(task_x[task:task + 1, prefix],
                                                 task_dt[task:task + 1, prefix], state)
                if not torch.isfinite(logits).all():
                    raise FloatingPointError('Nonfinite live classifier output')
                confidence = float(logits.softmax(-1).amax(-1).item())
                prediction = int(logits.argmax(-1).item())
            driver['model_cpu_seconds'] += time.process_time() - clock
            driver['prefix'] += 1
            driver['ticks'] -= 1
            driver['actual_reads'] += 1
            prefix, ticks = driver['prefix'], driver['ticks']
            clock = time.process_time()
            z = int(confidence_state(np.asarray(confidence), np.asarray(prefix), policy.edges))
            score = float(policy.score(prefix, z, ticks, 3 - task, price))
            driver['policy_cpu_seconds'] += time.process_time() - clock
            bounded = math.tanh(score)
            quantized = UPSTREAM.quantize(bounded)
            expected = 'keep' if quantized > 0 else 'stop'
            float_expected = 'keep' if score > 0 else 'stop'
            if float_expected != expected:
                if quantized != 0 or abs(bounded) > .5 / (1 << 24) + 1e-12:
                    raise AssertionError('Unexplained float/Q24 decision mismatch')
                driver['float_q24_disagreements'] += 1
            driver['zero_q24_ties'] += int(quantized == 0)
            table = policy.solutions[str(price)]
            qfire = float(table.fire[3 - task, ticks, prefix, z])
            qread = float(table.read[3 - task, ticks, prefix, z])
            context = {'source_id': source_ids[task], 'task_index': task, 'prefix': prefix,
                       'deadline_ticks_remaining': ticks, 'tasks_remaining': 3 - task,
                       'price': price, 'confidence': confidence, 'confidence_bin': z,
                       'identity': identity}
            row = native.tick(Signals(bounded, 0., 0., 0.), context=context)
            if row['native']['effective_action'] != expected:
                raise AssertionError('Actual native action differs from Q24 controller decision')
            driver['events'].append({'kind': 'read_and_decide', 'task_index': task,
                'prefix': prefix, 'clock': 48 - ticks, 'prediction': prediction,
                'confidence': confidence, 'confidence_bin': z, 'score': score,
                'score_q24': quantized, 'action': expected,
                'legal_forced_fire': ticks == 0 or prefix == 32,
                'teacher_fire_value': qfire, 'teacher_read_value': qread if math.isfinite(qread) else None,
                'teacher_future_after_reset': float(table.future_after_reset[3 - task, ticks]),
                'native': row['native']})
            if expected == 'keep':
                if not resume and checkpoint_active == (task, prefix):
                    return suspend()
                continue
            terminal = native.verify_terminal()
            driver['native_costs'].append(native.close())
            native = None
            correct = int(prediction == int(labels[task]))
            driver['task_results'].append({'task_index': task, 'source_id': source_ids[task],
                'prediction': prediction, 'label': int(labels[task]), 'correct': correct,
                'actual_reads': prefix, 'fire_clock': 48 - ticks, 'net_reward': correct - price * prefix,
                'teacher_future_after_reset': float(table.future_after_reset[3 - task, ticks]),
                'terminal_probe': terminal})
            if task == 2 or ticks <= 2:
                break
            driver['task_index'] += 1
            driver['prefix'] = 0
            driver['quiet_remaining'] = 2
            driver['mode'] = 'quiet'
            state = None
    finally:
        if native is not None:
            driver['native_costs'].append(native.close())
    costs = driver['native_costs']
    if any(cost['exit_code'] != 0 for cost in costs):
        raise AssertionError('Native child failed')
    if sum(cost['counters']['owner_ticks'] for cost in costs) != driver['actual_reads']:
        raise AssertionError('Paid read count differs from actual owner ticks')
    if sum(row['actual_reads'] for row in driver['task_results']) != driver['actual_reads']:
        raise AssertionError('Some executed reads escaped actual task reward accounting')
    correct = sum(row['correct'] for row in driver['task_results'])
    result = {'schema': 'hcsn-v2-regenerative-native-stream.v1', 'status': 'completed',
              'context_identity': context_identity, **driver,
              'correct': correct, 'utility': correct - price * driver['actual_reads'],
              'later_task_correct': sum(row['correct'] for row in driver['task_results'][1:]),
              'later_task_net_reward': sum(row['net_reward'] for row in driver['task_results'][1:]),
              'native_child_cpu_seconds': sum(cost['child_cpu_seconds'] for cost in costs),
              'neural_final_state_identity': state_identity(state),
              'cpu_scope': 'model/policy CPU nested in evaluator; native child CPU separately measured and nested in complete wait4 evaluator cost'}
    write_json(directory / 'RESULT.json', result)
    return result


def comparable_trajectory(result):
    """Cost/OS process identities can differ on replay; semantic evidence cannot."""
    keys = ('kind', 'task_index', 'prefix', 'clock', 'prediction', 'confidence',
            'confidence_bin', 'score', 'score_q24', 'action', 'legal_forced_fire',
            'teacher_fire_value', 'teacher_read_value', 'teacher_future_after_reset',
            'quiet_remaining', 'model_steps', 'owner_ticks')
    native_keys = ('checkpoint_before', 'checkpoint_after', 'activation_q24',
                   'readout', 'effective_action')
    events = []
    for event in result['events']:
        row = {key: event[key] for key in keys if key in event}
        if 'native' in event:
            row['native'] = {key: event['native'][key] for key in native_keys}
        events.append(row)
    return {'events': events, 'actual_reads': result['actual_reads'],
            'correct': result['correct'], 'utility': result['utility'],
            'quiet_ticks': result['quiet_ticks'],
            'final_state_identity': result['neural_final_state_identity']}
