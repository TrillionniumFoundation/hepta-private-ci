"""Numpy/ctypes bridge; all native execution keeps the same finite generator."""

import ctypes
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent
ERRORS = {1: "dimension", 2: "domain", 3: "generator", 4: "normalization", 5: "work_limit",
          6: "numerical", 7: "null_pointer", 8: "panic"}
DOUBLE_PTR = ctypes.POINTER(ctypes.c_double)


class NativeOperator:
    def __init__(self, library=None):
        self.path = Path(library or ROOT / "evidence" / "build" / "libhcsn_native.so")
        self.library = ctypes.CDLL(str(self.path.resolve()))
        self.library.propagate.argtypes = [ctypes.c_size_t, DOUBLE_PTR, ctypes.c_double, DOUBLE_PTR, DOUBLE_PTR]
        self.library.propagate.restype = ctypes.c_int
        self.library.observe.argtypes = [ctypes.c_size_t, DOUBLE_PTR, DOUBLE_PTR, DOUBLE_PTR]
        self.library.observe.restype = ctypes.c_int

    def raw_propagate(self, q, prior, dt):
        q, prior = np.ascontiguousarray(q, dtype=np.float64), np.ascontiguousarray(prior, dtype=np.float64)
        if prior.ndim != 1 or q.shape != (prior.size, prior.size):
            raise ValueError("Expected q[n,n] and prior[n]")
        result = np.full(prior.shape, -12345.0)
        code = self.library.propagate(prior.size, q.ctypes.data_as(DOUBLE_PTR), float(dt),
                                      prior.ctypes.data_as(DOUBLE_PTR), result.ctypes.data_as(DOUBLE_PTR))
        return code, result

    def propagate(self, q, prior, dt):
        code, result = self.raw_propagate(q, prior, dt)
        if code:
            raise ValueError(f"Native propagation refused: {ERRORS.get(code, code)}")
        return result

    def raw_observe(self, prior, likelihood):
        prior, likelihood = np.ascontiguousarray(prior, dtype=np.float64), np.ascontiguousarray(likelihood, dtype=np.float64)
        if prior.ndim != 1 or likelihood.shape != prior.shape:
            raise ValueError("Expected equal prior[n] and likelihood[n]")
        result = np.full(prior.shape, -12345.0)
        code = self.library.observe(prior.size, prior.ctypes.data_as(DOUBLE_PTR),
                                    likelihood.ctypes.data_as(DOUBLE_PTR), result.ctypes.data_as(DOUBLE_PTR))
        return code, result

    def observe(self, prior, likelihood):
        code, result = self.raw_observe(prior, likelihood)
        if code:
            raise ValueError(f"Native observation refused: {ERRORS.get(code, code)}")
        return result
