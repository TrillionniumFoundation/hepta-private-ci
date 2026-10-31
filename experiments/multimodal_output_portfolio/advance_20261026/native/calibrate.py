"""Fit frozen monotone operation confidence on old-source public feature caches.

Labels are read only in this offline fitting/scoring program. Native online
requests contain public features and real external observations, never labels.
"""

import argparse
import hashlib
import json
import math
from pathlib import Path

import numpy as np

from .common import sha, write

Q = 1 << 24
CUTS = np.array([.01, .05, .1, .25, .5, .75, .9])


def quantize(array):
    array = np.asarray(array, dtype=np.float64) * Q
    return (np.sign(array) * np.floor(np.abs(array) + .5)).astype(np.int64)


def posterior(export, features, raw, text_mask):
    """Q24 parity reference for actual native MLP, with a literal text bypass."""
    x = quantize(features) / Q
    r = quantize(raw) / Q
    state = export['state_dict']
    h = np.tanh(x @ np.asarray(state['first.weight']).T + np.asarray(state['first.bias']))
    logit = np.log(np.maximum(r, export['raw_probability_floor'])) + export['residual_bound'] * np.tanh(
        h @ np.asarray(state['last.weight']).T + np.asarray(state['last.bias']))
    p = np.exp(logit - logit.max(-1, keepdims=True))
    p /= p.sum(-1, keepdims=True)
    p[np.asarray(text_mask, dtype=bool)] = r[np.asarray(text_mask, dtype=bool)]
    law = (p[:, 0, :, None] * p[:, 1, None, :]).reshape(-1, 100)
    return law / law.sum(-1, keepdims=True)


def fit_curve(raw, outcome):
    index = np.searchsorted(CUTS, np.clip(raw, 0, 1), side='right').ravel()
    labels = np.asarray(outcome, dtype=np.float64).ravel()
    counts = np.bincount(index, minlength=8)
    successes = np.bincount(index, weights=labels, minlength=8)
    # Weighted pool-adjacent-violators on observed fixed bins. Empty bins carry
    # the preceding supported probability; below the first observed bin use 0.
    blocks = []
    for i in range(8):
        if not counts[i]:
            continue
        blocks.append(([i], float(successes[i]), int(counts[i])))
        while len(blocks) > 1 and blocks[-2][1] / blocks[-2][2] > blocks[-1][1] / blocks[-1][2]:
            right, left = blocks.pop(), blocks.pop()
            blocks.append((left[0] + right[0], left[1] + right[1], left[2] + right[2]))
    values = np.full(8, np.nan)
    for ids, success, count in blocks:
        values[ids] = success / count
    previous = 0.
    for i, value in enumerate(values):
        if np.isnan(value): values[i] = previous
        else: previous = value
    return {'cuts': CUTS.tolist(), 'probabilities': values.tolist(),
            'bin_counts': counts.tolist(), 'bin_successes': successes.tolist(),
            'fit': 'predeclared fixed-bin weighted PAV; empty bins previous supported value or zero'}


