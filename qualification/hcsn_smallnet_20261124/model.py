"""Independent populations retain full state; upwind space and Erlang delay
approximate a reset diffusion. QVI optimizes only its frozen local reward with
the same absolute reset/delay. Clocked writes and controls read OLD messages;
matrix actions include every phase/reset generation, without task-wide optimality.
"""

from dataclasses import dataclass
import math
import torch
from torch import nn
from torch.autograd.function import once_differentiable

from qualification.hcsn_training.population_generator import finite_volume_generator
from qualification.hcsn_adaptive.uniformized_flow import ActionBudget


@dataclass(frozen=True)
class ModelConfig:
    input_size: int = 6
    neurons: int = 8
    bins: int = 6
    stages: int = 3
    dt: float = .25
    extent: float = 2.0
    sigma: float = .55
    base_drift: float = -.2
    drift_scale: float = .15
    discount: float = .3
    refractory: float = .2
    reset_absolute: float = 1.2
    gain: float = .8
    maintenance: float = .25
    cost: float = .15
    cost_span: float = .02
    boundary_span: float = .1
    write_fraction: float = .5
    slow_every: int = 2
    boundary_mode: str = "qvi"
    message_mode: str = "full"
    feature_bank: str = "value_risk"
    feature_normalization: str = "none"
    precision: str = "float64"
    backend: str = "dense"

    def __post_init__(self):
        if (self.neurons not in (8, 32, 64) or not 1 <= self.input_size <= 256
                or not 3 <= self.bins <= 32 or not 1 <= self.stages <= 32
                or type(self.slow_every) is not int or self.slow_every < 1):
            raise ValueError("bounded independent populations, spatial bins and phases required")
        if (self.boundary_mode not in ("fixed", "learned", "qvi")
                or self.message_mode not in ("full", "boundary", "flow")
                or self.feature_bank not in ("value_risk", "tanh", "value_only", "risk_only")
                or self.feature_normalization not in ("none", "population")
                or self.precision not in ("float64", "mixed", "native32")
                or self.backend not in ("dense", "uniformized")):
            raise ValueError("unknown model mode")
        vals = (self.dt, self.extent, self.sigma, self.discount, self.refractory,
                self.gain, self.cost-self.cost_span, self.boundary_span)
        if (any(not math.isfinite(v) or v <= 0 for v in vals)
                or not 0 < self.write_fraction <= 1 or self.drift_scale < 0
                or not 0 < self.dt <= 1 or abs(self.base_drift)+self.drift_scale > 2):
            raise ValueError("invalid physical/numerical domain")


def _residual(b, mu, cost, absolute, sigma, rho, eta, gain, maintenance):
    root = torch.sqrt(mu.square()+2*rho*sigma*sigma)
    k = torch.where(mu >= 0, (mu+root)/(sigma*sigma), 2*rho/(root-mu))
    slope = gain/rho
    intercept = gain*mu/(rho*rho)-maintenance/rho
    amplitude = slope/k
    residual = (slope*b+intercept+amplitude+cost
                -eta*(slope*absolute+intercept+amplitude*torch.exp(-k*(absolute-b))))
    derivative = slope*(-torch.expm1(math.log(eta)-k*(absolute-b)))
    return residual, derivative


def _symmetric_clip(x):
    """Unit ramp, with the midpoint of its two slopes at an exact knot."""
    clipped = x.clamp(0, 1)
    edge = (x == 0) | (x == 1)
    return torch.where(edge, .5*x+.5*clipped.detach(), clipped)


