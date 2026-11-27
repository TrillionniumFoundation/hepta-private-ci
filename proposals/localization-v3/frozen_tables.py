"""Exact memoization of unchanged tables for explicitly frozen physics only.

The numerical operator is unchanged. Cache identity includes exact float64
duration and physical tensor bytes, grid/rewards, dtype/device and fixed buffer
bytes. No interpolation, time rounding, numerical repair or cross-fit reuse is
performed. Loading any state dict clears the cache, including best-checkpoint
selection. Construction and rebuild time remain inside the fit's measured cost.
"""

from collections import OrderedDict
from dataclasses import fields
import json
import math
import time

import torch
from qualification.hcsn_differentiable.operator import (
    DifferentiableDistributionOperator,
)


def _tensor_identity(tensor):
    if not isinstance(tensor, torch.Tensor):
        raise ValueError("frozen cache physical parameters must be tensors")
    if tensor.requires_grad:
        raise ValueError("frozen table cache rejects differentiable physics")
    return (
        str(tensor.dtype),
        str(tensor.device),
        tuple(tensor.shape),
        tensor.detach().cpu().contiguous().numpy().tobytes(),
    )


def _table_payload_bytes(table):
    # Tensor views such as risk=rewards[:,0] share storage. Count unique storage.
    storages = {}
    for field in fields(table):
        value = getattr(table, field.name)
        if isinstance(value, torch.Tensor):
            storage = value.untyped_storage()
            storages[(str(value.device), storage.data_ptr())] = storage.nbytes()
    return sum(storages.values())


class FrozenTableOperator(DifferentiableDistributionOperator):
    """Same physical configuration and arithmetic, bounded per-instance cache."""

    def __init__(self, *args, max_entries=512, **kwargs):
        super().__init__(*args, **kwargs)
        if type(max_entries) is not int or not 1 <= max_entries <= 1024:
            raise ValueError("max_entries must be an integer in [1,1024]")
        self.max_entries = max_entries
        self._tables = OrderedDict()
        self.hits = self.misses = self.evictions = self.clears = 0
        self.build_seconds = 0.0
        self.payload_bytes = self.peak_payload_bytes = 0

    def clear_cache(self):
        self._tables.clear()
        self.payload_bytes = 0
        self.clears += 1

    def _load_from_state_dict(self, *args, **kwargs):
        self.clear_cache()
        return super()._load_from_state_dict(*args, **kwargs)

    def cache_receipt(self):
        return {
            "mode": "exact_frozen_table_memoization",
            "max_entries": self.max_entries,
            "entries": len(self._tables),
            "hits": self.hits,
            "misses": self.misses,
            "evictions": self.evictions,
            "clears": self.clears,
            "build_seconds": self.build_seconds,
            "resident_table_tensor_bytes": self.payload_bytes,
            "peak_table_tensor_bytes": self.peak_payload_bytes,
            "bytes_scope": "unique table tensor storages; excludes Python keys and allocator overhead",
            "cold_start_per_fit": True,
            "checkpoint_load_clears_cache": True,
            "physical_operator_qualification_extended": False,
        }

    def forward(self, log_boundary, mu, sigma, absolute_reset, dt, discount):
        physical = (log_boundary, mu, sigma, absolute_reset, discount)
        identities = tuple(_tensor_identity(value) for value in physical)
        if isinstance(dt, torch.Tensor):
            if dt.numel() != 1 or dt.requires_grad:
                raise ValueError("table dt must be fixed scalar data")
            duration = float(dt.detach().cpu())
        elif isinstance(dt, bool) or not isinstance(dt, (int, float)):
            raise ValueError("table dt must be a finite real")
        else:
            duration = float(dt)
        if not math.isfinite(duration) or not 0 <= duration <= self.grid.refractory:
            raise ValueError("table duration outside declared fixed grid")
        geometry = json.dumps(
            super().configuration(), sort_keys=True, separators=(",", ":")
        )
        buffers = tuple(
            (name, _tensor_identity(value)) for name, value in self.named_buffers()
        )
        key = (duration.hex(), identities, geometry, buffers)
        if key in self._tables:
            self.hits += 1
            self._tables.move_to_end(key)
            return self._tables[key][0]
        started = time.perf_counter()
        try:
            table = super().forward(
                log_boundary, mu, sigma, absolute_reset, dt, discount
            )
        finally:
            self.build_seconds += time.perf_counter() - started
        if any(
            isinstance(getattr(table, field.name), torch.Tensor)
            and getattr(table, field.name).requires_grad
            for field in fields(table)
        ):
            raise ValueError("differentiable table cannot enter frozen cache")
        self.misses += 1
        payload = _table_payload_bytes(table)
        if len(self._tables) >= self.max_entries:
            _, (_, removed_bytes) = self._tables.popitem(last=False)
            self.payload_bytes -= removed_bytes
            self.evictions += 1
        self._tables[key] = (table, payload)
        self.payload_bytes += payload
        self.peak_payload_bytes = max(self.peak_payload_bytes, self.payload_bytes)
        return table
