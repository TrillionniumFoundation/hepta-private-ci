#!/usr/bin/env python3
"""Actual sparse-Cell SGD: packed bank versus independent modules, CPU-only.

The feature/targets are synthetic, and the experiment cannot authorize a Stem,
Worker, NDU or production action. All dormant Head weights must remain intact.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import resource
import time
from pathlib import Path

SCALES = (64, 256, 1024, 4096)
SHAPES = {
    'down.weight': (8, 384),
    'gate.weight': (8, 64),
    'gate.bias': (8,),
    'up.weight': (384, 8),
    'output.weight': (8, 384),
    'output.bias': (8,),
}
PER_HEAD = 9744
SCHEMA = 'hepta.e5.sparse-packed-sgd-cpu.v1'

class Invalid(ValueError):
    pass


def checked(logical, active, steps, seed, mode):
    if logical not in SCALES or type(active) is not int or not 1 <= active <= logical:
        raise Invalid('bad Cell population')
    if type(steps) is not int or not 1 <= steps <= 6 or type(seed) is not int or seed < 0:
        raise Invalid('invalid SGD configuration')
    if mode not in ('packed', 'modules'):
        raise Invalid('unregistered mode')


def selected_indices(torch, logical, active, seed):
    gen = torch.Generator(device='cpu').manual_seed(seed + 919)
    return torch.randperm(logical, generator=gen)[:active].sort()[0]


def synthetic_inputs(torch, selected):
    # Exact shared Q24 vector and Cell-local state; neither may receive gradient.
    common = torch.round(torch.linspace(-1, 1, 384) * (1 << 24)) / (1 << 24)
    state = ((selected.float() % 23) - 11).reshape(-1, 1).expand(-1, 64) / 20
    labels = (selected * 7 + 3) % 8
    return common, state, labels


def _write_cell(torch, target, index, seed):
    g = torch.Generator(device='cpu').manual_seed(seed + index)
    with torch.no_grad():
        for name, shape in SHAPES.items():
            if name == 'up.weight':
                target[name].zero_()
            else:
                fan = shape[-1] if len(shape) == 2 else 384
                bound = 1 / math.sqrt(fan)
                target[name].uniform_(-bound, bound, generator=g)


def packed_bank(torch, logical, seed):
    bank = {k: torch.empty((logical, *shape), dtype=torch.float32) for k, shape in SHAPES.items()}
    for index in range(logical):
        _write_cell(torch, {k: v[index] for k, v in bank.items()}, index, seed)
    if sum(t.numel() for t in bank.values()) != logical * PER_HEAD:
        raise Invalid('bad packed parameters')
    return bank


def independent_modules(torch, logical, seed):
    from e5_physical_head_fanout import make_head
    modules = []
    for index in range(logical):
        head = make_head(torch)
        _write_cell(torch, dict(head.named_parameters()), index, seed)
        modules.append(head)
    if sum(sum(v.numel() for v in h.parameters()) for h in modules) != logical * PER_HEAD:
        raise Invalid('bad independent parameters')
    return modules


def _inactive_ranges(logical, selected):
    start = 0
    for index in selected:
        if index > start:
            yield start, index
        start = index + 1
    if start < logical:
        yield start, logical


def frozen_hash(bank, logical, selected):
    h = hashlib.sha256(b'hepta.e5.dormant-cell-bank.v1')
    inactive = tuple(_inactive_ranges(logical, selected))
    for name, weight in sorted(bank.items()):
        h.update(name.encode())
        for start, stop in inactive:
            h.update(weight[start:stop].detach().contiguous().numpy().tobytes())
    return h.hexdigest()


def dormant_modules_hash(modules, selected):
    inactive = sorted(set(range(len(modules))) - set(selected))
    h = hashlib.sha256(b'hepta.e5.dormant-modules.v1')
    for name in sorted(SHAPES):
        h.update(name.encode())
        for i in inactive:
            h.update(dict(modules[i].named_parameters())[name].detach().numpy().tobytes())
    return h.hexdigest()

def trained_hash(tensors):
    h = hashlib.sha256(b'hepta.e5.trained-cells.v1')
    for name, weight in sorted(tensors.items()):
        h.update(name.encode())
        h.update(weight.detach().contiguous().numpy().tobytes())
    return h.hexdigest()


def run(logical=64, active=8, mode='packed', steps=3, seed=20261014,
        *, return_validation=False):
    checked(logical, active, steps, seed, mode)
    import psutil
    import torch
    import torch.nn.functional as F
    torch.set_num_threads(1)
    started_ns = time.perf_counter_ns()
    cpu_ns = time.process_time_ns()
    chosen = selected_indices(torch, logical, active, seed)
    selected = chosen.tolist()
    common, states, labels = synthetic_inputs(torch, chosen)
    index_signature = hashlib.sha256(chosen.numpy().tobytes()).hexdigest()
    init_started = time.perf_counter_ns()
    if mode == 'packed':
        bank = packed_bank(torch, logical, seed)
        dormant_before = frozen_hash(bank, logical, selected)
        active_params = {
            name: torch.nn.Parameter(weight.index_select(0, chosen).detach().clone())
            for name, weight in bank.items()
        }
        all_parameters = list(active_params.values())
        original = trained_hash(active_params)
        resident = sum(t.numel() for t in bank.values())
    else:
        modules = independent_modules(torch, logical, seed)
        active_modules = [modules[i] for i in selected]
        all_parameters = [p for model in active_modules for p in model.parameters()]
        active_params = {name:torch.stack([dict(h.named_parameters())[name].detach() for h in active_modules])
                         for name in SHAPES}
        original = trained_hash(active_params)
        dormant_before = dormant_modules_hash(modules, selected)
        resident = sum(sum(p.numel() for p in h.parameters()) for h in modules)
    initialize_ms = (time.perf_counter_ns() - init_started) / 1e6
    if resident != logical * PER_HEAD:
        raise Invalid('incomplete resident Head population')
    rng = common.reshape(1, -1).expand(active, -1)
    if rng.stride(0) != 0 or common.requires_grad or states.requires_grad:
        raise Invalid('shared synthetic input identity altered')
    optimizer = torch.optim.SGD(all_parameters, lr=.01)
    import e5_packed_head_fanout as packed
    losses = []
    update_started = time.perf_counter_ns()
    for step in range(steps):
        optimizer.zero_grad(set_to_none=True)
        if mode == 'packed':
            logits = packed.packed_forward(torch, active_params, rng, states)
        else:
            logits = torch.cat([model(common.reshape(1, -1), states[k:k + 1])
                                for k, model in enumerate(active_modules)], dim=0)
        # Sum of per-Cell losses: matches independent one-example SGD exactly.
        loss = F.cross_entropy(logits, labels, reduction='sum')
        if not bool(torch.isfinite(loss)):
            raise Invalid('nonfinite observed loss')
        losses.append(float(loss.detach()))
        loss.backward()
        if any(p.grad is None or not bool(torch.isfinite(p.grad).all()) for p in all_parameters):
            raise Invalid('SGD gradients incomplete')
        optimizer.step()
    train_ms = (time.perf_counter_ns() - update_started) / 1e6
    if mode == 'packed':
        updated = trained_hash(active_params)
        with torch.no_grad():
            for name, values in active_params.items():
                bank[name].index_copy_(0, chosen, values.detach())
        dormant_after = frozen_hash(bank, logical, selected)
        if dormant_before != dormant_after:
            raise Invalid('dormant Cell weights mutated')
        actual = {name:weight.index_select(0, chosen) for name,weight in bank.items()}
    else:
        actual = {name:torch.stack([dict(h.named_parameters())[name].detach() for h in active_modules])
                  for name in SHAPES}
        updated = trained_hash(actual)
        dormant_after = dormant_modules_hash(modules, selected)
        if dormant_before != dormant_after:
            raise Invalid('independent dormant Cell weights mutated')
    if updated == original:
        raise Invalid('SGD produced no weight updates')
    if common.grad is not None or states.grad is not None:
        raise Invalid('gradient escaped into shared feature or local state')
    if mode == 'packed':
        with torch.inference_mode():
            after = packed.packed_forward(torch, active_params, rng, states)
    else:
        with torch.inference_mode():
            after = torch.cat([model(common.reshape(1,-1), states[k:k+1])
                               for k,model in enumerate(active_modules)], dim=0)
    if after.shape != (active,8) or not bool(torch.isfinite(after).all()):
        raise Invalid('unusable trained logits')
    report = {
        'schema': SCHEMA, 'authority': 'DENY_ALL', 'production_promotion_permitted': False,
        'pretrained_encoder_executed': False, 'synthetic_labels_and_features': True,
        'production_worker_executed': False, 'independent_ndu_verified': False,
        'requested_logical_cells': logical, 'observed_resident_head_parameters': resident,
        'active_cell_count': active, 'inactive_cell_count': logical - active,
        'physical_feature_buffer_count': 1, 'mode': mode,
        'optimizer': 'torch.optim.SGD', 'optimizer_steps_per_active_cell': steps,
        'learning_rate': .01, 'seed': seed,
        'active_cell_index_sha256': index_signature,
        'initial_active_weights_sha256': original, 'final_active_weights_sha256': updated,
        'dormant_weights_unchanged': True,
        'dormant_bank_sha256_before': dormant_before,
        'dormant_bank_sha256_after': dormant_after,
        'training_loss_by_step_sum': losses,
        'last_step_training_loss_per_cell': losses[-1]/active,
        'measured_initialization_ms': initialize_ms,
        'measured_sgd_wall_ms': train_ms,
        'measured_end_to_end_process_wall_ms': (time.perf_counter_ns()-started_ns)/1e6,
        'measured_process_cpu_ms': (time.process_time_ns()-cpu_ns)/1e6,
        'measured_peak_rss_bytes': resource.getrusage(resource.RUSAGE_SELF).ru_maxrss*1024,
        'measured_current_rss_bytes': psutil.Process().memory_info().rss,
        'model_forward_call_count_attested': False,
        'p99_end_to_end_latency_verified': False,
        'measured_energy_joules': None,
        'prediction_logits_sha256': hashlib.sha256(after.numpy().tobytes()).hexdigest(),
    }
    if return_validation:
        return report, after.detach().clone(), {k:v.detach().clone() for k,v in actual.items()}
    return report


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--cells',type=int,required=True,choices=SCALES)
    p.add_argument('--active',type=int,required=True)
    p.add_argument('--mode',choices=('packed','modules'),required=True)
    p.add_argument('--steps',type=int,default=3)
    p.add_argument('--seed',type=int,default=20261014)
    p.add_argument('--output',type=Path,required=True)
    a = p.parse_args()
    if a.output.exists():
        raise FileExistsError('create-only physical receipt')
    report = run(a.cells,a.active,a.mode,a.steps,a.seed)
    with a.output.open('x',encoding='utf8') as file:
        json.dump(report,file,indent=2,sort_keys=True,allow_nan=False)
        file.write('\n')
if __name__=='__main__':
    main()
