"""Independent train-only SGD reconstruction of research E2 Head checkpoints.

This verifies optimizer provenance only relative to supplied source, initial Head
and frozen features. It does NOT authenticate pretrained Encoder or production.
"""
from __future__ import annotations

import math
import torch
from torch.nn import functional as F

from e2_token_query_ablation import Head, _materialize

ARMS = ('pooled_linear', 'pooled_gated', 'token_query')
SEED = 20261015
STEPS = 40
LEARNING_RATE = 0.15
MAX_ABSOLUTE_PARAMETER_ERROR = 2e-6


class Invalid(ValueError):
    pass


def replay_sgd(cases: list[dict], snapshots: dict, serialized_heads: dict,
               observation: dict, width: int) -> dict:
    """Recompute 40 full-batch SGD updates without using producer's train API.

    The independent run starts at the published frozen initial state, which
    must also match the pre-registered random seed / zero gate/query biases.
    Candidate final tensors must agree with independently replayed updates.
    """
    if width not in (384, 768) or type(observation) is not dict:
        raise Invalid('unregistered independent E2 optimizer profile')
    if (observation.get('seed') != SEED or observation.get('steps') != STEPS or
            observation.get('learning_rate') != LEARNING_RATE or
            observation.get('optimizer') != 'full_batch_sgd' or
            observation.get('production_promotion_permitted') is not False or
            observation.get('authority') != 'DENY_ALL'):
        raise Invalid('unregistered optimization schedule or authority')
    bysplit = {split: [r for r in cases if r.get('split') == split]
               for split in ('train', 'calibration', 'test')}
    if tuple(len(bysplit[s]) for s in bysplit) != (128, 32, 64):
        raise Invalid('wrong independent train/calibration/holdout partitions')
    train = bysplit['train']
    if any(type(row.get('label')) is not int or row['label'] not in (0, 1)
           for row in train):
        raise Invalid('missing original train-only target labels')
    if type(serialized_heads) is not dict or set(serialized_heads) != set(ARMS):
        raise Invalid('incomplete original Head checkpoints')
    tokens, mask, pool = _materialize(train, snapshots, width)
    y = torch.tensor([r['label'] for r in train], dtype=torch.long)
    seed_gen = torch.Generator(device='cpu').manual_seed(SEED)
    common_init = torch.randn(width, generator=seed_gen) * (0.05 / math.sqrt(width))
    greatest = 0.0
    compared = 0
    for kind in ARMS:
        state = serialized_heads[kind]
        if type(state) is not dict or set(state) != {'frozen', 'learned'}:
            raise Invalid('missing before/after checkpoint')
        reference = Head(width, kind, common_init)
        saved_init = state['frozen']
        if set(saved_init) != set(reference.state_dict()):
            raise Invalid('frozen initial tensor inventory mismatch')
        for name, expected in reference.state_dict().items():
            initial = saved_init[name]
            if not (isinstance(initial, torch.Tensor) and initial.dtype == torch.float32 and
                    initial.device.type == 'cpu' and initial.shape == expected.shape and
                    torch.equal(initial, expected)):
                raise Invalid('frozen Head does not match registered seeded initialization')
        reference.load_state_dict(saved_init, strict=True)
        optimizer = torch.optim.SGD(reference.parameters(), lr=LEARNING_RATE)
        for _ in range(STEPS):
            optimizer.zero_grad(set_to_none=True)
            loss = F.cross_entropy(reference(tokens, mask, pool), y)
            if not bool(torch.isfinite(loss)):
                raise Invalid('nonfinite optimizer replay loss')
            loss.backward()
            optimizer.step()
        actual = state['learned']
        if set(actual) != set(reference.state_dict()):
            raise Invalid('missing learned Head tensor')
        for name, predicted in reference.state_dict().items():
            saved = actual[name]
            if not (isinstance(saved, torch.Tensor) and saved.dtype == torch.float32 and
                    saved.device.type == 'cpu' and saved.shape == predicted.shape and
                    bool(torch.isfinite(saved).all())):
                raise Invalid('noncanonical optimizer result tensor')
            error = float((saved - predicted).abs().max())
            if error > MAX_ABSOLUTE_PARAMETER_ERROR:
                raise Invalid('saved learned Head cannot be reproduced from registered train-only SGD')
            greatest = max(greatest, error)
            compared += saved.numel()
    return {'optimizer': 'SGD', 'steps_per_head': STEPS, 'heads_retrained': len(ARMS),
            'parameters_compared': compared, 'max_absolute_parameter_error': greatest,
            'source_independently_attested': False, 'future_ndu_verified': False,
            'production_promotion_permitted': False, 'authority': 'DENY_ALL'}
