"""Source-bound research calls into the existing stopping executor, no new owner.

No test labels enter execution. Bind weights AND critic/threshold/runtime, verify
whole populations before microbatch dispatch, and never retry an ambiguous run.
Python/hash metadata is not a signature, a sandbox, live CURRENT or Final-use.
"""

from dataclasses import asdict
import hashlib
from pathlib import Path
import platform

import torch

from development_ablation import PhaseClock, RecurrentClassifier
from development_quality import (BoundPolicy, Census, Observation, RiskPlan, Selection,
                                 digest, require_disjoint_history)
from development_stopping import ContinuationCritic, run_stopping
from development_tensors import checked_tensor, parameter_digest


EXECUTION_SOURCES = ('development_quality_runtime.py', 'development_quality.py',
                     'development_stopping.py', 'development_ablation.py',
                     'development_composition.py', 'development_tensors.py')


def execution_source_digest():
    files = {name: hashlib.sha256(Path(__file__).with_name(name).read_bytes()).hexdigest()
             for name in EXECUTION_SOURCES}
    return digest({'files': files, 'torch': torch.__version__, 'python': platform.python_version(),
                   'machine': platform.machine(), 'torch_threads': torch.get_num_threads()})


def input_digests(tokens):
    checked_tensor(tokens, 3, 'whole population tokens')
    return tuple(hashlib.sha256(str((row.dtype, tuple(row.shape))).encode() +
                 row.detach().cpu().contiguous().numpy().tobytes()).hexdigest() for row in tokens)


def bind_policy(model, config, critic=None):
    if (type(model) is not RecurrentClassifier or type(config) is not dict
            or set(config) - {'mode', 'depth', 'threshold'} or not {'mode', 'depth'} <= set(config)):
        raise ValueError('existing model and exact stopping configuration required')
    learned = config['mode'] == 'learned'
    if (learned and (type(critic) is not ContinuationCritic or critic.horizon != config['depth']
                     or critic.model_digest != parameter_digest(model))) or (not learned and critic is not None):
        raise ValueError('stale or unexpected critic binding')
    policy = BoundPolicy(config['mode'], config['depth'], config.get('threshold', 0),
                         parameter_digest(model), critic.identity() if learned else None,
                         execution_source_digest())
    policy.validate()
    if policy.depth > model.recurrence.maximum_depth:
        raise ValueError('policy exceeds model depth bound')
    return policy


def check_binding(model, policy, critic):
    expected = bind_policy(model, {'mode': policy.mode, 'depth': policy.depth,
                                   'threshold': policy.threshold}, critic)
    if policy != expected:
        raise ValueError('model, critic, threshold or execution source drift')


@torch.no_grad()
def execute_policy(model, tokens, census, policy, critic=None):
    """Includes input hashing, identity checks, dispatch and output construction."""
    clock = PhaseClock()
    if type(policy) is not BoundPolicy or type(census) is not Census:
        raise ValueError('typed source-bound population required')
    census.validate()
    if len(census.sample_ids) != len(tokens) or census.input_digests != input_digests(tokens):
        raise ValueError('population content/order drift')
    check_binding(model, policy, critic)
    predictions, depths, schedules = [], [], []
    for offset in range(0, len(tokens), 32):
        result = run_stopping(model, tokens[offset:offset+32], horizon=policy.depth, mode=policy.mode,
                              threshold=policy.threshold, critic=critic)
        predictions.extend(result['logits'].argmax(-1).tolist())
        depths.extend(result['depths'].tolist())
        schedules.append(tuple(tuple(offset+i for i in rows) for rows in result['executed_rows_by_depth']))
    check_binding(model, policy, critic)
    if sum(depths) != sum(len(rows) for batch in schedules for rows in batch):
        raise RuntimeError('actual recurrence census mismatch')
    return {'policy_digest': policy.identity(), 'census_digest': census.identity(),
            'predictions': tuple(predictions), 'depths': tuple(depths),
            'executed_rows_by_microbatch': tuple(schedules), 'cell_transitions': sum(depths),
            **clock.finish(), 'production_authorized': False}


def collect_observations(model, tokens, census, policies, critic, *, repetitions=3):
    """Rotating order, complete repeats; no faster subset or borrowed inference."""
    if (type(policies) is not tuple or not 2 <= len(policies) <= 17
            or any(type(p) is not BoundPolicy for p in policies)
            or type(repetitions) is not int or not 3 <= repetitions <= 9):
        raise ValueError('bounded matched portfolio execution required')
    for policy in policies:
        check_binding(model, policy, critic if policy.mode == 'learned' else None)
    if len({p.identity() for p in policies}) != len(policies):
        raise ValueError('duplicate policy in execution portfolio')
    clock, by_policy, ledger = PhaseClock(), {p.identity(): [] for p in policies}, []
    for repeat in range(repetitions):
        shift = repeat % len(policies)
        order = policies[shift:] + policies[:shift]
        for policy in order:
            result = execute_policy(model, tokens, census, policy, critic if policy.mode == 'learned' else None)
            earlier = by_policy[policy.identity()]
            if earlier and any(result[k] != earlier[0][k] for k in ('predictions', 'depths', 'census_digest')):
                raise ValueError('policy output drift across repeated measurements')
            earlier.append(result)
            ledger.append({'repetition': repeat, **result})
    observations = tuple(Observation(p.identity(), census.identity(), by_policy[p.identity()][0]['predictions'],
                         by_policy[p.identity()][0]['depths'], tuple(r['wall_ns'] for r in by_policy[p.identity()]),
                         tuple(r['cpu_ns'] for r in by_policy[p.identity()])) for p in policies)
    return observations, {'ledger': ledger, 'observations': [asdict(o) for o in observations],
                          'actual_cell_transitions': sum(r['cell_transitions'] for r in ledger),
                          'initialization_and_cold_start_measured': False, **clock.finish()}


def run_selected(model, tokens, census, *, plan, selection, priors, risk_census, critic):
    """Only execute the preselected policy; no holdout label or post-failure retry.

    A baseline fallback is chosen at calibration time, never after observing a
    failed/undesirable test answer. Live authorized use is outside this module.
    """
    clock = PhaseClock()
    if type(plan) is not RiskPlan or type(selection) is not Selection:
        raise ValueError('typed research selection required')
    plan.validate()
    require_disjoint_history(priors, risk_census)
    require_disjoint_history(priors + (risk_census,), census)
    if (census.fold != 'heldout' or risk_census.fold != 'risk'
            or not set(census.strata) <= set(plan.strata)
            or model.output.out_features != plan.classes
            or selection.plan_digest != plan.identity() or selection.risk_digest != risk_census.identity()
            or selection.history_digests != tuple(p.identity() for p in priors)):
        raise ValueError('stale risk selection or reused calibration/test population')
    policies = {p.identity(): p for p in (plan.baseline,) + plan.candidates}
    if selection.selected_policy_digest not in policies:
        raise ValueError('unregistered selected policy')
    chosen = policies[selection.selected_policy_digest]
    result = execute_policy(model, tokens, census, chosen, critic if chosen.mode == 'learned' else None)
    result.update({'plan_digest': plan.identity(), 'risk_digest': risk_census.identity()})
    result['selection_check_and_execution'] = clock.finish()
    return result
