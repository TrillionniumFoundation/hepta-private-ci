"""E16: answer-contrastive 5-parameter Student, no source/answer authorization.

Physically executes 48 SGD steps on a 3-passage training-only label artifact.
All original Reader logits come from immutable E14 pretrained research data.
The held passage contributes UNLABELLED candidate feature vectors only.
This is a research-only, retrospective estimator (DENY_ALL).
"""
from __future__ import annotations

import argparse
from hashlib import sha256
import json
from math import exp, isfinite
from pathlib import Path
from time import process_time_ns

from e14_multirc_route import read_prelabel, write_once, strict_json, ARCHIVE_SHA, OBS_ID
from e15_reader_crossfit import (verify_train, groups, observations, sigmoid,
                                STEPS, LR, L2, TRAIN_SCHEMA, digest)

SCHEMA = 'hepta.e16.answer-centered-real-logits.v1'
METHODS = ('centered_raw_5', 'centered_scaled_5')
TRAINED_PARAMETERS = 5
FLOAT_BOUND = 128.0


def features(obs):
    """Question-wise centering uses ONLY complete unlabelled candidate slates."""
    records = observations(obs)
    by_q = {}
    for row in records:
        key = (row['source_group'], row['question_slot'])
        by_q.setdefault(key, []).append(row)
    if len(by_q) != 8 or any(not 2 <= len(v) <= 8 for v in by_q.values()):
        raise ValueError('missing genuine question answer slate')
    means = {k: tuple(sum(r['raw'][j] for r in v) / len(v) for j in range(1, 5))
             for k, v in by_q.items()}
    result = []
    for row in records:
        mean = means[(row['source_group'], row['question_slot'])]
        centered = [row['raw'][j] - mean[j - 1] for j in range(1, 5)]
        # No-query has no answer sensitivity. Use a fixed nonlinear interaction
        # rather than pretending a constant Reader contributes new signal.
        vector = (centered[0], centered[1], centered[2], centered[1] * centered[2])
        if any(not isfinite(x) or abs(x) > FLOAT_BOUND for x in vector):
            raise ValueError('nonfinite/unbounded frozen Reader geometry')
        result.append({'task_id': row['task_id'], 'group': row['source_group'],
                       'question': row['question_slot'], 'candidate_id': row['candidate_id'],
                       'x': vector})
    return result


def scales(rows, train_ids):
    """Fold-specific normalization is trained only on three source groups."""
    if type(train_ids) is not set or not train_ids:
        raise ValueError('missing train group')
    train = [r for r in rows if r['task_id'] in train_ids]
    if len(train) != len(train_ids) or not 20 <= len(train) <= 30:
        raise ValueError('incomplete original training inputs')
    # Cap tiny dimensions rather than exploding 1e-10 Reader noise.
    return tuple(max(1e-5, max(abs(r['x'][j]) for r in train)) for j in range(4))


def design(row, method, units):
    if method not in METHODS or type(units) is not tuple or len(units) != 4:
        raise ValueError('unregistered feature profile')
    if any(type(u) is not float or not isfinite(u) or not 1e-5 <= u <= FLOAT_BOUND for u in units):
        raise ValueError('invalid training-only scale')
    x = row['x'] if method == METHODS[0] else tuple(a / b for a, b in zip(row['x'], units, strict=True))
    if len(x) != 4 or any(not isfinite(v) or abs(v) > FLOAT_BOUND for v in x):
        raise ValueError('invalid centered inputs')
    return (1.0,) + x


def train(rows, labels, method, units):
    if method not in METHODS or type(labels) is not dict:
        raise ValueError('unsupported Head')
    admitted = [(design(r, method, units), labels[r['task_id']])
                for r in rows if r['task_id'] in labels]
    if not 20 <= len(admitted) <= 30 or any(type(y) is not int or y not in (0, 1) for _, y in admitted):
        raise ValueError('missing train-only original human labels')
    weights = [0.0] * TRAINED_PARAMETERS
    started = process_time_ns()
    for _ in range(STEPS):
        grad = [0.0] * TRAINED_PARAMETERS
        for x, y in admitted:
            p = sigmoid(sum(a * b for a, b in zip(weights, x, strict=True)))
            derivative = 2 * (p - y) * p * (1 - p)
            for j, v in enumerate(x):
                grad[j] += derivative * v
        for j in range(TRAINED_PARAMETERS):
            weights[j] -= LR * (grad[j] / len(admitted) + (L2 * weights[j] if j else 0.0))
        if any(not isfinite(w) or abs(w) > FLOAT_BOUND for w in weights):
            raise ValueError('SGD nonfinite')
    cpu = process_time_ns() - started
    if cpu <= 0:
        raise ValueError('missing real training work')
    return weights, cpu


def predict(row, weights, method, units):
    if type(weights) is not list or len(weights) != TRAINED_PARAMETERS:
        raise ValueError('wrong parameter inventory')
    return sigmoid(sum(w * z for w, z in zip(weights, design(row, method, units), strict=True)))


def train_fold(obs, training_only):
    labels = verify_train(obs, training_only)
    rows = features(obs)
    held = [r for r in rows if r['group'] == training_only['held_group']]
    if not 3 <= len(held) <= 10 or set(r['task_id'] for r in held) & set(labels):
        raise ValueError('heldout boundary not enforced')
    units = scales(rows, set(labels))
    fitted = {}; meters = {}; probabilities = {}
    for method in METHODS:
        w, fit_cpu = train(rows, labels, method, units)
        started = process_time_ns()
        ps = [predict(r, w, method, units) for r in held]
        eval_cpu = process_time_ns() - started
        if eval_cpu <= 0 or any(not 0 < p < 1 for p in ps):
            raise ValueError('invalid held predictions')
        fitted[method] = w
        meters[method] = {'train_cpu_ns': fit_cpu, 'held_cpu_ns': eval_cpu,
                          'parameter_count': TRAINED_PARAMETERS, 'steps': STEPS}
        probabilities[method] = ps
    predictions = [{'task_id': r['task_id'], 'source_group': r['group'],
                    'question_slot': r['question'], 'candidate_id': r['candidate_id'],
                    'probabilities': {m: probabilities[m][i] for m in METHODS}}
                   for i, r in enumerate(held)]
    return {'schema': SCHEMA, 'authority': 'DENY_ALL', 'fold': training_only['fold'],
            'held_group': training_only['held_group'], 'original_archive_sha256': ARCHIVE_SHA,
            'original_observation_id': OBS_ID, 'train_only_material_sha256': digest(training_only),
            'train_only_past_groups': 3, 'train_only_scaling': list(units),
            'methods': list(METHODS), 'weights': fitted, 'meters': meters,
            'predictions': predictions, 'held_human_labels_accessed': False,
            'original_model_forwards_new': 0, 'physical_train_steps_completed': STEPS,
            'total_service_cost_measured': False, 'natural_future_task_gain': False,
            'reader_semantic_adequacy_proven': False, 'production_accepted': False}


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    for name in ('archive', 'train-only-material', 'output'):
        ap.add_argument('--' + name, required=True)
    args = ap.parse_args()
    obs = read_prelabel(args.archive)
    t = strict_json(Path(args.train_only_material).read_bytes())
    rec = train_fold(obs, t)
    print(write_once(args.output, rec), 'DENY_ALL')


if __name__ == '__main__':
    main()
