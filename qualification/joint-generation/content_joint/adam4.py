"""Independent four-group adapter; never modifies the original six-group ABI."""

import ctypes
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import time

import numpy as np

from content_joint.native_model import KEYS, Native12


DOUBLE = ctypes.POINTER(ctypes.c_double)
POINTERS = DOUBLE * 4
SIZES = ctypes.c_size_t * 4
SCALARS = ctypes.c_double * 4


def clock():
    usage = os.times()
    return time.process_time() + usage.children_user + usage.children_system


def compile_once(folder):
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=False)
    source = Path(__file__).with_name("adam4.c")
    library = folder / "libsemantic4.so"
    compiler = shutil.which("cc")
    if compiler is None:
        raise RuntimeError("C compiler absent")
    argv = [compiler, "-O3", "-ffp-contract=off", "-std=c11", "-shared",
            "-fPIC", str(source), "-o", str(library), "-lm"]
    begin = clock()
    result = subprocess.run(argv, text=True, capture_output=True)
    receipt = dict(argv=argv, exit_code=result.returncode, stdout=result.stdout,
                   stderr=result.stderr, CPU=clock() - begin,
                   source_sha256=hashlib.sha256(source.read_bytes()).hexdigest(),
                   library_path=str(library.resolve()),
                   library_sha256=None if result.returncode else hashlib.sha256(library.read_bytes()).hexdigest())
    (folder / "compile.json").write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n")
    if result.returncode:
        raise RuntimeError("new four-group ABI compilation failed")
    return receipt


def rows(model):
    if not isinstance(model, Native12) or model.dimensions != (202, 12, 192, 32):
        raise ValueError("native12 model required")
    result = []
    for key, shape in zip(KEYS, ((202, 32), (32,), (32, 12), (12,))):
        parameter = model.params.get(key)
        if (not isinstance(parameter, np.ndarray) or parameter.dtype != np.float64
                or parameter.shape != shape or not parameter.flags.c_contiguous
                or not parameter.flags.writeable):
            raise ValueError("owned contiguous float64 parameter required")
        moment = model._moments.get(key)
        if key in model._moments and moment is None:
            raise ValueError("invalid native moment")
        if moment is not None:
            if (not isinstance(moment, tuple) or len(moment) != 3
                    or type(moment[2]) is not int or not 0 <= moment[2] < 2**63 - 1):
                raise ValueError("invalid native clock")
            for array in moment[:2]:
                if (not isinstance(array, np.ndarray) or array.dtype != np.float64
                        or array.shape != shape or not array.flags.c_contiguous
                        or not array.flags.writeable):
                    raise ValueError("invalid native moment array")
        result.append((key, parameter, moment))
    return result


def setup_work(model):
    return dict(compare_ops=sum(p.size * (1 if m is None else 3) for _, p, m in rows(model)))


class Adam4:
    def __init__(self, model, library):
        metadata = rows(model)
        self.model, self.mapping, self.moments = model, model.params, model._moments
        self.params, self.first, self.second, self.clocks = [], [], [], []
        for _, p, m in metadata:
            if any(not np.isfinite(a).all() for a in ((p,) if m is None else (p, m[0], m[1]))):
                raise ValueError("finite native initial state required")
            self.params.append(p)
            self.first.append(np.zeros_like(p) if m is None else m[0])
            self.second.append(np.zeros_like(p) if m is None else m[1])
            self.clocks.append(0 if m is None else m[2])
        self.published = [m is not None for _, _, m in metadata]
        arrays = self.params + self.first + self.second
        self.ranges = sorted((a.ctypes.data, a.ctypes.data + a.nbytes) for a in arrays)
        if any(right[0] < left[1] for left, right in zip(self.ranges, self.ranges[1:])):
            raise ValueError("overlapping native optimizer arrays")
        self.addresses = [a.ctypes.data for a in arrays]
        self.library = ctypes.CDLL(str(Path(library).resolve()))
        self.function = self.library.hepta_adam_semantic4_v1
        self.function.argtypes = [ctypes.c_size_t] + [ctypes.POINTER(DOUBLE)] * 4 + [
            ctypes.POINTER(ctypes.c_size_t), ctypes.POINTER(ctypes.c_double),
            ctypes.POINTER(ctypes.c_double), ctypes.c_double, ctypes.c_double]
        self.function.restype = ctypes.c_int
        self.pp = POINTERS(*(a.ctypes.data_as(DOUBLE) for a in self.params))
        self.mp = POINTERS(*(a.ctypes.data_as(DOUBLE) for a in self.first))
        self.vp = POINTERS(*(a.ctypes.data_as(DOUBLE) for a in self.second))
        self.sizes = SIZES(*(a.size for a in self.params))

    def apply_gradients(self, model, gradients, lr):
        if (model is not self.model or model.params is not self.mapping
                or model._moments is not self.moments or set(gradients) != set(KEYS)
                or not np.isfinite(lr) or not 0 < lr <= 1):
            raise ValueError("bound native model and complete gradients required")
        for index, (key, p, m) in enumerate(rows(model)):
            if p is not self.params[index]:
                raise ValueError("native parameter replaced")
            if self.published[index]:
                if m is None or m[0] is not self.first[index] or m[1] is not self.second[index] or m[2] != self.clocks[index]:
                    raise ValueError("native optimizer state replaced")
            elif m is not None:
                raise ValueError("native moment added externally")
        if self.addresses != [a.ctypes.data for a in self.params + self.first + self.second]:
            raise ValueError("native optimizer array moved")
        clean = {}
        for key, gradient in gradients.items():
            array = np.asarray(gradient, dtype=np.float64)
            if array.shape != model.params[key].shape or not np.isfinite(array).all():
                raise ValueError("finite matching native gradients required")
            clean[key] = array
        norm = np.sqrt(sum(float(np.sum(a * a)) for a in clean.values()))
        scale = min(1.0, 5.0 / max(norm, 1e-300))
        contiguous = [np.ascontiguousarray(clean[key]) for key in KEYS]
        if any(a.ctypes.data < stop and start < a.ctypes.data + a.nbytes
               for a in contiguous for start, stop in self.ranges):
            raise ValueError("native gradients alias optimizer state")
        pointers = POINTERS(*(a.ctypes.data_as(DOUBLE) for a in contiguous))
        first = SCALARS(*(1 - .9 ** (step + 1) for step in self.clocks))
        second = SCALARS(*(1 - .999 ** (step + 1) for step in self.clocks))
        status = self.function(4, self.pp, self.mp, self.vp, pointers, self.sizes,
                               first, second, scale, lr)
        if status:
            raise ValueError("four-group native preflight rejected " + str(status))
        for j, key in enumerate(KEYS):
            self.clocks[j] += 1
            self.published[j] = True
            model._moments[key] = (self.first[j], self.second[j], self.clocks[j])
        model.updates += 1