class _QVI(torch.autograd.Function):
    @staticmethod
    def forward(ctx, mu, cost, absolute, sigma, rho, eta, gain, maintenance):
        args = (sigma, rho, eta, gain, maintenance)
        low, high = absolute.expand_as(mu)-8, absolute.expand_as(mu)-1e-4
        if not bool((_residual(low, mu, cost, absolute, *args)[0] < 0).all()
                    & (_residual(high, mu, cost, absolute, *args)[0] > 0).all()):
            raise ValueError("QVI interior root is outside declared domain")
        for _ in range(56 if mu.dtype == torch.float64 else 28):
            mid = (low+high)/2
            below = _residual(mid, mu, cost, absolute, *args)[0] < 0
            low, high = torch.where(below, mid, low), torch.where(below, high, mid)
        result = (low+high)/2
        ctx.save_for_backward(result, mu, cost, absolute)
        ctx.args = args
        return result

    @staticmethod
    @once_differentiable
    def backward(ctx, upstream):
        b, mu, cost, absolute = ctx.saved_tensors
        with torch.enable_grad():
            values = tuple(t.detach().requires_grad_() for t in (mu, cost, absolute))
            residual, derivative = _residual(b.detach(), *values, *ctx.args)
            grads = torch.autograd.grad(residual, values, -upstream/derivative.detach())
        return (*grads, None, None, None, None, None)


@dataclass(frozen=True)
class PopulationState:
    density: torch.Tensor  # [batch, independent neuron, probability/signed mark, state]
    boundary: torch.Tensor
    drift: torch.Tensor
    cost: torch.Tensor
    message: torch.Tensor  # [batch, three channels, neuron]
    step: int
    config: ModelConfig

    def detach(self):
        return PopulationState(*(getattr(self, k).detach() for k in
            ("density", "boundary", "drift", "cost", "message")), self.step, self.config)


