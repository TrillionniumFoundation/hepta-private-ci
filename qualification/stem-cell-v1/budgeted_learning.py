"""Whole-update admission for the existing eager CPU CellBank/AdamW profile.

A shape-derived upper bound reserves room for a COMPLETE update before it starts.
Reservations are not charged as executed work: the existing strict ledger meters
actual dispatch. Unknown work, kernel failure or bound violation fails the arm.
No rollback, dummy work, uncharged profiling, held-out labels or quality stopping.
"""
from __future__ import annotations

import torch
from torch import nn

from matrix_bank import CellBank
from family_routing import FamilyCellBank


def step_upper_bound(bank, batch_size):
    """Conservative formula-work envelope for this exact MLP bank, not hardware.

    Forward/backward linear products: at most 6 multiplies/adds per input/weight
    pair (frozen inputs usually use fewer). 40 primitives per hidden row covers
    GELU forward/backward plus reductions. Dense gate and softmax/scatter are
    bounded separately. 48 per parameter plus 128 per tensor bounds clipping,
    AdamW first/second moments, bias correction and parameter update. All parameters
    are included even when sparse execution gives only some of them gradients.
    Copies, comparisons, allocation and integer RNG have zero *floating arithmetic*
    under the pinned meter profile, not zero time/memory. Only CPU FP32 is supported.
    """
    if type(bank) not in (CellBank, FamilyCellBank) or type(batch_size) is not int or not 1 <= batch_size <= 128:
        raise ValueError('registered CellBank and bounded batch required')
    d, c, n, k = bank.dimension, bank.classes, len(bank.heads), bank.top_k
    widths = []
    for head in bank.heads:
        if (type(head) is not nn.Sequential or len(head) != 3
                or type(head[0]) is not nn.Linear or type(head[1]) is not nn.GELU
                or head[1].approximate != 'none' or type(head[2]) is not nn.Linear
                or head[0].in_features != d or head[2].out_features != c
                or head[0].out_features != head[2].in_features
                or head[0].bias is None or head[2].bias is None):
            raise ValueError('unregistered Head geometry')
        widths.append(head[0].out_features)
    if (len(set(widths)) != 1 or type(bank.gate) is not nn.Linear
            or bank.gate.in_features != d or bank.gate.out_features != n
            or bank.gate.bias is None or not 1 <= k <= n):
        raise ValueError('unregistered routing geometry')
    tensors = list(bank.parameters())
    if any(p.dtype != torch.float32 or p.device.type != 'cpu' or not p.requires_grad for p in tensors):
        raise ValueError('trainable CPU FP32 bank required')
    p = sum(t.numel() for t in tensors)
    b, w = batch_size, widths[0]
    gate = 6*b*d*n + 20*b*n + 32*b*k*(c+1)
    heads = b*k*(6*d*w + 6*c*w + 40*w + 16*c + 8)
    loss = 16*b*(c+1)
    optimizer = 48*p + 128*len(tensors)
    extra = 0
    if type(bank) is FamilyCellBank:
        if n != 32 or k != 2 or not 0 < bank.sibling_loss_weight <= 1:
            raise ValueError('unregistered family routing')
        # Four detached sibling Head/row probes, label losses, binary selector
        # supervision and gathered gate gradients. No free counterfactual work.
        extra = b * 2*k * (2*d*w + 2*c*w + 8*w + 32*c + 32)
        extra += 64*b*n + 4*(d+1)*n
    return gate + heads + loss + optimizer + extra


def used_training_work(meter):
    """Read already observed prefixes without sealing or changing the ledger."""
    rows = [r for r in meter.rows.values() if r['phase'] == 'train']
    if meter.stopped or any(r['unknown_operators'] or r['failed_calls'] for r in rows):
        raise ValueError('incomplete training cannot support budget admission')
    return sum(r['formula_flops'] for r in rows)


