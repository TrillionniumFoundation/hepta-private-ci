"""Finite Adam first-moment ablation arithmetic, not a model or trainer.

Only reachable coordinates are supplied. Sparse clocks increment once. The
counterfactual retains the native updated second moment and bias corrections,
removes inherited first moment, then matches the native full-vector L2 norm.
It is a new diagnostic update rule, NOT a correction to Adam.
"""
import math


def _finite(value):
    if type(value) not in (int, float) or not math.isfinite(value):
        raise ValueError('finite non-boolean scalar required')
    return float(value)


def matched_directions(groups, *, learning_rate, beta1, beta2, epsilon):
    lr, b1, b2, eps = map(_finite, (learning_rate, beta1, beta2, epsilon))
    if not lr > 0 or not eps > 0 or not 0 <= b1 < 1 or not 0 <= b2 < 1:
        raise ValueError('valid Adam configuration required')
    native, current, history = {}, {}, {}
    if not groups:
        raise ValueError('reachable groups required')
    for name, group in groups.items():
        clock = group['clock']
        if type(clock) is not int or clock < 0:
            raise ValueError('nonnegative integer sparse clock required')
        arrays = [group[k] for k in ('gradient', 'first', 'second')]
        if not arrays[0] or len({len(a) for a in arrays}) != 1:
            raise ValueError('same nonempty group shapes required')
        native[name], current[name], history[name] = [], [], []
        for gradient, first, second in zip(*arrays):
            g, m, v = map(_finite, (gradient, first, second))
            if v < 0 or (clock == 0 and (m != 0 or v != 0)):
                raise ValueError('valid first/second moments at sparse clock required')
            t = clock + 1
            denominator = math.sqrt((b2*v+(1-b2)*g*g)/(1-b2**t))+eps
            scale = -lr/(1-b1**t)/denominator
            d = scale*(b1*m+(1-b1)*g)
            c = scale*(1-b1)*g
            h = scale*b1*m
            for value in (d, c, h):
                _finite(value)
            native[name].append(d); current[name].append(c); history[name].append(h)
    native_norm = math.sqrt(math.fsum(x*x for a in native.values() for x in a))
    current_norm = math.sqrt(math.fsum(x*x for a in current.values() for x in a))
    if current_norm == 0 and native_norm != 0:
        raise ValueError('cannot match a zero current direction to nonzero native step')
    factor = native_norm/current_norm if current_norm else 0.0
    matched = {name: [factor*x for x in a] for name, a in current.items()}
    return {'native': native, 'current': current, 'history': history,
            'matched_current': matched, 'native_norm': native_norm,
            'current_norm': current_norm, 'norm_matching_factor': factor}


def frozen_gate(cells):
    """All twelve cells, both paired seeds; heuristic not a significance test."""
    expected = {(s, a, m) for s in (1, 2) for a in ('C', 'E') for m in ('S', 'A', 'N')}
    indexed = {}
    for cell in cells:
        key = (cell['paired_seed_slot'], cell['anchor'], cell['trained_mode'])
        if type(key[0]) is not int or key not in expected or key in indexed:
            raise ValueError('exact unique twelve-cell inventory required')
        if type(cell['requests']) is not int or cell['requests'] != 20:
            raise ValueError('exact twenty requests required')
        count = cell['sentinel_text_improvement_count']
        if type(count) is not int or not 0 <= count <= 20:
            raise ValueError('bounded improvement count required')
        for key2 in ('median_sentinel_text_native_minus_matched',
                     'median_sentinel_text_history_cosine',
                     'mean_sentinel_total_matched_minus_native'):
            _finite(cell[key2])
        indexed[key] = cell
    if set(indexed) != expected:
        raise ValueError('all twelve cells required')
    by_anchor = {}
    for anchor in ('C', 'E'):
        parts = [indexed[(s, anchor, 'N')] for s in (1, 2)]
        by_anchor[anchor] = all(
            c['sentinel_text_improvement_count'] > 10
            and c['median_sentinel_text_native_minus_matched'] > 1e-10
            and c['median_sentinel_text_history_cosine'] > 1e-12
            and c['mean_sentinel_total_matched_minus_native'] <= 1e-10
            for c in parts)
    return {'by_anchor': by_anchor, 'any_gate': any(by_anchor.values())}
