"""Causal dual forces that actually enter the next frozen neuron law.

Call-gradient restoration uses the exact cell average of a reference continuous
QVI slope, integrated against the finite-volume population. Panic uses the last
interval's first-hit probability. This is an explicit bounded mean-field policy,
not an optimal policy for the resulting coupled network and not financial prices.
"""

from dataclasses import dataclass
import torch
from torch import nn

from qualification.hcsn_smallnet_20261124.model import PopulationState
from .models import SignedHCSN


@dataclass(frozen=True)
class DualState:
    population: PopulationState
    previous_risk: torch.Tensor

    def __getattr__(self, name):
        return getattr(self.population, name)

    def detach(self):
        return DualState(self.population.detach(), self.previous_risk.detach())


class DualForceHCSN(SignedHCSN):
    def __init__(self, config, *, call_gain=0., panic_gain=0., target_margin=.7):
        if not (0 <= call_gain <= 1 and 0 <= panic_gain <= 1 and .3 < target_margin < 1.5):
            raise ValueError("bounded nonnegative force gains and interior reference required")
        super().__init__(config)
        self.register_buffer("call_gain", self.reset_absolute.new_tensor(call_gain))
        self.register_buffer("panic_gain", self.reset_absolute.new_tensor(panic_gain))
        self.register_buffer("target_margin", self.reset_absolute.new_tensor(target_margin))

    def initial_state(self, batch, initial_margin=None):
        population = super().initial_state(batch, initial_margin)
        return DualState(population, torch.zeros_like(population.boundary))

    def forces(self, state):
        c, mu = self.config, state.drift
        root = torch.sqrt(mu.square()+2*c.discount*c.sigma*c.sigma)
        k = torch.where(mu >= 0, (mu+root)/(c.sigma*c.sigma),
                        2*c.discount/(root-mu))
        edges, _ = self._geometry(mu)
        width = c.extent/c.bins
        # Mean of q(y)=1-exp(-k*y) under each uniform cell. No q(mean(X)).
        q = 1-torch.exp(-k[..., None]*edges[:-1])*(-torch.expm1(-k[..., None]*width))/(k[..., None]*width)
        target = self._deposit(self.target_margin.expand_as(mu))
        target_q = (target*q).sum(-1)
        active = state.density[..., 0, :c.bins]
        restoring = self.call_gain*(active*(target_q[..., None]-q)).sum(-1)
        panic = -self.panic_gain*state.previous_risk
        return restoring, panic

    def _validate(self, x, state):
        c = self.config
        if (x.ndim != 3 or x.shape[-1] != c.input_size or not len(x)
                or not 1 <= x.shape[1] <= 256 or x.dtype != self.input_drive.weight.dtype
                or x.device != self.input_drive.weight.device or not bool(torch.isfinite(x).all())):
            raise ValueError("finite matching time/batch/input required")
        if not isinstance(state, DualState) or state.config != c:
            raise ValueError("complete dual state and matching configuration required")
        if (type(state.step) is not int or not 0 <= state.step < 2**32
                or state.density.shape != (x.shape[1], c.neurons, 2, c.bins+c.stages+1)
                or state.message.shape != (x.shape[1], 3, c.neurons)
                or any(getattr(state, name).shape != (x.shape[1], c.neurons)
                       for name in ("boundary", "drift", "cost", "previous_risk"))):
            raise ValueError("dual state dimensions or clock invalid")
        tensors = [getattr(state, name) for name in ("density", "boundary", "drift", "cost", "message", "previous_risk")]
        if any(t.dtype != self.reset_absolute.dtype or t.device != x.device
               or not bool(torch.isfinite(t).all()) for t in tensors):
            raise ValueError("dual state dtype, device or finiteness invalid")
        tol = 3e-5 if c.precision == "native32" else 2e-9
        if (bool((state.density[..., 0, :].sum(-1)-1).abs().gt(tol).any())
                or bool((state.density[..., 0, :] < -tol).any())
                or bool((state.density[..., 1, :].abs() > state.density[..., 0, :]+tol).any())
                or bool((state.drift-c.base_drift).abs().gt(c.drift_scale+1e-6).any())
                or bool((state.cost-c.cost).abs().gt(c.cost_span+1e-6).any())
                or bool(((state.previous_risk < -tol) | (state.previous_risk > 1+tol)).any())):
            raise ValueError("dual state violates the physical domain")
        return tol

    def forward(self, x, return_features=False, state=None):
        c, half = self.config, self.config.neurons//2
        state = self.initial_state(x.shape[1]) if state is None else state
        tolerance = self._validate(x, state)
        features_all, logits_all, errors, projections, forces = [], [], [], [], []
        for inputs in x:
            message = state.message.to(inputs)
            mask = inputs.new_tensor((0., 1., 1.))
            rec = nn.functional.linear((message*mask[None, :, None]).flatten(1), self.recurrent.weight*self.synaptic_mask)
            drive = nn.functional.pad(self.input_drive(inputs), (0, half))+rec
            raw_mark = nn.functional.pad(self.input_mark(inputs), (0, half))+rec
            restoring, panic = self.forces(state)
            if state.step % c.slow_every == 0:
                forced_drive = drive+(restoring+panic).to(drive)
                drift = (c.base_drift+c.drift_scale*forced_drive.tanh()).to(self.reset_absolute)
                cost = (c.cost+c.cost_span*(self.raw_cost+.15*drive).tanh()).to(drift)
                boundary = (self.qvi_boundary(drift, cost) if c.boundary_mode == "qvi" else
                    self.fixed_boundary.expand_as(drift) if c.boundary_mode == "fixed" else
                    self.fixed_boundary+c.boundary_span*(self.raw_boundary+.15*drive).tanh().to(drift))
            else:
                drift, cost, boundary = state.drift, state.cost, state.boundary
            density, jump, projected = self._remap(state.population, boundary)
            mark = raw_mark.tanh().to(density)
            content = ((1-c.write_fraction)*density[..., 1, :c.bins]
                       +c.write_fraction*mark[..., None]*density[..., 0, :c.bins])
            written = torch.stack((density[..., 0, :], torch.cat((content, density[..., 1, c.bins:]), -1)), -2)
            generator, event = self._generator(drift, boundary)
            density, hits, value, risk, margin = self._flow(written, jump, generator, event, boundary, cost)
            if bool(((risk < -tolerance) | (risk > 1+tolerance) | (risk > hits[..., 0]+tolerance)).any()):
                raise FloatingPointError("dual first-hit probability invariant failed")
            previous_risk = risk
            if c.feature_bank == "tanh":
                value, risk = drive.tanh().to(value), raw_mark.tanh().to(risk)
            elif c.feature_bank == "value_only":
                risk = torch.zeros_like(risk)
            elif c.feature_bank == "risk_only":
                value = torch.zeros_like(value)
            features = torch.stack((value, risk, hits[..., 1]/c.dt, hits[..., 0]/c.dt, margin), -1)[:, half:]
            if c.feature_normalization == "population":
                features = features-features.mean(1, keepdim=True)
                features = features*torch.rsqrt(features.square().mean(1, keepdim=True)+1e-12)
            features = features.flatten(1).to(inputs)
            new_message = torch.stack((boundary, hits[..., 0]/c.dt, hits[..., 1]/c.dt), 1)
            population = PopulationState(density, boundary, drift, cost, new_message, state.step+1, c)
            state = DualState(population, previous_risk)
            errors.append((density[..., 0, :].sum(-1)-1).abs().amax())
            projections.append(projected[..., 0].amax())
            forces.append(torch.stack((restoring, panic), -1).detach())
            features_all.append(features)
            logits_all.append(self.readout(features))
        mass_error = torch.stack(errors).max()
        force_tensor = torch.stack(forces)
        self.last_diagnostics = {"mass_error": float(mass_error.detach()),
            "probability_min": float(density[..., 0, :].detach().min()),
            "mark_excess": float((density[..., 1, :].abs()-density[..., 0, :]).detach().max()),
            "upper_projection_mass_max": float(torch.stack(projections).max().detach()),
            "call_force_rms": float(force_tensor[..., 0].square().mean().sqrt()),
            "panic_force_rms": float(force_tensor[..., 1].square().mean().sqrt()),
            "state_step": state.step,
            "complete_state_tensor_bytes": sum(getattr(state, name).numel()*getattr(state, name).element_size()
                 for name in ("density", "boundary", "drift", "cost", "message", "previous_risk"))}
        self._validate(x[-1:], state)
        if bool(mass_error > tolerance):
            raise FloatingPointError("dual mass balance failed; no renormalization applied")
        logits = torch.stack(logits_all)
        return (logits, torch.stack(features_all), state) if return_features else logits
