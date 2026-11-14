"""Offline event-boundary checkpoints for a real CTMC policy and resource ledger.

No registered Hepta schema is extended. SHA bindings detect mismatched artifacts
and alterations relative to an externally retained digest; they authenticate no
owner. A trained parameter artifact and an execution checkpoint are distinct.
"""
from dataclasses import asdict
import hashlib
import json
import math
from pathlib import Path
import struct
import sys

import numpy as np
import torch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from rrsnn_experiments.resource_env import (
    ACTION_DIGITS, EPS, Scenario, exogenous, legal_actions, next_deadlines,
    state_features, transition,
)
from rrsnn_v2.audit.sampled_policy import SampledDensityRollout
from rrsnn_v2.policy import Policy

SCHEMA = 'rrsnn.joint-ctmc-resource-checkpoint.v1'
DOMAIN = b'rrsnn.joint-ctmc-resource-checkpoint.v1\0'
SOURCES = [
    'rrsnn_v2/hepta/joint_checkpoint.py', 'rrsnn_v2/audit/sampled_policy.py',
    'rrsnn_v2/audit/exact_rollout.py', 'rrsnn_v2/density_model.py',
    'rrsnn_v2/policy.py', 'rrsnn_experiments/resource_env.py',
    'rrsnn_experiments/runtime/event_runtime.py',
]


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()


def weights_sha(model):
    hasher = hashlib.sha256(b'rrsnn.model.tensor-bytes.v1\0')
    for name, value in sorted(model.state_dict().items()):
        tensor = value.detach().cpu().contiguous()
        header = canonical({'name': name, 'dtype': str(tensor.dtype), 'shape': list(tensor.shape)})
        raw = tensor.numpy().tobytes()
        hasher.update(struct.pack('>Q', len(header)) + header)
        hasher.update(struct.pack('>Q', len(raw)) + raw)
    return hasher.hexdigest()


def operator_profile(model):
    encoder = model.encoder
    op = encoder.operator
    return {'variant': model.variant, 'input_size': encoder.input_size,
            'hidden_size': encoder.hidden_size, 'ablations': sorted(encoder.ablations),
            'grid_size': op.grid_size, 'refractory_phases': op.refractory_phases,
            'state_size': op.state_size, 'lower_bound': op.lower_bound, 'sigma': op.sigma,
            'refractory': op.refractory, 'reset': op.reset, 'method': op.method,
            'fixed_boundary': encoder.fixed_boundary, 'drift_scale': encoder.drift_scale,
            'kick_scale': encoder.kick_scale, 'dtype': str(next(model.parameters()).dtype)}


def load_model(path):
    blob = torch.load(path, map_location='cpu', weights_only=True)
    metadata = blob['metadata']
    model = Policy(blob['variant'], hidden=metadata['hidden_size'],
                   grid_size=metadata['grid_size'], phases=metadata['refractory_phases'])
    model.load_state_dict(blob['state_dict'], strict=True)
    model.eval()
    for key in ('lower_bound', 'sigma', 'reset'):
        if metadata[key] != getattr(model.encoder.operator, key):
            raise ValueError('Parameter artifact uses an unsupported operator configuration')
    if metadata['refractory_mean'] != model.encoder.operator.refractory:
        raise ValueError('Parameter artifact uses an unsupported refractory configuration')
    return model, blob


def validate_scenario(scenario):
    if len(scenario.values) != 4 or len(scenario.deadlines) != 4:
        raise ValueError('Exactly four obligations are required')
    if not all(math.isfinite(v) and 0 <= v <= 8 for v in scenario.values):
        raise ValueError('Invalid bounded fixture value')
    if not 0.01 <= scenario.renewal_period <= 64 or not 0 < scenario.horizon <= 64:
        raise ValueError('Invalid bounded event horizon/renewal period')
    if not all(math.isfinite(v) and 0 <= v <= scenario.horizon for v in scenario.deadlines):
        raise ValueError('Invalid deadline')
    if not all(type(v) is int and 0 <= v <= 100 for v in
               (scenario.budget, scenario.shock_amount, scenario.refill_amount)):
        raise ValueError('Invalid integer resource amount')
    if not all(math.isfinite(v) for v in (scenario.shock_time, scenario.refill_time, scenario.early_penalty)):
        raise ValueError('Nonfinite external schedule')
    scenario.events()


