"""Physically executed, non-authorizing cached-pooled versus token-query CPU probe.

This measures frozen Head readout on ONE selected already-encoded observation.
It does not execute an Encoder, issue Final-use, prove Cell-safe cross-scope
sharing, measure isolated resident memory or qualify a production Worker batch.
"""
from __future__ import annotations

import hashlib
import math
import os
import statistics
import time
from typing import Any

import torch
from torch import Tensor
from torch.nn import functional as F

from .token_reader_v1 import CellHead, _audit, snapshot_sha256

MAX_HEAD_WEIGHTS_BYTES = 256 * 1024 * 1024
MAX_HEAD_CALLS = 65536


def _rss_bytes() -> int | None:
    """Current Linux process resident bytes (not isolated/peak arm memory)."""
    try:
        with open('/proc/self/statm', encoding='ascii') as fd:
            pages = int(fd.read().split()[1])
        return pages * os.sysconf('SC_PAGE_SIZE')
    except (OSError, IndexError, ValueError, AttributeError):
        return None


def cached_pooled_logits(head: CellHead, pooled: Tensor) -> Tensor:
    """Same exact gated CellHead math, with a pooled vector cached just once."""
    if pooled.ndim != 2 or pooled.shape[1] != head.query.shape[0]:
        raise ValueError('incompatible cached pooled vector')
    selected = pooled * (2.0 * torch.sigmoid(head.query))
    gate = 2.0 * torch.sigmoid(head.up(F.silu(head.down(selected))))
    return head.classifier(selected * gate)


def prepared_token_query_logits(head: CellHead, masked_tokens: Tensor, mask: Tensor) -> Tensor:
    """Avoid repeated input masking while still paying per-Cell query attention."""
    if (masked_tokens.ndim != 3 or mask.ndim != 2
            or tuple(mask.shape) != tuple(masked_tokens.shape[:2])
            or masked_tokens.shape[2] != head.query.numel()
            or not bool(mask.any(dim=1).all())):
        raise ValueError('incompatible prepared token matrix')
    attention = (masked_tokens @ head.query) / math.sqrt(masked_tokens.shape[-1])
    attention = attention.masked_fill(~mask, float('-inf')).softmax(dim=1)
    selected = torch.sum(attention.unsqueeze(-1) * masked_tokens, dim=1)
    gate = 2.0 * torch.sigmoid(head.up(F.silu(head.down(selected))))
    return head.classifier(selected * gate)


def _nearest_rank(values: list[float], fraction: float) -> float:
    ordered = sorted(values)
    return ordered[math.ceil(fraction * len(ordered)) - 1]


def _arm(heads: list[CellHead], kind: str, masked_tokens: Tensor,
         mask: Tensor, pooled: Tensor) -> float:
    total = torch.zeros((), dtype=torch.float32)
    for head in heads:
        if kind == 'pooled_cached':
            logits = cached_pooled_logits(head, pooled)
        elif kind == 'token_query_prepared':
            logits = prepared_token_query_logits(head, masked_tokens, mask)
        else:
            raise ValueError('unknown readout arm')
        total += logits.sum()
    return float(total)  # identical CPU synchronization semantics for both arms


