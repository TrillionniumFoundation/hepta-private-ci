#!/usr/bin/env python3
"""Frozen Encoder feature study: baseline-preserving gated residuals vs controls.

Expects already-computed real Q24 frozen features from the E1 process. Synthetic
features are allowed in tests only and must never become empirical receipts.
This head is post-Encoder and feature-gated; it is NOT Cell-state FiLM or LoRA.
"""
from __future__ import annotations
import copy
import hashlib
import json
import math
import time

BUDGETS = (2048, 8192, 16384)
HEAD_ARMS = ('frozen_head', 'from_zero', 'cosine_prototype', 'residual_2k', 'residual_8k', 'residual_16k')
TEMPERATURES = (.5, .75, 1., 1.5, 2., 3., 4.)

class Invalid(ValueError):
    pass


def _digest(module):
    h = hashlib.sha256(b'hepta.e2.feature-gated-residual.v1')
    for name, tensor in sorted(module.state_dict().items()):
        h.update(name.encode() + b'\0')
        h.update(tensor.detach().cpu().contiguous().numpy().tobytes())
    return h.hexdigest()


def _train(module, train_x, train_y, *, steps, learning_rate, torch):
    import torch.nn.functional as F
    before = _digest(module)
    n = sum(t.numel() for t in module.parameters() if t.requires_grad)
    if n <= 0:
        raise Invalid('optimizer received a nontrainable Head')
    optimizer = torch.optim.SGD((v for v in module.parameters() if v.requires_grad), lr=learning_rate)
    began = time.perf_counter_ns()
    for _ in range(steps):
        optimizer.zero_grad(set_to_none=True)
        loss = F.cross_entropy(module(train_x), train_y)
        if not bool(torch.isfinite(loss)):
            raise Invalid('nonfinite training loss')
        loss.backward()
        optimizer.step()
    elapsed = (time.perf_counter_ns() - began) / 1e6
    module.eval()
    after = _digest(module)
    if before == after:
        raise Invalid('optimizer Head bytes did not change')
    return {'initial_head_sha256': before, 'final_head_sha256': after,
            'trainable_parameters': n, 'optimizer_steps': steps,
            'train_ms': elapsed, 'trainable_weights_changed': True}