class SmallHCSN(nn.Module):
    """Senders see raw input; receivers and readout must use learned messages."""
    def __init__(self, config=None):
        super().__init__()
        self.config = c = config or ModelConfig()
        n, half = c.neurons, c.neurons//2
        dtype = torch.float64 if c.precision == "float64" else torch.float32
        self.input_drive = nn.Linear(c.input_size, half, dtype=dtype)
        self.input_mark = nn.Linear(c.input_size, half, dtype=dtype)
        self.recurrent = nn.Linear(3*n, n, bias=False, dtype=dtype)
        nn.init.normal_(self.recurrent.weight, std=.12/math.sqrt(n))
        self.raw_cost = nn.Parameter(torch.zeros(n, dtype=dtype))
        self.raw_boundary = nn.Parameter(torch.zeros(n, dtype=dtype), requires_grad=c.boundary_mode == "learned")
        physical = torch.float32 if c.precision == "native32" else torch.float64
        absolute = torch.linspace(c.reset_absolute-.03, c.reset_absolute+.03, n, dtype=physical)
        self.register_buffer("reset_absolute", absolute)
        fixed = self.qvi_boundary(torch.full_like(absolute, c.base_drift), torch.full_like(absolute, c.cost))
        self.register_buffer("fixed_boundary", fixed.detach())
        mask = torch.ones(n, n, dtype=dtype)
        mask[:half, half:] = 0
        self.register_buffer("synaptic_mask", mask.repeat(1, 3))
        self.feature_dim = 5*half
        self.readout = nn.Linear(self.feature_dim, 2, dtype=dtype)
        self.feature_names = tuple(f"receiver_{i}_{name}" for i in range(half)
                                  for name in ("value", "risk", "signed_event_rate", "event_rate", "margin"))
        self.last_diagnostics = {}

    def qvi_boundary(self, drift, cost):
        c = self.config
        eta = math.exp(-c.stages*math.log1p(c.discount*c.refractory/c.stages))
        return _QVI.apply(drift, cost, self.reset_absolute, c.sigma, c.discount,
                          eta, c.gain, c.maintenance)

    def _geometry(self, like):
        c = self.config
        edges = torch.linspace(0, c.extent, c.bins+1, dtype=like.dtype, device=like.device)
        return edges, (edges[:-1]+edges[1:])/2

    def _deposit(self, margin):
        c = self.config
        _, centers = self._geometry(margin)
        if not bool(((margin > centers[0]) & (margin < centers[-1])).all()):
            raise ValueError("point initial/reset must be strictly within the cell-center hull")
        # Interior piecewise-linear deposition sums to one without mass repair.
        return _symmetric_clip(1-(margin[..., None]-centers).abs()/(c.extent/c.bins))

    def initial_state(self, batch, initial_margin=None):
        c, like = self.config, self.reset_absolute
        if type(batch) is not int or not 1 <= batch <= 256:
            raise ValueError("batch 1..256 required; neurons remain a separate axis")
        boundary = self.fixed_boundary.expand(batch, -1)
        margin = like-boundary if initial_margin is None else torch.as_tensor(initial_margin, device=like.device, dtype=like.dtype)
        margin = torch.broadcast_to(margin, (batch, c.neurons))
        active = self._deposit(margin)
        probability = torch.cat((active, like.new_zeros(batch, c.neurons, c.stages+1)), -1)
        return PopulationState(torch.stack((probability, torch.zeros_like(probability)), -2), boundary,
            torch.full_like(boundary, c.base_drift), torch.full_like(boundary, c.cost),
            like.new_zeros(batch, 3, c.neurons), 0, c)

    def _remap(self, state, boundary):
        c = self.config
        h = c.extent/c.bins
        index = torch.arange(c.bins+1, dtype=boundary.dtype, device=boundary.device)
        displacement = (boundary-state.boundary)/h
        cdf = _symmetric_clip(displacement[..., None, None]+index[None, :]-index[:-1, None])
        # One CDF conserves mass and its derivative; at grid knots use the
        # one-sided mean slope. This remap is not globally smooth.
        overlap = cdf[..., 1:]-cdf[..., :-1]
        lower, upper = cdf[..., 0], 1-cdf[..., -1]
        old = state.density[..., :c.bins]
        jump = (old*lower[..., None, :]).sum(-1)
        projected = (old*upper[..., None, :]).sum(-1)
        eye = torch.eye(c.bins, dtype=old.dtype, device=old.device)
        active = old @ overlap + projected[..., None]*eye[-1]
        phases = state.density[..., c.bins:c.bins+c.stages]
        phase0 = torch.eye(c.stages, dtype=old.dtype, device=old.device)[0]
        return torch.cat((active, phases+jump[..., None]*phase0, state.density[..., -1:]), -1), jump, projected

    def _generator(self, drift, boundary):
        c = self.config
        edges, _ = self._geometry(drift)
        spatial = finite_volume_generator(edges, drift[..., None].expand(*drift.shape, c.bins+1), c.sigma)
        q, hit, upper = spatial[..., :c.bins, :c.bins], spatial[..., :c.bins, c.bins], spatial[..., :c.bins, -1]
        q = q+torch.diag_embed(upper)  # declared reflecting finite upper edge
        reset = self._deposit(self.reset_absolute-boundary)
        phase_eye = torch.eye(c.stages, dtype=drift.dtype, device=drift.device)
        rate = c.stages/c.refractory
        phases = -rate*phase_eye+torch.diag(drift.new_full((c.stages-1,), rate), diagonal=1)
        top = torch.cat((q, hit[..., None]*phase_eye[0], torch.zeros_like(hit[..., None])), -1)
        bottom = torch.cat((rate*phase_eye[:, -1:]*reset[..., None, :],
                            phases.expand(*drift.shape, -1, -1), drift.new_zeros(*drift.shape, c.stages, 1)), -1)
        size = c.bins+c.stages+1
        generator = torch.cat((top, bottom, drift.new_zeros(*drift.shape, 1, size)), -2)
        event = torch.cat((hit, drift.new_zeros(*drift.shape, c.stages+1)), -1)
        return generator, event

    def _action(self, matrix, vectors, rate, duration, column=False):
        if self.config.backend == "dense":
            action = torch.matrix_exp(matrix*duration)
            return action @ vectors if column else vectors @ action
        # UniformizedFlow's tail planner, with DENSE batched action (not banded).
        # Its exact-arithmetic tail bound does not cover roundoff or VJP error.
        plan = ActionBudget().plan(float(rate.detach()), duration, max(1., float(rate.detach())))
        identity = torch.eye(matrix.shape[-1], dtype=matrix.dtype, device=matrix.device)
        transition = identity+matrix/rate
        dt = duration/plan["substeps"]
        z, zero = rate*dt, torch.exp(-rate*dt)
        result = vectors
        for _ in range(plan["substeps"]):
            term, weight = result, zero
            total = weight*term
            for k in range(1, plan["order"]+1):
                term = transition @ term if column else term @ transition
                weight = weight*z/k
                total = total+weight*term
            result = total
        return result

    def _flow(self, density, jump, generator, event, boundary, cost):
        c, size = self.config, generator.shape[-1]
        active = torch.cat((event.new_ones(c.bins), event.new_zeros(c.stages+1)))
        rewards = torch.stack((event, active.expand_as(event)), -1)
        augmented = torch.cat((torch.cat((generator, rewards), -1), event.new_zeros(*event.shape[:-1], 2, size+2)), -2)
        h = c.extent/c.bins
        # A configuration bound avoids numerical rate selection coupling batches.
        rate = event.new_tensor(max(c.stages/c.refractory,
            3*c.sigma**2/(2*h*h)+(abs(c.base_drift)+c.drift_scale)/h))
        padded = torch.cat((density, density.new_zeros(*density.shape[:-1], 2)), -1)
        result = self._action(augmented, padded, rate, c.dt)
        next_density, increments = result[..., :size], result[..., size:]
        destination = torch.eye(size, dtype=event.dtype, device=event.device)[c.bins]
        killed = generator-event[..., None]*destination
        first = torch.cat((torch.cat((killed, event[..., None]), -1), event.new_zeros(*event.shape[:-1], 1, size+1)), -2)
        terminal = event.new_zeros(*event.shape[:-1], size+1, 1)
        terminal[..., -1, 0] = 1
        first_prob = self._action(first, terminal, rate, c.dt, column=True)[..., :size, 0]
        # Include phase-release hits; count newly edge-crossed cohorts only once.
        never_hit = density[..., 0, :]-jump[..., :1]*destination
        risk = jump[..., 0]+(never_hit*first_prob).sum(-1)
        _, centers = self._geometry(event)
        reward = torch.cat((c.gain*(boundary[..., None]+centers)-c.maintenance,
                            event.new_zeros(*event.shape[:-1], c.stages+1)), -1)-cost[..., None]*event
        value = torch.linalg.solve(c.discount*torch.eye(size, dtype=event.dtype, device=event.device)-generator, reward[..., None])[..., 0]
        continuation = (next_density[..., 0, :]*value).sum(-1)
        margin = (next_density[..., 0, :c.bins]*centers).sum(-1)/c.extent
        hits = jump+increments[..., 0]
        return next_density, hits, continuation, risk, margin

    def forward(self, x, return_features=False, state=None):
        c, half = self.config, self.config.neurons//2
        if (x.ndim != 3 or x.shape[-1] != c.input_size or x.dtype != self.input_drive.weight.dtype
                or x.device != self.input_drive.weight.device or not len(x)
                or not 1 <= x.shape[1] <= 256 or not bool(torch.isfinite(x).all())):
            raise ValueError("finite matching [time,batch,input] required")
        state = self.initial_state(x.shape[1]) if state is None else state
        if (not isinstance(state, PopulationState) or state.config != c
                or type(state.step) is not int or not 0 <= state.step < 2**32
                or state.density.shape != (x.shape[1], c.neurons, 2, c.bins+c.stages+1)
                or any(getattr(state, key).shape != (x.shape[1], c.neurons) for key in ("boundary", "drift", "cost"))
                or state.message.shape != (x.shape[1], 3, c.neurons)
                or any(t.dtype != self.reset_absolute.dtype or t.device != x.device
                    or not bool(torch.isfinite(t).all()) for t in
                    (state.density, state.boundary, state.drift, state.cost, state.message))):
            raise ValueError("complete state configuration, clock, shape or precision mismatch")
        tolerance = 3e-5 if c.precision == "native32" else 2e-9
        if (bool((state.drift-c.base_drift).abs().gt(c.drift_scale+1e-6).any())
                or bool((state.cost-c.cost).abs().gt(c.cost_span+1e-6).any())
                or bool((state.density[..., 0, :].sum(-1)-1).abs().gt(tolerance).any())
                or bool((state.density[..., 0, :] < -tolerance).any())
                or bool((state.density[..., 1, :].abs() > state.density[..., 0, :]+tolerance).any())):
            raise ValueError("resumed population violates the physical domain")
        outputs, logits, errors, projections = [], [], [], []
        for inputs in x:
            message = state.message.to(inputs)
            mask = inputs.new_tensor((1., 1., 1.) if c.message_mode == "full" else
                                     (1., 0., 0.) if c.message_mode == "boundary" else (0., 1., 1.))
            rec = nn.functional.linear((message*mask[None, :, None]).flatten(1), self.recurrent.weight*self.synaptic_mask)
            drive = nn.functional.pad(self.input_drive(inputs), (0, half))+rec
            raw_mark = nn.functional.pad(self.input_mark(inputs), (0, half))+rec
            if state.step % c.slow_every == 0:
                drift = (c.base_drift+c.drift_scale*drive.tanh()).to(self.reset_absolute)
                cost = (c.cost+c.cost_span*(self.raw_cost+.15*drive).tanh()).to(drift)
                boundary = (self.qvi_boundary(drift, cost) if c.boundary_mode == "qvi" else
                    self.fixed_boundary.expand_as(drift) if c.boundary_mode == "fixed" else
                    self.fixed_boundary+c.boundary_span*(self.raw_boundary+.15*drive).tanh().to(drift))
            else:
                drift, cost, boundary = state.drift, state.cost, state.boundary
            density, jump, projected = self._remap(state, boundary)
            mark = raw_mark.tanh().to(density)
            content = ((1-c.write_fraction)*density[..., 1, :c.bins]
                       +c.write_fraction*mark[..., None]*density[..., 0, :c.bins])
            written = torch.stack((density[..., 0, :], torch.cat((content, density[..., 1, c.bins:]), -1)), -2)
            generator, event = self._generator(drift, boundary)
            density, hits, value, risk, margin = self._flow(written, jump, generator, event, boundary, cost)
            if bool(((risk < -tolerance) | (risk > 1+tolerance) | (risk > hits[..., 0]+tolerance)).any()):
                self.last_diagnostics = {"failed_step": state.step+1, "risk_min": float(risk.detach().min()),
                    "risk_max": float(risk.detach().max()), "risk_count_excess": float((risk-hits[..., 0]).detach().max())}
                raise FloatingPointError("first-event probability invariant failed")
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
            state = PopulationState(density, boundary, drift, cost, new_message, state.step+1, c)
            errors.append((density[..., 0, :].sum(-1)-1).abs().amax())
            projections.append(projected[..., 0].amax())
            outputs.append(features)
            logits.append(self.readout(features))
        mass_error = torch.stack(errors).max()
        self.last_diagnostics = {"mass_error": float(mass_error.detach()),
            "probability_min": float(density[..., 0, :].detach().min()),
            "mark_excess": float((density[..., 1, :].abs()-density[..., 0, :]).detach().max()),
            "all_finite": bool(torch.isfinite(density).all()), "state_step": state.step,
            "upper_projection_mass_max": float(torch.stack(projections).max().detach()),
            "independent_populations": c.neurons, "transport_dtype": str(density.dtype),
            "refractory_variance": c.refractory**2/c.stages, "state_elements": sum(t.numel() for t in
                (state.density, state.boundary, state.drift, state.cost, state.message))}
        if (not bool(torch.isfinite(density).all()) or bool(mass_error > tolerance)
                or bool((density[..., 0, :] < -tolerance).any())
                or bool((density[..., 1, :].abs() > density[..., 0, :]+tolerance).any())):
            raise FloatingPointError("complete probability/mark invariant failed; no normalization applied")
        result = torch.stack(logits)
        return (result, torch.stack(outputs), state) if return_features else result
