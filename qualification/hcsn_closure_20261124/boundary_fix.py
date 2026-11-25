"""Causal slow-control accumulation and fixed nominal boundary messages.

The physical generator, moving boundary and local emission values remain the
qualified mixed core's equations. Only the old inter-population boundary
coordinate is optionally centered; no data mean, gain search or label enters.
"""

from dataclasses import asdict, dataclass, replace

import torch

from qualification.hcsn_smallnet_20261124.model import ModelConfig, PopulationState, SmallHCSN
from .communication import ControlSpec, ControlState, _ControlLinear, control_step, initial_control
from .joint_run import JointHCSN


@dataclass(frozen=True)
class BoundaryState:
    population: PopulationState
    control: ControlState
    boundary_policy: str

    def detach(self):
        return BoundaryState(self.population.detach(), self.control.detach(), self.boundary_policy)

    def __getattr__(self, name):
        if name in ("density", "boundary", "drift", "cost", "message", "step", "config"):
            return getattr(self.population, name)
        raise AttributeError(name)


def delivered_boundary(message, reference, mode, step):
    if mode not in ("raw", "centered") or type(step) is not int or step < 0:
        raise ValueError("registered boundary message policy and causal clock required")
    if message.ndim != 3 or message.shape[1] != 3 or reference.shape != (message.shape[-1],):
        raise ValueError("complete three-channel message and per-unit nominal boundary required")
    if mode == "raw" or step == 0:
        return message
    return torch.stack((message[:, 0]-reference.to(message), message[:, 1], message[:, 2]), 1)


def pack_state(state):
    return {"schema":"boundary-control-state-v1", "config":asdict(state.config),
        "population":{key:getattr(state,key).detach().clone() for key in
                      ("density","boundary","drift","cost","message")},
        "step":state.step, "control_step":state.control.step,
        "control_spec":asdict(state.control.spec), "pending":state.control.pending.detach().clone(),
        "held":state.control.held.detach().clone(), "boundary_policy":state.boundary_policy}


def unpack_state(value):
    if value["schema"] != "boundary-control-state-v1" or value["step"] != value["control_step"]:
        raise ValueError("foreign or inconsistent boundary-control state")
    population = PopulationState(**value["population"], step=value["step"], config=ModelConfig(**value["config"]))
    control = ControlState(value["pending"], value["held"], value["control_step"], ControlSpec(**value["control_spec"]))
    return BoundaryState(population, control, value["boundary_policy"])


class BoundaryControlHCSN(JointHCSN):
    def __init__(self, config, *, channel, control_mode, boundary_mode):
        if control_mode not in ("raw", "accumulate") or boundary_mode not in ("raw", "centered"):
            raise ValueError("registered raw/accumulate and nominal-centered policies required")
        super().__init__(config, channel)
        self.control_spec = ControlSpec(control_mode, config.slow_every)
        self.boundary_mode = boundary_mode
        self.input_drive = _ControlLinear(self.input_drive)
        self.register_buffer("boundary_reference", self.fixed_boundary.detach().clone())
        self.observer = None

    def initial_state(self, batch, initial_margin=None):
        physical = super().initial_state(batch, initial_margin)
        frame = self.input_drive.weight.new_zeros(batch, self.config.input_size)
        return BoundaryState(physical, initial_control(frame,self.control_spec), self.boundary_mode)

    def forward(self, x, return_features=False, state=None):
        if self._interval is not None or self.input_drive.frame is not None:
            raise RuntimeError("concurrent/reentrant boundary-control forward is unsupported")
        if x.ndim != 3 or not len(x):
            raise ValueError("nonempty [time,batch,input] sequence required")
        state = self.initial_state(x.shape[1]) if state is None else state
        if (not isinstance(state,BoundaryState) or state.control.spec != self.control_spec
                or state.control.step != state.population.step or state.boundary_policy != self.boundary_mode):
            raise ValueError("complete matching physical/control clocks and policy required")
        logits, features, mass_errors, upper = [], [], [], []
        self._interval = {}
        try:
            for frame in x:
                control, buffered, _ = control_step(frame,state.control)
                population = state.population
                message = delivered_boundary(population.message,self.boundary_reference,
                                               self.boundary_mode,population.step)
                if self.observer is not None:
                    self.observer(self,frame,control,population.message,message,population.step)
                delivered = replace(population,message=message)
                self.input_drive.frame = control
                try:
                    # Keep the fast generator/flow cache alive across this whole
                    # sequence, while the core processes each observed frame once.
                    out,latent,physical = SmallHCSN.forward(self,frame[None],return_features=True,state=delivered)
                finally:
                    self.input_drive.frame = None
                # Store the raw physical emission, never a repeatedly centered
                # message, so cold/chunk continuation applies the transform once.
                state = BoundaryState(physical,buffered,self.boundary_mode)
                logits.append(out); features.append(latent)
                mass_errors.append(self.last_diagnostics["mass_error"])
                upper.append(self.last_diagnostics["upper_projection_mass_max"])
        finally:
            self._interval = None
            self.input_drive.frame = None
        self.last_diagnostics.update(mass_error=max(mass_errors), upper_projection_mass_max=max(upper),
            control_mode=self.control_spec.mode,boundary_message_mode=self.boundary_mode,
            additional_control_state_bytes=sum(v.numel()*v.element_size() for v in
                                               (state.control.pending,state.control.held)))
        out = torch.cat(logits)
        return (out,torch.cat(features),state) if return_features else out