def study(panel, model_id, vectors, *, seed=20261014, steps=40, learning_rate=.15):
    import torch
    import torch.nn.functional as F
    if (type(panel) is not dict or panel.get('case_count') != 224 or
            panel.get('cross_sectional_not_future') is not True or
            panel.get('production_promotion') != 'DENY_ALL'):
        raise Invalid('E2 requires frozen approved public E1 panel')
    if not isinstance(model_id, str) or not model_id or type(seed) is not int or type(steps) is not int or not 1 <= steps <= 128:
        raise Invalid('missing model identity or bounded optimizer schedule')
    if type(learning_rate) not in (float, int) or not math.isfinite(learning_rate) or not 0 < learning_rate <= 1:
        raise Invalid('invalid learning rate')
    cases = panel['cases']
    if type(cases) is not list or len(cases) != 224 or type(vectors) is not dict or set(vectors) != {c['case_id'] for c in cases}:
        raise Invalid('incomplete frozen Encoder feature inventory')
    dims = {len(v) for v in vectors.values() if isinstance(v, (list, tuple))}
    if len(dims) != 1:
        raise Invalid('inconsistent feature width')
    width = dims.pop()
    if width not in (256, 384) or any(type(value) not in (float, int) or not math.isfinite(value) or abs(value) > 8
                                        for v in vectors.values() for value in v):
        raise Invalid('bad feature width or unsafe Q24 float')
    parts = {name: [c for c in cases if c['split'] == name] for name in ('train', 'calibration', 'test')}
    if {k:len(v) for k,v in parts.items()} != {'train':128, 'calibration':32, 'test':64}:
        raise Invalid('unexpected source partitions')
    def x(rows):
        return torch.tensor([vectors[c['case_id']] for c in rows], dtype=torch.float32)
    train_x, calibration_x = x(parts['train']), x(parts['calibration'])
    train_y = torch.tensor([c['label'] for c in parts['train']], dtype=torch.long)
    cal_y = torch.tensor([c['label'] for c in parts['calibration']], dtype=torch.long)
    if not bool(torch.isfinite(train_x).all()) or not bool(torch.isfinite(calibration_x).all()):
        raise Invalid('nonfinite feature matrix')
    torch.manual_seed(seed)
    baseline = torch.nn.Linear(width, 2).eval()
    base_initial = _digest(baseline)
    baseline.train(False)
    # From-zero linear has precisely the frozen control's initialization.
    from_zero = copy.deepcopy(baseline).train()

    class FeatureGatedResidual(torch.nn.Module):
        def __init__(self, frozen_base, rank):
            super().__init__()
            self.base = frozen_base
            self.base.requires_grad_(False)
            self.down = torch.nn.Linear(width, rank, bias=False)
            self.gate = torch.nn.Linear(width, rank)
            self.up = torch.nn.Linear(rank, 2, bias=False)
            torch.nn.init.zeros_(self.up.weight)

        def forward(self, inputs):
            constant = self.base(inputs)
            correction = self.up(F.silu(self.down(inputs)) * torch.sigmoid(self.gate(inputs)))
            return constant + correction

    modules = {'frozen_head': baseline, 'from_zero': from_zero}
    params = {'frozen_head': sum(t.numel() for t in baseline.parameters()),
              'from_zero': sum(t.numel() for t in from_zero.parameters())}
    init_equal = {}
    for budget, name in zip(BUDGETS, ('residual_2k', 'residual_8k', 'residual_16k')):
        rank = min(64, budget // (2 * width + 3))
        if rank < 1:
            raise Invalid('infeasible residual rank')
        mod = FeatureGatedResidual(baseline, rank)
        trainable = sum(p.numel() for p in mod.parameters() if p.requires_grad)
        total = sum(p.numel() for p in mod.parameters())
        if not 0 < trainable <= budget or total != trainable + params['frozen_head']:
            raise Invalid('hidden trainable projection or incorrect parameter ledger')
        with torch.inference_mode():
            init_equal[name] = bool(torch.equal(mod(train_x), baseline(train_x)))
        if not init_equal[name]:
            raise Invalid('residual does not preserve unmodified baseline logits')
        if mod.base.weight.data_ptr() != baseline.weight.data_ptr():
            raise Invalid('frozen base weight was unexpectedly copied')
        modules[name] = mod
        params[name] = trainable
    frozen_after_init = _digest(baseline)
    if frozen_after_init != base_initial:
        raise Invalid('frozen Head mutated during construction')
    measurements = {}
    for name in ('from_zero', 'residual_2k', 'residual_8k', 'residual_16k'):
        measurements[name] = _train(modules[name], train_x, train_y, steps=steps,
                                    learning_rate=learning_rate, torch=torch)
        if name.startswith('residual_') and _digest(modules[name].base) != base_initial:
            raise Invalid('frozen residual base changed during training')
    if _digest(baseline) != base_initial:
        raise Invalid('frozen baseline changed during training')
    # Cosine uses class centroids computed from TRAIN labels. This is a fitted
    # non-parametric classifier, NOT a no-fit or no-change control.
    centroids = []
    for target in (0, 1):
        candidate = train_x[train_y == target].mean(0)
        if float(candidate.norm()) <= 1e-8:
            raise Invalid('degenerate train-only cosine prototype')
        centroids.append(F.normalize(candidate, dim=0))
    prototypes = torch.stack(centroids)
    scored = parts['calibration'] + parts['test']
    outputs = {}
    for name in HEAD_ARMS:
        if name == 'cosine_prototype':
            def predict(vals):
                v = F.normalize(vals, dim=-1)
                return v @ prototypes.T
            head_sha = hashlib.sha256(b'hepta.e2.train-only-cosine-prototypes.v1' +
                                      prototypes.cpu().contiguous().numpy().tobytes()).hexdigest()
            trained_count = 0
        else:
            module = modules[name]
            def predict(vals, _module=module):
                return _module(vals)
            head_sha = _digest(module)
            trained_count = 0 if name == 'frozen_head' else params[name]
        with torch.inference_mode():
            calibration_logits = predict(calibration_x)
            t = min(TEMPERATURES, key=lambda value: float(F.cross_entropy(calibration_logits / value, cal_y)))
            probs = F.softmax(predict(x(scored)) / t, dim=-1)[:,1].tolist()
        outputs[name] = {'head_sha256': head_sha, 'trainable_parameters': trained_count,
                         'calibration_temperature': t,
                         'initial_baseline_logits_identical': init_equal.get(name),
                         'predictions': [{'case_id': c['case_id'], 'split': c['split'],
                                          'joint_input_digest': c['joint_input_digest'],
                                          'positive_probability': float(p)}
                                         for c,p in zip(scored, probs)]}
    from e1e2_q24_identity import feature_inventory
    bank=feature_inventory([c['case_id'] for c in cases],vectors)
    return {'schema': 'hepta.e2-feature-gated-head-public.v1', 'model': model_id,
            'frozen_feature_bank_identity':bank,
            'width':width, 'case_count':len(cases), 'train_case_ids_sha256':hashlib.sha256(json.dumps(
                [c['case_id'] for c in parts['train']],sort_keys=True,separators=(',',':')).encode()).hexdigest(),
            'head_kind':'post_encoder_feature_gated_residual_not_cell_state_film',
            'head_parameter_ceiling_by_arm':{'residual_2k':2048,'residual_8k':8192,'residual_16k':16384},
            'frozen_base_parameters_counted_as_shared_storage':params['frozen_head'],
            'frozen_base_weight_storage_shared_among_residual_arms':True,
            'cosine_uses_train_labels_not_no_fit':True,
            'optimizer':'SGD_full_train_batch', 'seed':seed, 'steps':steps, 'learning_rate':learning_rate,
            'training':measurements,'arms':outputs,
            'independent_no_change_production_arm_present':False,
            'reader_sufficiency_evaluated':False, 'chronological_future_ndu_verified':False,
            'production_promotion_permitted':False,'authority':'DENY_ALL'}
