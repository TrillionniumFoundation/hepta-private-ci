"""Frozen conditional specialists plus a learned gate on ONE shared feature.

Training labels may identify old/new groups; inference never receives that truth.
This preserves within-group log odds in exact arithmetic, not overall retention.
No Encoder, runtime, durable routing service or model authority is introduced.
"""
from __future__ import annotations

from copy import deepcopy
import math
import time

import torch
from torch.nn import functional as F

from cell_anchor_consolidation import fold_film
from cell_consolidation import metrics, training_partition
from development_tensors import checked_tensor

GATE_ARMS = ("conditional_half", "conditional_concat", "gate_memory", "gate_all_old", "gate_score_memory")
LEARNED = GATE_ARMS[2:]
# Fixed before the first experiment; no held-out choice of shifts or grid size.
OFFSETS = (0., -1., -2., -4., -8., 1., 2., 4., 8.)
CONDITIONAL_TOLERANCE = 1e-4


def frozen_experts(teachers, width, config):
    """Fold selected FiLM rows once, discarding unused teacher output rows."""
    config.validate()
    if set(teachers) != {"frozen", "new_only"}:
        raise ValueError("exact old and new teachers required")
    old = fold_film(teachers['frozen'], width, config.classes).float()
    new = fold_film(teachers['new_only'], width, config.classes).float()
    selected = new.clone()
    selected[list(config.old_classes)] = old[list(config.old_classes)]
    checked_tensor(selected, 2, 'packed frozen specialists')
    return {'weight': selected[:, :-1].contiguous(), 'bias': selected[:, -1].contiguous()}


def expert_logits(tensors, x, config, *, gated):
    checked_tensor(x, 2, 'conditional features')
    config.validate()
    width = x.shape[1]
    shapes = {'weight': (config.classes, width), 'bias': (config.classes,)}
    if gated:
        shapes.update(gate_weight=((1,) if gated == 'score' else (width,)), gate_bias=(1,))
    if (x.dtype != torch.float32 or not 1 <= width <= 512 or len(x) > 4096
            or type(tensors) is not dict or set(tensors) != set(shapes)):
        raise ValueError('invalid conditional Head inventory/input')
    for k, shape in shapes.items():
        v = tensors[k]
        if (not isinstance(v, torch.Tensor) or v.device.type != 'cpu' or v.dtype != x.dtype
                or tuple(v.shape) != shape or not torch.isfinite(v).all()):
            raise ValueError('invalid conditional tensor shape/dtype/value')
    logits = x @ tensors['weight'].T + tensors['bias']
    if not torch.isfinite(logits).all():
        raise ValueError('nonfinite conditional expert scores')
    return logits


def conditional_logits(tensors, x, config, rule):
    """Return a normalized eight-way distribution, never a task-oracle route.

    Existing metrics accept log probabilities as logits. Runtime checks protect
    against finite-precision cancellation as well as finite-operand overflow.
    """
    if rule not in GATE_ARMS:
        raise ValueError('unknown conditional inference rule')
    logits = expert_logits(tensors, x, config, gated='score' if rule == 'gate_score_memory' else rule in LEARNED)
    if rule == 'conditional_concat':
        return logits
    old = list(config.old_classes)
    new = [i for i in range(config.classes) if i not in old]
    gate_input = (torch.logsumexp(logits[:, new], -1)-torch.logsumexp(logits[:, old], -1))[:, None] if rule == 'gate_score_memory' else x
    g = (gate_input @ tensors['gate_weight'] + tensors['gate_bias'][0]
         if rule in LEARNED else torch.zeros(len(x), dtype=x.dtype))
    if not torch.isfinite(g).all():
        raise ValueError('nonfinite learned gate score')
    result = torch.empty_like(logits)
    for columns, mass in ((old, F.logsigmoid(-g)), (new, F.logsigmoid(g))):
        conditional = F.log_softmax(logits[:, columns], -1)
        values = conditional + mass[:, None]
        if not torch.isfinite(values).all():
            raise ValueError('nonfinite hierarchical output')
        recovered = F.log_softmax(values, -1)
        if float((recovered-conditional).abs().max()) > CONDITIONAL_TOLERANCE:
            raise ValueError('finite-precision conditional odds lost')
        result[:, columns] = values
    return result


def shifted(tensors, offset):
    if type(offset) not in (float, int) or not math.isfinite(offset) or offset not in OFFSETS:
        raise ValueError('unregistered gate offset')
    result = {k: v.detach().clone() for k, v in tensors.items()}
    result['gate_bias'].add_(offset)
    return result


