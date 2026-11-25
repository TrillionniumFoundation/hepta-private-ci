"""Explicit causal input buffers and inter-population message diagnostics.

This module is outside the prospective training closure. The input writer and
physical transition law remain the original core's. Only the input-drive path
uses the declared buffer, and only OLD unsigned messages are transformed.
"""

from dataclasses import asdict, dataclass, replace
import math

import torch
from torch import nn

from qualification.hcsn_smallnet_20261124.model import ModelConfig, PopulationState, SmallHCSN


@dataclass(frozen=True)
class ControlSpec:
    mode: str = "raw"
    period: int = 2
    pulse_columns: tuple = (0, 1, 2, 3)
    cue_pairs: tuple = ((0, 2), (1, 3))

    def __post_init__(self):
        if self.mode not in ("raw", "accumulate", "hold") or type(self.period) is not int or self.period < 1:
            raise ValueError("declared causal mode and positive integer period required")
        if len(set(self.pulse_columns)) != len(self.pulse_columns):
            raise ValueError("pulse columns must be distinct")


@dataclass(frozen=True)
class ControlState:
    pending: torch.Tensor
    held: torch.Tensor
    step: int
    spec: ControlSpec

    def detach(self):
        return ControlState(self.pending.detach(), self.held.detach(), self.step, self.spec)


def initial_control(frame, spec, step=0):
    if frame.ndim != 2 or type(step) is not int or step < 0:
        raise ValueError("[batch,input] template and nonnegative integer clock required")
    return ControlState(torch.zeros_like(frame), torch.zeros_like(frame), step, spec)


def control_step(frame, state):
    """Process one observed frame before its possible slow-control update.

    Accumulate sums declared impulse coordinates since the preceding update and
    consumes them exactly once; other coordinates retain the current frame.
    Hold retains the last value and observed flag for each explicit cue pair.
    Neither operation sees labels, future frames, or other batch members.
    """
    spec = state.spec
    if (frame.ndim != 2 or frame.shape != state.pending.shape or frame.shape != state.held.shape
            or frame.dtype != state.pending.dtype or frame.dtype != state.held.dtype
            or frame.device != state.pending.device or frame.device != state.held.device
            or not bool(torch.isfinite(frame).all()) or not bool(torch.isfinite(state.pending).all())
            or not bool(torch.isfinite(state.held).all()) or type(state.step) is not int or state.step < 0):
        raise ValueError("finite complete control state must match this frame")
    width = frame.shape[-1]
    if spec.mode == "accumulate" and any(type(i) is not int or not 0 <= i < width for i in spec.pulse_columns):
        raise ValueError("pulse coordinate outside the declared input")
    due = state.step % spec.period == 0
    pending, held = state.pending, state.held
    if spec.mode == "accumulate":
        mask = frame.new_zeros(width)
        mask[list(spec.pulse_columns)] = 1
        pending = pending + frame*mask
        control = frame*(1-mask) + pending
        pending = torch.zeros_like(pending) if due else pending
    elif spec.mode == "hold":
        held, control = held.clone(), frame.clone()
        used = set()
        for value, flag in spec.cue_pairs:
            if (value in used or flag in used or value == flag
                    or not 0 <= value < width or not 0 <= flag < width):
                raise ValueError("distinct in-range value/arrival-flag pairs required")
            used.update((value, flag))
            arrival = frame[:, flag]
            if not bool(((arrival == 0) | (arrival == 1)).all()):
                raise ValueError("hold requires explicit binary observed arrival flags")
            held[:, value] = torch.where(arrival.bool(), frame[:, value], state.held[:, value])
            held[:, flag] = torch.where(arrival.bool(), torch.ones_like(arrival), state.held[:, flag])
            control[:, value], control[:, flag] = held[:, value], held[:, flag]
    else:
        control = frame
    return control, ControlState(pending, held, state.step+1, spec), due


def transform_unsigned(message, reference, mode, scale=1.):
    """Change the unsigned coordinate only; local physical emissions stay raw."""
    if mode not in ("raw", "centered", "bounded", "centered_bounded"):
        raise ValueError("unknown unsigned-message diagnostic")
    if not math.isfinite(scale) or scale <= 0:
        raise ValueError("finite positive message scale required")
    if message.ndim != 3 or message.shape[1] != 3 or reference.shape != (message.shape[-1],):
        raise ValueError("message [batch,three,neuron] and per-unit reference required")
    if mode == "raw":
        return message
    unsigned = message[:, 1]
    if mode in ("centered", "centered_bounded"):
        unsigned = unsigned-reference
    if mode in ("bounded", "centered_bounded"):
        unsigned = scale*torch.tanh(unsigned/scale)
    return torch.stack((message[:, 0], unsigned, message[:, 2]), 1)


class _ControlLinear(nn.Linear):
    """Share the original parameters without additional RNG draws or key names."""
    def __init__(self, linear):
        nn.Module.__init__(self)
        self.in_features, self.out_features = linear.in_features, linear.out_features
        self.weight, self.bias = linear.weight, linear.bias
        self.frame = None

    def forward(self, value):
        return nn.functional.linear(value if self.frame is None else self.frame, self.weight, self.bias)


@dataclass(frozen=True)
class CommunicationState:
    population: object
    control: ControlState
    unsigned_policy: tuple

    def detach(self):
        return CommunicationState(self.population.detach(), self.control.detach(), self.unsigned_policy)

    @property
    def density(self):
        return self.population.density

    @property
    def boundary(self):
        return self.population.boundary

    @property
    def drift(self):
        return self.population.drift

    @property
    def cost(self):
        return self.population.cost

    @property
    def message(self):
        return self.population.message

    @property
    def step(self):
        return self.population.step

    @property
    def config(self):
        return self.population.config


