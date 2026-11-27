"""Fixed joint/heads blocks, with genuinely omitted encoder derivatives."""

import ctypes
import hashlib
from pathlib import Path
import shutil
import subprocess

import numpy as np

from independent.learning import CONTENT_PARAMETERS, step_work
from independent.native_adam import NativeAdam, _DOUBLE, _POINTERS, _SCALARS, _pointer
from independent.run import cpu_clock
from model import softmax


HEADS = CONTENT_PARAMETERS[2:]


def compile_library(path):
    start = cpu_clock()
    source = Path(__file__).with_name("adam.c")
    compiler = shutil.which("cc")
    if compiler is None:
        raise RuntimeError("C compiler unavailable")
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=False)
    argv = [compiler, "-O3", "-ffp-contract=off", "-std=c11", "-shared", "-fPIC", str(source), "-o", str(path), "-lm"]
    version = subprocess.run([compiler,"--version"],text=True,capture_output=True,check=True).stdout.splitlines()[0]
    result = subprocess.run(argv, text=True, capture_output=True)
    if result.returncode:
        raise RuntimeError(result.stderr)
    return {"argv": argv, "compiler_version":version, "cpu_seconds": cpu_clock()-start,
            "source_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
            "library_sha256": hashlib.sha256(path.read_bytes()).hexdigest(), "library": str(path.resolve())}


class BlockAdam(NativeAdam):
    """Retain inactive parameter/moment storage and clocks exactly, even at zero."""

    def __init__(self, model, library_path):
        super().__init__(model, library_path)
        self._function = self._library.hepta_adam_blocks_v1
        self._function.argtypes = [ctypes.c_size_t] + [ctypes.POINTER(_DOUBLE)] * 4 + [
            ctypes.POINTER(ctypes.c_size_t), ctypes.POINTER(ctypes.c_double),
            ctypes.POINTER(ctypes.c_double), ctypes.c_double, ctypes.c_double, ctypes.c_int]
        self._function.restype = ctypes.c_int

    def apply_gradients(self, model, grads, lr):
        self._check_binding(model)
        if set(grads) not in (set(CONTENT_PARAMETERS), set(HEADS)) or not np.isfinite(lr) or not 0 < lr <= 1:
            raise ValueError("complete joint or heads-only gradients required")
        clean = {}
        for key, value in grads.items():
            g = np.asarray(value, dtype=np.float64)
            if g.shape != model.params[key].shape or not np.isfinite(g).all():
                raise ValueError("invalid active gradient")
            clean[key] = g
        norm = np.sqrt(sum(float(np.sum(g*g)) for g in clean.values()))
        scale = min(1.0, 5.0/max(norm, 1e-300))
        active = [key in clean for key in CONTENT_PARAMETERS]
        first = _SCALARS(*(1-.9**(clock+1) if yes else 1 for clock,yes in zip(self._clocks,active)))
        second = _SCALARS(*(1-.999**(clock+1) if yes else 1 for clock,yes in zip(self._clocks,active)))
        contiguous = {key: np.ascontiguousarray(g) for key,g in clean.items()}
        if any(g.ctypes.data < stop and start < g.ctypes.data+g.nbytes
               for g in contiguous.values() for start,stop in self._state_ranges):
            raise ValueError("gradient aliases optimizer state")
        pointers = _POINTERS(*(_pointer(contiguous[k]) if k in contiguous else _DOUBLE() for k in CONTENT_PARAMETERS))
        status = self._function(6, self._parameter_pointers, self._first_pointers, self._second_pointers,
            pointers, self._sizes, first, second, scale, lr, int(not active[0]))
        if status:
            raise ValueError("block Adam preflight rejected " + str(status))
        for index, key in enumerate(CONTENT_PARAMETERS):
            if active[index]:
                self._clocks[index] += 1
                self._published[index] = True
                model._moments[key] = (self._first[index], self._second[index], self._clocks[index])
        model.updates += 1


def heads_work(dimensions, arm, n):
    d,k,_,h = dimensions
    work = step_work(dimensions, arm, n)
    skipped = d*h+h
    # Delete exactly the encoder/tanh derivatives and inactive optimizer work.
    work["macs"] -= n*(d*h+2*h*k)
    work["scalar_ops"] -= 4*n*h+(n-1)*h+13*skipped+8
    work["div_ops"] -= 3*skipped
    work["sqrt_ops"] -= skipped
    work["pow_ops"] -= 4
    work["compare_ops"] -= skipped
    return work


def heads_step(objective, model, x, labels, lr, ledger):
    x, y = model._input(x), np.asarray(labels)
    if (tuple(model.dimensions) != objective.dimensions or hasattr(model, "ledger")
            or y.shape != (len(x),) or y.dtype.kind not in "iu" or np.any(y<0) or np.any(y>=12)
            or not np.isfinite(lr) or not 0<lr<=1):
        raise ValueError("plain matching model, valid labels and learning rate required")
    if objective._decoder is not None and any(not np.array_equal(model.params[k],v) for k,v in objective._decoder.items()):
        raise ValueError("decoder changed")
    n, (d,k,_,h) = len(x), model.dimensions
    counts = {"content_updates": 1, "head_updates": 1, "heads_only_steps": 1,
              "model_forward_calls": 1, "model_forward_rows": n, "head_backward_calls": 1,
              "head_backward_rows": n, "training_examples": n, "optimizer_updates": 1,
              "optimizer_elements": 2*h*k+2*k, "cross_entropy_calls": 1,
              "model_forward_macs": n*(d*h+2*h*k), "model_backward_macs": 2*n*h*k}
    if objective.arm == "A":
        counts.update(joint_utility_calls=1, joint_utility_cells=n*k*k, additive_gradient_calls=1)
    ledger.charge_kernel("search_train", "heads_only", **heads_work(model.dimensions, objective.arm, n), counts=counts)
    hidden = np.tanh(x @ model.params["encoder"] + model.params["bias"])
    p = softmax(hidden @ model.params["text"] + model.params["text_bias"])
    q = softmax(hidden @ model.params["image"] + model.params["image_bias"])
    loss, dt, di = objective._policy_gradients_checked(p,q,y)
    gradients = {"text": hidden.T@dt, "text_bias": dt.sum(0),
                 "image": hidden.T@di, "image_bias": di.sum(0)}
    objective.optimizer.apply_gradients(model, gradients, lr)
    return loss
