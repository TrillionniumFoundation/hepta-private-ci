"""Scoped measurement of real model-module forwards for offline Encoder experiments.

Counts PyTorch module forward entry/completion, rows and padded token slots.
It does NOT prove GPU kernels, physical sharing in the Rust Worker, execution
entitlement, data-use approval, or independent production receipts.
"""
from __future__ import annotations

from typing import Any

import torch
from torch import Tensor, nn


class EncoderModuleForwardMeter:
    """Synchronous, single-threaded offline accounting, scoped to one model.

    Hooks are removed on *every* context exit, including failed inference.
    The prehook counts an attempt even if model forward later raises; the
    successful posthook counts a completion. No input tensors or raw text
    are retained beyond the hook invocation.
    """

    def __init__(self, model: nn.Module):
        if not isinstance(model, nn.Module):
            raise TypeError('a PyTorch model module is required')
        self.model = model
        self.attempts = 0
        self.completions = 0
        self.attempted_rows = 0
        self.completed_rows = 0
        self.attempted_padded_token_slots = 0
        self.completed_padded_token_slots = 0
        self._pending: list[tuple[int, int]] = []
        self._handles: list[Any] = []
        self._entered = False

    def _before(self, _module: nn.Module, args: tuple, kwargs: dict) -> None:
        tokens = kwargs.get('input_ids')
        if tokens is None and args:
            tokens = args[0]
        if not isinstance(tokens, Tensor) or tokens.ndim != 2:
            raise ValueError('cannot account for model forward without rank-2 input_ids')
        rows, sequence = tokens.shape
        if rows < 1 or sequence < 1:
            raise ValueError('empty Encoder forward input')
        # Use shape only: summing a GPU attention mask would force a device sync
        # and change the timing and concurrency of the experiment itself.
        self.attempts += 1
        self.attempted_rows += rows
        padded = rows * sequence
        self.attempted_padded_token_slots += padded
        self._pending.append((rows, padded))

    def _after(self, _module: nn.Module, _args: tuple, _kwargs: dict, _output: Any) -> None:
        if not self._pending:
            raise RuntimeError('unpaired model-forward completion')
        rows, padded = self._pending.pop()
        self.completions += 1
        self.completed_rows += rows
        self.completed_padded_token_slots += padded

    def __enter__(self) -> 'EncoderModuleForwardMeter':
        if self._entered:
            raise RuntimeError('meter cannot be entered twice')
        self._entered = True
        try:
            self._handles.append(self.model.register_forward_pre_hook(self._before, with_kwargs=True))
            self._handles.append(self.model.register_forward_hook(self._after, with_kwargs=True))
        except Exception:
            self._remove()
            raise
        return self

    def _remove(self) -> None:
        for handle in reversed(self._handles):
            handle.remove()
        self._handles.clear()

    def __exit__(self, _type, _value, _traceback) -> None:
        self._remove()

    def receipt(self) -> dict[str, Any]:
        return {
            'meter_kind': 'PYTORCH_MODULE_FORWARD_OBSERVATION',
            'module_forward_attempts': self.attempts,
            'module_forward_completions': self.completions,
            'module_forward_failures_or_incomplete': self.attempts - self.completions,
            'rows_attempted': self.attempted_rows,
            'rows_completed': self.completed_rows,
            'padded_token_slots_attempted': self.attempted_padded_token_slots,
            'padded_token_slots_completed': self.completed_padded_token_slots,
            'physical_gpu_kernels_verified': False,
            'production_worker_execution_verified': False,
            'independent_signature_verified': False,
            'production_admission': 'BLOCKED',
            'warning': ('Only model __call__ is counted. Model submodule forwards, GPU kernels, '
                        'asynchronous errors and real memory are not verified.'),
        }
