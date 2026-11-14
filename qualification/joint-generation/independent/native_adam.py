"""Bound adaptation-only Adam; original per-element math with fewer temporaries.

Arithmetic inventories remain the original optimizer inventory. Binding and
allocation are real billed setup CPU; ``setup_work`` quotes its one finite scan.
This module never compiles, changes the public model optimizer, or trains data.
"""

import ctypes
from pathlib import Path

import numpy as np

from independent.learning import CONTENT_PARAMETERS
from model import JointModel


_DOUBLE = ctypes.POINTER(ctypes.c_double)
_POINTERS = _DOUBLE * len(CONTENT_PARAMETERS)
_SIZES = ctypes.c_size_t * len(CONTENT_PARAMETERS)
_SCALARS = ctypes.c_double * len(CONTENT_PARAMETERS)


def _array(value, shape):
    if (not isinstance(value, np.ndarray) or value.dtype != np.float64
            or value.shape != shape or not value.flags.c_contiguous
            or not value.flags.writeable):
        raise ValueError("owned writable contiguous float64 optimizer arrays required")
    return value


def _metadata(model):
    if (not isinstance(model, JointModel) or hasattr(model, "ledger")
            or tuple(model.dimensions[:3]) != (202, 12, 192)
            or len(model.dimensions) != 4 or not 1 <= model.dimensions[3] <= 512
            or not isinstance(model.params, dict) or not isinstance(model._moments, dict)
            or type(model.updates) is not int or not 0 <= model.updates < 2**63 - 1):
        raise ValueError("plain bounded content model required")
    d, k, _, h = model.dimensions
    shapes = ((d, h), (h,), (h, k), (k,), (h, k), (k,))
    rows = []
    for key, shape in zip(CONTENT_PARAMETERS, shapes):
        param = _array(model.params.get(key), shape)
        moment = model._moments.get(key)
        if key in model._moments and moment is None:
            raise ValueError("missing moment tuple required for an uninitialized group")
        if moment is not None:
            if (not isinstance(moment, tuple) or len(moment) != 3
                    or type(moment[2]) is not int or not 0 <= moment[2] < 2**63 - 1):
                raise ValueError("valid per-parameter Adam clock required")
            _array(moment[0], shape)
            _array(moment[1], shape)
        rows.append((key, param, moment))
    return rows


def setup_work(model, *, empty_moments=False):
    """One initial finite scan of content parameters and existing moments."""
    if type(empty_moments) is not bool:
        raise ValueError("boolean empty-copy inventory profile required")
    return {"compare_ops": sum(param.size * (1 if empty_moments or moment is None else 3)
                               for _, param, moment in _metadata(model))}


def _pointer(array):
    return array.ctypes.data_as(_DOUBLE)