def measure_cached_head_cost(tokens: Tensor, mask: Tensor, labels: Tensor,
                             rows: list[dict], pins: dict, expected_sha256: str, *,
                             cells: int = 8, rank: int = 8, rounds: int = 3,
                             warmups: int = 1, seed: int = 20261014) -> dict[str, Any]:
    """A readout-only process-local experiment using one shared frozen snapshot.

    The SAME physically independent CellHead objects and parameter tensors are
    read by each arm, and both arms reuse their respective preprocessed input.
    Models are NOT trained in this benchmark; the paired quality experiment is
    separate. Results are descriptive and are never evidence for promotion.
    """
    if (type(cells) is not int or not 1 <= cells <= 4096 or type(rank) is not int
            or not 1 <= rank <= 32 or type(rounds) is not int or not 1 <= rounds <= 128
            or type(warmups) is not int or not 0 <= warmups <= 16
            or cells * (2 * rounds + 2 * warmups) > MAX_HEAD_CALLS
            or type(seed) is not int or not 0 <= seed < 2**31):
        raise ValueError('bounded active Cell/call budget required')
    # Hard-bound inputs and preserve the model, lineage, scope and generation
    # identities even though these self-reported pins grant no authority.
    indices = _audit(tokens, mask, labels, rows, pins, expected_sha256)
    sample_index = int(indices['validation'][0])
    one = tokens[sample_index:sample_index + 1].detach()
    valid = mask[sample_index:sample_index + 1].detach()
    dimension = one.shape[-1]
    classes = len(rows[0]['options'])
    one_head_params = dimension + 2 * dimension * rank + dimension * classes + classes
    if cells * one_head_params * 4 > MAX_HEAD_WEIGHTS_BYTES:
        raise ValueError('Head bank would exceed the independent weight memory cap')
    baseline_rss = _rss_bytes()
    with torch.random.fork_rng(devices=[]):
        torch.manual_seed(seed)
        heads = [CellHead(dimension, rank, classes).eval() for _ in range(cells)]
    # One unique parameter bank, not one shared Head disguised as thousands.
    pointers = [p.data_ptr() for head in heads for p in head.parameters()]
    if len(pointers) != len(set(pointers)):
        raise ValueError('mutable parameter tensor unexpectedly shared across Cells')
    bank_rss = _rss_bytes()
    weights = sum(p.numel() * p.element_size() for head in heads for p in head.parameters())
    # The pooled control is optimized: one masked pooling reduction before all
    # Cell invocations; never recompute pooled features for each Cell.
    preparation_start = time.perf_counter_ns()
    masked = one.masked_fill(~valid.unsqueeze(-1), 0)
    pooled = masked.sum(1) / valid.sum(1, keepdim=True)
    prep_ns = time.perf_counter_ns() - preparation_start
    prepared_rss = _rss_bytes()
    # Enforce numerical equivalence with the original unoptimized CellHead
    # implementation on precisely the same input and SAME weights.
    with torch.inference_mode():
        for head in heads[:min(cells, 3)]:
            if not torch.allclose(cached_pooled_logits(head, pooled),
                                  head(one, valid, 'pooled_feature_gate'), atol=1e-6, rtol=1e-6):
                raise ValueError('pooled cache numerical parity mismatch')
            if not torch.allclose(prepared_token_query_logits(head, masked, valid),
                                  head(one, valid, 'token_query_gate'), atol=1e-6, rtol=1e-6):
                raise ValueError('token reader numerical parity mismatch')
        observations: dict[str, dict[str, Any]] = {}
        # Alternating order makes systematic first-arm bias visible, without
        # falsely claiming balanced cold-start or independent process RSS.
        samples: dict[str, list[float]] = {'pooled_cached': [], 'token_query_prepared': []}
        cpu_samples: dict[str, list[float]] = {'pooled_cached': [], 'token_query_prepared': []}
        outputs: dict[str, float] = {}
        for round_index in range(rounds + warmups):
            names = ('pooled_cached', 'token_query_prepared')
            if round_index % 2:
                names = tuple(reversed(names))
            for kind in names:
                wall0 = time.perf_counter_ns()
                cpu0 = time.process_time_ns()
                outputs[kind] = _arm(heads, kind, masked, valid, pooled)
                cpu_delta = (time.process_time_ns() - cpu0) / 1e6
                wall_delta = (time.perf_counter_ns() - wall0) / 1e6
                if round_index >= warmups:
                    samples[kind].append(wall_delta)
                    cpu_samples[kind].append(cpu_delta)
        for name, values in samples.items():
            observations[name] = {
                'rounds': len(values),
                'batch_wall_ms_min': min(values),
                'batch_wall_ms_median': statistics.median(values),
                'batch_wall_ms_p95': _nearest_rank(values, .95) if len(values) >= 20 else None,
                'batch_wall_ms_p99': _nearest_rank(values, .99) if len(values) >= 100 else None,
                'batch_process_cpu_ms_median': statistics.median(cpu_samples[name]),
                'wall_ms_samples': values,  # bounded by rounds <=128
                'logit_sum_checksum_sha256': hashlib.sha256(
                    repr(outputs[name]).encode('ascii')).hexdigest(),
            }
    if snapshot_sha256(tokens, mask, rows, pins) != expected_sha256:
        raise ValueError('shared token snapshot changed during readout benchmark')
    return {
        'experiment': 'E2_CACHED_POOL_VS_TOKEN_QUERY_COST_SHADOW_V1',
        'production_admission': 'BLOCKED', 'selection_authorized': False,
        'real_encoder_forward_measured_by_this_probe': False,
        'runtime_final_use_or_source_entitlement_verified': False,
        'independent_NDU_or_future_utility_verified': False,
        'physical_worker_batch_verified': False,
        'evidence_class': 'LOCAL_TORCH_CPU_READOUT_ONLY',
        'sample_source_split': 'validation',
        'snapshot_sha256': expected_sha256,
        'scope': {key: rows[0][key] for key in ('principal', 'purpose', 'organ_id', 'cell_id')},
        'generation': pins['generation'], 'authority_epoch': pins['authority_epoch'],
        'cell_count': cells, 'active_cell_count': cells,
        'head_parameters_per_cell': one_head_params,
        'independent_parameter_bank_bytes': weights,
        'cached_pooled_feature_bytes': pooled.numel() * pooled.element_size(),
        'prepared_full_token_bytes': masked.numel() * masked.element_size() + valid.numel(),
        'shared_feature_preparation_wall_ms': prep_ns / 1e6,
        'process_rss_before_head_bank_bytes': baseline_rss,
        'process_rss_after_head_bank_bytes': bank_rss,
        'process_rss_after_shared_preparation_bytes': prepared_rss,
        'rss_is_current_co_resident_process_not_isolated_per_arm': True,
        'torch_cpu_num_threads': torch.get_num_threads(),
        'benchmark_order_alternates_after_warmup': True,
        'rounds': rounds, 'warmups': warmups,
        'observations': observations,
        'warnings': [
            'Both readouts share initialized frozen Head weights, NOT trained candidate checkpoints.',
            'This is one precomputed observation with N serial CPU Head calls, NOT fused Worker batch.',
            'The Pooled arm reuses its one cached vector; the Token arm reuses a masked matrix.',
            'No true per-request queue latency, GPU peak, isolated arm RSS, Encoder or training cost.',
            'No causal learning/NDU, independent source authority, model selection or release.',
        ],
    }
