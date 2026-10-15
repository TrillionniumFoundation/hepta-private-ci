"""Torch-free reference forward for a frozen V6 42,562-weight BridgeReader.

Research-only numerical conformance. This module never loads the 97M Granite
Encoder and cannot establish natural-task quality, origin, NDU admission,
CellSplit, model promotion or execution authority. Inputs are already encoded
feature tensors, with explicit source/version provenance owned by the caller.

NumPy's CPU BLAS and math.erf have different floating-point reduction ordering
from Torch; numeric *tolerances*, not bitwise equality, are preregistered.
"""
from __future__ import annotations

import math

import numpy as np

from bridge_gradient_archive_replay import SHAPES, decode_fp32_checkpoint, require

MAX_BATCH = 32
MAX_FACTS = 32
MAX_TOKENS = 128
MAX_HOPS = 8
MAX_ALIGNMENT = 2_000_000
MAX_BRIDGE = 2_000_000


def weights_from_checkpoint(raw):
    """Return copied immutable FP32 values only after restricted ZIP decoding."""
    parsed = decode_fp32_checkpoint(raw, include_tensor_bytes=True)
    weights = {}
    for name, shape in SHAPES.items():
        value = np.frombuffer(parsed["tensor_bytes"][name], dtype="<f4").copy().reshape(shape)
        value.setflags(write=False)
        weights[name] = value
    # In particular, do not serialize the tensor_bytes mapping in metadata.
    return weights, {k: v for k, v in parsed.items() if k != "tensor_bytes"}


def _weights(w):
    require(type(w) is dict and set(w) == set(SHAPES), "complete registered Bridge weights required")
    for name, shape in SHAPES.items():
        t = w[name]
        require(type(t) is np.ndarray and t.shape == shape and t.dtype == np.float32
                and bool(np.isfinite(t).all()), "FP32 finite named Bridge tensor required")


def _linear(x, w, b=None):
    return np.matmul(x, w.T) + (b if b is not None else np.float32(0))


def _layer_norm(x):
    mean = np.mean(x, axis=-1, keepdims=True, dtype=np.float32)
    centered = x - mean
    var = np.mean(centered * centered, axis=-1, keepdims=True, dtype=np.float32)
    return centered / np.sqrt(var + np.float32(1e-5))


def _gelu(x):
    # Exact (not tanh-approx) nn.GELU. Explicit FP32 cast avoids float64 creep.
    cdf = np.vectorize(math.erf, otypes=[np.float32])(
        (x / np.float32(math.sqrt(2))).astype(np.float32))
    return (np.float32(.5) * x * (np.float32(1) + cdf)).astype(np.float32)


def _sigmoid(x):
    return np.float32(1) / (np.float32(1) + np.exp(-np.clip(x, -30, 30)))


def _tanh(x):
    return _sigmoid(x * np.float32(2)) * np.float32(2) - np.float32(1)


def _mean(x, mask):
    weight = mask.astype(np.float32)[..., None]
    return np.sum(x * weight, axis=-2) / np.maximum(np.sum(weight, axis=-2), np.float32(1))


def _attention(scores, mask):
    mask = np.broadcast_to(mask, scores.shape)
    x = np.where(mask, scores, np.float32(-10000))
    e = np.exp(x - x.max(axis=-1, keepdims=True)) * mask.astype(np.float32)
    return e / np.maximum(e.sum(axis=-1, keepdims=True), np.float32(1e-9))


def _features(features, masks, *, steps, state, feedback):
    require(isinstance(features, tuple) and len(features) == 3
            and isinstance(masks, tuple) and len(masks) == 3,
            "three feature tensors and three masks required")
    facts, question, candidate = features
    fm, qm, cm = masks
    require(all(type(v) is np.ndarray and v.dtype == np.float32
                and np.isfinite(v).all() for v in features),
            "finite FP32 encoded input tensors required")
    require(all(type(v) is np.ndarray and v.dtype == np.bool_ for v in masks),
            "boolean typed token masks required")
    require(facts.ndim == 4 and question.ndim == candidate.ndim == 3,
            "fact/question/candidate dimensions must remain distinct")
    b, f, t, d = facts.shape
    require(1 <= b <= MAX_BATCH and 1 <= f <= MAX_FACTS and
            1 <= t <= MAX_TOKENS and d == 384
            and 1 <= question.shape[1] <= MAX_TOKENS
            and 1 <= candidate.shape[1] <= MAX_TOKENS
            and question.shape == (b, question.shape[1], d)
            and candidate.shape == (b, candidate.shape[1], d)
            and fm.shape == (b, f, t) and qm.shape == question.shape[:-1]
            and cm.shape == candidate.shape[:-1], "bounded aligned feature/mask geometry required")
    require(b*f*t*(question.shape[1]+candidate.shape[1]) <= MAX_ALIGNMENT
            and b*f*f <= MAX_BRIDGE, "bounded attention work required")
    require(type(steps) is int and 1 <= steps <= MAX_HOPS,
            "bounded true hop count required")
    if state is not None:
        require(type(state) is np.ndarray and state.dtype == np.float32
                and state.shape == (b, 32) and bool(np.isfinite(state).all())
                and np.max(np.abs(state)) <= 1.000001,
                "finite bounded initial state required")
    if feedback is not None:
        require(type(feedback) is np.ndarray and feedback.dtype == np.float32
                and feedback.shape == (b, 4) and bool(np.isfinite(feedback).all()),
                "finite four-coordinate feedback required")


