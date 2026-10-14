"""A physical Torch CPU batched Cell-head *shadow*, not a Hepta Worker.

Pack distinct immutable Head parameter snapshots and evaluate many logical Cells
against one already-admitted observation. No Encoder forward, signature, CAS,
Q24 parity, final-use, selection or online training is performed here.
"""
from __future__ import annotations

import hashlib
import math
import statistics
import time
from typing import Any

import torch
from torch import Tensor
from torch.nn import functional as F

from .token_reader_v1 import CellHead, _audit, _tensor_storage_bytes, snapshot_sha256
from .token_reader_cost_v1 import cached_pooled_logits, prepared_token_query_logits

MAX_CELLS = 4096
MAX_PACKED_WEIGHT_BYTES = 128 * 1024 * 1024


def _finite_float32(tensor: Tensor) -> bool:
    return (isinstance(tensor, Tensor) and tensor.device.type == 'cpu'
            and tensor.dtype == torch.float32 and bool(torch.isfinite(tensor).all()))


class PackedCellHeadBankV1:
    """A read-only, per-Cell parameter bank with one native Tensor batch call.

    Construction physically stacks clones of selected Head tensors, so no Cell
    holds another Cell's mutable model parameter. No re-training or promotion
    can occur through the packed copy. Caller still owns source/final-use checks.
    """

    def __init__(self, heads: list[tuple[str, CellHead]]):
        if not isinstance(heads, list) or not 1 <= len(heads) <= MAX_CELLS:
            raise ValueError('bounded nonempty Cell bank required')
        seen = set()
        first = heads[0][1]
        if not isinstance(first, CellHead):
            raise ValueError('CellHead tensors required')
        dim = first.query.numel()
        rank = first.down.out_features
        classes = first.classifier.out_features
        if not 1 <= dim <= 768 or not 1 <= rank <= 32 or not 2 <= classes <= 16:
            raise ValueError('bounded Head dimensions required')
        expected_params = dim + 2 * dim * rank + dim * classes + classes
        if len(heads) * expected_params * 4 > MAX_PACKED_WEIGHT_BYTES:
            raise ValueError('packed Head bank exceeds memory cap')
        original_parameter_pointers = set()
        for cell_id, head in heads:
            if not isinstance(cell_id, str) or not 1 <= len(cell_id) <= 128 or cell_id in seen:
                raise ValueError('unique bounded Cell IDs required')
            seen.add(cell_id)
            if (not isinstance(head, CellHead) or head.query.numel() != dim
                    or head.down.in_features != dim or head.down.out_features != rank
                    or head.up.in_features != rank or head.up.out_features != dim
                    or head.classifier.in_features != dim
                    or head.classifier.out_features != classes):
                raise ValueError('incompatible Cell Head geometry')
            tensors = (head.query, head.down.weight, head.up.weight,
                       head.classifier.weight, head.classifier.bias)
            if any(not _finite_float32(p) for p in tensors):
                raise ValueError('nonfinite/unsupported Head parameter')
            if any(p.data_ptr() in original_parameter_pointers for p in tensors):
                raise ValueError('mutable Cell parameter alias refused')
            original_parameter_pointers.update(p.data_ptr() for p in tensors)
        self._cell_ids = tuple(cell_id for cell_id, _ in heads)
        self._dim, self._rank, self._classes = dim, rank, classes
        with torch.inference_mode():
            self._query = torch.stack([h.query.detach().clone() for _, h in heads]).contiguous()
            self._down = torch.stack([h.down.weight.detach().clone() for _, h in heads]).contiguous()
            self._up = torch.stack([h.up.weight.detach().clone() for _, h in heads]).contiguous()
            self._classifier = torch.stack([h.classifier.weight.detach().clone() for _, h in heads]).contiguous()
            self._bias = torch.stack([h.classifier.bias.detach().clone() for _, h in heads]).contiguous()
        self._weight_bytes = sum(t.numel() * t.element_size() for t in
                                 (self._query, self._down, self._up, self._classifier, self._bias))
        if self._weight_bytes != len(heads) * expected_params * 4:
            raise ValueError('physical packed bank parameter count mismatch')
        digest = hashlib.sha256(b'hepta.packed-cell-head.shadow.v1\0')
        digest.update(len(heads).to_bytes(4, 'big'))
        for name in self._cell_ids:
            raw = name.encode('utf-8')
            digest.update(len(raw).to_bytes(4, 'big'))
            digest.update(raw)
        for t in (self._query, self._down, self._up, self._classifier, self._bias):
            chunk = _tensor_storage_bytes(t)
            digest.update(len(chunk).to_bytes(8, 'big'))
            digest.update(chunk)
        self._bank_sha256 = digest.hexdigest()

    @property
    def cell_count(self) -> int:
        return len(self._cell_ids)

    @property
    def head_weight_bytes(self) -> int:
        return self._weight_bytes

    @property
    def bank_sha256(self) -> str:
        return self._bank_sha256

    def _classify(self, selected: Tensor) -> Tensor:
        hidden = torch.bmm(self._down, selected.unsqueeze(-1)).squeeze(-1)
        gate = 2.0 * torch.sigmoid(torch.bmm(
            self._up, F.silu(hidden).unsqueeze(-1)).squeeze(-1))
        return torch.bmm(self._classifier, (selected * gate).unsqueeze(-1)).squeeze(-1) + self._bias

    def execute(self, tokens: Tensor, mask: Tensor, *, kind: str) -> Tensor:
        """One shared [L,d] source, many Cell Heads; no per-Cell token clones."""
        if (not _finite_float32(tokens) or tokens.ndim != 2
                or tuple(tokens.shape)[1] != self._dim
                or not 1 <= len(tokens) <= 256
                or not isinstance(mask, Tensor) or mask.dtype != torch.bool
                or mask.device.type != 'cpu' or mask.ndim != 1
                or mask.shape[0] != tokens.shape[0] or not bool(mask.any())):
            raise ValueError('bounded compatible token observation/mask required')
        with torch.inference_mode():
            masked = tokens.masked_fill(~mask[:, None], 0)
            if kind == 'pooled_cached':
                pooled = masked.sum(0) / mask.sum()
                selected = pooled.unsqueeze(0) * (2 * torch.sigmoid(self._query))
            elif kind == 'token_query_prepared':
                attention = self._query @ masked.T / math.sqrt(self._dim)
                attention = attention.masked_fill(~mask[None, :], float('-inf')).softmax(1)
                selected = attention @ masked
            else:
                raise ValueError('unknown packed Head readout arm')
            return self._classify(selected)