def initial_ledger(scenario):
    return {'live': 15, 'budget': scenario.budget, 'spent': 0, 'removed': 0, 'added': 0,
            'reward': 0.0, 'renewals': 0, 'emissions': 0, 'dropped': 0,
            'terminal_utility': None}


def commit_ledger(scenario, previous, index, action):
    """Pure validation/replay of exactly one external event and one legal action."""
    ledger = dict(previous)
    times = scenario.events()
    current = times[index]
    available, removed, added = exogenous(scenario, current, ledger['budget'])
    observation = state_features(scenario, current, ledger['live'], available)
    ledger['removed'] += removed
    ledger['added'] += added
    if index == len(times)-1:
        if action is not None:
            raise ValueError('No terminal action is permitted')
        ledger['budget'] = available
        ledger['reward'] += sum(scenario.values[i] for i in range(4) if ledger['live'] >> i & 1)
        ledger['terminal_utility'] = ledger['reward']
    else:
        if type(action) is not int:
            raise ValueError('Action must be an integer')
        live, budget, reward, info = transition(scenario, current, ledger['live'], available, action)
        ledger['live'], ledger['budget'] = live, budget
        ledger['reward'] += reward
        ledger['spent'] += info['cost']
        for name in ('renewals', 'emissions', 'dropped'):
            ledger[name] += info[name]
    if ledger['budget'] != scenario.budget + ledger['added'] - ledger['removed'] - ledger['spent']:
        raise ValueError('Resource conservation violated')
    if ledger['budget'] < 0:
        raise ValueError('Negative resource balance')
    return ledger, observation


