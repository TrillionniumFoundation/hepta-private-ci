"""Frozen support backoff and held-out policy-risk calibration, not a new owner.

Bounds are conditional on independent sources and the same target population.
Text hashes are not proof of those conditions. This module cannot promote a model.
"""
from dataclasses import asdict
import math

from four_gate_common import digest, require
from fbsde_acquisition import history_key

CANDIDATES = ('full_symbol', 'ndu_bsde', 'ndu_backoff_5', 'ndu_backoff_20')
RULE = {'alpha': .05, 'max_accepted_error': .10, 'min_coverage': .50, 'min_sources': 200}


def bernoulli_bounds(successes, count, delta):
    """One-sided Chernoff inversion; never use pseudo-counts as sample support.

    For independent (not necessarily identically distributed) Bernoulli trials,
    exp(-n*KL(observed||mean)) bounds the appropriate tail at the average mean.
    Return conservative float endpoints. This is not outward-rounded arithmetic.
    """
    require(type(count) is int and 0 <= count <= 100000 and type(successes) is int
            and 0 <= successes <= count, 'actual bounded Bernoulli counts')
    require(type(delta) is float and 0 < delta < 1, 'tail probability')
    if not count:
        return 0., 1.
    p = successes/count; target = -math.log(delta)/count
    def kl(q):
        if q in (0., 1.):
            return 0. if p == q else math.inf
        return ((p*math.log(p/q) if p else 0.) +
                ((1-p)*math.log((1-p)/(1-q)) if p < 1 else 0.))
    lo, hi = 0., p
    for _ in range(64):
        mid = (lo+hi)/2
        if kl(mid) > target: lo = mid
        else: hi = mid
    lower = lo if p else 0.
    lo, hi = p, 1.
    for _ in range(64):
        mid = (lo+hi)/2
        if kl(mid) > target: hi = mid
        else: lo = mid
    return lower, hi if p < 1 else 1.


def compile_guard(kernel, raw_rows, neutral_actions, objective):
    """Raw support alone activates fallback; smoothed masses are never counts."""
    require(type(raw_rows) is list and 1 <= len(raw_rows) <= 4096, 'raw training rows')
    require(all(type(r) is tuple and len(r) == 4 and all(type(x) is int and
                0 <= x < kernel.symbols for x in r) for r in raw_rows), 'raw label/symbol tuple')
    actions = {}; supports = {}
    for h in neutral_actions:
        support = sum(all(row[v+1] == s for v, s in h) for row in raw_rows)
        supports[h] = support
        for minimum in (5, 20):
            action = neutral_actions[h]
            if support < minimum:
                action = f'answer:{dict(h)[2]}' if 2 in dict(h) else 'read:2'
            actions[(f'ndu_backoff_{minimum}', h)] = action
    return {'binding': digest([kernel.identity, asdict(objective)]),
            'actions': actions, 'supports': supports, 'selected': None}


def guarded_action(arm, kernel, history, objective, guard):
    require(guard is not None and guard['binding'] == digest([kernel.identity, asdict(objective)]),
            'stale guard model or objective')
    h = history_key(history, kernel.symbols)
    require(arm in CANDIDATES[2:] and (arm, h) in guard['actions'], 'registered guard history')
    return guard['actions'][(arm, h)]


def calibrate(records, labelled_sources, binding):
    """Choose only among pre-fitted complete policies after all predictions seal.

    Input rows are (id, original-text-hash, class). Balanced class sampling makes
    the average mean the declared balanced target, assuming stability per class.
    No per-history selection is performed on these calibration labels.
    """
    require(set(records) == set(CANDIDATES), 'complete frozen candidate family')
    require(type(labelled_sources) is list and 1 <= len(labelled_sources) <= 4096,
            'bounded independent calibration inventory')
    labels = {uid: label for uid, _, label in labelled_sources}
    hashes = [h for _, h, _ in labelled_sources]
    by_id = {uid: h for uid, h, _ in labelled_sources}
    require(len(labels) == len(hashes) == len(set(hashes)), 'duplicate calibration source')
    require(all(type(h) is str and len(h) == 64 and all(c in '0123456789abcdef' for c in h)
                for h in hashes), 'original source hashes')
    require(all(type(y) is int and 0 <= y < 8 for y in labels.values()), 'calibration class labels')
    classes = sorted(set(labels.values()))
    require(classes == list(range(len(classes))) and len(classes) >= 2 and
            len({sum(y == c for y in labels.values()) for c in classes}) == 1,
            'predeclared balanced class target')
    delta = RULE['alpha']/(2*len(CANDIDATES)); report = {}; passed = []
    for arm in CANDIDATES:
        rows = records[arm]
        require(len(rows) == len(labels) and {r['id'] for r in rows} == set(labels),
                'paired calibration predictions')
        accepted = wrong = 0; score = 0.
        for row in rows:
            require(row['source_input_sha256'] == by_id[row['id']],
                    'calibration input drift')
            if row['action'] != 'abstain':
                require(row['action'] in {f'answer:{c}' for c in classes}, 'nonterminal calibration action')
                accepted += 1; wrong += int(int(row['action'].split(':')[1]) != labels[row['id']])
            # Original objective is frozen; this is only a tie-break among certified policies.
            score += (0 if row['action'] == 'abstain' else
                      1 if row['action'] == f"answer:{labels[row['id']]}" else -1)-row['modeled_cost']
        coverage_lcb = bernoulli_bounds(accepted, len(rows), delta)[0]
        joint_error_ucb = bernoulli_bounds(wrong, len(rows), delta)[1]
        risk_ucb = min(1., joint_error_ucb/coverage_lcb) if coverage_lcb > 0 else 1.
        certified = (len(rows) >= RULE['min_sources'] and accepted > 0 and
                     coverage_lcb >= RULE['min_coverage'] and risk_ucb <= RULE['max_accepted_error'])
        report[arm] = {'sources': len(rows), 'accepted': accepted, 'wrong': wrong,
            'coverage_lcb': coverage_lcb, 'joint_error_ucb': joint_error_ucb,
            'accepted_error_ucb': risk_ucb, 'empirical_score': score/len(rows),
            'conditional_certificate': certified}
        if certified: passed.append(arm)
    winner = max(passed, key=lambda a: (report[a]['accepted'], report[a]['empirical_score'],
                                       -CANDIDATES.index(a))) if passed else 'abstain'
    return {'schema': 'hepta.acquisition.policy-calibration.v1', 'binding': binding, 'rule': RULE,
        'source_inventory_sha256': digest(labelled_sources), 'candidate_predictions_sha256': digest(records),
        'profiles': report, 'selected': winner, 'no_candidate_passes': not passed,
        'assumptions': 'independent_sources_and_same_class_balanced_target_after_model_freeze',
        'assumptions_authenticated': False, 'production_promotion_permitted': False}