def bridge_forward(weights, features, masks, *, steps=3, state=None,
                   feedback=None, reset_state=False, return_trace=False):
    """Compute exact V6 BridgeReader operator graph, without Torch or labels."""
    _weights(weights)
    _features(features, masks, steps=steps, state=state, feedback=feedback)
    require(type(reset_state) is bool and type(return_trace) is bool,
            "explicit boolean model behavior required")
    facts, question, candidate = features
    fm, qm, cm = masks
    linear = lambda x, name: _linear(x, weights[name+".weight"], weights.get(name+".bias"))
    evidence, qtokens, atokens = (linear(_layer_norm(v), "project")
                                 for v in (facts, question, candidate))
    qmean, amean = _mean(qtokens, qm), _mean(atokens, cm)
    query = _tanh(linear(np.concatenate((qmean, amean, qmean*amean, qmean-amean),-1), "query"))
    aligned = []
    for tokens, mask in ((qtokens, qm),(atokens,cm)):
        scores = np.einsum("bftd,bqd->bftq", evidence, tokens, optimize=True) / np.float32(math.sqrt(32))
        att = _attention(scores, mask[:,None,None,:])
        aligned.append(np.einsum("bftq,bqd->bftd", att, tokens, optimize=True))
    qalign, aalign = aligned
    relations = _gelu(linear(np.concatenate((evidence, qalign, aalign,
        evidence*qalign, evidence*aalign, qalign*aalign,
        evidence-qalign, evidence-aalign), axis=-1), "relation"))
    # The cross-fact residual changes keys BEFORE any recurrent step.
    present = fm.any(axis=-1)
    summaries = _mean(relations,fm)
    q = linear(summaries,"fact_bridge.query")
    k = linear(summaries,"fact_bridge.key")
    v = linear(summaries,"fact_bridge.value")
    scores = np.matmul(q, np.swapaxes(k,-1,-2)) / np.float32(math.sqrt(32))
    mix = _attention(scores, present[:,None,:])
    message = linear(np.matmul(mix,v), "fact_bridge.output")
    relations = relations + (message * present[:,:,None].astype(np.float32))[:,:,None,:] * fm[:,:,:,None].astype(np.float32)
    keys = linear(relations, "token_key")
    if state is None:
        state = query.copy()
    if feedback is None:
        feedback = np.zeros((query.shape[0],4),dtype=np.float32)
    history = []
    for _ in range(steps):
        if reset_state:
            state = query.copy()
        lookup = linear(np.concatenate((query,state),axis=-1),"state_query")
        token_scores = linear(relations,"token_score")[...,0]
        token_scores += np.sum(keys*lookup[:,None,None,:],axis=-1) / np.float32(math.sqrt(32))
        token_att = _attention(token_scores, fm)
        reduced = np.sum(relations*token_att[...,None],axis=-2)
        fact_scores = linear(reduced,"fact_score")[...,0]
        fact_scores += np.sum(linear(reduced,"fact_key")*lookup[:,None,:],axis=-1) / np.float32(math.sqrt(32))
        fact_att = _attention(fact_scores,present)
        context = np.sum(reduced*fact_att[...,None],axis=1)
        update = np.concatenate((query,state,context,feedback),axis=-1)
        gate = _sigmoid(linear(update,"update_gate"))
        state = (np.float32(1)-gate)*state + gate*_tanh(linear(update,"proposal"))
        p = present.any(axis=-1).astype(np.float32)[:,None]
        head_input = np.concatenate((query,state,context,p),axis=-1)
        hidden = _gelu(linear(head_input, "head.0"))
        logits = linear(hidden, "head.2").astype(np.float32)
        require(bool(np.isfinite(logits).all()) and np.max(np.abs(state)) <= 1.000001,
                "finite bounded Reader execution required")
        if return_trace:
            history.append((state.copy(), logits.copy(), fact_att.copy(), token_att.copy()))
    if return_trace:
        return dict(logits=logits,state=state,steps=history,
                    pretrained_encoder_executed=False,semantic_accuracy_established=False)
    return logits
