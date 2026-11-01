"""Immutable native Q with exact time caching, reusable output buffers and batches."""

import ctypes
from pathlib import Path
import platform

import numpy as np

ROOT = Path(__file__).resolve().parent
DOUBLE = ctypes.POINTER(ctypes.c_double)
U64 = ctypes.POINTER(ctypes.c_uint64)
ERRORS = {1: "dimension", 2: "domain", 3: "generator", 4: "normalization", 5: "work_limit",
          6: "numerical", 7: "null_pointer", 8: "panic", 9: "invalid_handle",
          10: "model_version", 11: "cache_limit"}
MODES = {"sparse": 0, "dense": 1}


def _check(code):
    if code:
        raise ValueError(f"Native R13 refused: {ERRORS.get(code, code)}")


def _library(path):
    library = ctypes.CDLL(str(Path(path).resolve()))
    handle, size, version = ctypes.c_uint64, ctypes.c_size_t, ctypes.c_uint64
    signatures = {
        "hcsn_model_create": [size, DOUBLE, version, U64],
        "hcsn_model_release": [handle],
        "hcsn_model_identity": [handle, version, ctypes.POINTER(ctypes.c_ubyte)],
        "hcsn_prepare": [handle, version, ctypes.c_double, ctypes.c_uint32],
        "hcsn_cache_clear": [handle, version],
        "hcsn_cache_statistics": [handle, version, U64],
        "hcsn_transition": [handle, version, ctypes.c_double, DOUBLE],
        "hcsn_propagate_batch": [handle, version, ctypes.c_double, ctypes.c_uint32, size, DOUBLE, DOUBLE],
        "hcsn_observe_batch": [handle, version, size, DOUBLE, DOUBLE, size, DOUBLE],
    }
    for name, signature in signatures.items():
        function = getattr(library, name)
        function.argtypes, function.restype = signature, ctypes.c_int
    return library


class PreparedModel:
    """A copied, validated immutable generator; version changes require a new model.

    Floating inputs are f64 row distributions. `out` permits output reuse; native
    scratch capacity is thread-local and reused. First-call allocation and every
    cache build belong in measured preparation/online costs. This is inference,
    not an autograd bridge. A cache is local to this model and exact dt bits.
    """

    def __init__(self, q, version=0, mode="dense", library=None):
        if mode not in MODES:
            raise ValueError("mode must be sparse or dense")
        if not isinstance(version, (int, np.integer)) or not 0 <= int(version) < 2**64:
            raise ValueError("version must be a uint64")
        q = np.ascontiguousarray(q, dtype=np.float64)
        if q.ndim != 2 or q.shape[0] != q.shape[1]:
            raise ValueError("Expected square row-generator Q")
        suffix = {"Linux": ".so", "Darwin": ".dylib", "Windows": ".dll"}[platform.system()]
        self.library_path = Path(library or ROOT / "evidence/build" / ("libhcsn_prepared" + suffix))
        self.library = _library(self.library_path)
        self.n, self.version, self.mode = len(q), int(version), mode
        handle = ctypes.c_uint64()
        _check(self.library.hcsn_model_create(self.n, q.ctypes.data_as(DOUBLE), self.version,
                                             ctypes.byref(handle)))
        self.handle = handle.value

    def close(self):
        if getattr(self, "handle", 0):
            _check(self.library.hcsn_model_release(self.handle))
            self.handle = 0

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()

    def __del__(self):
        if getattr(self, "handle", 0):
            self.library.hcsn_model_release(self.handle)
            self.handle = 0

    @property
    def identity(self):
        data = (ctypes.c_ubyte * 64)()
        _check(self.library.hcsn_model_identity(self.handle, self.version, data))
        return bytes(data).decode("ascii")

    def prepare(self, dt, mode=None):
        _check(self.library.hcsn_prepare(self.handle, self.version, float(dt), MODES[mode or self.mode]))
        return self

    def clear_cache(self):
        _check(self.library.hcsn_cache_clear(self.handle, self.version))

    def cache_info(self):
        counts = (ctypes.c_uint64 * 4)()
        _check(self.library.hcsn_cache_statistics(self.handle, self.version, counts))
        return dict(zip(["generator_validations", "preparations", "cache_hits", "cached_bytes"], counts))

    def transition(self, dt):
        result = np.empty((self.n, self.n), dtype=np.float64)
        _check(self.library.hcsn_transition(self.handle, self.version, float(dt), result.ctypes.data_as(DOUBLE)))
        return result

    def _arrays(self, prior, out):
        prior = np.ascontiguousarray(prior, dtype=np.float64)
        if prior.ndim not in (1, 2) or prior.shape[-1] != self.n:
            raise ValueError("Expected prior[n] or prior[batch,n]")
        if out is None:
            out = np.empty_like(prior)
        if (not isinstance(out, np.ndarray) or out.shape != prior.shape or out.dtype != np.float64
                or not out.flags.c_contiguous or not out.flags.writeable):
            raise ValueError("out must be a writable C-contiguous f64 array matching prior")
        return prior, out, prior.size // self.n

    def propagate(self, prior, dt, out=None, mode=None):
        prior, out, batch = self._arrays(prior, out)
        _check(self.library.hcsn_propagate_batch(self.handle, self.version, float(dt),
                MODES[mode or self.mode], batch, prior.ctypes.data_as(DOUBLE), out.ctypes.data_as(DOUBLE)))
        return out

    def observe(self, prior, likelihood, out=None):
        prior, out, batch = self._arrays(prior, out)
        likelihood = np.ascontiguousarray(likelihood, dtype=np.float64)
        if likelihood.shape == (self.n,):
            rows = 1
        elif likelihood.shape == (batch, self.n):
            rows = batch
        else:
            raise ValueError("Expected likelihood[n] or likelihood[batch,n]")
        _check(self.library.hcsn_observe_batch(self.handle, self.version, batch,
                prior.ctypes.data_as(DOUBLE), likelihood.ctypes.data_as(DOUBLE), rows, out.ctypes.data_as(DOUBLE)))
        return out
