"""Physical-time adapter and diagnostics for the HX value-feature encoder A.

The input is held on each supplied interval. Substeps approximate A's nonlinear
memory/recovery ODE; they do not solve a moving-boundary first-passage problem.
There is no reset or task-regenerative QVI in this mechanism. Frozen historical
campaign sources and budgets are not changed by this additive module.
"""

import copy
from dataclasses import dataclass
import math

import torch

from .cells import ValueKernelCell


@dataclass(frozen=True)
class TimedCellState:
    memory: torch.Tensor
    recovery: torch.Tensor
    time_seconds: float
    seconds_per_model_time: float


@dataclass(frozen=True)
class HeldInputTrace:
    memory: torch.Tensor
    recovery: torch.Tensor
    times_seconds: tuple
    state: TimedCellState


def _positive_number(value, name):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0:
        raise ValueError(f"{name} must be finite and positive")
    return float(value)


def _positive_integer(value, name):
    if type(value) is not int or value <= 0:
        raise ValueError(f"{name} must be a positive integer")
    return value


def stream_held_inputs(cell, inputs, time_edges_seconds, *, seconds_per_model_time=1.0,
                       initial_state=None, subdivisions=1):
    """Advance A through physical-time intervals and return their endpoint states.

    ``inputs`` has shape [batch, intervals, input]. Interval i uses inputs[:, i]
    throughout [edges[i], edges[i+1]); no new input is invented by refinement.
    Absolute time may have any finite origin. Repeated endpoints are zero-time
    observations, which do not advance state. A resumed stream must begin at its
    state's endpoint and use the identical physical/model time conversion.
    The returned tensors retain autograd history; callers choose detach points.
    """
    if not isinstance(cell, ValueKernelCell):
        raise TypeError("This profile requires ValueKernelCell mechanism A")
    subdivisions = _positive_integer(subdivisions, "subdivisions")
    scale = _positive_number(seconds_per_model_time, "seconds_per_model_time")
    if inputs.ndim != 3 or min(inputs.shape[:2]) <= 0 or inputs.shape[2] != cell.margin_input.in_features:
        raise ValueError("inputs must have shape [positive batch, positive intervals, cell input]")
    if inputs.dtype != cell.raw_financial.dtype or inputs.device != cell.raw_financial.device:
        raise ValueError("input dtype/device must match the cell")
    if not bool(torch.isfinite(inputs).all()):
        raise ValueError("inputs must be finite")
    try:
        edges = tuple(float(value) for value in time_edges_seconds)
    except (TypeError, ValueError, OverflowError) as error:
        raise ValueError("time edges must be finite scalar numbers") from error
    if len(edges) != inputs.shape[1]+1 or not all(math.isfinite(value) for value in edges):
        raise ValueError("finite time edges must contain one more entry than input intervals")
    durations = tuple(right-left for left, right in zip(edges, edges[1:]))
    if any(not math.isfinite(dt) or dt < 0 or not math.isfinite(dt/scale) for dt in durations):
        raise ValueError("time edges must be nondecreasing with finite model-time durations")
    steps = tuple(duration/scale/subdivisions for duration in durations)
    if any(duration > 0 and dt <= 0 for duration, dt in zip(durations, steps)):
        raise ValueError("positive physical duration underflows the model-time substep")
    if initial_state is None:
        state = cell.initial_state(inputs.shape[0], like=inputs)
    else:
        if not isinstance(initial_state, TimedCellState):
            raise TypeError("initial_state must carry physical-time metadata")
        if initial_state.time_seconds != edges[0] or initial_state.seconds_per_model_time != scale:
            raise ValueError("resumed time origin or time conversion differs from saved state")
        state = initial_state.memory, initial_state.recovery
        for value in state:
            if (value.shape != (inputs.shape[0], cell.hidden_size) or value.dtype != inputs.dtype
                    or value.device != inputs.device or not bool(torch.isfinite(value).all())):
                raise ValueError("saved state shape, dtype, device or finiteness is invalid")
        if bool((state[0].abs() > 1).any()) or bool(((state[1] < 0) | (state[1] > 1)).any()):
            raise ValueError("saved state violates mechanism-A state bounds")
    params = cell.financial_parameters()
    boundary = cell._base_boundary(params)
    memory, recovery = [], []
    for value, dt in zip(inputs.unbind(1), steps):
        if dt > 0:
            for _ in range(subdivisions):
                state = cell.step(value, state, dt, params=params, base_boundary=boundary)
        memory.append(state[0])
        recovery.append(state[1])
    final = TimedCellState(*state, edges[-1], scale)
    return HeldInputTrace(torch.stack(memory, 1), torch.stack(recovery, 1), edges[1:], final)


def _rms(value):
    return float(value.double().square().mean().sqrt())


