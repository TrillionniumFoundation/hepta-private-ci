"""Predict the incremental correctness of a paid view using the free first prefix."""
import numpy as np

PRICE = .30
RESERVES = (0., .10)
MODELS = ('global', 'cell-2', 'cell-6', 'cue-svd-.1', 'cue-svd-1',
          'full-svd-.1', 'full-svd-1', 'neighbours', 'tanh-keep', 'tanh-bp')
POLICIES = ('free', 'paid') + tuple(f'{m}/{r:.2f}' for m in MODELS for r in RESERVES)


def visible(free, gallery, acoustic):
    """Only purchase-time observable variables are accepted; no identities or target."""
    p, g = np.asarray(free)[:, 0, 1], np.asarray(gallery)[:, 0, 1]
    m, v = 2*p-1, 2*g-1
    cues = np.column_stack((m, abs(m), m*m, p >= .5, v, abs(v), abs(m-v),
                            m*v, (p >= .5) != (g >= .5), m*abs(m)))
    return np.column_stack((cues, np.asarray(acoustic)[:, 0, :8]))


def source_mass(group):
    unique, index, counts = np.unique(group, return_inverse=True, return_counts=True)
    return 1. / (len(unique) * counts[index])


def target(data):
    y = data['target']
    free = data['scores'][:, 0].argmax(-1) == y
    paid = data['read_scores'][:, 0].argmax(-1) == y
    return paid.astype(float) - free.astype(float)


def cells(x):
    return (x[:, 3].astype(int)*4 + (x[:, 1] > .65).astype(int)*2 + x[:, 8].astype(int))


def solve(a, y, w, penalty):
    center, offset = w @ a, w @ y
    design = (a - center) * np.sqrt(w[:, None])
    u, s, vt = np.linalg.svd(design, full_matrices=False)
    beta = vt.T @ ((s / (s*s + penalty)) * (u.T @ (np.sqrt(w)*(y-offset))))
    return beta, float(offset - center @ beta)


def fit(name, x, y, groups):
    w = source_mass(groups)
    mu = w @ y
    if name == 'global':
        return {'mean': float(mu)}
    if name.startswith('cell-'):
        ids = cells(x)
        scale = len(set(groups))
        strength = float(name.split('-')[1])
        pred = (np.bincount(ids, w*y*scale, minlength=8) + strength*mu) / (
            np.bincount(ids, w*scale, minlength=8) + strength)
        return {'values': pred.tolist()}
    width = 10 if name.startswith('cue-') else x.shape[1]
    a = x[:, :width]
    mean = w @ a
    std = np.sqrt(w @ (a-mean)**2).clip(.15)
    a = ((a-mean) / std).clip(-5, 5)
    state = {'mean': mean.tolist(), 'std': std.tolist()}
    if name == 'neighbours':
        return {**state, 'train': a.tolist(), 'y': y.tolist(), 'w': w.tolist(), 'prior': float(mu)}
    if name.startswith('tanh-'):
        rng = np.random.default_rng(181391)
        matrix = rng.normal(0, 1/np.sqrt(width), size=(width, 8))
        initial = matrix.copy()
        for _ in range(16 if name == 'tanh-bp' else 0):
            h = np.tanh(a @ matrix)
            beta, bias = solve(h, y, w, .1)
            error = h @ beta + bias - y
            grad = a.T @ ((2*w*error)[:, None] * beta * (1-h*h))
            matrix -= .12 * grad
            displacement = matrix-initial
            matrix = initial + displacement/max(1., np.linalg.norm(displacement)/.35)
        a = np.tanh(a @ matrix)
        state['matrix'] = matrix.tolist()
        penalty = .1
    else:
        penalty = float(name.rsplit('-', 1)[1])
    beta, bias = solve(a, y, w, penalty)
    return {**state, 'beta': beta.tolist(), 'bias': bias}


def predict(name, state, x):
    if name == 'global':
        return np.full(len(x), state['mean'])
    if name.startswith('cell-'):
        return np.asarray(state['values'])[cells(x)]
    width = len(state['mean'])
    a = ((x[:, :width]-state['mean']) / state['std']).clip(-5, 5)
    if name == 'neighbours':
        d = ((a[:, None, :] - np.asarray(state['train'])[None, :, :])**2).mean(-1)
        mass = np.exp(-d) * state['w']
        return (mass @ state['y'] + .1*state['prior']) / (mass.sum(1) + .1)
    if 'matrix' in state:
        a = np.tanh(a @ state['matrix'])
    return (a @ state['beta'] + state['bias']).clip(-1, 1)


def actions(policy, predictions):
    n = len(predictions['global'])
    if policy in ('free', 'paid'):
        return np.full(n, policy == 'paid')
    name, reserve = policy.split('/')
    return predictions[name] > PRICE + float(reserve)
