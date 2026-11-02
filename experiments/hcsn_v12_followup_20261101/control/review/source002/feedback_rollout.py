"""Two-pool conservative feedback rollout around the frozen light policy."""
import hashlib
import math
import numpy as np
from experiments.hcsn_v10_followup_20261101.control import mpc
from experiments.hcsn_v9_followup_20261101.mechanisms import campaign as v9

ACTIONS = ('STOP', 'WAIT', 'READ')


def model_pool(obs, physics, matrix, config, seed, size):
    rng = np.random.default_rng(seed)
    start = round(obs.time/config.dt)
    grid = np.arange(start, config.ticks+1)*config.dt
    paths = [v9.old.generate_path(rng, physics, grid, obs.x,
        int(rng.choice(config.classes, p=obs.content_probs)), matrix, obs.refractory_remaining)
        for _ in range(size)]
    pool = {name: np.asarray([p[name] for p in paths])
            for name in ('x', 'refractory_remaining', 'content')}
    pool['service_uniform'] = rng.random((size, config.ticks+1))
    digest = hashlib.sha256()
    for name in sorted(pool):
        digest.update(name.encode()+pool[name].tobytes())
    return pool, start, digest.hexdigest()


def probabilities(core, x, times, remaining, content_probs, target, physics, matrix):
    packets = np.column_stack((x, target-times, np.full(len(x), physics.nu),
        np.full(len(x), physics.sigma), np.full(len(x), physics.reset),
        np.full(len(x), physics.refractory), remaining))
    counts = mpc.batch_counts(core, packets, physics)
    powers = np.stack([np.linalg.matrix_power(matrix, n) for n in range(counts.shape[1])])
    result = np.einsum('bn,nij,bj->bi', counts, powers, content_probs, optimize=False)
    # Preserve the original scalar head's floating-point argmax for exact ties.
    # A mathematical uniform replacement would change the inherited baseline.
    uniform = np.all(content_probs == content_probs[:, :1], axis=1)
    if uniform.any():
        rows, inverse = np.unique(np.column_stack((x[uniform], times[uniform], remaining[uniform],
                                                  content_probs[uniform])), axis=0, return_inverse=True)
        canonical = []
        for row in rows:
            observation = v9.old.Observation(float(row[1]), float(row[0]), float(row[2]),
                                              row[3:].tolist(), False)
            canonical.append(v9.old.predict(core, observation, target, physics, matrix)[0])
        result[uniform] = np.asarray(canonical)[inverse]
    return result


def branch_rewards(core, obs, tick, budget, physics, matrix, config, q, pool, start, roots):
    """Root action then actual feedback light tail; coupled model paths only."""
    n = len(pool['x'])
    total = n*len(roots)
    index = np.tile(np.arange(n), len(roots))
    x = np.full(total, obs.x)
    times = np.full(total, obs.time)
    rests = np.full(total, obs.refractory_remaining)
    content = np.tile(obs.content_probs, (total, 1))
    budgets = np.full(total, budget, dtype=int)
    pending = np.full(total, -1, dtype=int)
    stopped = np.zeros(total, dtype=bool)
    reads = np.zeros(total, dtype=int)
    correct = np.zeros(total, dtype=int)
    trace = hashlib.sha256()
    for t in range(tick, config.ticks+1):
        if t > tick:
            delivered = pending == t
            success = delivered & (pool['service_uniform'][index, t] < q[t])
            x[success] = pool['x'][index[success], t-start]
            times[success] = t*config.dt
            rests[success] = pool['refractory_remaining'][index[success], t-start]
            content[success] = np.eye(config.classes)[pool['content'][index[success], t-start]]
            pending[delivered] = -1
            if t in config.deadlines:
                predicted = probabilities(core, x, times, rests, content, t*config.dt, physics, matrix).argmax(1)
                correct += predicted == pool['content'][index, t-start]
        if t == config.ticks:
            break
        if t == tick:
            actions = np.repeat([ACTIONS.index(a) for a in roots], n)
        else:
            future = [d for d in config.deadlines if d > t]
            actions = np.zeros(total, dtype=int)
            active = ~stopped & (budgets > 0)
            if future and active.any():
                probs = probabilities(core, x[active], times[active], rests[active], content[active],
                                      future[0]*config.dt, physics, matrix)
                request = (q[t+1]*(1-probs.max(1)) > config.light_threshold) & (future[0]-t <= 2)
                actions[active] = np.where(request, 2, 1)
        actions[stopped] = 0
        requested = actions == 2
        if np.any(requested & ((budgets <= 0) | (pending >= 0))):
            raise ValueError('Invalid feedback READ branch')
        budgets[requested] -= 1
        reads[requested] += 1
        pending[requested] = t+1
        stopped |= actions == 0
        for value in (actions, budgets, pending, x, times, rests, content):
            trace.update(value.tobytes())
    units = 25*correct-4*reads
    return {'reward_units': units.reshape(len(roots), n).tolist(),
            'correct_counts': correct.reshape(len(roots), n).tolist(),
            'read_counts': reads.reshape(len(roots), n).tolist(), 'feedback_trace_sha256': trace.hexdigest()}


def choose(core, obs, tick, budget, physics, matrix, config, seeds, q, size, alpha):
    baseline, _ = v9.choose(core, 'lightweight', obs, tick, budget, physics, matrix, config, seeds[0], q, True)
    future = [d for d in config.deadlines if d > tick]
    if not future or budget <= 0:
        return baseline, {'baseline_action': baseline, 'reason': 'no_future_or_budget', 'fallback': True}
    roots = [baseline]+[a for a in ACTIONS if a != baseline]
    pool, start, digest = model_pool(obs, physics, matrix, config, seeds[0], size)
    selection = branch_rewards(core, obs, tick, budget, physics, matrix, config, q, pool, start, roots)
    means = [sum(values)/(100*size) for values in selection['reward_units']]
    chosen = max(range(len(roots)), key=lambda i: (means[i], -i))
    detail = {'baseline_action': baseline, 'roots': roots, 'selection': selection,
              'selection_means': means, 'candidate_action': roots[chosen], 'selection_pool_sha256': digest,
              'pool_seeds': list(seeds), 'pool_size': size, 'alpha': alpha, 'fallback': True}
    if chosen == 0:
        detail['reason'] = 'selection_keeps_light'
        return baseline, detail
    pool2, start2, digest2 = model_pool(obs, physics, matrix, config, seeds[1], size)
    validation = branch_rewards(core, obs, tick, budget, physics, matrix, config, q,
                                pool2, start2, [baseline, roots[chosen]])
    differences = [b-a for a, b in zip(*validation['reward_units'])]
    mean = sum(differences)/(100*size)
    bound = len(future)/len(config.deadlines)+budget*config.read_cost
    radius = bound*math.sqrt(2*math.log(1/alpha)/size)
    lcb = mean-radius
    if any(abs(v/100) > bound+1e-12 for v in differences):
        raise ArithmeticError('Paired reward bound violated')
    detail.update(validation=validation, validation_pool_sha256=digest2,
                  paired_difference_units=differences, mean_difference=mean,
                  bound=bound, radius=radius, lcb=lcb, fallback=not (lcb > 0),
                  reason='independent_validation_passes' if lcb > 0 else 'independent_validation_fallback')
    return (roots[chosen] if lcb > 0 else baseline), detail