def calibrated(raw, curve):
    p = np.asarray(curve['probabilities'])[np.searchsorted(CUTS, np.clip(raw, 0, 1), side='right')]
    q = np.floor(p * Q + .5).astype(np.int64)
    return (1_000_000 - np.minimum(np.abs(Q - q) * 1_000_000 // Q, 1_000_000)) / 1e6


def ece(probability, outcome):
    p, y = np.asarray(probability).ravel(), np.asarray(outcome).ravel()
    if not len(p): return None
    # Each realized mapped confidence is a calibration bin, without hiding
    # between-bin error by a second arbitrary equal-width regrouping.
    return sum(np.count_nonzero(p == v) / len(p) * abs(float(y[p == v].mean()) - float(v))
               for v in np.unique(p))


def load(directory):
    import torch
    torch.set_num_threads(1)
    data = torch.load(Path(directory) / 'features.pt', map_location='cpu', weights_only=True)
    source = json.loads((Path(directory) / 'SOURCES.json').read_text())
    if source['role'] not in ('train', 'development') or source['new_confirmation_sources_opened']:
        raise ValueError('Only frozen old fitting/development sources may calibrate this model')
    return {key: value.numpy() for key, value in data.items()}, source


def acquisitions(laws, data, source, likelihood, emit_curve):
    rows = source['cases_identity']
    audio = {row['pair']: i for i, row in enumerate(rows) if row['route'] == 'audio'}
    result = []
    factor, reject = math.exp(.004), math.exp(2.)
    for i, row in enumerate(rows):
        if row['route'] not in ('image', 'video'): continue
        a = audio[row['pair']]
        if rows[a]['image_source_ids'] != row['image_source_ids']:
            raise ValueError('External audio must be paired with the same old target sources')
        prior = laws[i]
        joint = likelihood * prior[None, :]
        mass = joint.sum(1)
        post = np.divide(joint, mass[:, None], out=np.zeros_like(joint), where=mass[:, None] > 0)
        maximum = post.max(1)
        allowed = calibrated(maximum, emit_curve) >= .75
        # Identity U/K was measured with the actual renderer and checked below.
        moments = np.where(allowed, factor * (1 - (1 - math.exp(-2)) * maximum), reject)
        p_acquire = float(np.sum(mass * maximum * allowed))
        m_acquire = float(np.sum(mass * factor * moments))
        actual = data['raw_probabilities'][a].argmax(-1)
        observed = int(actual[0] * 10 + actual[1])
        chosen = int(post[observed].argmax()) if allowed[observed] else -1
        success = int(chosen == int(data['target_codes'][i]))
        result.append({'index': i, 'raw': p_acquire, 'moment': m_acquire,
                       'actual_source_cnn_label': observed, 'continuation': chosen, 'success': success})
    return result


def evaluate(laws, data, source, curve, acquisition, acquire_curve):
    target = data['target_codes']
    truth = np.eye(100, dtype=np.float64)[target]
    probabilities = calibrated(laws, curve)
    code = laws.argmax(1)
    p = probabilities[np.arange(len(code)), code]
    selected = p >= .75
    selected_y = (code == target).astype(float)
    acquire_selected = []
    ac_p, ac_y = [], []
    for row in acquisition:
        i = row['index']
        ap = float(calibrated(row['raw'], acquire_curve))
        immediate = math.exp(.004) * (1 - (1 - math.exp(-2)) * laws[i, code[i]])
        choose = ap >= .75 and (not selected[i] or row['moment'] < immediate)
        ac_p.append(ap); ac_y.append(row['success'])
        acquire_selected.append(choose)
        if choose:
            p[i], selected_y[i], selected[i] = ap, row['success'], True
    return {'rows': len(laws), 'pooled_candidate_ece': ece(probabilities, truth),
            'selected_action_ece': ece(p[selected], selected_y[selected]),
            'ID_request_coverage': float(selected.mean()),
            'selected_action_success': float(selected_y[selected].mean()) if selected.any() else None,
            'candidate_admission_coverage': float((probabilities >= .75).mean()),
            'acquire_operation_ece': ece(ac_p, ac_y), 'acquire_chosen': int(sum(acquire_selected)),
            'initial_emit_selected_count': int((probabilities[np.arange(len(code)), code] >= .75).sum())}


def run(args):
    out = args.output
    out.mkdir(parents=True, exist_ok=False)
    export = json.loads(args.weights.read_text())
    utility = np.asarray(export['utility_action_by_target'])
    strict = np.asarray(export['strict_success_action_by_target'])
    if not np.array_equal(utility, np.eye(100)) or not np.array_equal(strict, np.eye(100)):
        raise ValueError('This fast calibration is scoped to the measured identity endpoint table')
    likelihood = np.asarray(json.loads(args.likelihood.read_text())['pair_observation_by_target'])
    fit, fit_source = load(args.fit)
    dev, dev_source = load(args.development)
    fit_law = posterior(export, fit['features'], fit['raw_probabilities'], fit['text_mask'])
    dev_law = posterior(export, dev['features'], dev['raw_probabilities'], dev['text_mask'])
    emit = fit_curve(fit_law, np.eye(100)[fit['target_codes']])
    fit_acquire = acquisitions(fit_law, fit, fit_source, likelihood, emit)
    acquire = fit_curve([r['raw'] for r in fit_acquire], [r['success'] for r in fit_acquire])
    # There is no retained-bundle stop action in this initial exact two-stage schema.
    stop = {'cuts': CUTS.tolist(), 'probabilities': [0.] * 8, 'supported': False}
    calibration = {'schema': 'hepta.advance.operation-confidence.v1', 'roles': {'emit': emit, 'acquire': acquire, 'stop': stop},
        'weights_sha256': sha(args.weights), 'likelihood_sha256': sha(args.likelihood),
        'fit_features_sha256': sha(args.fit / 'features.pt'), 'fit_source_sha256': sha(args.fit / 'SOURCES.json'),
        'new_confirmation_used': False, 'explicit_missing_probability': 0., 'operation_curves_monotone': True}
    write(out / 'calibration.json', calibration)
    dev_acquire = acquisitions(dev_law, dev, dev_source, likelihood, emit)
    report = {'schema': 'hepta.advance.old-development-calibration.v1',
        'calibration_sha256': sha(out / 'calibration.json'), 'weights_sha256': sha(args.weights),
        'fit': evaluate(fit_law, fit, fit_source, emit, fit_acquire, acquire),
        'old_development': evaluate(dev_law, dev, dev_source, emit, dev_acquire, acquire),
        'independent_qualification': False, 'old_development_previously_used_for_selection': True,
        'source_speech_labels_are_raw_frozen_CNN_argmax': True, 'endpoint_identity_is_measured_not_assumed': True}
    write(out / 'REPORT.json', report)
    np.savez_compressed(out / 'old-development-public.npz', features=quantize(dev['features']),
        raw_probabilities=quantize(dev['raw_probabilities']), text_mask=dev['text_mask'], law=dev_law)
    write(out / 'old-development-offline-labels.json', {'labels': dev['target_codes'].tolist(),
        'source': dev_source, 'not_an_online_input': True, 'acquisitions': dev_acquire})
    print(json.dumps(report))


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    for name in ('weights', 'likelihood', 'fit', 'development', 'output'):
        p.add_argument('--' + name, type=Path, required=True)
    run(p.parse_args())