def refinement_diagnostic(cell, inputs, time_edges_seconds, *, factors=(1, 2, 4, 8),
                          seconds_per_model_time=1.0, initial_state=None, readout=None):
    """Compare unchanged weights/input at common physical endpoints, without training.

    Successive differences are discretization evidence, not exact errors to a
    continuum solution. Readout diagnostics compare actual terminal predictions,
    separately from hidden-trace RMS. No universal convergence pass is inferred.
    """
    factors = tuple(_positive_integer(value, "refinement factor") for value in factors)
    if len(factors) < 2 or any(b <= a for a, b in zip(factors, factors[1:])):
        raise ValueError("at least two strictly increasing refinement factors are required")
    rows, previous = [], None
    with torch.no_grad():
        for factor in factors:
            trace = stream_held_inputs(cell, inputs, time_edges_seconds,
                                       seconds_per_model_time=seconds_per_model_time,
                                       initial_state=initial_state, subdivisions=factor)
            prediction = None if readout is None else readout(trace.state.memory)
            finite = bool(torch.isfinite(trace.memory).all() and torch.isfinite(trace.recovery).all())
            if prediction is not None:
                finite = finite and bool(torch.isfinite(prediction).all())
            row = {"subdivisions": factor, "finite": finite, "previous_subdivisions": None,
                   "memory_trace_rms_change": None, "recovery_trace_rms_change": None,
                   "terminal_memory_rms_change": None, "terminal_prediction_rms_change": None}
            if previous is not None:
                old_factor, old_trace, old_prediction = previous
                row.update(previous_subdivisions=old_factor,
                           memory_trace_rms_change=_rms(trace.memory-old_trace.memory),
                           recovery_trace_rms_change=_rms(trace.recovery-old_trace.recovery),
                           terminal_memory_rms_change=_rms(trace.state.memory-old_trace.state.memory),
                           terminal_prediction_rms_change=(None if prediction is None else
                                                          _rms(prediction-old_prediction)))
            rows.append(row)
            previous = factor, trace, prediction
    return {"schema": "hx-value-stream-refinement-v1", "mechanism": "stationary_value_gating_A",
            "kernel": cell.kernel, "channel": cell.channel, "boundary": cell.boundary_mode,
            "input_hold": "piecewise_constant", "seconds_per_model_time": seconds_per_model_time,
            "rows": rows, "continuum_error_known": False,
            "moving_boundary_first_passage_error": None,
            "limits": ["Stationary conditioned features do not define moving-boundary first passage.",
                       "Successive endpoint differences do not prove global convergence.",
                       "No training, model selection or quality advantage is established."]}


def boundary_gradient_diagnostic(cell, inputs, time_edges_seconds, *, subdivisions=1,
                                 seconds_per_model_time=1.0, epsilon=1e-4,
                                 absolute_tolerance=1e-7, relative_tolerance=2e-3):
    """Check end-to-end boundary/financial directional derivatives on a cloned cell.

    The fixed probe objective is mean squared terminal memory, not a task loss.
    Central differences independently rerun both sides of each parameter-space
    direction; original weights and their gradients are untouched. FP64 is
    recommended. Report inactive directions instead of accepting zero gradients
    as evidence of learning. This is a finite fixture, not a general proof.
    """
    epsilon = _positive_number(epsilon, "epsilon")
    absolute_tolerance = _positive_number(absolute_tolerance, "absolute_tolerance")
    relative_tolerance = _positive_number(relative_tolerance, "relative_tolerance")
    candidate = copy.deepcopy(cell)
    fixed_input = inputs.detach().clone()

    def objective():
        trace = stream_held_inputs(candidate, fixed_input, time_edges_seconds,
                                   seconds_per_model_time=seconds_per_model_time,
                                   subdivisions=subdivisions)
        return trace.state.memory.square().mean()

    named = dict(candidate.named_parameters())
    selected = [(name, named[name]) for name in ("boundary_input.weight", "raw_financial")]
    active = [(name, parameter) for name, parameter in selected if parameter.requires_grad]
    with torch.enable_grad():
        gradients = (torch.autograd.grad(objective(), [parameter for _, parameter in active], allow_unused=True)
                     if active else [])
    derivatives = {name: gradient for (name, _), gradient in zip(active, gradients)}
    rows = []
    for name, parameter in selected:
        if not parameter.requires_grad or derivatives.get(name) is None:
            rows.append({"parameter": name, "status": "inactive", "reason": "not differentiably active"})
            continue
        direction = torch.cos(torch.arange(parameter.numel(), dtype=parameter.dtype,
                                           device=parameter.device)+.5).reshape_as(parameter)
        direction /= direction.norm()
        analytical = float((derivatives[name]*direction).sum())
        original = parameter.detach().clone()
        with torch.no_grad():
            try:
                parameter.copy_(original+epsilon*direction)
                plus = float(objective())
                parameter.copy_(original-epsilon*direction)
                minus = float(objective())
            finally:
                parameter.copy_(original)
        numerical = (plus-minus)/(2*epsilon)
        error = abs(analytical-numerical)
        limit = absolute_tolerance+relative_tolerance*max(abs(analytical), abs(numerical))
        finite = all(math.isfinite(value) for value in (analytical, numerical, error))
        nonzero = max(abs(analytical), abs(numerical)) > absolute_tolerance
        status = "passed" if finite and nonzero and error <= limit else "inactive" if finite and not nonzero else "failed"
        rows.append({"parameter": name, "status": status, "analytical_directional_derivative": analytical,
                     "central_difference": numerical, "absolute_error": error, "allowed_error": limit})
    return {"schema": "hx-value-stream-gradient-v1", "objective": "mean_squared_terminal_memory",
            "epsilon": epsilon, "subdivisions": subdivisions, "rows": rows,
            "status": "passed" if all(row["status"] == "passed" for row in rows) else "incomplete_or_failed"}