def train_to_budget(bank, features, targets, study, seed, *, meter, stop_at_work=None):
    """Same AdamW/loss/clipping as train_bank, but admit whole steps by work.

    Batch sizes shrink geometrically only when the remaining budget cannot fund
    the larger bound. A single seeded sampler is retained across accepted steps.
    Different numbers of examples/updates are part of this compute-budget estimand.
    """
    if (study.get('schedule') != 'formula_budget_whole_updates_v1'
            or meter.current is not None or meter.policy != study['measurement_policy']
            or meter.caps['train'] != study['training_flops_budget']):
        raise ValueError('bound budget schedule and idle matching meter required')
    if (features.ndim != 2 or not 1 <= len(features) <= 128
            or features.shape[1] != bank.dimension or features.requires_grad
            or features.dtype != torch.float32 or features.device.type != 'cpu'
            or targets.dtype != torch.long or targets.device.type != 'cpu'
            or targets.shape != (len(features),)):
        raise ValueError('bounded frozen features and training labels required')
    budget = study['training_flops_budget']
    if stop_at_work is not None:
        if type(stop_at_work) is not int or not 0 < stop_at_work <= budget:
            raise ValueError('stage boundary must fit the original phase budget')
        budget = stop_at_work
    max_steps = study['max_budget_steps']
    if type(budget) is not int or budget < 1 or type(max_steps) is not int or not 1 <= max_steps <= 4096:
        raise ValueError('bounded budget and step ceiling required')
    sizes = []
    size = min(study['batch_size'], len(features))
    if type(size) is not int or not 1 <= size <= 128:
        raise ValueError('invalid batch size')
    while size:
        sizes.append(size); size //= 2
    bounds = {b: step_upper_bound(bank, b) for b in sizes}
    # Validation is observed too. No preflight optimizer or synthetic calibration run.
    with meter.scope('train', 'bank'):
        if (not torch.isfinite(features).all().item() or targets.min().item() < 0
                or targets.max().item() >= bank.classes):
            raise ValueError('invalid training values')
        rng = torch.Generator(device='cpu').manual_seed(seed)
        optimizer = torch.optim.AdamW(bank.parameters(), lr=.001, weight_decay=.01)
    bank.train()
    steps = []
    reason = 'step_limit'
    for index in range(max_steps):
        before = used_training_work(meter)
        chosen_size = next((b for b in sizes if bounds[b] <= budget-before), None)
        if chosen_size is None:
            reason = 'insufficient_room_for_complete_update'
            break
        with meter.scope('train', 'bank'):
            ids = torch.randint(len(targets), (chosen_size,), generator=rng)
            optimizer.zero_grad(set_to_none=True)
            loss = (bank.training_loss(features[ids], targets[ids]) if type(bank) is FamilyCellBank
                    else nn.functional.cross_entropy(bank(features[ids]), targets[ids]))
            if not torch.isfinite(loss).item():
                raise ValueError('nonfinite loss')
            loss.backward()
            nn.utils.clip_grad_norm_(bank.parameters(), 1.0)
            optimizer.step()
            if not all(torch.isfinite(p).all().item() for p in bank.parameters()):
                raise ValueError('nonfinite candidate')
            value = float(loss.detach())
        after = used_training_work(meter)
        actual = after - before
        if not 0 < actual <= bounds[chosen_size]:
            raise ValueError('actual update exceeded its declared admission bound')
        steps.append(dict(index=index, batch_size=chosen_size, loss=value,
                          reserved_upper_bound=bounds[chosen_size], actual_formula_flops=actual))
    if not steps:
        raise ValueError('budget funded no complete parameter update')
    bank.eval()
    used = used_training_work(meter)
    optimizer_bytes = sum(v.numel()*v.element_size() for state in optimizer.state.values()
                          for v in state.values() if isinstance(v, torch.Tensor))
    return dict(steps=len(steps), examples_seen=sum(s['batch_size'] for s in steps),
        losses=[s['loss'] for s in steps], optimizer_tensor_bytes=optimizer_bytes,
        budget=dict(schema='hepta.cell-training-budget.v1', limit=budget, observed=used,
            remaining=budget-used, utilization=used/budget, stop_reason=reason,
            smallest_complete_update_bound=bounds[1], updates=steps,
            unit=meter.arithmetic_profile, conservative_reservations_are_not_charges=True,
            initialization_included=True, hardware_or_full_system_cost=False))


def validate_budget_results(study, arms):
    """Check actual budget records at scoring; hashes alone do not prove claims."""
    from work_record import validate_work_record
    result = []
    for arm in arms:
        validate_work_record(arm['work'], expected_policy=study['measurement_policy'])
        if arm['status'] != 'completed':
            result.append(dict(topology=arm['topology'], status='failed', utilization=None))
            continue
        train, count = arm['training'], arm['work']['phase_flops']['train']
        b = train['budget']
        if (b.get('schema') != 'hepta.cell-training-budget.v1'
                or b.get('conservative_reservations_are_not_charges') is not True
                or b.get('hardware_or_full_system_cost') is not False
                or type(b.get('smallest_complete_update_bound')) is not int or b['smallest_complete_update_bound'] < 1
                or type(count) is not int or not 0 < count <= study['training_flops_budget']
                or b['limit'] != study['training_flops_budget'] or b['observed'] != count
                or b['remaining'] != b['limit']-count or b['unit'] != arm['work']['profile']
                or b['utilization'] != count/b['limit']
                or b['stop_reason'] not in ('step_limit', 'insufficient_room_for_complete_update')
                or len(b['updates']) != train['steps'] or not 1 <= train['steps'] <= study['max_budget_steps']):
            raise ValueError('inconsistent training-budget receipt')
        work = examples = 0
        for i, row in enumerate(b['updates']):
            if (row['index'] != i or any(type(row[k]) is not int or row[k] < 1 for k in
                    ('batch_size', 'actual_formula_flops', 'reserved_upper_bound'))
                    or row['batch_size'] > study['batch_size']
                    or row['actual_formula_flops'] > row['reserved_upper_bound']):
                raise ValueError('inconsistent complete-update accounting')
            work += row['actual_formula_flops']; examples += row['batch_size']
        if b['stop_reason'] == 'step_limit' and train['steps'] != study['max_budget_steps']:
            raise ValueError('incorrect step-limit disposition')
        prefix = count - work
        for row in b['updates']:
            if prefix + row['reserved_upper_bound'] > b['limit']:
                raise ValueError('update started without its declared reservation')
            prefix += row['actual_formula_flops']
        if work > count or examples != train['examples_seen']:
            raise ValueError('budget step denominator mismatch')
        if (b['stop_reason'] == 'insufficient_room_for_complete_update'
                and b['remaining'] >= b['smallest_complete_update_bound']):
            raise ValueError('unjustified budget stop')
        result.append(dict(topology=arm['topology'], status='completed', steps=train['steps'],
            examples_seen=examples, formula_flops=count, remaining=b['remaining'],
            utilization=b['utilization'], stop_reason=b['stop_reason']))
    return result
