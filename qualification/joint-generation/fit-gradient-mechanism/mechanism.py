"""Portable scalar checks for a frozen diagnostic; not a trainer or data loader.

No tensors, model states, dataset paths, or execution grants are accepted here.
This helper reproduces the diagnostic coefficient formula and decision rules;
it does not reproduce the private experiment's forward/backward computation.
"""
import math


def _number(value, low, high):
    if type(value) not in (int, float) or not math.isfinite(value) or not low <= value <= high:
        raise ValueError('finite real number in the declared range required')
    return float(value)


def conditional_rho2_coefficients(p, q):
    """Exact local CE versus expected-utility coefficients at fixed p,q.

    CE = -log(1-p+p*exp(-2*q))/2; EU = p*q.
    Ratios exclude a common risk weight. Undefined zero-denominator ratios are
    None. This does not turn Euclidean gradients into Adam update directions.
    """
    p, q = _number(p, 0, 1), _number(q, 0, 1)
    exp = math.exp(-2*q)
    denominator = 1-p+p*exp
    d_p = -math.expm1(-2*q)/(2*denominator)
    d_q = p*exp/denominator
    return {'CE_p': d_p, 'CE_q': d_q, 'EU_p': q, 'EU_q': p,
            'N_to_A_p': d_p/q if q else None,
            'N_to_A_q': d_q/p if p else None}


def frozen_gates(cells):
    """Recompute the two prespecified heuristic gates from all 12 summaries.

    Every cell needs exactly 20 requests. This function cannot select a model,
    relax a gate, modify an objective or authorize another experiment.
    """
    expected = {(seed, anchor, mode) for seed in (1, 2)
                for anchor in ('C', 'E') for mode in ('S', 'A', 'N')}
    indexed = {}
    for cell in cells:
        key = (cell['paired_seed_slot'], cell['anchor'], cell['trained_mode'])
        if type(key[0]) is not int or key not in expected or key in indexed:
            raise ValueError('exact unique twelve-cell inventory required')
        value = cell['shared_body']
        if type(value['requests']) is not int or value['requests'] != 20:
            raise ValueError('fixed twenty requests per model required')
        for name in ('T_I', 'T_A', 'T_N'):
            n = value['conflicts'][name]
            if type(n) is not int or not 0 <= n <= 20:
                raise ValueError('finite integer conflict count required')
        ratio = value['median_image_text_norm_ratio']
        if ratio is not None:
            _number(ratio, 0, float('inf'))
        indexed[key] = value
    if set(indexed) != expected:
        raise ValueError('all twelve summaries required; no partial winner')
    h1 = {}
    for mode in ('S', 'A', 'N'):
        parts = [indexed[(seed, 'E', mode)] for seed in (1, 2)]
        h1[mode] = all(v['conflicts']['T_I'] > 10
                       and v['median_image_text_norm_ratio'] is not None
                       and v['median_image_text_norm_ratio'] > 1 for v in parts)
    h2 = {}
    for anchor in ('C', 'E'):
        parts = [indexed[(seed, anchor, 'N')] for seed in (1, 2)]
        h2[anchor] = all(v['conflicts']['T_N'] > v['conflicts']['T_A'] for v in parts)
    return {'H1_by_mode': h1, 'H2_by_anchor': h2,
            'H1_any_gate': any(h1.values()), 'H2_any_gate': any(h2.values())}