class JointRollout:
    """Single-episode research owner, with an explicit committed-event frontier."""
    def __init__(self, model, artifact_path, scenario, seed=99011):
        if not model.is_density or model.variant == 'rr_moment_collapse':
            raise ValueError('A sampled-law-compatible density policy is required')
        if next(model.parameters()).dtype != torch.float32:
            raise ValueError('This checkpoint profile is float32/CPU')
        validate_scenario(scenario)
        self.model = model.eval()
        self.artifact = Path(artifact_path).resolve()
        self.scenario = scenario
        self.times = scenario.events()
        self.engine = SampledDensityRollout(model.encoder, 1, 'ctmc', seed=seed, record_spikes=True)
        self.ledger = initial_ledger(scenario)
        self.next_index = 0
        self.committed = []
        self.in_event = False

    @torch.no_grad()
    def advance(self, event_index):
        if self.in_event or type(event_index) is not int or event_index != self.next_index:
            raise ValueError('Duplicate/stale tick, wrong event frontier, or uncommitted transition')
        if event_index >= len(self.times):
            raise ValueError('Episode has already terminated')
        self.in_event = True
        current = self.times[event_index]
        available, _, _ = exogenous(self.scenario, current, self.ledger['budget'])
        observation = state_features(self.scenario, current, self.ledger['live'], available)
        dt = current - float(self.engine.time[0])
        out = self.engine.step(torch.from_numpy(observation[None, :]), dt)
        action = None
        if event_index < len(self.times)-1:
            valid, due = legal_actions(self.scenario, current, self.ledger['live'], available)
            if due.any():
                logits = self.model.head(out['latent'])[0]
                action = int(torch.argmax(logits.masked_fill(~torch.from_numpy(valid), -1e9)))
            else:
                action = 0
        updated, checked_observation = commit_ledger(self.scenario, self.ledger, event_index, action)
        if not np.array_equal(observation, checked_observation):
            raise AssertionError('Ledger observation changed during the event')
        row = {'event_index': event_index, 'time': current, 'action': action,
               'action_digits': None if action is None else ACTION_DIGITS[action].tolist(),
               'observation': observation.tolist(), 'latent': out['latent'][0].tolist(),
               'interval_counts': out['actual_counts'][0].tolist(),
               'spikes': out['spike_times'], 'ledger_after': updated}
        self.ledger = updated
        self.committed.append(row)
        self.next_index += 1
        self.in_event = False
        return row

    def deadline_queue(self):
        now = self.times[self.next_index-1] if self.next_index else 0
        # Terminal utility queries the left limit and performs no renewal.
        # Only nonterminal committed events advance a due live obligation.
        queue_time = now if self.next_index == len(self.times) else now+4*EPS
        deadlines = next_deadlines(self.scenario, queue_time)
        return [{'item': i, 'value': self.scenario.values[i], 'next_deadline': float(deadlines[i])}
                for i in range(4) if self.ledger['live'] >> i & 1]

    def binding(self):
        return {'model_artifact_sha256': sha(self.artifact), 'model_weights_sha256': weights_sha(self.model),
                'operator_profile': operator_profile(self.model),
                'source_sha256': {p: sha(ROOT/p) for p in SOURCES},
                'numpy_version': np.__version__, 'torch_version': str(torch.__version__)}

    def checkpoint(self):
        if self.in_event or self.next_index == 0:
            raise ValueError('Checkpoint requires a fully committed event boundary')
        state = self.engine
        rng = json.loads(json.dumps(state.rng.bit_generator.state))
        for name in ('state', 'inc'):
            rng['state'][name] = str(rng['state'][name])
        execution = {'backend': 'ctmc', 'indices': state.indices.tolist(),
                     'counts': state.total_counts.tolist(), 'time': state.time.tolist(),
                     'observed': state.has_observed.tolist(), 'rng': rng}
        for name in ('context', 'drift', 'boundary', 'initial_resource'):
            value = getattr(state.state, name)
            execution[name] = None if value is None else value.tolist()
        payload = {'schema': SCHEMA, 'phase': 'after_committed_event', 'binding': self.binding(),
                   'scenario': asdict(self.scenario), 'event_schedule': self.times,
                   'next_event_index': self.next_index, 'ledger': self.ledger,
                   'deadline_queue': self.deadline_queue(), 'execution': execution,
                   'committed_events': self.committed}
        payload = json.loads(canonical(payload))
        return {'schema': SCHEMA, 'payload': payload,
                'payload_sha256': hashlib.sha256(DOMAIN+canonical(payload)).hexdigest(),
                'authority': 'none', 'official_owner_receipt': None,
                'production_activation_allowed': False}

    @classmethod
    def restore(cls, envelope, model, artifact_path, expected_checkpoint_sha256):
        if set(envelope) != {'schema', 'payload', 'payload_sha256', 'authority',
                             'official_owner_receipt', 'production_activation_allowed'}:
            raise ValueError('Unknown checkpoint envelope fields')
        payload = envelope['payload']
        actual_digest = hashlib.sha256(DOMAIN+canonical(payload)).hexdigest()
        if (envelope['schema'] != SCHEMA or payload['schema'] != SCHEMA
                or actual_digest != envelope['payload_sha256']
                or actual_digest != expected_checkpoint_sha256
                or envelope['authority'] != 'none' or envelope['official_owner_receipt'] is not None
                or envelope['production_activation_allowed'] is not False):
            raise ValueError('Checkpoint integrity or non-authorizing envelope mismatch')
        if payload['phase'] != 'after_committed_event':
            raise ValueError('Mid-event restore is unsupported')
        record = dict(payload['scenario'])
        record['values'], record['deadlines'] = tuple(record['values']), tuple(record['deadlines'])
        instance = cls(model, artifact_path, Scenario(**record), seed=0)
        if payload['binding'] != instance.binding():
            raise ValueError('Model artifact, weights, code, numeric implementation, or operator mismatch')
        frontier = payload['next_event_index']
        if type(frontier) is not int or not 1 <= frontier <= len(instance.times):
            raise ValueError('Invalid committed frontier')
        if payload['event_schedule'] != list(instance.times) or len(payload['committed_events']) != frontier:
            raise ValueError('Event schedule/frontier mismatch')
        ledger = initial_ledger(instance.scenario)
        counts = np.zeros((1, instance.engine.hidden), dtype=np.int64)
        context = instance.engine.state.context
        initial_resource = instance.engine.state.initial_resource
        for index, row in enumerate(payload['committed_events']):
            if row['event_index'] != index or row['time'] != instance.times[index]:
                raise ValueError('Noncontiguous committed event history')
            ledger, observation = commit_ledger(instance.scenario, ledger, index, row['action'])
            if ledger != row['ledger_after'] or observation.tolist() != row['observation']:
                raise ValueError('Resource ledger/observation replay mismatch')
            reconstructed = np.zeros(instance.engine.hidden, dtype=np.int64)
            last_time = instance.times[index-1] if index else 0.0
            for spike in row['spikes']:
                if not (last_time <= spike['time'] <= row['time'] and spike['batch'] == 0
                        and 0 <= spike['component'] < instance.engine.hidden):
                    raise ValueError('Invalid event-boundary spike record')
                reconstructed[spike['component']] += 1
            if reconstructed.tolist() != row['interval_counts']:
                raise ValueError('Spike events and interval counts disagree')
            counts += reconstructed[None, :]
            obs = torch.from_numpy(observation[None, :])
            resource = obs[:, 4:5].clamp(0, 1)
            if initial_resource is not None:
                initial_resource = torch.where(initial_resource < 0, resource, initial_resource)
                resource = initial_resource
            with torch.no_grad():
                controls = model.encoder.controls_from_observation(context, obs, resource)
            context = controls['context']
        if ledger != payload['ledger']:
            raise ValueError('Checkpoint budget/reward ledger does not replay')
        instance.ledger, instance.next_index = ledger, frontier
        if instance.deadline_queue() != payload['deadline_queue']:
            raise ValueError('Deadline queue does not match the committed obligations')
        execution = payload['execution']
        engine = instance.engine
        shape = (1, engine.hidden)
        indices = np.asarray(execution['indices'])
        if (execution['backend'] != 'ctmc' or indices.shape != shape or indices.dtype.kind not in 'iu'
                or (indices < 0).any() or (indices >= engine.operator.state_size).any()):
            raise ValueError('Invalid CTMC state indices')
        if execution['time'] != [instance.times[frontier-1]] or execution['observed'] != [True]:
            raise ValueError('Execution clock/observation frontier mismatch')
        if execution['counts'] != counts.tolist():
            raise ValueError('Cumulative spikes do not match committed events')
        for name in ('context', 'drift', 'boundary'):
            value = np.asarray(execution[name], dtype=np.float32)
            if value.shape != shape or not np.isfinite(value).all() or not np.array_equal(value, controls[name].numpy()):
                raise ValueError('Learned context/held control does not replay')
            setattr(engine.state, name, torch.from_numpy(value.copy()))
        expected_resource = None if initial_resource is None else initial_resource.tolist()
        if execution['initial_resource'] != expected_resource:
            raise ValueError('Frozen-resource memory mismatch')
        engine.state.initial_resource = initial_resource
        engine.indices = indices.astype(np.int64)
        engine.total_counts = counts
        engine.time = np.asarray(execution['time'], dtype=np.float64)
        engine.has_observed = np.asarray(execution['observed'], dtype=bool)
        rng = json.loads(json.dumps(execution['rng']))
        if (set(rng) != {'bit_generator', 'state', 'has_uint32', 'uinteger'}
                or set(rng['state']) != {'state', 'inc'}
                or rng['bit_generator'] != 'PCG64'
                or type(rng['has_uint32']) is not int or rng['has_uint32'] not in (0, 1)
                or type(rng['uinteger']) is not int or not 0 <= rng['uinteger'] < 2**32):
            raise ValueError('Unsupported RNG')
        for name in ('state', 'inc'):
            raw = rng['state'][name]
            if not isinstance(raw, str) or not raw.isdecimal() or str(int(raw)) != raw or not 0 <= int(raw) < 2**128:
                raise ValueError('Invalid canonical PCG64 integer')
            rng['state'][name] = int(raw)
        if rng['state']['inc'] % 2 != 1:
            raise ValueError('PCG64 increment must be odd')
        engine.rng.bit_generator.state = rng
        instance.committed = json.loads(canonical(payload['committed_events']))
        return instance


def read_checkpoint(path):
    raw = Path(path).read_bytes()
    if len(raw) > 1_048_576:
        raise ValueError('Checkpoint byte cap exceeded')
    def unique(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError('Duplicate JSON key')
            result[key] = value
        return result
    return json.loads(raw, object_pairs_hook=unique)
