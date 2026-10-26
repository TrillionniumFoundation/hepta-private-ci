"""Small regularized paired heads with future admission/rejection in the backup.

Only value heads are source-fold fitted. The separately frozen admission model
is part of the supplied environment and previously used some old fit sources;
these development folds are not an independent qualification of that model.
"""

from dataclasses import dataclass
import math

import numpy as np

from .features import DIM


GAMMA, ACTION_COST, REJECTION_UTILITY = 2., .002, -1.
RIDGES = (.001, .01, .1)
LOWER, UPPER = math.exp(-2.), math.exp(2.008)


@dataclass
class Head:
    mean: np.ndarray
    scale: np.ndarray
    weight: np.ndarray
    bias: np.ndarray

    def predict(self, x):
        x = np.asarray(x, dtype=np.float64)
        if x.ndim != 2 or x.shape[1] != DIM or not np.isfinite(x).all():
            raise ValueError('Invalid compact public inputs')
        paired = ((x - self.mean) / self.scale) @ self.weight.T + self.bias
        absolute = paired.copy()
        absolute[:, 1:] += paired[:, :1]
        return np.clip(absolute, LOWER, UPPER)

    def export(self):
        weight = self.weight / self.scale
        bias = self.bias - weight @ self.mean
        # Encode absolute moments with one affine map and a positive bound.
        weight[1:] += weight[:1]
        bias[1:] += bias[:1]
        return {'weight': weight.tolist(), 'bias': bias.tolist(),
                'activation': 'clamp', 'minimum': LOWER, 'maximum': UPPER}


def fit_head(x, absolute, ridge):
    x, absolute = np.asarray(x, dtype=np.float64), np.asarray(absolute, dtype=np.float64)
    if x.shape != (len(absolute), DIM) or absolute.shape[1:] != (5,):
        raise ValueError('Complete five-action paired outcomes required')
    target = absolute.copy()
    target[:, 1:] -= target[:, :1]
    mean, scale = x.mean(0), x.std(0)
    scale = np.where(scale > 1e-6, scale, 1.)
    nx = (x - mean) / scale
    bias = target.mean(0)
    gram = nx.T @ nx + ridge * len(x) * np.eye(DIM)
    weight = np.linalg.solve(gram, nx.T @ (target - bias)).T
    return Head(mean, scale, weight, bias)


def choose(predicted, admitted, *, remaining_decisions=1):
    predicted, admitted = np.asarray(predicted), np.asarray(admitted, dtype=bool)
    if predicted.shape != admitted.shape or predicted.ndim != 2 or predicted.shape[1] != 5:
        raise ValueError('Predictions and actual feasible sets must have five actions')
    if remaining_decisions < 1:
        return np.full(len(predicted), -1, dtype=np.int64)
    masked = np.where(admitted, predicted, np.inf)
    selected = masked.argmin(1)
    return np.where(admitted.any(1), selected, -1)


def terminal_tables(utility):
    utility = np.asarray(utility, dtype=np.float64)
    if utility.ndim != 2 or utility.shape[1] != 21 or not np.isfinite(utility).all():
        raise ValueError('The real 21-endpoint finite tree is required')
    values = np.empty((len(utility), 5, 5))
    values[:, 0] = utility[:, :5]
    for node in range(1, 5):
        values[:, node, 0] = utility[:, node]
        values[:, node, 1:] = utility[:, 5 + (node - 1) * 4:9 + (node - 1) * 4]
    return np.exp(-GAMMA * (values - np.array([0., ACTION_COST, ACTION_COST, ACTION_COST, ACTION_COST])))


def selected_terminal(actual, choices):
    chosen = actual[np.arange(len(actual)), np.maximum(choices, 0)]
    return np.where(choices >= 0, chosen, math.exp(-GAMMA * REJECTION_UTILITY))


def fit(x, admitted, terminal, cases, ridge):
    """Cross-fit the future H1 choice, then score its actual outcome or rejection."""
    folds = np.asarray(cases) % 2
    if x.shape[1:] != (5, DIM) or admitted.shape != terminal.shape or terminal.shape[1:] != (5, 5):
        raise ValueError('Complete root and four child public states are required')
    targets = np.empty((len(x), 5))
    targets[:, 0] = terminal[:, 0, 0]
    choices = np.empty((len(x), 4), dtype=np.int64)
    oof = np.empty_like(terminal)
    fold_rows = []
    for held in (0, 1):
        train, test = folds != held, folds == held
        head = fit_head(x[train].reshape(-1, DIM), terminal[train].reshape(-1, 5), ridge)
        oof[test] = head.predict(x[test].reshape(-1, DIM)).reshape(-1, 5, 5)
        future = choose(oof[test, 1:].reshape(-1, 5), admitted[test, 1:].reshape(-1, 5))
        choices[test] = future.reshape(-1, 4)
        actual = selected_terminal(terminal[test, 1:].reshape(-1, 5), future).reshape(-1, 4)
        targets[test, 1:] = math.exp(GAMMA * ACTION_COST) * actual
        fold_rows.append({'held': held, 'fit_source_pairs': len(set(np.asarray(cases)[train])),
                          'held_source_pairs': len(set(np.asarray(cases)[test])),
                          'actual_future_no_admitted_rejections': int((future < 0).sum())})
    one = fit_head(x.reshape(-1, DIM), terminal.reshape(-1, 5), ridge)
    two = fit_head(x[:, 0], targets, ridge)
    return Policy(one, two), {'folds': fold_rows, 'OOF_predictions': oof,
        'root_actual_policy_targets': targets, 'fold_future_choices': choices}


@dataclass
class Policy:
    one: Head
    two: Head

    def predict(self, x, remaining, *, remaining_decisions=None):
        if remaining not in (1, 2):
            raise ValueError('Only original H1/H2 supported')
        prediction = (self.one if remaining == 1 else self.two).predict(x)
        if remaining == 2 and remaining_decisions == 1:
            prediction[:, 1:] = math.exp(GAMMA * (ACTION_COST - REJECTION_UTILITY))
        return prediction

    def export(self):
        return {'schema': 'hepta.advance.admission-aware-paired-moments.v1',
                'gamma': GAMMA, 'action_cost': ACTION_COST, 'rejection_utility': REJECTION_UTILITY,
                'feature_width': DIM, 'heads': [self.one.export(), self.two.export()],
                'future_constraints': 'fixed correctness admission and no-admitted rejection; explicit remaining-decision exhaustion',
                'resource_law': 'No calibrated stochastic resource-tail model; actual native mask still authoritative',
                'production_authority': False}
