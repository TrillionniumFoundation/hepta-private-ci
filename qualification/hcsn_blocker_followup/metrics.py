"""Source-balanced realized utility, calibration and source-paired tests."""
import math
import numpy as np

from .selector import PRICE, source_mass


def sign_p(x):
    nonzero = np.asarray(x)[abs(np.asarray(x)) > 1.e-12]
    n, k = len(nonzero), sum(nonzero > 0.)
    return sum(math.comb(n, j) for j in range(k, n+1)) / (2**n)


def evaluate(data, read, predicted=None):
    y, group = data['target'], data['group']
    free = data['scores'][:, 0].argmax(-1) == y
    cam = data['read_scores'][:, 0].argmax(-1) == y
    hit = np.where(read, cam, free)
    value = hit - PRICE*read
    net = cam.astype(float) - free.astype(float) - PRICE
    w = source_mass(group)
    perf = {}
    for g in sorted(set(group)):
        ix = group == g
        perf[str(g)] = {'n': int(ix.sum()), 'buy': int(read[ix].sum()),
                        'value': float(value[ix].mean()), 'accuracy': float(hit[ix].mean()),
                        'delta_free': float((value[ix]-free[ix]).mean()),
                        'delta_paid': float((value[ix]-cam[ix]+PRICE).mean())}
    contrasts = [[a[k] for a in perf.values()] for k in ['delta_free', 'delta_paid']]
    pvalues = [sign_p(q) for q in contrasts]
    delta = [float(np.mean(v)) for v in contrasts]
    res = {'utility': float(w@value), 'r1': float(w@hit), 'buy': int(read.sum()),
           'buy_rate':float(w@read),
           'break_even_price_vs_free':float(w@(read*(cam.astype(float)-free.astype(float)))/(w@read)) if read.any() else None,
           'n': len(y), 'sources': perf, 'delta_free': delta[0], 'delta_paid': delta[1],
           'worst_delta_free': min(contrasts[0]), 'one_sided_sign_p': pvalues,
           'adopt': bool(0 < read.sum() < len(y) and min(delta) >= .03-1.e-12
                         and min(contrasts[0]) >= -.05-1.e-12
                         and min(pvalues) <= .025 and max(pvalues) <= .05),
           'bought': {'rescue':int(sum(read & cam & ~free)), 'harm':int(sum(read & ~cam & free)),
                      'already_right':int(sum(read & cam & free)), 'both_wrong':int(sum(read & ~cam & ~free))},
           'missed_rescues':int(sum(~read & cam & ~free)),
           'oracle_buy_gain':float(w@np.maximum(net,0))}
    if predicted is not None:
        bins = np.searchsorted([0., .30, .50], predicted, side='left')
        res['calibration'] = []
        for b in range(4):
            ix = bins == b
            # Keep the original source weights, renormalized within the reported bin.
            weighted = w[ix] / w[ix].sum() if ix.any() else []
            res['calibration'].append({'bin': b, 'n': int(ix.sum()),
                'sources':len(set(group[ix])), 'bought':int(read[ix].sum()),
                'rescue':int(sum(cam[ix] & ~free[ix])), 'harm':int(sum(~cam[ix] & free[ix])),
                'predicted_gain':float(weighted@predicted[ix]) if ix.any() else None,
                'actual_net':float(weighted@net[ix]) if ix.any() else None})
    return res
