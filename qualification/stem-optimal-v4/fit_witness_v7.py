"""Immutable FIT-only original-embedding witness; no heldout targets or future observations.

This records a frozen 64x384 FP32 *producer output*, not a substitute for a
second real model forward or a signed model-origin receipt.  The independent
observer must reconstruct the LOO calibration without importing this module.
"""
from __future__ import annotations

import hashlib
import math
import struct

SCHEMA = 'hepta.stem.fit-feature-witness-fp32.v7'
SOURCE_DIGEST_DOMAIN = b'hepta.stem.cal-fit-fp32.v5\0'
ROWS, WIDTH = 64, 384


def need(ok, reason):
    if not ok:
        raise ValueError(reason)


def build(source, fit_features, calibration, *, source_weight_sha256, projection):
    import torch
    need(type(source) is dict and type(source.get('train')) is list and
         len(source['train']) == ROWS and type(source.get('source_plan_sha256')) is str,
         'registered original FIT source absent')
    need(type(fit_features) is torch.Tensor and fit_features.shape == (ROWS, WIDTH)
         and fit_features.dtype == torch.float32
         and fit_features.device.type == 'cpu'
         and bool(torch.isfinite(fit_features).all()),
         'not original bounded FP32 FIT feature tensor')
    need(type(calibration) is dict and type(calibration.get('train_feature_digest')) is str
         and type(calibration.get('fit_examples')) is int
         and calibration['fit_examples'] == ROWS,
         'not the FIT-only calibration control')
    need(type(source_weight_sha256) is str and len(source_weight_sha256) == 64 and
         type(projection) is str and 0 < len(projection) <= 128,
         'missing frozen model/projection source')
    rows, labels, payload = [], [], bytearray()
    data = fit_features.detach().contiguous().tolist()
    for original, vector in zip(source['train'], data):
        need(type(original) is dict and set(original) ==
             {'case_id','source_sha256','text','label'}, 'FIT source content leak/absence')
        label = original['label']
        need(type(label) is int and 0 <= label <= 3,
             'missing or invalid original TRAIN label')
        need(type(vector) is list and len(vector) == WIDTH and
             all(type(x) is float and math.isfinite(x) and -1.01 <= x <= 1.01 for x in vector),
             'out of bounds FIT feature')
        need(abs(sum(x*x for x in vector) - 1) < 2e-3, 'not normalized frozen FIT feature')
        payload.extend(struct.pack('<384f', *vector))
        labels.append(label)
        rows.append({'case_id':original['case_id'],
                     'source_sha256':original['source_sha256'], 'fp32':vector})
    counts = [labels.count(i) for i in range(4)]
    need(counts == [16]*4, 'FIT original sample balance')
    h = hashlib.sha256()
    h.update(SOURCE_DIGEST_DOMAIN)
    h.update(payload)
    h.update(bytes(labels))
    need(h.hexdigest() == calibration['train_feature_digest'],
         'original runtime FIT calibration witness digest mismatch')
    return {'schema':SCHEMA, 'source_plan_sha256':source['source_plan_sha256'],
            'model_weights_sha256':source_weight_sha256,
            'feature_projection':projection, 'rows':rows,
            'train_feature_digest':h.hexdigest(),
            'label_free_heldout':True, 'model_origin_independently_attested':False,
            'production_authorized':False}
