"""First-order Torch custom VJP for a fixed continuous finite delay equation."""

from dataclasses import dataclass, field
from fractions import Fraction
import math
from types import SimpleNamespace
import time

import numpy as np
import torch
from torch.autograd.function import once_differentiable

from qualification.hcsn_boundary_audit.refractory_transport import Packet
from qualification.hcsn_joint_dde.model import JointModel
from qualification.hcsn_initial_adjoint.solver import amplitude_vjp, freeze_problem


def _signature(value):
    return (
        value.dtype,
        value.device,
        tuple(value.shape),
        tuple(value.stride()),
        value.storage_offset(),
        value.data_ptr(),
        value.requires_grad,
    )


@dataclass
class CallBudget:
    forward_limit: int = 220
    adjoint_limit: int = 32
    forward_calls: int = 0
    adjoint_calls: int = 0
    backward_attempts: int = 0
    guard_rejections: int = 0
    metadata_checks: int = 0
    recorded_scalars: int = 0
    label: str = "unspecified"
    forward_records: list = field(default_factory=list)
    backward_records: list = field(default_factory=list)
    _locked_limits: object = field(default=None, init=False, repr=False)

    def validate(self):
        for name, maximum in (("forward_limit", 220), ("adjoint_limit", 32)):
            value = getattr(self, name)
            if type(value) is not int or not 1 <= value <= maximum:
                raise ValueError("exact positive bounded integer call limits required")
        for name in (
            "forward_calls",
            "adjoint_calls",
            "backward_attempts",
            "guard_rejections",
            "metadata_checks",
            "recorded_scalars",
        ):
            value = getattr(self, name)
            if type(value) is not int or value < 0:
                raise ValueError("exact nonnegative integer call counters required")
        if (
            self.forward_calls > 220
            or self.adjoint_calls > 32
            or self.recorded_scalars > 1000000
        ):
            raise ValueError("absolute prototype budget exceeded")
        limits = (self.forward_limit, self.adjoint_limit)
        if self._locked_limits is None:
            self._locked_limits = limits
        elif self._locked_limits != limits:
            raise ValueError("call limits changed after admission")

    def retain(self, arrays):
        self.validate()
        self.recorded_scalars += sum(value.size for value in arrays)
        if self.recorded_scalars > 1000000:
            raise ValueError("small-probe recorded-array payload budget exceeded")


@dataclass(frozen=True)
class _LiveMetadata:
    model: object
    times: object
    supports: object
    model_representation: str
    identity: str

    def check(self, budget):
        budget.metadata_checks += 1
        try:
            current = freeze_problem(self.model, self.times, self.supports)
            valid = (
                current.identity == self.identity
                and repr(self.model) == self.model_representation
            )
        except Exception as exc:
            raise RuntimeError("fixed forward metadata changed") from exc
        if not valid:
            raise RuntimeError("fixed forward metadata changed")


@dataclass(frozen=True)
class _FrozenForward:
    problem: object

    @property
    def spatial(self):
        return SimpleNamespace(intervals=self.problem.intervals)

    @property
    def delay(self):
        return float(self.problem.delay)

    @property
    def discount(self):
        return self.problem.discount

    def ingredients(self):
        p = self.problem
        return p.transient, p.lower, p.upper, p.reset


def _primal(problem, inputs, options):
    """The unchanged JointModel.solve consumes only this private fixed snapshot.

    No live model, caller time/support container or basis-direction map is read.
    The original method is called unbound; all required fixed ingredients are
    supplied by the private adapter rather than reconstructed from uniform nodes.
    """
    active, content, mass, phase_content = inputs
    count = problem.intervals
    probability = np.r_[0.0, active]
    marked = np.vstack([np.zeros((1, content.shape[1])), content])
    packets = tuple(
        Packet(
            f"fixed-{j}",
            a,
            b,
            Fraction(str(float(mass[j]))),
            tuple(Fraction(str(float(v))) for v in phase_content[j]),
        )
        for j, (a, b) in enumerate(problem.supports)
    )
    rtol, atol, max_step = options
    flow = JointModel.solve(
        _FrozenForward(problem),
        list(map(float, problem.times)),
        probability,
        marked,
        packets,
        rtol=rtol,
        atol=atol,
        max_step=max_step,
    )
    fields = (
        "active",
        "upper",
        "refractory",
        "events",
        "discounted_events",
        "discounted_active_time",
        "discounted_remaining_phase",
    )
    result = np.stack(
        [
            np.vstack(
                [
                    np.asarray(row[name])
                    if name == "active"
                    else np.asarray(row[name])[None, :]
                    for name in fields
                ]
            )
            for row in flow["rows"]
        ]
    )
    if not np.all(np.isfinite(result)) or result.shape != (
        len(problem.times),
        count + 5,
        content.shape[1] + 1,
    ):
        raise ArithmeticError("nonfinite or mismatched fixed-snapshot forward")
    if flow["internal_steps"] > 4096:
        raise ValueError("small forward post-solve step budget exceeded")
    return result, flow["internal_steps"]


