"""Promote evidence models by protected deployment outcomes, not density alone."""

import hashlib
import json

import numpy as np


FIELDS = ('conditional_nll', 'posterior_nll', 'map_accuracy', 'mean_utility', 'risk_moment')


def decisions(probabilities):
    probabilities = np.asarray(probabilities, dtype=float)
    if (probabilities.ndim != 2 or not np.isfinite(probabilities).all()
            or np.any(probabilities < 0) or not np.allclose(probabilities.sum(1), 1, rtol=0, atol=1e-10)):
        raise ValueError('Only normalized posterior distributions are deployable')
    label = probabilities.argmax(1)
    confidence = probabilities.max(1)
    none = probabilities.shape[1]
    mean = np.where(confidence*.99+(1-confidence)*(-.51) > -.003, label, none)
    risk = np.where(confidence*np.exp(-1.98)+(1-confidence)*np.exp(1.02) < np.exp(.006), label, none)
    return label, mean, risk


def summarize(name, likelihood, posterior, targets, sources, sample_ids, actual_actions):
    """Private validation truth enters only after prediction and text readback."""
    target = np.asarray(targets, dtype=int)
    label, mean, risk = [np.asarray(values, dtype=int) for values in actual_actions]
    if len(target) != len(set(sample_ids)) or len(target) != len(sources):
        raise ValueError('A complete unique paired validation panel is required')
    expected = decisions(posterior)
    if any(not np.array_equal(a, b) for a, b in zip(actual_actions, expected)):
        raise ValueError('Readback differs from the frozen public-input decision')
    reject = posterior.shape[1]
    mean_u = np.where(mean == reject, -.003, np.where(mean == target, .99, -.51))
    risk_u = np.where(risk == reject, -.003, np.where(risk == target, .99, -.51))
    rows = np.column_stack((-np.log(likelihood[np.arange(len(target)), target]),
                            -np.log(posterior[np.arange(len(target)), target]),
                            label == target, mean_u, np.exp(-2*risk_u)))
    by_source, counts = {}, {}
    for source in sorted(set(sources)):
        selected = np.array([value == source for value in sources])
        counts[source] = int(selected.sum())
        by_source[source] = dict(zip(FIELDS, rows[selected].mean(0).tolist()))
    if len(by_source) < 2:
        raise ValueError('The protected selector requires multiple validation sources')
    means = {field: float(np.mean([value[field] for value in by_source.values()])) for field in FIELDS}
    means['risk_ce'] = float(-np.log(means['risk_moment'])/2)
    panel = list(zip(sample_ids, sources, map(int, target)))
    return {'name': name, 'case_sha256': hashlib.sha256(json.dumps(panel, separators=(',', ':')).encode()).hexdigest(),
            'source_counts': counts, 'by_source': by_source, 'means': means}


def protection(candidate, baseline):
    if (candidate['case_sha256'] != baseline['case_sha256']
            or candidate['source_counts'] != baseline['source_counts']):
        return {'eligible': False, 'reasons': ['Validation panels differ'], 'differences': {}}
    sources = sorted(baseline['by_source'])
    if set(candidate['by_source']) != set(sources):
        return {'eligible': False, 'reasons': ['Validation source groups differ'], 'differences': {}}
    indices = np.random.default_rng(272037).integers(len(sources), size=(20000, len(sources)))
    deltas, reasons = {}, []
    for metric in ('posterior_nll', 'map_accuracy', 'mean_utility', 'risk_ce'):
        key = 'risk_moment' if metric == 'risk_ce' else metric
        first = np.array([candidate['by_source'][source][key] for source in sources])
        second = np.array([baseline['by_source'][source][key] for source in sources])
        if not np.isfinite(first).all() or not np.isfinite(second).all() or (key == 'risk_moment' and np.any(first <= 0)):
            reasons.append(f'Invalid {metric} validation record')
            continue
        values = ((np.log(second[indices].mean(1))-np.log(first[indices].mean(1)))/2
                  if key == 'risk_moment' else (first-second)[indices].mean(1))
        lower, upper = np.quantile(values, [.0125, .9875])
        deltas[metric] = {'difference': candidate['means'][metric]-baseline['means'][metric],
                         'paired_source_ci97_5': [float(lower), float(upper)]}
        if (upper > 1e-12) if metric == 'posterior_nll' else (lower < -1e-12):
            reasons.append(f'{metric} baseline protection not established')
    return {'eligible': not reasons, 'reasons': reasons, 'differences': deltas,
            'conditional_nll_diagnostic': candidate['means']['conditional_nll']-baseline['means']['conditional_nll']}


def select(candidates, baseline_name):
    if len({row['name'] for row in candidates}) != len(candidates):
        raise ValueError('Candidate identities must be unique')
    baselines = [row for row in candidates if row['name'] == baseline_name]
    if len(baselines) != 1:
        raise ValueError('Exactly one declared unchanged baseline is required')
    baseline = baselines[0]
    decisions_by_name = {row['name']: protection(row, baseline) for row in candidates}
    if not decisions_by_name[baseline_name]['eligible']:
        raise ValueError('Invalid baseline validation panel')
    eligible = [row for row in candidates if decisions_by_name[row['name']]['eligible']]
    chosen = min(eligible, key=lambda row: (-round(row['means']['risk_ce'], 12),
                                          round(row['means']['posterior_nll'], 12),
                                          row['name'] != baseline_name, row['name']))
    return {'baseline': baseline_name, 'selected': chosen['name'], 'unchanged_baseline_selected': chosen['name'] == baseline_name,
            'admission': decisions_by_name,
            'rule': 'Paired-source posterior-log-score, MAP, mean-return and risk-CE protection; eligible models maximize validation risk CE, then proper posterior score; baseline wins exact ties.',
            'conditional_nll_alone_can_promote': False, 'new_source_generalization_established': False,
            'validation_scope': 'Historical-source development only; these intervals are conservative model-selection diagnostics, not new qualification evidence.'}
