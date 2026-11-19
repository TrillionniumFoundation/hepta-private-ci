"""Common CPU backend; declared work is distinct from measured CPU time.

Retained pre-batch negative diagnostic (untrained h32, 1000 handwritten random
requests): full/always-stop control CPU 0.0410/0.0691s without ledger and
0.2374/0.2910s including ledger. Batching is a separately declared throughput
interface, not evidence of low single-request latency or a passed held-out gate.
"""

import ctypes
import hashlib
import json
from pathlib import Path
import platform
import resource
import shutil
import subprocess
import time
from types import MappingProxyType

import numpy as np

from control import Controller
from independent.accounting import BudgetExceeded
from independent.inference import FrozenGenerator, _sum_work, units


SOURCE = Path(__file__).with_suffix(".c")
DEFAULT_LIBRARY = SOURCE.parent / "build" / "libhepta_joint_native.so"
_DOUBLE = ctypes.POINTER(ctypes.c_double)


class NativeBuildError(RuntimeError):
    def __init__(self, receipt):
        self.receipt = receipt
        super().__init__(json.dumps(receipt, sort_keys=True))


def _cpu():
    child = resource.getrusage(resource.RUSAGE_CHILDREN)
    return time.process_time() + child.ru_utime + child.ru_stime


def compile_native(output_path):
    """Always compile, retaining total parent+child CPU and the exact command.

    Formal runs must use their own run/build path and attribute this one shared
    compilation CPU cost in full to every compared system, including static
    baselines. Existing output is never treated as free cached compilation.
    """
    start_wall, start_cpu = time.perf_counter(), _cpu()
    compiler = shutil.which("cc")
    if compiler is None:
        raise RuntimeError("configured environment has no cc compiler")
    target = Path(output_path).resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    version = subprocess.run([compiler, "--version"], capture_output=True, text=True, check=True)
    argv = [compiler, "-O3", "-ffp-contract=off", "-std=c11", "-shared", "-fPIC", str(SOURCE), "-o", str(target), "-lm"]
    completed = subprocess.run(argv, capture_output=True, text=True)
    receipt = {"schema": "hepta.native-build.v1", "argv": argv,
               "compiler_version": version.stdout.splitlines()[0], "library_path": str(target),
               "source_path": str(SOURCE), "source_sha256": hashlib.sha256(SOURCE.read_bytes()).hexdigest(),
               "platform": platform.platform(), "machine": platform.machine(),
               "exit_code": completed.returncode, "stdout": completed.stdout, "stderr": completed.stderr,
               "cached_compilation_used": False,
               "cost_policy": "attribute complete compilation CPU to every system; not only control"}
    if completed.returncode:
        receipt.update(cpu_seconds=_cpu() - start_cpu, wall_seconds=time.perf_counter() - start_wall)
        raise NativeBuildError(receipt)
    receipt["library_sha256"] = hashlib.sha256(target.read_bytes()).hexdigest()
    receipt.update(cpu_seconds=_cpu() - start_cpu, wall_seconds=time.perf_counter() - start_wall)
    return receipt


def _pointer(array):
    return array.ctypes.data_as(_DOUBLE)


def _bind(path):
    library = ctypes.CDLL(str(path))
    library.hepta_forward.argtypes = [_DOUBLE, ctypes.c_size_t, ctypes.c_int, ctypes.c_int] + [_DOUBLE] * 8
    library.hepta_forward.restype = ctypes.c_int
    library.hepta_low_critic.argtypes = [_DOUBLE, ctypes.c_int] + [_DOUBLE] * 9 + [ctypes.c_double] * 3 + [_DOUBLE] * 3
    library.hepta_low_critic.restype = ctypes.c_int
    library.hepta_batch.argtypes = ([_DOUBLE, ctypes.c_size_t, ctypes.c_int, ctypes.c_int]
        + [_DOUBLE] * 10 + [ctypes.c_double] * 4 + [ctypes.POINTER(ctypes.c_ubyte)]
        + [_DOUBLE] * 3 + [ctypes.POINTER(ctypes.c_int)] * 2)
    library.hepta_batch.restype = ctypes.c_int
    return library


