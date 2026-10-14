"""Opt-in CPU FP32 formulas for the four operators observed in the public probe.

Matmul counts two operations per multiply-accumulate, including vector and
broadcast batch cases: 2 * batch_outputs * M * N * K. Empty contraction is zero.
This is the existing dense arithmetic convention, not retired instructions.
Transpose views and CPU dtype/layout copies or conversions have zero floating
arithmetic under this profile, NOT zero bandwidth, allocation, latency or energy.
Only explicit overloads and supported CPU/strided dtype destinations are admitted.
V1/V2 formulas and old observations are not rewritten. Unknown work stays unknown.
"""
from itertools import zip_longest
from math import prod

import torch

from transformer_work import cost as previous_cost

PROFILE = 'hepta.cpu-eager-transformer-formula-work.v3'
_DTYPES = (torch.float32, torch.bool, torch.uint8, torch.int8,
           torch.int16, torch.int32, torch.int64)


def _tensor(value):
    return (isinstance(value, torch.Tensor) and value.device.type == 'cpu'
            and value.layout == torch.strided and value.dtype in _DTYPES
            and all(type(n) is int and n >= 0 for n in value.shape))


def _bind(args, kwargs, names, required, defaults):
    """Bind exact ATen overload arguments without tensor evaluation or execution."""
    if (len(args) > len(names) or set(kwargs) - set(names)
            or set(kwargs) & set(names[:len(args)])):
        return None
    values = {**defaults, **dict(zip(names, args)), **kwargs}
    return values if all(k in values for k in required) else None


def matmul_work(left, right):
    """Metadata-only dense FP32 work; None is unsupported, never a zero guess."""
    if (not _tensor(left) or not _tensor(right) or left.dtype != torch.float32
            or right.dtype != torch.float32 or left.ndim < 1 or right.ndim < 1):
        return None
    a = (1, *left.shape) if left.ndim == 1 else tuple(left.shape)
    b = (*right.shape, 1) if right.ndim == 1 else tuple(right.shape)
    if a[-1] != b[-2]:
        return None
    batches = []
    for x, y in zip_longest(reversed(a[:-2]), reversed(b[:-2]), fillvalue=1):
        if x != y and x != 1 and y != 1:
            return None
        # max(x,y) would be wrong for the valid broadcast of zero with one.
        batches.append(y if x == 1 else x)
    return 2 * prod(batches) * a[-2] * b[-1] * a[-1]


def cost(operator, args, kwargs):
    name = str(operator)
    if name == 'aten.matmul.default':
        values = _bind(args, kwargs, ('self', 'other'), ('self', 'other'), {})
        return None if values is None else matmul_work(values['self'], values['other'])
    if name == 'aten.numpy_T.default':
        values = _bind(args, kwargs, ('self',), ('self',), {})
        return 0 if values is not None and _tensor(values['self']) else None
    if name in ('aten.to.dtype', 'aten.to.dtype_layout'):
        if name == 'aten.to.dtype':
            names = ('self', 'dtype', 'non_blocking', 'copy', 'memory_format')
            required = ('self', 'dtype')
            defaults = dict(non_blocking=False, copy=False, memory_format=None)
        else:
            if len(args) > 1:  # All other fields are keyword-only in this overload.
                return None
            names = ('self', 'dtype', 'layout', 'device', 'pin_memory',
                     'non_blocking', 'copy', 'memory_format')
            required = ('self',)
            defaults = dict(dtype=None, layout=None, device=None, pin_memory=None,
                            non_blocking=False, copy=False, memory_format=None)
        values = _bind(args, kwargs, names, required, defaults)
        if values is None or not _tensor(values['self']):
            return None
        x = values['self']
        dtype = values['dtype']
        if dtype is None and name == 'aten.to.dtype':
            return None
        if dtype is not None and dtype not in _DTYPES:
            return None
        if values.get('layout') not in (None, torch.strided):
            return None
        device = values.get('device')
        if device is not None:
            try:
                if torch.device(device).type != 'cpu':
                    return None
            except (TypeError, RuntimeError):
                return None
        if (values.get('pin_memory') not in (None, False)
                or any(type(values[k]) is not bool for k in ('non_blocking', 'copy'))):
            return None
        memory = values['memory_format']
        if memory not in (None, torch.preserve_format, torch.contiguous_format,
                          torch.channels_last, torch.channels_last_3d):
            return None
        if (memory == torch.channels_last and x.ndim != 4
                or memory == torch.channels_last_3d and x.ndim != 5):
            return None
        return 0
    return previous_cost(operator, args, kwargs)
