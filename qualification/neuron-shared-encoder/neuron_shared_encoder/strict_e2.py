"""Equal-parameter E2 diagnostic for two genuinely nonlinear Cell heads.

Research-only. Deterministic CPU batches and train-only normalization cannot
establish real-world causal learning, NDU benefit, signatures or final-use.
"""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import math
from typing import Any

import torch
from torch import Tensor
from torch.nn import functional as F

from .validation_v3 import SmallHead, _scores, _auroc

KINDS = ('dynamic_gate', 'swiglu')
SPLITS = ('train', 'validation', 'future', 'ood')


def _utc(value: Any) -> datetime:
    if not isinstance(value, str):
        raise ValueError('timezone-aware event_time required')
    try:
        instant = datetime.fromisoformat(value.replace('Z', '+00:00'))
    except ValueError as exc:
        raise ValueError('invalid ISO-8601 event_time') from exc
    if instant.tzinfo is None or instant.utcoffset() is None:
        raise ValueError('timezone-aware event_time required')
    return instant.astimezone(timezone.utc)


def _audit_dataset(features: Tensor, labels: Tensor, rows: list[dict]) -> dict[str, Tensor]:
    if features.ndim != 2 or not 1 <= features.shape[1] <= 512 or len(features) != len(rows):
        raise ValueError('invalid bounded feature matrix')
    if features.dtype not in (torch.float16, torch.float32, torch.float64, torch.bfloat16):
        raise ValueError('floating point features required')
    if features.device.type != 'cpu' or not torch.isfinite(features).all():
        raise ValueError('finite CPU feature matrix required')
    if labels.ndim != 1 or len(labels) != len(rows) or labels.dtype != torch.long:
        raise ValueError('aligned integer class labels required')
    if not 8 <= len(rows) <= 8192 or int(labels.min()) < 0 or int(labels.max()) >= 16:
        raise ValueError('bounded rows/classes required')
    if not isinstance(rows[0], dict):
        raise ValueError('dataset rows must be mappings')
    scope = (rows[0].get('principal'), rows[0].get('organ_id'), rows[0].get('cell_id'))
    if any(not isinstance(s, str) or not s for s in scope):
        raise ValueError('complete Cell scope required')
    seen_ids: set[str] = set()
    groups: dict[str, str] = {}
    dates: dict[str, list[datetime]] = {s: [] for s in SPLITS}
    indices: dict[str, list[int]] = {s: [] for s in SPLITS}
    for i, row in enumerate(rows):
        if not isinstance(row, dict):
            raise ValueError('dataset rows must be mappings')
        if (row.get('principal'), row.get('organ_id'), row.get('cell_id')) != scope:
            raise ValueError('cross-Cell / cross-principal rows refused')
        split, row_id, source = (row.get('split'), row.get('row_id'), row.get('source_group'))
        if split not in SPLITS or not isinstance(row_id, str) or not row_id:
            raise ValueError('invalid split or row identity')
        if not isinstance(source, str) or not source or row_id in seen_ids:
            raise ValueError('missing source group or duplicate row')
        seen_ids.add(row_id)
        previous = groups.setdefault(source, split)
        if previous != split:
            raise ValueError('source group leakage across splits')
        dates[split].append(_utc(row.get('event_time')))
        indices[split].append(i)
        choices = row.get('options')
        if (not isinstance(choices, list) or len(choices) < 2 or len(choices) > 16
                or len(choices) != len(rows[0].get('options', []))):
            raise ValueError('option geometry mismatch')
        if row.get('label') != int(labels[i]) or type(row.get('label')) is not int:
            raise ValueError('tensor labels differ from pinned dataset rows')
    if any(not indices[s] for s in SPLITS):
        raise ValueError('train, validation, future, OOD splits all required')
    if min(dates['validation']) <= max(dates['train']):
        raise ValueError('validation must begin after training observations')
    if min(dates['future']) <= max(dates['validation'] + dates['train']):
        raise ValueError('future must begin after train and validation')
    classes = len(rows[0]['options'])
    if any(int(v) >= classes for v in labels):
        raise ValueError('label exceeds common class width')
    if len(set(labels[indices['train']].tolist())) != classes:
        raise ValueError('all classes must be present in training rows')
    return {s: torch.tensor(values, dtype=torch.long) for s, values in indices.items()}


