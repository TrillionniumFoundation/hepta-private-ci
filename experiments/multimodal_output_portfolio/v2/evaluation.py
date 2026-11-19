"""Validation-only static selection and lazy, charged generation execution."""

import hashlib
import time

import numpy as np
import torch

from control import (COSTS, MISSING, MODALITIES, fixed_policies,
                     fixed_portfolio, next_preference)
from controlled_model import ControlledOutputModel
from generation_control import generation_cost
from metrics import cvar, score_outputs, summarize
from model import WIDTH, NUM_CLASSES, encode, mac_counts


def select_static(predictions, truth, losses, grid, budget):
    """Search the registered subset/weight/depth family on validation only."""
    best = None
    count = len(truth)
    for spec in fixed_policies(budget):
        acquisition = sum(COSTS[j] + 1 for j in spec['order'])
        public = np.full((count, 4), -1, dtype=np.int64)
        public[:, [0] + spec['order']] = predictions[:, [0] + spec['order']]
        unique, inverse = np.unique(public, axis=0, return_inverse=True)
        choices = np.array([fixed_portfolio(tuple(row), spec, grid)
                            for row in unique])[inverse]
        for depth in range(4):
            if acquisition + generation_cost(depth) > budget:
                continue
            observed = losses[depth, choices, truth]
            score = float(observed.mean() + 0.5 * cvar(observed))
            if best is None or score < best['validation_objective'] - 1e-12:
                best = {**spec, 'depth': depth, 'validation_objective': score,
                        'declared_units': acquisition + generation_cost(depth)}
    if best is None:
        raise ValueError('no static policy satisfies the generation contract')
    return best


@torch.inference_mode()
def rollout(model, world, policy, budget, grid, targets):
    """The policy sees only acquired encoder reports; truth is evaluator-only."""
    raw = world['raw']
    count = len(raw['text'])
    observations = np.full((count, 4), -1, dtype=np.int64)
    remaining = np.full(count, budget, dtype=np.int64)
    preference = np.zeros(count, dtype=np.int64)
    portfolio = np.zeros(count, dtype=np.int64)
    depths = np.zeros(count, dtype=np.int64)
    macs = np.zeros(count, dtype=np.int64)
    calls = {name: 0 for name in MODALITIES}
    examples = {name: 0 for name in MODALITIES}
    traces = [[] for _ in range(count)]
    profile = mac_counts(model)
    wall, cpu = time.perf_counter(), time.process_time()
    controller_seconds = 0.0

    def acquire(rows, modality, initial=False):
        if len(rows) == 0:
            return
        name = MODALITIES[modality]
        if not initial:
            charge = COSTS[modality] + 1
            if np.any(remaining[rows] < charge + generation_cost(0)):
                raise AssertionError('acquisition spends required emission reserve')
            if np.any(observations[rows, modality] != -1):
                raise AssertionError('modality acquired twice')
            remaining[rows] -= charge
        data = raw[name][rows]
        present = np.any(data != 0, axis=1)
        reports = np.full(len(rows), MISSING, dtype=np.int64)
        if present.any():
            reports[present] = encode(model, name, data[present])[0]
            calls[name] += 1
            examples[name] += int(present.sum())
            macs[rows[present]] += profile['encoder'][name]
        for row, report in zip(rows, reports):
            if not initial:
                preference[row] = next_preference(int(preference[row]),
                                                   tuple(observations[row]), int(report))
            observations[row, modality] = report
            traces[row].append({'event': 'initial_text' if initial else 'acquire',
                                'modality': name, 'report': int(report),
                                'remaining': int(remaining[row])})

    acquire(np.arange(count), 0, initial=True)
    if isinstance(policy, dict):
        for modality in policy['order']:
            acquire(np.arange(count), modality)
        started = time.perf_counter()
        for row in range(count):
            portfolio[row] = fixed_portfolio(tuple(observations[row]), policy, grid)
        depths[:] = policy['depth']
        controller_seconds += time.perf_counter() - started
    else:
        active = np.ones(count, dtype=bool)
        while active.any():
            requests = {modality: [] for modality in range(1, 4)}
            started = time.perf_counter()
            for row in np.flatnonzero(active):
                plan = policy.solve(tuple(int(x) for x in observations[row]),
                                    int(remaining[row]), int(preference[row]))
                if plan.action == -1:
                    portfolio[row], depths[row] = plan.portfolio, plan.depth
                    active[row] = False
                else:
                    requests[plan.action].append(row)
            controller_seconds += time.perf_counter() - started
            for modality, rows in requests.items():
                acquire(np.asarray(rows, dtype=np.int64), modality)

    outputs = {name: np.empty((count, model.dimensions[name]), dtype=np.float32)
               for name in MODALITIES}
    wrapper = ControlledOutputModel(model, copy_model=False)
    for depth in range(4):
        rows = np.flatnonzero(depths == depth)
        if not len(rows):
            continue
        charge = generation_cost(depth)
        if np.any(remaining[rows] < charge):
            raise AssertionError('generation exceeds remaining budget')
        state = wrapper.initialize(grid[portfolio[rows]])
        remaining[rows] -= 2
        for row in rows:
            traces[row].append({'event': 'initialize', 'portfolio': int(portfolio[row]),
                                'remaining': int(remaining[row])})
        for step in range(depth):
            state = wrapper.refine_step(state)
            remaining[rows] -= 2
            for row in rows:
                traces[row].append({'event': 'refine', 'depth': step + 1,
                                    'remaining': int(remaining[row])})
        generated = wrapper.emit(state)
        remaining[rows] -= 2
        for name in MODALITIES:
            outputs[name][rows] = generated[name].cpu().numpy()
        for row in rows:
            traces[row].append({'event': 'emit_all_four', 'depth': depth,
                                'remaining': int(remaining[row]), 'sealed': True})
        macs[rows] += (NUM_CLASSES * WIDTH + depth * 2 * WIDTH * WIDTH
                       + sum(profile['decoder'].values()))
    if np.any(remaining < 0):
        raise AssertionError('negative budget')
    execution_seconds = time.perf_counter() - wall
    execution_cpu = time.process_time() - cpu
    scores = score_outputs(outputs, world['truth'], targets)
    summary = summarize(scores)
    summary.update({'mean_linear_macs': float(macs.mean()),
                    'mean_declared_units': float((budget - remaining).mean()),
                    'depth_counts': np.bincount(depths, minlength=4).tolist(),
                    'execution_wall_seconds': execution_seconds,
                    'execution_cpu_seconds': execution_cpu,
                    'controller_wall_seconds': controller_seconds})
    receipt = {'linear_macs': macs, 'remaining': remaining, 'depth': depths,
               'portfolio': portfolio, 'preference': preference, 'trace': traces,
               'encoder_calls': calls, 'encoded_examples': examples,
               'all_four_outputs': True, 'budget_violations': 0,
               'output_sha256': {name: hashlib.sha256(values.tobytes()).hexdigest()
                                 for name, values in outputs.items()}}
    return scores, receipt, summary