class _Amplitude(torch.autograd.Function):
    @staticmethod
    def forward(ctx, problem, metadata, options, budget, *inputs):
        budget.validate()
        if budget.forward_calls >= min(220, budget.forward_limit):
            raise ValueError("prefrozen Torch forward-call budget exceeded")
        budget.forward_calls += 1
        metadata.check(budget)
        arrays = tuple(value.detach().numpy().copy() for value in inputs)
        wall, cpu = time.perf_counter(), time.process_time()
        value, steps = _primal(problem, arrays, options)
        metadata.check(budget)
        budget.retain((*arrays, value))
        budget.forward_records.append(
            dict(
                label=budget.label,
                inputs=arrays,
                output=value.copy(),
                internal_steps=steps,
                wall_seconds=time.perf_counter() - wall,
                cpu_seconds=time.process_time() - cpu,
                problem_identity=problem.identity,
            )
        )
        ctx.problem, ctx.metadata, ctx.options, ctx.budget = (
            problem,
            metadata,
            options,
            budget,
        )
        ctx.live_inputs = tuple(
            inputs
        )  # Independent live references also cover SavedVariable packing.
        ctx.input_signatures = tuple(_signature(value) for value in inputs)
        ctx.save_for_backward(*inputs, *(v.detach().clone() for v in inputs))
        ctx.set_materialize_grads(False)
        return torch.from_numpy(value.copy())

    @staticmethod
    @once_differentiable
    def backward(ctx, gradient):
        budget = ctx.budget
        budget.validate()
        budget.backward_attempts += 1
        try:
            saved = ctx.saved_tensors  # Standard Torch version checks read originals.
            originals, copies = ctx.live_inputs, saved[4:]
            if tuple(_signature(value) for value in originals) != ctx.input_signatures:
                raise RuntimeError("initial amplitude tensor metadata/storage changed")
            if any(
                not torch.equal(value, copy) for value, copy in zip(originals, copies)
            ):
                raise RuntimeError("initial amplitude input changed after forward")
            ctx.metadata.check(budget)
        except RuntimeError:
            budget.guard_rejections += 1
            raise
        if gradient is None:
            return (None,) * 8
        if not bool(torch.isfinite(gradient).all()) or bool(
            (gradient.abs() > 1e6).any()
        ):
            raise ValueError("bounded finite output cotangent required")
        budget.validate()
        if budget.adjoint_calls >= min(32, budget.adjoint_limit):
            raise ValueError("prefrozen Torch adjoint-call budget exceeded")
        budget.adjoint_calls += 1
        rtol, atol, max_step = ctx.options
        cotangent = gradient.detach().contiguous().numpy().copy()
        result = amplitude_vjp(
            ctx.problem, cotangent, rtol=rtol, atol=atol, max_step=max_step
        )
        vjp = result.pop("vjp")
        budget.retain((cotangent, vjp))
        budget.backward_records.append(
            dict(label=budget.label, cotangent=cotangent, vjp=vjp.copy(), **result)
        )
        count = ctx.problem.intervals
        gradients = (vjp[:count, 0], vjp[:count, 1:], vjp[count:, 0], vjp[count:, 1:])
        return (None,) * 4 + tuple(
            torch.from_numpy(np.array(value, copy=True)) for value in gradients
        )


def amplitude_flow(
    model,
    query_times,
    active,
    content,
    phase_mass,
    phase_content,
    *,
    supports=(),
    budget=None,
    rtol=2e-11,
    atol=2e-13,
    max_step=0.01,
):
    """Ambient amplitude VJP: nonnegative finite measures, independent signed marks.

    Physics, supports, delay, geometry and source migration are fixed. There is
    no silent normalization. A normalized client must explicitly construct its
    own softmax and probability-times-mark graph. This is a continuous-DDE
    numerical custom adjoint, not autodiff of the adaptive BDF instructions.
    """
    values = (active, content, phase_mass, phase_content)
    if any(
        not isinstance(v, torch.Tensor)
        or v.dtype != torch.float64
        or v.device.type != "cpu"
        or not bool(torch.isfinite(v).all())
        or bool((v.abs() > 1e6).any())
        for v in values
    ):
        raise ValueError("bounded finite CPU FP64 amplitude tensors required")
    problem = freeze_problem(model, query_times, supports)
    if problem.intervals > 12:
        raise ValueError("this separate Torch candidate admits only N<=12")
    n, k = problem.intervals, len(problem.supports)
    if (
        active.shape != (n,)
        or content.ndim != 2
        or content.shape[0] != n
        or not 1 <= content.shape[1] <= 4
        or phase_mass.shape != (k,)
        or phase_content.shape != (k, content.shape[1])
        or bool((active < 0).any())
        or bool((phase_mass < 0).any())
    ):
        raise ValueError("active/phase probability and signed-content shapes differ")
    if (
        not 1e-12 <= rtol <= 1e-3
        or not 1e-14 <= atol <= 1e-5
        or not math.isfinite(max_step)
        or not 0 < max_step <= float(problem.delay)
    ):
        raise ValueError("explicit bounded numerical controls required")
    if budget is None:
        budget = CallBudget()
    if type(budget) is not CallBudget:
        raise ValueError("bounded prototype call ledger required")
    budget.validate()
    metadata = _LiveMetadata(
        model, query_times, supports, repr(model), problem.identity
    )
    output = _Amplitude.apply(
        problem, metadata, (float(rtol), float(atol), float(max_step)), budget, *values
    )
    return output, budget
