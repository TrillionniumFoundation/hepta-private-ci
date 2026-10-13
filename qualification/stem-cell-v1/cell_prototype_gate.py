"""Training-only class geometry for a frozen-specialist gate, research candidates.

No Encoder, owner, deployment authority or persistent routing cache. The
reference teachers stay frozen. Prototypes are fitted to original train groups;
class labels and old/new membership are not supplied at prediction time.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import math
import time

import torch
from torch.nn import functional as F

from cell_anchor_consolidation import fold_film
from cell_consolidation import training_partition
from development_tensors import checked_tensor

SHRINKAGES = (0.1, 1.0)
TEMPERATURES = (1.0, 4.0, 16.0, 64.0)
FOLDS = 4
ARMS = ('prototype_memory', 'prototype_all_old', 'geometry_memory', 'geometry_all_old')


@dataclass(frozen=True)
class JointFloor:
    """Additional empirical usefulness floors; not a statistical certificate."""
    minimum_new_accuracy: float = .90
    minimum_each_new_accuracy: float = .80
    maximum_each_new_brier: float = .20

    def validate(self):
        for name, high in (('minimum_new_accuracy', 1), ('minimum_each_new_accuracy', 1),
                           ('maximum_each_new_brier', 2)):
            v = getattr(self, name)
            if type(v) not in (float, int) or not math.isfinite(v) or not 0 <= v <= high:
                raise ValueError('invalid joint-usefulness floor')
        return self


def joint_select(scores, config, floor=JointFloor()):
    """Do not admit an almost-frozen model solely for tiny positive new gain."""
    config.validate(); floor.validate()
    if type(scores) is not dict or 'frozen' not in scores:
        raise ValueError('frozen reference required')
    reference = scores['frozen']; checks = {}; eligible = []
    for name, s in scores.items():
        if type(name) is not str or not name or set(s['per_class']) != set(map(str, range(config.classes))):
            raise ValueError('invalid paired class census')
        for c in (s['old'], s['new'], *s['per_class'].values()):
            if (any(type(c[k]) not in (float, int) or not math.isfinite(c[k]) for k in ('accuracy', 'brier'))
                    or not 0 <= c['accuracy'] <= 1 or not 0 <= c['brier'] <= 2):
                raise ValueError('invalid joint metric')
        retained = all(s['per_class'][str(k)]['accuracy'] >= reference['per_class'][str(k)]['accuracy']-config.maximum_old_accuracy_drop
            and s['per_class'][str(k)]['brier'] <= reference['per_class'][str(k)]['brier']+config.maximum_old_brier_increase for k in config.old_classes)
        useful = s['new']['accuracy'] >= floor.minimum_new_accuracy and all(
            s['per_class'][str(k)]['accuracy'] >= floor.minimum_each_new_accuracy
            and s['per_class'][str(k)]['brier'] <= floor.maximum_each_new_brier
            for k in range(config.classes) if k not in config.old_classes)
        qualified = retained and useful and s['new']['accuracy'] > reference['new']['accuracy']
        checks[name] = {'old_retained': retained, 'new_useful': useful, 'qualified': qualified}
        if qualified: eligible.append(name)
    selected = min(eligible, key=lambda n: (scores[n]['old']['brier']+scores[n]['new']['brier'], n)) if eligible else 'frozen'
    return {'selected': selected, 'qualified': bool(eligible), 'checks': checks,
            'floor': asdict(floor), 'statistical_superiority_established': False, 'production_authorized': False}


def training_folds(labels, groups, classes):
    """Place an entire source group in one deterministic, class-stratified fold."""
    if (type(groups) not in (list, tuple) or not isinstance(labels, torch.Tensor)
            or labels.dtype != torch.long or labels.device.type != 'cpu'
            or labels.shape != (len(groups),) or not 1 <= len(groups) <= 4096
            or type(classes) is not int or not 4 <= classes <= 16):
        raise ValueError('invalid grouped training rows')
    by_group = {}
    for i, (y, g) in enumerate(zip(labels.tolist(), groups)):
        if type(g) is not str or not g or len(g) > 512 or not 0 <= y < classes:
            raise ValueError('invalid training group or class')
        if g in by_group and by_group[g][0] != y: raise ValueError('conflicting training-group labels')
        by_group.setdefault(g, (y, []))[1].append(i)
    assignments = torch.empty(len(groups), dtype=torch.long)
    for y in range(classes):
        gs = sorted((g for g, (c, _) in by_group.items() if c == y), key=lambda g: (hashlib.sha256(g.encode()).hexdigest(), g))
        if len(gs) < FOLDS: raise ValueError('insufficient training groups for four-fold geometry')
        for j, g in enumerate(gs): assignments[by_group[g][1]] = j % FOLDS
    return assignments


def geometry_fit(x, labels, groups, classes, shrinkage):
    """Equal-class, equal-source pooled diagonal covariance, no evaluation rows."""
    checked_tensor(x, 2, 'prototype fitting features')
    if x.dtype != torch.float32 or not 1 <= x.shape[1] <= 512 or len(x) != len(groups):
        raise ValueError('invalid geometry features')
    training_folds(labels, groups, classes)  # Validates support, identity and labels.
    if shrinkage not in SHRINKAGES or type(shrinkage) is not float: raise ValueError('unregistered shrinkage')
    xx = x.detach().double(); means = []; variances = []
    for y in range(classes):
        buckets = {}
        for i, (label, group) in enumerate(zip(labels.tolist(), groups)):
            if label == y: buckets.setdefault(group, []).append(i)
        # Sorting makes duplicate-row and input-order behavior deterministic.
        values = torch.stack([xx[buckets[g]].mean(0) for g in sorted(buckets)])
        mu = values.mean(0); means.append(mu); variances.append((values-mu).square().mean(0))
    means = torch.stack(means); center = means.mean(0)
    pooled = torch.stack(variances).mean(0)
    variance = ((1-shrinkage)*pooled+shrinkage*pooled.mean()).clamp_min(1e-8)
    delta = means-center
    weight = delta/variance
    bias = -.5*(delta*weight).sum(1)
    if any(not torch.isfinite(v).all() for v in (weight, bias, center)):
        raise ValueError('nonfinite fitted geometry')
    return weight, bias, center


def fit_geometry_candidates(inputs, truth, features, config, teachers):
    """Two replay budgets, each with its own training-only CV; no test selection."""
    start = time.process_time_ns(), time.perf_counter_ns()
    old, new, memory = training_partition(inputs, truth, config)
    checked_tensor(features, 2, 'raw geometry source')
    if features.dtype != torch.float32 or len(features) != len(inputs) or not 1 <= features.shape[1] <= 512:
        raise ValueError('invalid source features')
    d, k = features.shape[1], config.classes
    if set(teachers) != {'frozen', 'new_only'}: raise ValueError('exact frozen teachers required')
    experts = fold_film(teachers['new_only'], d, k).float()
    experts[list(config.old_classes)] = fold_film(teachers['frozen'], d, k).float()[list(config.old_classes)]
    mean = features[old].mean(0); scale = features[old].std(0, unbiased=False).clamp_min(1e-6)
    candidates, reports = {}, {}
    for suffix, replay in (('memory', memory), ('all_old', old)):
        before = time.process_time_ns(), time.perf_counter_ns()
        ids = replay+new; x = features[ids].detach().clone()
        y = torch.tensor([truth[inputs[i]['sample_id']] for i in ids])
        groups = [inputs[i]['source_group'] for i in ids]; folds = training_folds(y, groups, k)
        grid = []
        for shrinkage in SHRINKAGES:
            # Cross-validation uses only this arm's training rows and recomputes all statistics.
            held_scores = torch.empty(len(x), k, dtype=torch.float64)
            for f in range(FOLDS):
                fit = (folds != f).nonzero().flatten().tolist(); val = (folds == f).nonzero().flatten().tolist()
                w, b, center = geometry_fit(x[fit], y[fit], [groups[i] for i in fit], k, shrinkage)
                held_scores[val] = (x[val].double()-center)@w.T+b
            for temperature in TEMPERATURES:
                raw = held_scores/temperature; old_cols = list(config.old_classes)
                new_cols = [i for i in range(k) if i not in old_cols]
                g = torch.logsumexp(raw[:, new_cols], -1)-torch.logsumexp(raw[:, old_cols], -1)
                target = torch.tensor([c not in old_cols for c in y.tolist()], dtype=torch.float64)
                losses = F.binary_cross_entropy_with_logits(g, target, reduction='none')
                class_losses = []
                for c in range(k):
                    gs = sorted({groups[i] for i in range(len(y)) if int(y[i]) == c})
                    class_losses.append(sum(float(losses[[i for i, gg in enumerate(groups) if gg == g0]].mean()) for g0 in gs)/len(gs))
                score = sum(class_losses)/k
                if not math.isfinite(score): raise ValueError('nonfinite CV loss')
                grid.append({'shrinkage': shrinkage, 'temperature': temperature, 'group_balanced_binary_log_loss': score})
        chosen = min(range(len(grid)), key=lambda i: (grid[i]['group_balanced_binary_log_loss'], i))
        row = grid[chosen]; w, b, center = geometry_fit(x, y, groups, k, row['shrinkage'])
        # Fold raw-space geometry into the existing old-only-normalized coordinates.
        routing_w = (w*scale.double()/row['temperature']).float()
        routing_b = (b+w@(mean.double()-center)).div(row['temperature']).float()
        if any(not torch.isfinite(v).all() for v in (routing_w, routing_b)): raise ValueError('nonfinite packed geometry')
        candidates[suffix] = {'weight': experts[:, :-1].contiguous().clone(), 'bias': experts[:, -1].contiguous().clone(),
                             'routing_weight': routing_w, 'routing_bias': routing_b}
        reports[suffix] = {'grid': grid, 'selected': chosen, 'training_indices': ids,
            'folds': folds.tolist(), 'statistics_fits': len(SHRINKAGES)*FOLDS+1,
            'cv_prediction_rows': len(x)*len(SHRINKAGES)*len(TEMPERATURES),
            'training_feature_rows': len(x), 'replay_feature_bytes': len(replay)*d*4,
            'conditional_parameters': 2*k*(d+1), 'conditional_weight_bytes': 2*k*(d+1)*4,
            'standalone_parameters': k*(d+1), 'standalone_weight_bytes': k*(d+1)*4,
            'optimizer_steps': 0, 'cpu_ns': time.process_time_ns()-before[0], 'wall_ns': time.perf_counter_ns()-before[1]}
    return candidates, mean, scale, {'arms': reports, 'current_encoder_calls': 0,
        'cpu_ns': time.process_time_ns()-start[0], 'wall_ns': time.perf_counter_ns()-start[1]}


def geometry_logits(tensors, x, config, *, conditional):
    """Group marginal probabilities from multiple prototypes, without a task ID."""
    checked_tensor(x, 2, 'geometry inference features'); config.validate()
    if type(conditional) is not bool or x.dtype != torch.float32 or not 1 <= x.shape[1] <= 512 or len(x)>4096:
        raise ValueError('invalid geometry prediction')
    shapes = {'routing_weight': (config.classes, x.shape[1]), 'routing_bias': (config.classes,)}
    if conditional: shapes.update(weight=(config.classes, x.shape[1]), bias=(config.classes,))
    if type(tensors) is not dict or set(tensors)!=set(shapes): raise ValueError('invalid geometry tensor census')
    for n,v in tensors.items():
        if not isinstance(v,torch.Tensor) or v.device.type!='cpu' or v.dtype!=x.dtype or tuple(v.shape)!=shapes[n] or not torch.isfinite(v).all():
            raise ValueError('invalid geometry tensor')
    raw = x@tensors['routing_weight'].T+tensors['routing_bias']
    if not torch.isfinite(raw).all(): raise ValueError('nonfinite geometry scores')
    if not conditional: return raw
    experts = x@tensors['weight'].T+tensors['bias']
    old = list(config.old_classes); new = [i for i in range(config.classes) if i not in old]
    masses = torch.stack([torch.logsumexp(raw[:,cols],-1) for cols in (old,new)],1)
    masses = F.log_softmax(masses,1); out = torch.empty_like(raw)
    for j,cols in enumerate((old,new)):
        q = F.log_softmax(experts[:,cols],-1); out[:,cols] = q+masses[:,j,None]
        if not torch.isfinite(out[:,cols]).all() or float((F.log_softmax(out[:,cols],-1)-q).abs().max())>1e-4:
            raise ValueError('conditional odds lost')
    return out