def fit_gates(inputs, truth, features, config, teachers):
    """Only gate scalars learn; each arm pays its own balanced 200-step fit.

    The bigger old-memory arm is explicitly NOT a matched-memory comparator.
    No calibration/test rows are normalized or read by the optimizer.
    """
    start = time.process_time_ns(), time.perf_counter_ns()
    old, new, memory = training_partition(inputs, truth, config)
    checked_tensor(features, 2, 'raw frozen gate features')
    if features.dtype != torch.float32 or len(features) != len(inputs) or not 1 <= features.shape[1] <= 512:
        raise ValueError('invalid gate source features')
    mean = features[old].mean(0)
    scale = features[old].std(0, unbiased=False).clamp_min(1e-6)
    packed = frozen_experts(deepcopy(teachers), features.shape[1], config)
    candidates = {n: deepcopy(packed) for n in GATE_ARMS[:2]}
    costs = {'packing_cpu_ns': time.process_time_ns()-start[0],
             'packing_wall_ns': time.perf_counter_ns()-start[1], 'arms': {}}
    for name, replay_rows in zip(LEARNED, (memory, old, memory)):
        before = time.process_time_ns(), time.perf_counter_ns()
        x = (features[replay_rows+new].detach().clone()-mean)/scale
        checked_tensor(x, 2, 'normalized gate training')
        d = features.shape[1]
        if name == 'gate_score_memory':
            with torch.no_grad():
                raw = expert_logits(packed, x, config, gated=False)
                new_columns = [i for i in range(config.classes) if i not in config.old_classes]
                x = (torch.logsumexp(raw[:, new_columns], -1)-torch.logsumexp(raw[:, list(config.old_classes)], -1))[:, None]
            checked_tensor(x, 2, 'teacher evidence gate feature')
        gate = torch.nn.Parameter(torch.zeros(x.shape[1]+1))
        if name == 'gate_score_memory':
            with torch.no_grad(): gate[0] = 1
        optimizer = torch.optim.AdamW([gate], lr=.001, weight_decay=.01)
        rng = torch.Generator().manual_seed(config.seed+2)
        target = torch.cat((torch.zeros(16), torch.ones(16)))
        for _ in range(config.steps):
            ids = torch.cat((torch.randint(len(replay_rows), (16,), generator=rng),
                             len(replay_rows)+torch.randint(len(new), (16,), generator=rng)))
            prediction = x[ids] @ gate[:-1] + gate[-1]
            loss = F.binary_cross_entropy_with_logits(prediction, target)
            if not torch.isfinite(loss):
                raise ValueError('nonfinite gate training loss')
            optimizer.zero_grad(set_to_none=True); loss.backward()
            if not torch.isfinite(gate.grad).all():
                raise ValueError('nonfinite gate gradient')
            optimizer.step()
            if not torch.isfinite(gate).all():
                raise ValueError('nonfinite gate update')
        candidates[name] = {**deepcopy(packed), 'gate_weight': gate[:-1].detach().clone(),
                            'gate_bias': gate[-1:].detach().clone()}
        count = sum(v.numel() for v in candidates[name].values())
        costs['arms'][name] = {'cpu_ns': time.process_time_ns()-before[0],
            'wall_ns': time.perf_counter_ns()-before[1], 'steps': config.steps,
            'sample_presentations': config.steps*32, 'replay_indices': replay_rows,
            'replay_feature_bytes': len(replay_rows)*d*4,
            'fitting_feature_bytes': x.numel()*4,
            'trainable_parameters': gate.numel(), 'deployed_parameters': count,
            'deployed_weight_bytes': count*4, 'optimizer_moment_bytes': gate.numel()*8}
    for name in GATE_ARMS[:2]:
        count = sum(v.numel() for v in candidates[name].values())
        costs['arms'][name] = {'steps': 0, 'sample_presentations': 0,
            'trainable_parameters': 0, 'deployed_parameters': count, 'deployed_weight_bytes': count*4}
    costs.update(current_encoder_calls=0, total_steps=len(LEARNED)*config.steps,
                 total_cpu_ns=time.process_time_ns()-start[0], total_wall_ns=time.perf_counter_ns()-start[1])
    return candidates, mean, scale, costs, {'old': old, 'new': new, 'memory': memory}


def calibrate(tensors, x, labels, groups, reference, config, rule):
    """Enumerate fixed intercepts on calibration only; no guarantee from grid search.

    Unsupported grids keep zero offset. Final selection against ALL inherited
    controls still uses the unchanged select_retained rule.
    """
    if rule not in LEARNED:
        raise ValueError('only learned gates have offset calibration')
    table, supported = [], []
    for offset in OFFSETS:
        candidate = shifted(tensors, offset)
        score = metrics(conditional_logits(candidate, x, config, rule), labels, groups, config)
        retain = all(score['per_class'][str(k)]['accuracy'] >= reference['per_class'][str(k)]['accuracy']-config.maximum_old_accuracy_drop
                     and score['per_class'][str(k)]['brier'] <= reference['per_class'][str(k)]['brier']+config.maximum_old_brier_increase for k in config.old_classes)
        gain = score['new']['accuracy'] > reference['new']['accuracy']
        table.append({'offset': offset, 'metrics': score, 'retained': retain, 'new_gain': gain})
        if retain and gain:
            supported.append(len(table)-1)
    index = min(supported, key=lambda i: table[i]['metrics']['old']['brier']+table[i]['metrics']['new']['brier']) if supported else 0
    return shifted(tensors, table[index]['offset']), {'selected_offset': table[index]['offset'],
        'supported': bool(supported), 'grid': table, 'statistical_superiority_established': False}
