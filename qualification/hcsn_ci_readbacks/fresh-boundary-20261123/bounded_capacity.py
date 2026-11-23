"""Verify one post-outcome utility witness on the 48 published windows, or rerun its discovery."""
import argparse
import json
from fractions import Fraction
from pathlib import Path

import numpy as np
from qualification.hcsn_blocker_followup import metrics
from intercept_capacity import load_first_prefix
from bounded_optimizer import discover

UNIT = 1_000_000_000
NUMERATORS = [0, 0, 0, 44981304, 0, -95531148, 0, 0, 0, 0, 0, 9308000, -139416516, 0, 218952670, 78676745, -190553278, 0, 58163903]
ROBUST_NUMERATORS = [103256055, 0, 0, 879199, 0, -213629494, 0, 0, 0, 0, 0, -21224262, -208604722, 0, 220323123, 0, -157687426, -10307741, 29575420]



def verify(numerators, inputs):
    design, coefficients, data, free, paid, ids = inputs
    delta = [Fraction(n, UNIT) for n in numerators]
    weights = [Fraction(float(w)) + d for w, d in zip(coefficients, delta, strict=True)]
    scores = [sum(Fraction(float(v))*w for v, w in zip(row, weights, strict=True)) - Fraction(3,10) for row in design]
    actions = np.array([s > 0 for s in scores])
    assert np.array_equal(actions, design @ (coefficients + np.asarray(numerators)/UNIT) > 0.30)
    distance = sum(map(abs, delta))
    assert distance <= 1 and min(map(abs, scores)) > 0
    native = metrics.evaluate(data, actions)
    gains = actions.astype(int) * (10*(paid.astype(int)-free.astype(int))-3)
    values = 10*free.astype(int) + gains
    by_source = {}
    for group in sorted(set(data['group'])):
        mask = data['group'] == group
        by_source[str(group)] = {'free_contrast': str(Fraction(int(gains[mask].sum()), 10*int(mask.sum()))),
                                'utility': str(Fraction(int(values[mask].sum()), 10*int(mask.sum())))}
    base = design @ coefficients > 0.30
    assert native['adopt'] and min(Fraction(s['free_contrast']) for s in by_source.values()) == 0
    return {'scope':'Joint construction using already public fresh outcomes. A capacity witness only; no held-out policy performance or adaptation time advantage.',
            'edit_unit': str(Fraction(1, UNIT)), 'edit_numerators': numerators, 'edit_l1': str(distance),
            'nonzero_coordinates': sum(bool(n) for n in numerators), 'min_exact_absolute_margin':str(min(map(abs,scores))),
            'purchases':int(actions.sum()), 'free_to_paid':int((actions & ~base).sum()), 'paid_to_free':int((~actions & base).sum()),
            'correct':int(np.where(actions,paid,free).sum()), 'rescued':native['bought']['rescue'], 'already_right':native['bought']['already_right'],
            'harmed':native['bought']['harm'], 'utility':str(Fraction(int(values.sum()), 10*len(ids))),
            'delta_free':native['delta_free'], 'delta_paid':native['delta_paid'], 'worst_delta_free':native['worst_delta_free'],
            'nominal_sign_p':native['one_sided_sign_p'], 'source': by_source,
            'windows':{i:{'buy':bool(a),'margin':str(s)} for i,a,s in zip(ids,actions,scores,strict=True)}}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--discover', action='store_true', help='Run the retrospective mixed-integer fit again.')
    parser.add_argument('--robust', action='store_true', help='Use the historical minimum per-query margin 0.10.')
    args = parser.parse_args()
    source = load_first_prefix()
    separation = 0.10001 if args.robust else 0.0001
    coordinates = discover(*source[:5], separation) if args.discover else (ROBUST_NUMERATORS if args.robust else NUMERATORS)
    proof = verify(coordinates, source)
    if args.robust:
        assert Fraction(proof['min_exact_absolute_margin']) >= Fraction(1,10)
    print(json.dumps(proof, sort_keys=True, indent=2))
