"""Training-only joint-law shrinkage; no solver, runtime authority or test tuning.

The full-view-anchored distribution is a regularization target, NOT a claim that
view errors are conditionally independent. Observed joint counts are retained.
"""
from collections import Counter
from itertools import product
import math

from four_gate_common import digest, require

LEGACY_KERNEL = 'uniform_joint_v1'
SUPPORTED_KERNEL = 'joint_backoff_cv_v2'
KERNEL_PROFILES = (LEGACY_KERNEL, SUPPORTED_KERNEL)
CANDIDATES = ('legacy', 'anchor:8', 'anchor:32', 'anchor:128', 'anchor:512')
FOLDS = 4


def regularized_counts(rows, classes, candidate):
    """Finite positive table; every observed tuple contributes exactly one count."""
    require(candidate in CANDIDATES, 'unregistered smoothing candidate')
    require(type(classes) is int and 2 <= classes <= 8 and rows, 'bounded class/row inventory')
    require(all(type(r) is tuple and len(r) == 4 and
                all(type(x) is int and 0 <= x < classes for x in r) for r in rows), 'label/symbol tuples')
    raw = Counter(rows)
    worlds = tuple(product(range(classes), repeat=4))
    if candidate == 'legacy':
        return tuple(raw[w] + .01 for w in worlds)
    strength = int(candidate.split(':')[1])
    full = Counter(r[3] for r in rows)
    label_full = Counter((r[0], r[3]) for r in rows)
    views_full = Counter(r[1:] for r in rows)
    result = []
    for y, a, b, c in worlds:
        # P(c) P(y|c) P(a,b|c), estimated on this fitting fold ONLY.
        prior = ((full[c]+.5)/(len(rows)+.5*classes) *
                 (label_full[y, c]+.5)/(full[c]+.5*classes) *
                 (views_full[a, b, c]+.5)/(full[c]+.5*classes**2))
        result.append(raw[y, a, b, c] + strength*prior)
    return tuple(result)


def select_counts(rows, source_hashes, classes):
    """Four source-hash folds; label log score on four registered information sets.

    The same observed row's correlated histories stay in its original fold. No
    selection/validation/test labels or backend-specific tuning enter this API.
    """
    require(len(rows) == len(source_hashes) and 8 <= len(rows) <= 4096, 'bounded kernel sources')
    require(all(type(h) is str and len(h) == 64 and all(c in '0123456789abcdef' for c in h)
                for h in source_hashes) and len(set(source_hashes)) == len(rows), 'unique original source hashes')
    folds = [int(h[:16], 16) % FOLDS for h in source_hashes]
    require(set(folds) == set(range(FOLDS)), 'all registered folds need support')
    subsets = ((0,), (0, 1), (0, 2), (0, 1, 2))
    scores = []
    for candidate in CANDIDATES:
        losses = []; by_fold = []
        for fold in range(FOLDS):
            fitting = [r for r, f in zip(rows, folds) if f != fold]
            held = [r for r, f in zip(rows, folds) if f == fold]
            counts = regularized_counts(fitting, classes, candidate)
            marginals = {}
            for w, mass in zip(product(range(classes), repeat=4), counts):
                for subset in subsets:
                    key = tuple((v, w[v+1]) for v in subset)
                    value = marginals.setdefault(key, [0.]*classes)
                    value[w[0]] += mass
            fold_loss = []
            for row in held:
                value = 0.
                for subset in subsets:
                    masses = marginals[tuple((v, row[v+1]) for v in subset)]
                    value -= math.log(masses[row[0]] / sum(masses))/len(subsets)
                fold_loss.append(value)
            losses.extend(fold_loss)
            by_fold.append({'fold': fold, 'fitting_rows': len(fitting), 'held_rows': len(held),
                            'mean_conditional_log_loss': sum(fold_loss)/len(fold_loss)})
        scores.append({'candidate': candidate, 'mean_conditional_log_loss': sum(losses)/len(losses),
                       'folds': by_fold})
    # Grid order deterministically breaks exact ties, preferring the legacy model.
    selected = min(scores, key=lambda r: r['mean_conditional_log_loss'])['candidate']
    report = {'schema': 'hepta.acquisition.kernel-cv.v1', 'profile': SUPPORTED_KERNEL,
              'scores': scores, 'selected': selected, 'source_folds': list(zip(source_hashes, folds)),
              'fit_tuples_sha256': digest(rows), 'sources_sha256': digest(source_hashes),
              'selection_criterion': 'mean_label_log_loss_four_history_subsets',
              'test_labels_used': False, 'prior_mass_is_observation_count': False}
    return regularized_counts(rows, classes, selected), report


def support_summary(fit_rows, records, labels, kernel):
    """Post-scoring diagnosis; never used to revise the selected law or policy."""
    bins = {'zero': [], 'one_to_four': [], 'five_plus': []}
    for record in records:
        history = tuple(tuple(p) for p in record['decisions'][-1]['history'])
        count = sum(all(r[v+1] == symbol for v, symbol in history) for r in fit_rows)
        belief = kernel.distribution(history)[1]; label = labels[record['id']]
        brier = sum((q-(j == label))**2 for j, q in enumerate(belief))/len(belief)
        loss = -math.log(belief[label])
        bins['zero' if count == 0 else 'one_to_four' if count < 5 else 'five_plus'].append((count, loss, brier))
    return {name: {'cases': len(rows), 'minimum_raw_support': min((r[0] for r in rows), default=None),
                   'mean_log_loss': sum(r[1] for r in rows)/len(rows) if rows else None,
                   'mean_brier': sum(r[2] for r in rows)/len(rows) if rows else None}
            for name, rows in bins.items()}
