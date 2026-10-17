"""Train-only, leave-one-out centroid temperature control for frozen Stem features.

No heldout labels, no SGD, no learned model parameter and no tuning on TEST.
Centroid means and the temperature are fitted on registered FIT-only examples.
"""
from __future__ import annotations

import hashlib
import math
import struct
import time

PROFILE = 'hepta.stem.train-loo-centroid-calibration.v5'
TEMPERATURES = (1.0, 0.5, 0.25, 0.125, 0.0625, 0.03125, 0.015625)
FIT_SIZE = 64
HELD_SIZE = 32
CLASS_COUNT = 4


def need(ok, reason):
    if not ok:
        raise ValueError(reason)


def calculate(fit_features, fit_labels, held_features, held_source):
    import torch
    import torch.nn.functional as F

    start = time.perf_counter()
    need(type(fit_features) is torch.Tensor and fit_features.shape == (64, 384) and
         type(held_features) is torch.Tensor and held_features.shape == (32, 384) and
         fit_features.dtype is torch.float32 and held_features.dtype is torch.float32 and
         bool(torch.isfinite(fit_features).all()) and
         bool(torch.isfinite(held_features).all()), 'actual bounded source features')
    need(type(fit_labels) is list and len(fit_labels) == FIT_SIZE and
         all(type(label) is int and 0 <= label < CLASS_COUNT for label in fit_labels),
         'FIT labels only, no heldout gold')
    need(type(held_source) is list and len(held_source) == HELD_SIZE and
         all(type(row) is dict and set(row) == {'case_id', 'source_sha256', 'text'}
             for row in held_source), 'heldout source must be label-free')
    need(len({r['case_id'] for r in held_source}) == HELD_SIZE,
         'heldout case IDs must be unique')
    counts = [fit_labels.count(i) for i in range(CLASS_COUNT)]
    need(counts == [16, 16, 16, 16], 'original FIT per-class coverage')
    train = fit_features.detach().to('cpu').contiguous()
    held = held_features.detach().to('cpu').contiguous()
    labels = torch.tensor(fit_labels, dtype=torch.long)
    sums = torch.stack([train[labels == i].sum(0) for i in range(CLASS_COUNT)])
    prototypes = F.normalize(sums/counts[0], dim=-1)
    need(bool((prototypes.square().sum(-1) > 1e-7).all()), 'degenerate centroid')

    # Leave each TRAIN example out of its *own class* mean. It is never scored
    # against a centroid that includes its own embedding, avoiding the cheap
    # baseline's trivial self-similarity optimism.
    loo = []
    for idx, feature in enumerate(train):
        candidate_sums = sums.clone()
        own = fit_labels[idx]
        candidate_sums[own] -= feature
        divisors = torch.tensor([counts[i] - int(i == own) for i in range(CLASS_COUNT)],
                                dtype=torch.float32).unsqueeze(-1)
        c = F.normalize(candidate_sums / divisors, dim=-1)
        need(bool((c.square().sum(-1) > 1e-7).all()), 'degenerate LOO centroid')
        loo.append(feature @ c.T)
    loo_logits = torch.stack(loo)
    target = F.one_hot(labels, CLASS_COUNT).float()
    losses = []
    for temp in TEMPERATURES:
        prob = F.softmax(loo_logits / temp, dim=-1)
        loss = float(((prob-target).square().sum(-1)).mean().item())
        need(math.isfinite(loss) and 0 <= loss <= 2, 'nonfinite train-only loss')
        losses.append(loss)
    # Ties favor *less sharp* probabilities. This selection never looks at held.
    idx = min(range(len(TEMPERATURES)), key=lambda i: (losses[i], i))
    selected = TEMPERATURES[idx]
    scores = F.softmax((held @ prototypes.T) / selected, dim=-1)
    need(scores.shape == (32, 4) and bool(torch.isfinite(scores).all()),
         'invalid frozen TEST probability vectors')
    result = []
    for row, prediction in zip(held_source, scores.tolist()):
        result.append({'case_id':row['case_id'], 'source_sha256':row['source_sha256'],
                       'probabilities':prediction})
    # Bind to the exact 64 FP32 FIT features and labels without exporting them.
    source_hash = hashlib.sha256()
    source_hash.update(b'hepta.stem.cal-fit-fp32.v5\0')
    source_hash.update(memoryview(train.numpy()))
    source_hash.update(bytes(fit_labels))
    return {
        'schema':PROFILE,
        'selected_temperature':selected,
        'registered_temperatures':list(TEMPERATURES),
        'fit_only_loocv_multiclass_brier':losses,
        'fit_examples':FIT_SIZE, 'fit_per_class_counts':counts,
        'heldout_labels_used_for_calibration':False,
        'heldout_calibration_metric_selected':False,
        'new_head_sgd_steps':0,
        'train_feature_digest':source_hash.hexdigest(),
        'output_rows':result,
        'fit_and_output_wall_seconds_unattested':time.perf_counter()-start,
        'new_model_forward_calls':0,
        'production_authorized':False,
    }