def measure_packed_readout(tokens: Tensor, mask: Tensor, labels: Tensor,
                           rows: list[dict], pins: dict, expected_sha256: str,
                           *, cells: int = 64, rank: int = 8,
                           rounds: int = 3, warmups: int = 1,
                           seed: int = 20261014) -> dict[str, Any]:
    """Descriptive CPU comparison of serial vs packed inference; never production."""
    if (type(cells) is not int or not 1 <= cells <= MAX_CELLS
            or type(rank) is not int or not 1 <= rank <= 32
            or type(rounds) is not int or not 1 <= rounds <= 128
            or type(warmups) is not int or not 0 <= warmups <= 16
            or type(seed) is not int or not 0 <= seed < 2**31):
        raise ValueError('bounded Cell/readout benchmark controls required')
    by_split = _audit(tokens, mask, labels, rows, pins, expected_sha256)
    i = int(by_split['validation'][0])
    source, valid = tokens[i].detach(), mask[i].detach()
    dim, classes = source.shape[1], len(rows[0]['options'])
    parameters = dim + 2 * dim * rank + dim * classes + classes
    if cells * parameters * 4 > MAX_PACKED_WEIGHT_BYTES:
        raise ValueError('packed Head bank exceeds memory cap')
    with torch.random.fork_rng(devices=[]):
        torch.manual_seed(seed)
        scalar = [(f'cell-{i:04d}', CellHead(dim, rank, classes).eval()) for i in range(cells)]
    bank = PackedCellHeadBankV1(scalar)
    masked = source.masked_fill(~valid[:, None], 0)
    pooled = masked.sum(0, keepdim=True) / valid.sum()
    # Full bank parity BEFORE timing, not just the first few Cells.
    with torch.inference_mode():
        for kind in ('pooled_cached', 'token_query_prepared'):
            original = torch.cat([
                cached_pooled_logits(head, pooled) if kind == 'pooled_cached'
                else prepared_token_query_logits(head, masked[None, :, :], valid[None, :])
                for _, head in scalar], dim=0)
            packed = bank.execute(source, valid, kind=kind)
            if not torch.allclose(original, packed, rtol=1e-5, atol=1e-5):
                raise ValueError('packed/scalar numerical parity mismatch')
        samples: dict[str, list[float]] = {f'{mode}_{kind}': []
                for mode in ('serial', 'packed')
                for kind in ('pooled_cached', 'token_query_prepared')}
        names = tuple(samples)
        for j in range(rounds + warmups):
            # Rotating order reduces deterministic first/last cache advantage.
            scheduled = names[j % len(names):] + names[:j % len(names)]
            for arm in scheduled:
                mode, kind = arm.split('_', 1)
                start = time.perf_counter_ns()
                if mode == 'packed':
                    result = bank.execute(source, valid, kind=kind)
                else:
                    result = torch.cat([
                        cached_pooled_logits(head, pooled) if kind == 'pooled_cached'
                        else prepared_token_query_logits(head, masked[None, :, :], valid[None, :])
                        for _, head in scalar], dim=0)
                # CPU checksum gives both arms the same synchronization boundary.
                _ = result.sum().item()
                if j >= warmups:
                    samples[arm].append((time.perf_counter_ns() - start) / 1e6)
    if snapshot_sha256(tokens, mask, rows, pins) != expected_sha256:
        raise ValueError('frozen token snapshot changed during benchmark')
    return {
        'experiment': 'E2_PACKED_SHARED_HEAD_READOUT_SHADOW_V1',
        'evidence_class': 'LOCAL_CPU_NUMERIC_AND_TIMING_ONLY',
        'production_admission': 'BLOCKED', 'selection_authorized': False,
        'native_rust_worker_batch_verified': False,
        'independent_source_use_or_final_use_verified': False,
        'independent_future_NDU_verified': False,
        'actual_pretrained_encoder_called_in_this_probe': False,
        'physical_distinct_Cell_head_parameters': True,
        'no_per_Cell_token_feature_clone_in_packed_kernel': True,
        'full_Cell_bank_numerical_parity_checked': True,
        'common_weight_bank_for_all_comparisons': True,
        'weight_bank_sha256': bank.bank_sha256,
        'cell_count': cells, 'rank': rank,
        'parameters_per_cell': parameters,
        'packed_weight_bytes': bank.head_weight_bytes,
        'serial_and_packed_banks_co_resident_during_probe': True,
        'source_snapshot_sha256': expected_sha256,
        'rounds': rounds, 'warmups': warmups,
        'cpu_threads': torch.get_num_threads(),
        'timings': {k: {'raw_ms': v, 'median_ms': statistics.median(v),
                        'p95_ms': sorted(v)[math.ceil(.95 * len(v)) - 1] if len(v) >= 20 else None,
                        'p99_ms': sorted(v)[math.ceil(.99 * len(v)) - 1] if len(v) >= 100 else None}
                    for k, v in samples.items()},
        'warnings': [
            'Precomputed single observation, not a complete request/service latency.',
            'Encoder, per-Cell training, power and physical Worker/WAL are excluded.',
            'Python reference scalar baseline, not an optimized alternative batched backend.',
            'GPU kernels/target-host throughput and prospective future learning are unverified.',
        ],
    }