def equal_parameter_nonlinear_trial(features: Tensor, labels: Tensor, rows: list[dict], *,
                                    budget: int = 16384, seeds: tuple[int, ...] = (11, 29, 47),
                                    steps: int = 32, batch: int = 32, lr: float = 1e-3) -> dict:
    """Compare Sigmoid/SiLU dynamic gating vs SwiGLU with identical true counts.

    Exactly the same training rows/steps, learning rate, batch draws, initial
    parameter tensors, normalization and future window for both variants.
    Only validation Brier selects the descriptive shadow winner; future is
    reported post hoc and does not determine an upgrade or NDU action.
    """
    if budget not in (2048, 16384, 65536, 262144):
        raise ValueError('unsupported parameter budget')
    if (not isinstance(seeds, tuple) or not 1 <= len(seeds) <= 8
            or any(type(s) is not int or not 0 <= s <= 2**31 - 1 for s in seeds)
            or len(set(seeds)) != len(seeds)):
        raise ValueError('distinct bounded seeds required')
    if not 1 <= steps <= 512 or not 1 <= batch <= 256 or not math.isfinite(lr) or not 0 < lr <= 1:
        raise ValueError('bounded training budget required')
    groups = _audit_dataset(features, labels, rows)
    x = features.float()
    train = groups['train']
    center = x[train].mean(0)
    spread = x[train].std(0, unbiased=False).clamp_min(1e-4)
    x = ((x - center) / spread).clamp(-10, 10)
    classes = len(rows[0]['options'])
    result = []
    for seed in seeds:
        with torch.random.fork_rng(devices=[]):
            torch.manual_seed(seed)
            dynamic = SmallHead('dynamic_gate', x.shape[1], classes, budget)
            torch.manual_seed(seed)
            swiglu = SmallHead('swiglu', x.shape[1], classes, budget)
        if dynamic.parameter_count != swiglu.parameter_count:
            raise ValueError('candidate parameters not identical')
        if dynamic.parameter_count > budget:
            raise ValueError('actual parameter ceiling exceeded')
        # Exact same initial tensors per matching parameter shape and order.
        for a, b in zip(dynamic.parameters(), swiglu.parameters()):
            if a is b or not torch.equal(a.detach(), b.detach()):
                raise ValueError('unequal or shared initial parameters')
        generator = torch.Generator(device='cpu').manual_seed(seed + 9127)
        batches = [torch.randint(0, len(train), (min(batch, len(train)),), generator=generator)
                   for _ in range(steps)]
        sampling_hash = hashlib.sha256(json.dumps([v.tolist() for v in batches],
                                                  separators=(',', ':')).encode()).hexdigest()
        records = {}
        for kind, model in zip(KINDS, (dynamic, swiglu)):
            optimizer = torch.optim.AdamW(model.parameters(), lr=lr)
            model.train()
            for ids in batches:
                logits = model(x[train[ids]])
                loss = F.cross_entropy(logits, labels[train[ids]])
                optimizer.zero_grad(set_to_none=True)
                loss.backward()
                optimizer.step()
            model.eval()
            with torch.inference_mode():
                probabilities = {k: model(x[groups[k]]).softmax(-1) for k in ('validation', 'future', 'ood')}
                metrics = {k: _scores(probabilities[k], labels[groups[k]]) for k in ('validation', 'future')}
                metrics['ood_auroc_msp'] = _auroc(
                    1 - probabilities['ood'].max(1).values,
                    1 - probabilities['validation'].max(1).values)
            records[kind] = {'parameter_count': model.parameter_count,
                             'optimizer_state_bytes': sum(t.numel() * t.element_size()
                                 for state in optimizer.state.values() for t in state.values()
                                 if isinstance(t, Tensor)),
                             'validation': metrics['validation'], 'future': metrics['future'],
                             'ood_auroc_msp': metrics['ood_auroc_msp']}
        result.append({'seed': seed, 'train_sampling_sha256': sampling_hash,
                       'candidates': records})
    val_brier = {kind: sum(item['candidates'][kind]['validation']['brier'] for item in result) / len(result)
                 for kind in KINDS}
    selected = min(KINDS, key=lambda kind: val_brier[kind])
    return {'experiment': 'E2_EQUAL_PARAMETERS_NONLINEAR',
            'evidence_class': 'RETROSPECTIVE_RESEARCH_ONLY',
            'production_admission': 'BLOCKED', 'causal_learning_verified': False,
            'ndu_verified': False, 'selection_authorized': False,
            'parameter_count': result[0]['candidates']['dynamic_gate']['parameter_count'],
            'max_parameter_budget': budget, 'same_initial_parameters': True,
            'same_train_only_normalization': True,
            'training_steps': steps, 'training_batch': batch, 'learning_rate': lr,
            'validation_only_descriptive_winner': selected,
            'future_used_to_select_winner': False, 'validation_mean_brier': val_brier,
            'runs': result,
            'warning': 'Held-out future results here are retrospective, untrusted, not independently precommitted NDU evidence.'}