class NativeAdam:
    """Bind six content groups to one model, retaining moment array lifetimes.

    The owning runner charges ``setup_work(model)`` before construction. New zero
    moments are private until the first successful update; pre-existing moments
    and all parameter identities must remain bound for the adapter's lifetime.
    """

    def __init__(self, model, library_path):
        rows = _metadata(model)
        if any(not np.isfinite(value).all() for _, param, moment in rows
               for value in ((param,) if moment is None else (param, moment[0], moment[1]))):
            raise ValueError("finite initial optimizer state required")
        self._library = ctypes.CDLL(str(Path(library_path).resolve()))
        try:
            self._function = self._library.hepta_adam_content_v1
        except AttributeError as error:
            raise RuntimeError("native library lacks hepta_adam_content_v1") from error
        self._function.argtypes = [ctypes.c_size_t] + [ctypes.POINTER(_DOUBLE)] * 4 + [
            ctypes.POINTER(ctypes.c_size_t), ctypes.POINTER(ctypes.c_double),
            ctypes.POINTER(ctypes.c_double), ctypes.c_double, ctypes.c_double]
        self._function.restype = ctypes.c_int
        self._model, self._params_map, self._moments_map = model, model.params, model._moments
        self._params, self._first, self._second, self._clocks, self._published = [], [], [], [], []
        for _, param, moment in rows:
            self._params.append(param)
            self._first.append(np.zeros_like(param) if moment is None else moment[0])
            self._second.append(np.zeros_like(param) if moment is None else moment[1])
            self._clocks.append(0 if moment is None else moment[2])
            self._published.append(moment is not None)
        arrays = self._params + self._first + self._second
        self._addresses = [value.ctypes.data for value in arrays]
        ranges = sorted((value.ctypes.data, value.ctypes.data + value.nbytes) for value in arrays)
        if any(right[0] < left[1] for left, right in zip(ranges, ranges[1:])):
            raise ValueError("optimizer state arrays must not overlap")
        self._state_ranges = tuple(ranges)
        self._parameter_pointers = _POINTERS(*map(_pointer, self._params))
        self._first_pointers = _POINTERS(*map(_pointer, self._first))
        self._second_pointers = _POINTERS(*map(_pointer, self._second))
        self._sizes = _SIZES(*(value.size for value in self._params))

    def _check_binding(self, model):
        if (model is not self._model or model.params is not self._params_map
                or model._moments is not self._moments_map):
            raise ValueError("optimizer is bound to one unchanged model state")
        for index, (key, param, moment) in enumerate(_metadata(model)):
            if param is not self._params[index]:
                raise ValueError("bound optimizer parameter was replaced")
            if self._published[index]:
                if (moment is None or moment[0] is not self._first[index]
                        or moment[1] is not self._second[index] or moment[2] != self._clocks[index]):
                    raise ValueError("bound optimizer moment or clock was replaced")
            elif moment is not None:
                raise ValueError("bound optimizer moment was added externally")
        arrays = self._params + self._first + self._second
        if any(value.ctypes.data != address for value, address in zip(arrays, self._addresses)):
            raise ValueError("bound optimizer storage address changed")

    def apply_gradients(self, model, grads, lr):
        self._check_binding(model)
        if (not np.isfinite(lr) or not 0 < lr <= 1
                or set(grads) != set(CONTENT_PARAMETERS)):
            raise ValueError("complete content gradients and valid learning rate required")
        clean = {}
        # Preserve the caller's dict order in the original norm reduction.
        for key, grad in grads.items():
            g = np.asarray(grad, dtype=np.float64)
            if g.shape != model.params[key].shape or not np.isfinite(g).all():
                raise ValueError("invalid parameter gradient")
            clean[key] = g
        norm = np.sqrt(sum(float(np.sum(g * g)) for g in clean.values()))
        scale = min(1.0, 5.0 / max(norm, 1e-300))
        first = _SCALARS(*(1 - 0.9 ** (clock + 1) for clock in self._clocks))
        second = _SCALARS(*(1 - 0.999 ** (clock + 1) for clock in self._clocks))
        contiguous = [np.ascontiguousarray(clean[key]) for key in CONTENT_PARAMETERS]
        gradient_ranges = [(g.ctypes.data, g.ctypes.data + g.nbytes) for g in contiguous]
        if any(first < stop and start < last
               for first, last in gradient_ranges for start, stop in self._state_ranges):
            raise ValueError("gradient arrays must not overlap bound optimizer state")
        pointers = _POINTERS(*map(_pointer, contiguous))
        status = self._function(len(CONTENT_PARAMETERS), self._parameter_pointers,
            self._first_pointers, self._second_pointers, pointers, self._sizes,
            first, second, scale, lr)
        if status:
            raise ValueError("native Adam ABI preflight rejected " + str(status))
        for index, key in enumerate(CONTENT_PARAMETERS):
            self._clocks[index] += 1
            self._published[index] = True
            model._moments[key] = (self._first[index], self._second[index], self._clocks[index])
        model.updates += 1