class NativeGenerator(FrozenGenerator):
    """FrozenGenerator API using the same C tensor kernel for every system.

    Low plus critic is one C call. Optional full is a second call so its actual
    execution can be charged before it happens, without padding stopped routes.
    Input/shape validation and copies remain real measured CPU overhead.
    """

    def __init__(self, model, library_path=None, ledger=None, stage="prepare", *, prepare_low=True):
        super().__init__(model, ledger, stage, prepare_low=False)
        if type(prepare_low) is not bool:
            raise ValueError("prepare_low must be boolean")
        maximum = np.longdouble(np.finfo(np.float64).max)
        for name, bias in (("encoder", "bias"), ("text", "text_bias"), ("image", "image_bias")):
            bound = np.abs(self.params[name].astype(np.longdouble)).sum(axis=0)
            bound += np.abs(self.params[bias].astype(np.longdouble))
            if np.any(bound > maximum):
                raise ValueError("parameters can overflow the bounded input profile")
        contiguous = {key: np.ascontiguousarray(value) for key, value in self.params.items()}
        for value in contiguous.values():
            value.flags.writeable = False
        self.params = MappingProxyType(contiguous)
        self.library_path = str(Path(DEFAULT_LIBRARY if library_path is None else library_path).resolve())
        if not Path(self.library_path).is_file():
            raise FileNotFoundError("compile_native must create the explicit library path first: " + self.library_path)
        self._native = _bind(self.library_path)
        self._last_critic = None
        self._state_function = self._gain_function = None
        if prepare_low:
            self._prepare(ledger)

    def _input(self, x):
        value = np.asarray(x)
        if (value.dtype != np.float64 or value.ndim != 2 or not 1 <= len(value) <= 65536
                or value.shape[1] != 202 or not np.isfinite(value).all()
                or np.any(value < 0) or np.any(value > 1)):
            raise ValueError("expected normalized finite float64 [N,202] input")
        return np.ascontiguousarray(value)

    def _counts(self, n, low):
        h, k = self.dimensions[3], self.dimensions[1]
        result = {"model_forward_calls": 1, "model_forward_rows": n,
                  "model_forward_macs": n * ((58 if low else 202) * h + 2 * h * k)}
        if low:
            result.update(thumbnail_calls=1, thumbnail_rows=n)
        return result

    def _state_entry(self):
        if self._state_function is None:
            try:
                function = self._native.hepta_forward_state_v1
            except AttributeError as error:
                raise RuntimeError("native library lacks hepta_forward_state_v1 for low hidden state") from error
            function.argtypes = [_DOUBLE, ctypes.c_size_t, ctypes.c_int, ctypes.c_int] + [_DOUBLE] * 9
            function.restype = ctypes.c_int
            self._state_function = function
        return self._state_function

    def _gain_entry(self):
        if self._gain_function is None:
            try:
                function = self._native.hepta_batch_gain_v1
            except AttributeError as error:
                raise RuntimeError("native library lacks hepta_batch_gain_v1 for affine gain head") from error
            function.argtypes = ([_DOUBLE, ctypes.c_size_t, ctypes.c_int] + [_DOUBLE] * 10
                + [ctypes.c_double] * 4 + [_DOUBLE] * 3 + [ctypes.POINTER(ctypes.c_int)] * 2)
            function.restype = ctypes.c_int
            self._gain_function = function
        return self._gain_function

    def _call_forward(self, x, low, *, return_state=False):
        p, q = np.empty((len(x), 12)), np.empty((len(x), 12))
        parameters = self.params
        encoder = self._folded_encoder if low else parameters["encoder"]
        hidden = np.empty((len(x), self.dimensions[3])) if return_state else None
        function = self._state_entry() if return_state else self._native.hepta_forward
        arguments = [
            *[_pointer(value) for value in (encoder, parameters["bias"], parameters["text"],
              parameters["text_bias"], parameters["image"], parameters["image_bias"], p, q)]]
        if return_state:
            arguments.append(_pointer(hidden))
        status = function(_pointer(x), len(x), self.dimensions[3], int(low), *arguments)
        if status:
            raise FloatingPointError("native tensor kernel returned " + str(status))
        return (p, q, hidden) if return_state else (p, q)

    def forward_full(self, x_full, ledger=None, stage="inference"):
        x = self._input(x_full)
        ledger = self._ledger_for(ledger)
        work = self.full_work(len(x))
        self._admit(work, ledger, stage)
        if ledger is not None:
            ledger.charge_kernel(stage, "native_full", **work, counts=self._counts(len(x), False))
        return self._call_forward(x, False)

    def forward_low(self, x_full, ledger=None, stage="inference"):
        x = self._input(x_full)
        ledger = self._ledger_for(ledger)
        work = self.low_work(len(x))
        required = work if self.prepared_low else _sum_work(work, self.prepare_work())
        self._admit(required, ledger, stage)
        self._prepare(ledger)
        if ledger is not None:
            ledger.charge_kernel(stage, "native_low", **work, counts=self._counts(len(x), True))
        return self._call_forward(x, True)

    def forward_low_state(self, x_full, ledger=None, stage="inference"):
        x = self._input(x_full)
        self._state_entry()  # Old libraries reject unsupported new API before charging.
        ledger = self._ledger_for(ledger)
        work = self.low_work(len(x))
        self._admit(work if self.prepared_low else _sum_work(work, self.prepare_work()), ledger, stage)
        self._prepare(ledger)
        if ledger is not None:
            ledger.charge_kernel(stage, "native_low_state", **work, counts=self._counts(len(x), True))
        return self._call_forward(x, True, return_state=True)

    def _critic(self, critic):
        if self._last_critic is not None and self._last_critic[0] is critic:
            return self._last_critic[1]
        if isinstance(critic, Controller):
            frozen = Controller(critic.classes, critic.mean, critic.scale, critic.weights,
                                critic.intercept, critic.bounds)
        else:
            from independent.gain_head import AffineGainHead
            if not isinstance(critic, AffineGainHead) or critic.hidden_dim != self.dimensions[3]:
                raise ValueError("compatible frozen affine gain head required")
            frozen = AffineGainHead.from_arrays(critic.to_arrays())
        if frozen.classes != 12:
            raise ValueError("compatible frozen critic required")
        # Ridge probabilities are [0,1]; affine hidden states are [-1,1].
        normalized_bound = ((np.longdouble(1.000000000001) + np.abs(frozen.mean.astype(np.longdouble)))
                            / frozen.scale.astype(np.longdouble))
        bound = normalized_bound * np.abs(frozen.weights.astype(np.longdouble))
        if (np.any(normalized_bound > np.finfo(np.float64).max)
                or bound.sum() + abs(np.longdouble(frozen.intercept)) > np.finfo(np.float64).max):
            raise ValueError("critic can overflow its bounded feature profile")
        self._last_critic = (critic, frozen)
        return frozen

    def _call_low_critic(self, x, critic):
        p, q, gain = np.empty((1, 12)), np.empty((1, 12)), ctypes.c_double()
        parameters = self.params
        status = self._native.hepta_low_critic(_pointer(x), self.dimensions[3],
            *[_pointer(value) for value in (self._folded_encoder, parameters["bias"],
              parameters["text"], parameters["text_bias"], parameters["image"],
              parameters["image_bias"], critic.mean, critic.scale, critic.weights)],
            float(critic.intercept), float(critic.bounds[0]), float(critic.bounds[1]),
            _pointer(p), _pointer(q), ctypes.byref(gain))
        if status:
            raise FloatingPointError("native low/critic kernel returned " + str(status))
        return p, q, gain.value

    def continuation(self, x_full, critic, price=0.02, ledger=None, stage="inference"):
        x = self._input(x_full)
        if (len(x) != 1 or type(price) not in (int, float) or not np.isfinite(price) or price < 0):
            raise ValueError("one request and finite nonnegative price required")
        critic = self._critic(critic)
        affine = not isinstance(critic, Controller)
        if affine:
            self._gain_entry()
        ledger = self._ledger_for(ledger)
        work = _sum_work(self.low_work(1), self.critic_work(1, critic))
        required = work if self.prepared_low else _sum_work(work, self.prepare_work())
        self._admit(required, ledger, stage)
        before = 0 if ledger is None else ledger.consumed_units
        self._prepare(ledger)
        if ledger is not None:
            counts = {**self._counts(1, True), "critic_decisions": 1, "critic_rows": 1}
            ledger.charge_kernel(stage, "native_low_critic", **work, counts=counts)
        available = ledger is None or ledger.remaining_units >= units(self.full_work(1), ledger)
        if affine:
            # The same exclusive-ledger admission as batch: optional full is
            # funded before C and charged only if that fused branch executes.
            p, q, _, _, full = self._call_batch(x, 3, critic,
                price if available else np.finfo(np.float64).max, None)
            continued = bool(full[0])
            if continued and ledger is not None:
                ledger.charge_kernel(stage, "native_full", **self.full_work(1), counts=self._counts(1, False))
        else:
            p, q, gain = self._call_low_critic(x, critic)
            continued = bool(available and gain > price)
            if continued:
                p, q = self.forward_full(x, ledger, stage)
        return p, q, {"continued": continued, "model_forwards": 1 + int(continued),
            "low_forwards": 1, "full_forwards": int(continued),
            "charged_units": None if ledger is None else ledger.consumed_units - before,
            "price_per_extra_full_pass": price}

    def _call_batch(self, x, mode, critic, price, mask):
        n = len(x)
        p, q, gains = np.empty((n, 12)), np.empty((n, 12)), np.zeros(n)
        low, full = np.zeros(n, dtype=np.intc), np.zeros(n, dtype=np.intc)
        params = self.params
        arrays = (params["encoder"], self._folded_encoder, params["bias"], params["text"],
                  params["text_bias"], params["image"], params["image_bias"],
                  None if critic is None else critic.mean, None if critic is None else critic.scale,
                  None if critic is None else critic.weights)
        values = (0.0, 0.0, 0.0) if critic is None else (critic.intercept, *critic.bounds)
        pointers = [None if value is None else _pointer(value) for value in arrays]
        outputs = [_pointer(p), _pointer(q), _pointer(gains),
            low.ctypes.data_as(ctypes.POINTER(ctypes.c_int)), full.ctypes.data_as(ctypes.POINTER(ctypes.c_int))]
        if critic is not None and not isinstance(critic, Controller):
            if mode != 3 or mask is not None:
                raise ValueError("affine gain entry only supports continuation")
            status = self._gain_entry()(_pointer(x), n, self.dimensions[3], *pointers, *values, price, *outputs)
        else:
            status = self._native.hepta_batch(_pointer(x), n, self.dimensions[3], mode,
                *pointers, *values, price,
                None if mask is None else mask.ctypes.data_as(ctypes.POINTER(ctypes.c_ubyte)), *outputs)
        if status:
            raise FloatingPointError("native batch kernel returned " + str(status))
        return p, q, gains, low, full

    def batch(self, x_full, mode, critic=None, price=0.02, ledger=None, stage="inference",
              random_full_mask=None, per_request_cap=None):
        """Serve 1..64 requests with one C call and one actual-work charge.

        The caller exclusively owns its ledger during execution. Before calling
        C, every row and the whole batch must fund the mathematical worst case;
        this reservation is not spending. Only executed kernels are charged.
        PNG/JSON work and its real CPU must be included by the service caller.
        """
        modes = ("full", "low", "ensemble", "continuation", "random")
        x = self._input(x_full)
        n = len(x)
        if (not isinstance(mode, str) or mode not in modes or n > 64
                or type(price) not in (int, float) or not np.isfinite(price) or price < 0):
            raise ValueError("bounded batch, declared mode and finite price required")
        mask = None
        if mode == "random":
            value = np.asarray(random_full_mask)
            if (value.shape != (n,) or value.dtype not in (np.dtype(bool), np.dtype(np.uint8))
                    or np.any(value > 1)):
                raise ValueError("one declared boolean/uint8 random view choice per row required")
            mask = np.ascontiguousarray(value, dtype=np.uint8)
        elif random_full_mask is not None:
            raise ValueError("random mask is only valid for random mode")
        frozen = self._critic(critic) if mode == "continuation" else None
        if frozen is not None and not isinstance(frozen, Controller):
            self._gain_entry()
        ledger = self._ledger_for(ledger)
        full_work, low_work = self.full_work(1), self.low_work(1)
        critic_work = self.critic_work(1, frozen) if mode == "continuation" else {}
        extra = {"scalar_ops": 24, "div_ops": 24} if mode == "ensemble" else (
            {"scalar_ops": 1, "compare_ops": 1} if mode == "random" else {})
        fu, lu, cu, eu = (units(work, ledger) for work in (full_work, low_work, critic_work, extra))
        need_low = mode in ("low", "ensemble", "continuation") or (mode == "random" and not mask.all())
        prepare = units(self.prepare_work(), ledger) if need_low and not self.prepared_low else 0
        worst = ([fu] * n if mode == "full" else [lu] * n if mode == "low" else
                 [fu + lu + cu + eu] * n if mode in ("ensemble", "continuation") else
                 [fu + eu if choice else lu + eu for choice in mask])
        worst[0] += prepare
        cap = 2 * fu if per_request_cap is None else per_request_cap
        if type(cap) is not int or not 0 < cap <= 2**63 - 1:
            raise ValueError("bounded positive per-request cap required")
        if max(worst) > cap or (ledger is not None and sum(worst) > ledger.remaining_units):
            raise BudgetExceeded("batch worst-case reservation exceeds request or total cap")
        before = 0 if ledger is None else ledger.consumed_units
        if need_low:
            self._prepare(ledger)
        p, q, gains, low, full = self._call_batch(x, modes.index(mode), frozen, price, mask)
        low_count, full_count = int(low.sum()), int(full.sum())
        row_units = [int(l) * lu + int(f) * fu + cu + eu for l, f in zip(low, full)]
        row_units[0] += prepare
        actual = {}
        for work, count in ((low_work, low_count), (full_work, full_count), (critic_work, n), (extra, n)):
            for key, value in work.items():
                actual[key] = actual.get(key, 0) + value * count
        h, k = self.dimensions[3], self.dimensions[1]
        counts = {"model_forward_calls": low_count + full_count, "model_forward_rows": low_count + full_count,
            "model_forward_macs": low_count * (58 * h + 2 * h * k) + full_count * (202 * h + 2 * h * k),
            "thumbnail_calls": low_count, "thumbnail_rows": low_count, "native_batches": 1, "batch_requests": n}
        if mode == "continuation":
            counts.update(critic_decisions=n, critic_rows=n)
        if mode == "random":
            counts.update(random_view_choices=n)
        if ledger is not None:
            ledger.charge_kernel(stage, "native_batch_" + mode, **actual, counts=counts)
            if ledger.consumed_units - before != sum(row_units):
                raise RuntimeError("batch receipt and actual ledger charge differ")
        forwards = (low + full).tolist()
        per_row = {"work_units": row_units, "model_forwards": forwards,
            "low_forwards": low.tolist(), "full_forwards": full.tolist(), "gain": gains.tolist()}
        return p, q, {"mode": mode, "batch_size": n, "per_row": per_row,
            "per_row_work_units": row_units, "per_row_forwards": forwards,
            "continued": (full.astype(bool).tolist() if mode == "continuation" else [False] * n),
            "actual_units": sum(row_units), "charged_units": None if ledger is None else ledger.consumed_units - before,
            "prepare_units": prepare, "worst_reserved_units": sum(worst), "reservation_charged": False,
            "request_cap_units": cap, "model_forwards": low_count + full_count}
