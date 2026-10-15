"""Independent NumPy scalar/probability oracle for E2 frozen Token Matrix Heads.

This implementation does NOT invoke the producer's PyTorch Head, trainer, or
fused softmax. Safe tensor state and case-bound features are supplied only after
an upstream verifier's source/digest checks. It grants no model authority.
"""
from __future__ import annotations

import math

import numpy as np
import torch

ARMS = ('pooled_linear', 'pooled_gated', 'token_query')
TEMPERATURES = (0.5, 0.75, 1., 1.5, 2., 3., 4.)
MAX_DEVIATION = 2e-5


class Invalid(ValueError):
    pass


def _as_array(obj: torch.Tensor, shape: tuple[int, ...]) -> np.ndarray:
    if (not isinstance(obj, torch.Tensor) or obj.device.type != 'cpu'
            or obj.dtype != torch.float32 or tuple(obj.shape) != shape):
        raise Invalid('unregistered original Q24/Head shape or dtype')
    array = obj.detach().numpy().astype(np.float64)
    if not np.isfinite(array).all():
        raise Invalid('nonfinite Q24/Head value')
    return array


def _positive_logit(kind: str, head: dict, snapshot: dict, width: int) -> float:
    """Independent, variable-length NumPy forward — never pads or masks tokens."""
    if kind not in ARMS or width not in (384, 768) or type(head) is not dict:
        raise Invalid('unregistered oracle Head kind or width')
    keys = {'readout', 'bias'}
    if kind == 'pooled_gated':
        keys.add('gate')
    if kind == 'token_query':
        keys.add('query')
    if set(head) != keys or type(snapshot) is not dict or set(snapshot) != {'tokens','native_pooled'}:
        raise Invalid('missing or extra original Head/snapshot tensor')
    readout = _as_array(head['readout'], (width,))
    bias = float(_as_array(head['bias'], ()))
    pooled = _as_array(snapshot['native_pooled'], (width,))
    if kind == 'token_query':
        q = _as_array(head['query'], (width,))
        raw = snapshot['tokens']
        if (not isinstance(raw, torch.Tensor) or raw.ndim != 2 or
                not 1 <= raw.shape[0] <= 512):
            raise Invalid('noncanonical unpadded oracle Token Matrix')
        tokens = _as_array(raw, (raw.shape[0], width))
        token_logits = (tokens @ q) * math.sqrt(width)
        # Explicit stabilized unpadded softmax and token-weighted query.
        w = np.exp(token_logits - np.max(token_logits))
        w /= np.sum(w)
        value = np.sum(tokens * w[:, None], axis=0)
        norm = float(np.linalg.norm(value))
        if norm <= 1e-12 or not math.isfinite(norm):
            raise Invalid('degenerate retrieved attention feature')
        value /= norm
        logit = float(np.dot(value, readout)) + bias
    else:
        weighted = float(np.dot(pooled, readout))
        if kind == 'pooled_gated':
            gate = _as_array(head['gate'], (width,))
            z = float(np.dot(pooled, gate)) * math.sqrt(width)
            # Stable sigmoid, independently from torch.sigmoid.
            factor = 1. / (1. + math.exp(-z)) if z >= 0 else math.exp(z) / (1. + math.exp(z))
            weighted *= factor
        logit = weighted + bias
    if not math.isfinite(logit):
        raise Invalid('nonfinite independent log-odds')
    return logit


def _binary_prob(logit: float, temperature: float) -> float:
    z = logit / temperature
    return 1. / (1. + math.exp(-z)) if z >= 0 else math.exp(z) / (1. + math.exp(z))


def review(cases: list[dict], snapshots: dict, heads: dict, report: dict, width: int) -> dict:
    """Replay all six E2 Heads against 96 source cases without PyTorch forward."""
    if width not in (384, 768) or type(report) is not dict or set(report.get('arms',{})) != set(ARMS):
        raise Invalid('incomplete registered E2 original report')
    if type(cases) is not list or len(cases) != 224 or type(snapshots) is not dict:
        raise Invalid('incomplete registered E2 cohort')
    scored = [r for r in cases if r.get('split') in ('calibration','test')]
    calibration = [r for r in scored if r['split']=='calibration']
    if len(scored) != 96 or len(calibration) != 32:
        raise Invalid('missing original E2 CAL/TEST partitions')
    if len({r['case_id'] for r in cases}) != 224 or set(snapshots) != {r['case_id'] for r in cases}:
        raise Invalid('nonpaired original source')
    max_error = 0.
    checked = 0
    for kind in ARMS:
        arm=report['arms'][kind]
        for state,prediction_key,temp_key in (
            ('frozen','frozen_predictions','frozen_calibration_temperature'),
            ('learned','predictions','calibration_temperature')):
            prefix=f'{kind}.{state}.'
            names={'readout','bias'} | ({'gate'} if kind=='pooled_gated' else set()) | ({'query'} if kind=='token_query' else set())
            expected={prefix+n for n in names}
            if not expected.issubset(heads):
                raise Invalid('missing original serialized NumPy oracle Head state')
            weights={n:heads[prefix+n] for n in names}
            temperatures=arm.get(temp_key)
            if temperatures not in TEMPERATURES:
                raise Invalid('unregistered E2 calibration temperature')
            logits={r['case_id']:_positive_logit(kind,weights,snapshots[r['case_id']],width) for r in scored}
            objectives={t:sum(np.logaddexp(0.,logits[r['case_id']]/t) -
                              r['label']*logits[r['case_id']]/t for r in calibration)/len(calibration)
                        for t in TEMPERATURES}
            best=min(TEMPERATURES,key=lambda t:objectives[t])
            if best != temperatures and objectives[temperatures]-objectives[best] > 1e-6:
                raise Invalid('independent NumPy calibration differs materially')
            prediction_rows=arm.get(prediction_key)
            if type(prediction_rows) is not list or len(prediction_rows) != 96:
                raise Invalid('missing frozen/learned original oracle probabilities')
            observed={p.get('case_id'):p for p in prediction_rows if type(p) is dict}
            if len(observed)!=96 or set(observed)!={r['case_id'] for r in scored}:
                raise Invalid('duplicated or swapped E2 oracle predictions')
            for row in scored:
                p=observed[row['case_id']]
                if p.get('joint_input_digest') != row['joint_input_digest'] or p.get('split') != row['split']:
                    raise Invalid('source identity changed in NumPy oracle')
                stored=p.get('positive_probability')
                if type(stored) not in (float,int) or not math.isfinite(stored) or not 0<=stored<=1:
                    raise Invalid('invalid submitted E2 oracle probability')
                independent=_binary_prob(logits[row['case_id']],temperatures)
                error=abs(float(stored)-independent)
                if error > MAX_DEVIATION:
                    raise Invalid('NumPy independent probability does not match reported PyTorch Head')
                max_error=max(max_error,error)
                checked+=1
    return {'schema':'hepta.stem.e2-numpy-oracle.v1',
            'verified_head_states':6,'verified_original_probabilities':checked,
            'max_probability_absolute_error':max_error,
            'matched_calibration_only_temperature':True,
            'independent_numpy_forward_not_producer_torch_head':True,
            'pretrained_model_origin_authenticated':False,
            'future_ndu_verified':False,'production_promotion_permitted':False,
            'authority':'DENY_ALL'}
