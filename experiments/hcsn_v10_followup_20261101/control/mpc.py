"""Finite-budget multi-READ schedule MPC; no actual hidden world is accepted."""
import itertools
import time
import numpy as np
import torch
from experiments.hcsn_mechanism_content_v2 import mechanism as old
from experiments.hcsn_mechanism_content_v2.renewal import first_passage_cdf


def score_schedule(schedule, deadlines, base_correct, read_correct, q, fee=.04, normalizer=4):
    """Exact service mixture of the last successful read for a fixed schedule."""
    reward = 0.
    for d in deadlines:
        survival = 1.
        for a in reversed([a for a in schedule if a <= d]):
            reward += survival*q[a]*read_correct[(a, d)]/normalizer
            survival *= 1-q[a]
        reward += survival*base_correct[d]/normalizer
    return reward-len(schedule)*fee


def batch_counts(core, packets, physics):
    if hasattr(core, 'model'):
        with torch.no_grad():
            answer = core.model(torch.as_tensor(packets, dtype=torch.float64)).softmax(-1).numpy()
    else:
        n = np.arange(1, 33, dtype=float)[None]
        elapsed = packets[:, 1:2]-packets[:, 6:7]-(n-1)*physics.refractory
        distance = packets[:, :1]+(n-1)*physics.reset
        tails = first_passage_cdf(elapsed, distance, physics.nu*core.scale, physics.sigma)
        if np.any(tails[:, -1] > 1e-9):
            raise ValueError('Batch event support exceeded')
        answer = np.concatenate((np.ones((len(packets), 1)), tails[:, :-1]), axis=1)-tails
    inactive = packets[:, 1] <= packets[:, 6]
    answer[inactive] = 0.
    answer[inactive, 0] = 1.
    if not np.isfinite(answer).all() or answer.min() < -1e-10 or not np.allclose(answer.sum(1), 1., atol=1e-9):
        raise ArithmeticError('Invalid batch count law')
    core.calls += len(packets)
    return answer


def choose(core, obs, tick, budget, physics, matrix, config, seed, q, samples=64):
    started = time.process_time()
    deadlines = [d for d in config.deadlines if d > tick]
    if not deadlines or budget <= 0:
        return 'STOP', {'reason': 'no_future_output_or_budget', 'samples': 0}
    start_tick = round(obs.time/config.dt)
    grid = np.arange(start_tick, config.ticks+1)*config.dt
    rng = np.random.default_rng(seed)
    paths = [old.generate_path(rng, physics, grid, obs.x,
        int(rng.choice(config.classes, p=obs.content_probs)), matrix, obs.refractory_remaining)
        for _ in range(samples)]
    base = {}
    for d in deadlines:
        pred = old.predict(core, obs, d*config.dt, physics, matrix)[0].argmax()
        base[d] = float(np.mean([path['content'][d-start_tick] == pred for path in paths]))
    packets, labels, futures, pairs = [], [], [], []
    for a in range(tick+1, max(deadlines)+1):
        for d in deadlines:
            if a > d:
                continue
            pairs.append((a, d))
            for path in paths:
                ai, di = a-start_tick, d-start_tick
                packets.append([path['x'][ai], (d-a)*config.dt, physics.nu, physics.sigma,
                                physics.reset, physics.refractory, path['refractory_remaining'][ai]])
                labels.append(path['content'][ai])
                futures.append(path['content'][di])
    packets = np.asarray(packets, dtype=float)
    counts = batch_counts(core, packets, physics)
    powers = np.stack([np.linalg.matrix_power(matrix, n) for n in range(counts.shape[1])])
    content = np.einsum('bn,bnk->bk', counts, powers[:, :, np.asarray(labels)].transpose(2, 0, 1))
    correct = (content.argmax(1) == futures).reshape(len(pairs), samples).mean(1)
    read = {pair: float(value) for pair, value in zip(pairs, correct)}
    candidates = []
    for size in range(min(budget, config.ticks-tick)+1):
        for schedule in itertools.combinations(range(tick+1, max(deadlines)+1), size):
            candidates.append({'arrivals': schedule, 'score': score_schedule(
                schedule, deadlines, base, read, q, config.read_cost, len(config.deadlines))})
    # Stable ties prefer fewer READ fees, then the earliest schedule.
    best = min(candidates, key=lambda row: (-row['score'], len(row['arrivals']), row['arrivals']))
    schedule = best['arrivals']
    action = 'STOP' if not schedule else ('READ' if schedule[0] == tick+1 else 'WAIT')
    return action, {'selected_arrivals': list(schedule), 'selected_score': best['score'],
        'candidates': candidates, 'samples': samples, 'base_correct': base,
        'read_correct': [{'arrival': a, 'deadline': d, 'correct': read[(a, d)]} for a, d in pairs],
        'service_forecast': q, 'cpu_seconds_nested': time.process_time()-started,
        'packet_evaluations': len(packets), 'actual_hidden_world_accepted': False}
