"""Replay frozen purchase heads and compare LP with gradient at each common L1 radius."""

import argparse
import hashlib
import json
import math
import zipfile
from collections import Counter, defaultdict
from pathlib import Path


ARCHIVE = '4a69291c427ea72a4d1e10eac64d459dd32606045f2e16c320b2bfad5578af43'
AFFINE = '38ccaa0d206c53afaad059a94232c62d8c532216f5c8016711cb3da3d2f37e56'
PRICE = 0.30
RADII = ('0.0', '0.25', '1.0', '4.0')


def check(condition, message):
    if not condition:
        raise ValueError(message)


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def close(left, right):
    return math.isclose(left, right, abs_tol=1e-10, rel_tol=0.0)


def replay(base, fit, observations, original):
    weights = [w + d for w, d in zip(base, fit['delta'], strict=True)]
    actions = {}
    totals = defaultdict(Counter)
    for query, row in observations.items():
        state = [float.fromhex(v) for v in row['state_hex']] + [1.0]
        score = math.fsum(v * w for v, w in zip(state, weights, strict=True))
        buy = score > PRICE
        correct = row['paid' if buy else 'free'] == row['target']
        totals[row['source']].update(n=1, buy=int(buy), correct=int(correct))
        actions[query] = buy

    check(set(totals) == set(original['sources']), 'Source roster mismatch')
    utilities = {}
    for group, count in totals.items():
        saved = original['sources'][group]
        value = (count['correct'] - PRICE * count['buy']) / count['n']
        check(
            count['n'] == saved['n'] and count['buy'] == saved['buy'],
            'Purchase counts mismatch',
        )
        check(close(count['correct'] / count['n'], saved['accuracy']), 'Accuracy mismatch')
        check(close(value, saved['value']), 'Source utility mismatch')
        utilities[group] = value
    mean = math.fsum(utilities.values()) / len(utilities)
    check(close(mean, original['utility']), 'Source macro utility mismatch')
    return actions, utilities, {
        'source_macro_utility': mean,
        'purchase_count': sum(actions.values()),
        'correct_windows': sum(c['correct'] for c in totals.values()),
        'observed_solver_ms': fit['elapsed'] * 1000,
        'training_objective': fit['check']['objective'],
        'actual_l1_displacement': math.fsum(abs(d) for d in fit['delta']),
        'registered_adopt': original['adopt'],
    }


def compare(evidence):
    archive = evidence / 'paid-roster-04.zip'
    affine = evidence / 'affine_inputs.json'
    check(digest(archive) == ARCHIVE and digest(affine) == AFFINE, 'Evidence digest mismatch')
    with zipfile.ZipFile(archive) as z:
        seal_bytes = z.read('outcomes/edit_seal.json')
        fit = json.loads(seal_bytes)
        test = json.loads(z.read('outcomes/edit_test.json'))
        base = json.loads(z.read('outcomes/fit.json'))['full-svd-.1']
    check(hashlib.sha256(seal_bytes).hexdigest() == test['edit_seal'], 'Edit seal mismatch')
    check(fit['heldout_opened'] is False and fit['selected'] == test['selected'], 'Selection mismatch')
    queries = {q: row for q, row in json.loads(affine.read_bytes()).items() if row['split'] == 'test'}
    groups = sorted({row['source'] for row in queries.values()})
    check(len(queries) == 32 and len(groups) == 8, 'Unexpected test roster')
    by_radius = {}
    for r in RADII:
        outcomes = {}
        for method in ('lp', 'gradient'):
            solution = fit['rows'][method][r]
            check(len(solution['delta']) == 19, 'Unexpected editable dimension')
            check(math.fsum(map(abs, solution['delta'])) <= float(r) + 1e-7, 'Radius exceeded')
            outcomes[method] = replay(
                base['beta'] + [base['bias']], solution, queries, test['rows'][method][r]
            )
        lp_actions, lp_utility, lp = outcomes['lp']
        gd_actions, gd_utility, gd = outcomes['gradient']
        diffs = [round(gd_utility[g] - lp_utility[g], 12) for g in groups]
        by_radius[r] = {
            'lp': lp,
            'gradient': gd,
            'gradient_minus_lp_source_macro': math.fsum(diffs) / len(diffs),
            'gradient_win_tie_loss_sources': [
                sum(d > 0 for d in diffs), diffs.count(0), sum(d < 0 for d in diffs)
            ],
            'paired_source_delta': dict(zip(groups, diffs, strict=True)),
            'differing_purchase_decisions': [
                {
                    'query': q,
                    'source': row['source'],
                    'lp_buys': lp_actions[q],
                    'gradient_buys': gd_actions[q],
                    'free_correct': row['free'] == row['target'],
                    'paid_correct': row['paid'] == row['target'],
                }
                for q, row in sorted(queries.items())
                if lp_actions[q] != gd_actions[q]
            ],
        }
    distinct = {
        m: len({tuple(fit['rows'][m][r]['delta']) for r in RADII})
        for m in ('lp', 'gradient')
    }
    return {
        'source_commit': '7b0af00123582ab16f55cb3f0c4314d0d3099909',
        'price': PRICE,
        'scope': 'Descriptive replay of the published cohort at the original price and all registered radii.',
        'independent_recording_sources': len(groups),
        'recorded_windows': len(queries),
        'new_training_runs': 0,
        'new_confirmations': 0,
        'dev_selected_radii': fit['selected'],
        'distinct_parameter_updates_including_origin': distinct,
        'same_radius': by_radius,
    }


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('evidence', type=Path, help='Original qualification/hcsn_blocker_followup/evidence directory')
    print(json.dumps(compare(parser.parse_args().evidence), indent=2, sort_keys=True))