def pack_state(state):
    """Portable tensors/primitives only; safe to load with torch weights_only."""
    return {"schema": "communication-state-v1", "config": asdict(state.config),
            "population": {key: getattr(state, key).detach().clone() for key in
                           ("density", "boundary", "drift", "cost", "message")},
            "step": state.step, "control_step": state.control.step,
            "control_spec": asdict(state.control.spec),
            "pending": state.control.pending.detach().clone(), "held": state.control.held.detach().clone(),
            "unsigned_policy": state.unsigned_policy}


def unpack_state(value):
    if value["schema"] != "communication-state-v1" or value["step"] != value["control_step"]:
        raise ValueError("foreign or inconsistent serialized communication state")
    physical = PopulationState(**value["population"], step=value["step"], config=ModelConfig(**value["config"]))
    control = ControlState(value["pending"], value["held"], value["control_step"], ControlSpec(**value["control_spec"]))
    return CommunicationState(physical, control, tuple(value["unsigned_policy"]))


class CommunicationHCSN(SmallHCSN):
    """Single-instance causal diagnostic wrapper, with all persistent state explicit.

    input_drive sees buffered input; input_mark sees the original observed frame.
    The shared module parameters retain their original state_dict paths. The
    temporary frame override exists only inside one synchronous forward tick;
    nested/reentrant calls are rejected. This wrapper is not a speed benchmark.
    """
    def __init__(self, config, *, control_mode="raw", unsigned_mode="raw", unsigned_scale=1.):
        super().__init__(config)
        self.control_spec = ControlSpec(control_mode, config.slow_every)
        self.unsigned_mode, self.unsigned_scale = unsigned_mode, unsigned_scale
        self.input_drive = _ControlLinear(self.input_drive)
        self.observer = None
        with torch.no_grad():
            drift = torch.full_like(self.fixed_boundary, config.base_drift)
            generator, event = self._generator(drift, self.fixed_boundary)
            # The final unused absorbing bookkeeping state is excluded: keeping
            # it would make the stationary distribution non-unique.
            matrix = generator[:, :-1, :-1].transpose(-1, -2).clone()
            matrix[:, -1] = 1
            target = event.new_zeros(config.neurons, matrix.shape[-1])
            target[:, -1] = 1
            stationary = torch.linalg.solve(matrix, target[..., None])[..., 0]
            if not bool(torch.isfinite(stationary).all()) or bool((stationary < -1e-8).any()):
                raise ValueError("nominal stationary reference is outside the probability domain")
            reference = (stationary*event[:, :-1]).sum(-1)
        self.register_buffer("unsigned_reference", reference)
        transform_unsigned(reference.new_zeros(1, 3, config.neurons), reference, unsigned_mode, unsigned_scale)

    def initial_state(self, batch, initial_margin=None):
        physical = super().initial_state(batch, initial_margin)
        template = self.input_drive.weight.new_zeros(batch, self.config.input_size)
        return CommunicationState(physical, initial_control(template, self.control_spec),
                                  (self.unsigned_mode, self.unsigned_scale))

    def forward(self, x, return_features=False, state=None):
        if self.input_drive.frame is not None:
            raise RuntimeError("reentrant diagnostic forward is unsupported")
        if x.ndim != 3 or not len(x):
            raise ValueError("nonempty [time,batch,input] sequence required")
        state = self.initial_state(x.shape[1]) if state is None else state
        if (not isinstance(state, CommunicationState) or state.control.spec != self.control_spec
                or state.control.step != state.population.step
                or state.unsigned_policy != (self.unsigned_mode, self.unsigned_scale)):
            raise ValueError("complete physical and control state with matching clock required")
        outputs, features, mass_errors, projections = [], [], [], []
        for frame in x:
            control, buffered, _ = control_step(frame, state.control)
            physical = state.population
            # There is no previous interval at step zero: retain its zero message.
            if physical.step:
                transformed = transform_unsigned(physical.message, self.unsigned_reference,
                                                 self.unsigned_mode, self.unsigned_scale)
                physical = replace(physical, message=transformed)
            if self.observer is not None:
                self.observer(self, frame, control, state.population.message, physical.message, physical.step)
            self.input_drive.frame = control
            try:
                output, latent, physical = super().forward(frame[None], return_features=True, state=physical)
            finally:
                self.input_drive.frame = None
            state = CommunicationState(physical, buffered, state.unsigned_policy)
            outputs.append(output)
            features.append(latent)
            mass_errors.append(self.last_diagnostics["mass_error"])
            projections.append(self.last_diagnostics["upper_projection_mass_max"])
        self.last_diagnostics.update(mass_error=max(mass_errors), upper_projection_mass_max=max(projections),
            control_mode=self.control_spec.mode, unsigned_mode=self.unsigned_mode,
            additional_control_state_bytes=sum(v.numel()*v.element_size() for v in (state.control.pending, state.control.held)))
        result = torch.cat(outputs)
        return (result, torch.cat(features), state) if return_features else result


def make_communication_model(config, *, control_mode="raw", unsigned_mode="raw", unsigned_scale=1.):
    return CommunicationHCSN(config, control_mode=control_mode, unsigned_mode=unsigned_mode,
                             unsigned_scale=unsigned_scale)
