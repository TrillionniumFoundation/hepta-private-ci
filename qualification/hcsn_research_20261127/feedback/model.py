"""A delayed, centered boundary link and two causal forces on the same #7149 population law."""
from dataclasses import dataclass, replace
import torch
from torch import nn
from torch.nn import functional as F
from qualification.hcsn_smallnet_20261124.model import ModelConfig, PopulationState
from qualification.hcsn_closure_20261124.boundary_fix import delivered_boundary
from qualification.hcsn_closure_20261124.communication import ControlSpec, control_step, initial_control
from qualification.hcsn_closure_20261124.dual_force import DualForceHCSN, DualState
from qualification.hcsn_closure_20261124.joint_run import JointHCSN

GAINS = {"zero": (0., 0.), "restore": (.6, 0.), "risk": (0., .6), "dual": (.6, .6)}

@dataclass(frozen=True)
class FeedbackState:
    physical: DualState
    control: object

class FeedbackBoundary(JointHCSN):
    """Send the previous physical boundary. Only the next drift receives restoring/risk feedback."""
    def __init__(self, arm, neurons=8, channel="boundary_only"):
        call, panic = GAINS[arm]
        config = ModelConfig(neurons=neurons, precision="mixed", backend="uniformized",
                             boundary_mode="qvi", message_mode="full", feature_bank="value_risk",
                             feature_normalization="none")
        super().__init__(config, channel)
        self.register_buffer("boundary_reference", self.fixed_boundary.detach().clone())
        self.register_buffer("call_gain", self.reset_absolute.new_tensor(call))
        self.register_buffer("panic_gain", self.reset_absolute.new_tensor(panic))
        self.register_buffer("target_margin", self.reset_absolute.new_tensor(.7))
        self.control_spec = ControlSpec("accumulate", config.slow_every)
        self.channel = channel

    def initial_state(self, batch, initial_margin=None):
        p = super().initial_state(batch, initial_margin)
        blank = self.input_drive.weight.new_zeros(batch, self.config.input_size)
        return FeedbackState(DualState(p,torch.zeros_like(p.boundary)), initial_control(blank, self.control_spec))

    def forward(self, x, state=None, return_features=False, silence_boundary=False, trace=False):
        c, half = self.config, self.config.neurons // 2
        state = self.initial_state(x.shape[1]) if state is None else state
        if self._interval is not None or state.physical.step != state.control.step:
            raise ValueError("forward requires nonreentrant, synchronized state")
        physical, control = state.physical, state.control
        tolerance = DualForceHCSN._validate(self, x, physical)
        logits, features, traces = [], [], []
        self._interval = {}
        try:
            for frame in x:
                driven, control, due = control_step(frame, control)
                message = delivered_boundary(physical.message, self.boundary_reference, "centered", physical.step)
                if silence_boundary:
                    message = torch.cat((torch.zeros_like(message[:, :1]), message[:, 1:]), 1)
                rec = F.linear(message.to(frame).flatten(1), self.recurrent.weight * self.synaptic_mask)
                drive = F.pad(self.input_drive(driven), (0, half)) + rec
                raw_mark = F.pad(self.input_mark(frame), (0, half)) + rec
                if due:
                    restoring, panic = DualForceHCSN.forces(self, physical)
                    forced_drive = drive + (restoring + panic).to(drive)
                    drift = (c.base_drift + c.drift_scale * torch.tanh(forced_drive)).to(self.reset_absolute)
                    cost = (c.cost + c.cost_span * torch.tanh(self.raw_cost + .15*drive)).to(drift)
                    boundary = self.qvi_boundary(drift, cost)
                else:
                    drift, cost, boundary = physical.drift, physical.cost, physical.boundary
                density, jump, projected = self._remap(physical.population, boundary)
                mark = raw_mark.tanh().to(density)
                content = ((1-c.write_fraction)*density[..., 1, :c.bins]
                           + c.write_fraction*mark[..., None]*density[..., 0, :c.bins])
                written = torch.stack((density[..., 0, :], torch.cat((content, density[..., 1, c.bins:]), -1)), -2)
                generator, event = self._generator(drift, boundary)
                density, hits, value, risk, margin = self._flow(written, jump, generator, event, boundary, cost)
                if bool(((risk < -tolerance) | (risk > 1+tolerance) | (risk > hits[..., 0]+tolerance)).any()):
                    raise FloatingPointError("invalid first-event probability")
                f = torch.stack((value, risk, hits[..., 1]/c.dt, hits[..., 0]/c.dt, margin), -1)[:, half:]
                f = f.flatten(1).to(frame)
                features.append(f)
                logits.append(self.readout(f))
                new_message = torch.stack((boundary, hits[..., 0]/c.dt, hits[..., 1]/c.dt), 1)
                p = PopulationState(density, boundary, drift, cost, new_message, physical.step+1, c)
                physical = DualState(p, risk)
                if trace:
                    traces.append({"step":p.step,"due":due,"mass":float((p.density[...,0,:].sum(-1)-1).abs().max().detach()),
                                   "projected_max":float(projected[...,0].max().detach()),
                                   "drift_absolute_mean":float(drift.abs().mean().detach()),
                                   "restoring_rms":float(restoring.square().mean().sqrt().detach()) if due else 0.,
                                   "panic_rms":float(panic.square().mean().sqrt().detach()) if due else 0.})
        finally:
            self._interval = None
        DualForceHCSN._validate(self, x[-1:], physical)
        self.last_trace = traces
        outputs = torch.stack(logits)
        return (outputs,torch.stack(features), FeedbackState(physical,control)) if return_features else outputs

class PlainCenteredGate(nn.Module):
    """Same one-coordinate delayed sender, receiver-only readout, centered tanh gate; no diffusion."""
    def __init__(self, n=8):
        super().__init__()
        self.n = n
        self.control_spec = ControlSpec("accumulate",2)
        self.encoder = nn.Linear(6,n//2)
        self.synapse = nn.Linear(n,n,bias=False)
        self.keep = nn.Parameter(torch.zeros(n))
        self.readout = nn.Linear(n//2,2)
        mask = torch.ones(n,n)
        mask[:n//2,n//2:] = 0
        self.register_buffer("mask",mask)
        self.register_buffer("reference",torch.full((n,),.7))

    def forward(self, x):
        z=x.new_zeros((x.shape[1],self.n))
        control=initial_control(x[0],self.control_spec)
        outputs=[]
        for i,frame in enumerate(x):
            driven,control,due=control_step(frame,control)
            if due:
                old = (z-self.reference) if i else torch.zeros_like(z)
                u=F.pad(self.encoder(driven),(0,self.n//2))+F.linear(old,self.synapse.weight*self.mask)
                gate=self.keep.sigmoid()
                z=self.reference+gate*old+(1-gate)*u.tanh()
            outputs.append(self.readout(z[:,self.n//2:]-self.reference[self.n//2:]))
        return torch.stack(outputs)
