"""Batched adaptive population flow on the existing conservative spatial generator.

Coordinates are x=log(V)-boundary. A boundary changes only at a step edge:
piecewise-uniform active density is conservatively remapped, new lower exits
enter phase zero. Upper exits are absorbed by default; the reflecting variant
lumps projected upper mass into the last cell and reports that projection.
This finite-cell lumping is not an exact moving reflected diffusion. During the step
the boundary/drift are held fixed. Phase completion resets relative to the
CURRENT boundary, including cohorts created before a boundary change.

The spatial upwind discretization, boundary projection, and Erlang waiting law
(mean h, variance h*h/stages) are explicit approximations. Matrix exponentials
solve only the declared frozen finite process. The output is deterministic
population flow, not the expected nonlinear loss of a sampled SNN. Streaming
state size is fixed; an unrolled autograd tape and saved outputs are separate.
Default transport_precision='float64' keeps probability/content state, geometry,
matrix actions and solves in FP64 even with FP32 trainable layers and outputs.
This is mixed precision, NOT native-FP32 execution. Native mode is an explicit
comparison and retains the same strict state checks. Writes occur once per
observation; subdividing time with additional writes changes the content law.
"""

from dataclasses import asdict, dataclass
import math

import torch

from qualification.hcsn_training.population_generator import finite_volume_generator


@dataclass(frozen=True)
class FlowConfig:
    input_size: int
    content_size: int = 4
    bins: int = 6
    stages: int = 3
    extent: float = 2.0
    dt: float = 0.1
    sigma: float = 0.35
    base_drift: float = -0.15
    drift_scale: float = 0.8
    reset_margin: float = 0.8
    refractory: float = 0.2
    discount: float = 0.25
    gain: float = 0.5
    maintenance: float = 0.2
    spike_cost: float = 0.05
    write_fraction: float = 0.35
    boundary_limit: float = 4.0
    drift_limit: float = 4.0
    max_batch: int = 256
    upper_mode: str = "absorbing"
    transport_precision: str = "float64"

    def __post_init__(self):
        for name, low, high in (("input_size", 1, 256), ("content_size", 1, 64),
                                ("bins", 2, 64), ("stages", 1, 128), ("max_batch", 1, 256)):
            value = getattr(self, name)
            if type(value) is not int or not low <= value <= high:
                raise ValueError(f"{name} must lie in {low}..{high}")
        if self.upper_mode not in ("absorbing", "reflecting"):
            raise ValueError("upper_mode must be absorbing or reflecting")
        if self.transport_precision not in ("native", "float64"):
            raise ValueError("transport_precision must be native or float64")
        numeric = [value for name, value in asdict(self).items()
                   if name not in ("upper_mode", "transport_precision") and type(value) is not int]
        if any(type(v) is not float or not math.isfinite(v) for v in numeric):
            raise ValueError("finite numeric configuration required")
        if (min(self.extent, self.dt, self.sigma, self.refractory, self.discount,
                self.boundary_limit, self.drift_limit) <= 0 or self.drift_scale < 0
                or abs(self.base_drift)+self.drift_scale > self.drift_limit
                or not 0 <= self.write_fraction <= 1
                or not self.extent/(2*self.bins) < self.reset_margin < self.extent*(1-1/(2*self.bins))):
            raise ValueError("invalid rates, write fraction, or interior reset margin")


@dataclass(frozen=True)
class FlowState:
    """All future-relevant state; density axes are batch, probability/content, state.

    Spatial bins precede refractory stages and one upper account (zero in reflecting
    mode). Both modes accept existing phase mass; mode changes cannot reuse a state,
    and reflecting mode rejects nonzero escape mass instead of reviving it. Signed
content is a bounded mark carried by probability, so abs(content)<=probability.
The clock is integer microseconds; snapshots deliberately omit the old AD tape.
"""

    density: torch.Tensor
    boundary: torch.Tensor
    time_micros: int
    config: FlowConfig

    def detach(self):
        return FlowState(self.density.detach(), self.boundary.detach(), self.time_micros, self.config)

    def tensor_bytes(self):
        return sum(t.numel()*t.element_size() for t in (self.density, self.boundary))

    def to_record(self):
        return {"schema": "hcsn-adaptive-phase-state-v2", "past_autograd_retained": False,
                "density": self.density.detach().clone(), "boundary": self.boundary.detach().clone(),
                "time_micros": self.time_micros, "config": asdict(self.config)}

    @classmethod
    def from_record(cls, record):
        """Decode trusted tensors; model.validate_state/step checks their semantics."""
        if (set(record) != {"schema", "past_autograd_retained", "density", "boundary", "time_micros", "config"}
                or record["schema"] != "hcsn-adaptive-phase-state-v2"
                or record["past_autograd_retained"] is not False):
            raise ValueError("unsupported adaptive state record")
        if not all(isinstance(record[k], torch.Tensor) for k in ("density", "boundary")):
            raise ValueError("state record must contain tensors")
        return cls(record["density"].detach().clone(), record["boundary"].detach().clone(),
                   record["time_micros"], FlowConfig(**record["config"]))


class BatchedFlow(torch.nn.Module):
    """Independent probability dynamics per sample with learnable drive and marks.

Features: event=count during the interval INCLUDING edge-jump hits; content=
signed marks carried by those events; risk=probability that mass active at the
start has its FIRST hit, including edge-jump hits (initial refractory mass is
excluded); margin=unconditional active mean margin/extent at the end;
occupation=interval-average active probability; call=frozen finite-policy
continuation value at the end, from the SAME generator, running rewards and
spike costs. Call is allowed to be negative: it is neither HX equity nor an
optimal stopping advantage. Full-equity ablations may replace its last column
with an existing equity operator evaluated on the returned state's nodes.
"""

    def __init__(self, config):
        super().__init__()
        if not isinstance(config, FlowConfig):
            raise TypeError("FlowConfig required")
        self.config = config
        self.drive = torch.nn.Linear(config.input_size, 1, dtype=torch.float64)
        self.writer = torch.nn.Linear(config.input_size, config.content_size, dtype=torch.float64)
        edges = torch.linspace(0.0, config.extent, config.bins+1, dtype=torch.float64)
        centers = (edges[1:]+edges[:-1])/2
        reset = torch.relu(1-(centers-config.reset_margin).abs()/(config.extent/config.bins))
        self.register_buffer("edges", edges)
        self.register_buffer("centers", centers)
        self.register_buffer("reset", reset/reset.sum())
        self.feature_names = ("event", *[f"content_{i}" for i in range(config.content_size)],
                              "risk", "margin", "occupation", "call")

    def _apply(self, fn, recurse=True):
        super()._apply(fn, recurse=recurse)
        # Rebuild physical constants from the declared grid, not rounded buffers.
        dtype = torch.float64 if self.config.transport_precision == "float64" else self.drive.weight.dtype
        self.edges = torch.linspace(0.0, self.config.extent, self.config.bins+1,
                                    dtype=dtype, device=self.drive.weight.device)
        self.centers = (self.edges[1:]+self.edges[:-1])/2
        reset = torch.relu(1-(self.centers-self.config.reset_margin).abs()/(self.config.extent/self.config.bins))
        self.reset = reset/reset.sum()
        return self

    def initial_state(self, batch, *, like=None, boundary=None):
        c = self.config
        like = self.drive.weight if like is None else like
        if type(batch) is not int or not 1 <= batch <= c.max_batch:
            raise ValueError("batch exceeds configured capacity")
        if like.dtype not in (torch.float32, torch.float64):
            raise ValueError("FP32 or FP64 required")
        work = like.to(dtype=self.edges.dtype)
        probability = torch.cat((self.reset.to(work), work.new_zeros(c.stages+1)))
        density = torch.cat((probability.expand(batch, 1, -1),
                             work.new_zeros(batch, c.content_size, len(probability))), 1)
        boundary = work.new_zeros(batch) if boundary is None else self._batch_value(boundary, work, batch)
        state = FlowState(density, boundary, 0, c)
        self.validate_state(state, batch, like.dtype, like.device)
        return state

    @staticmethod
    def _batch_value(value, like, batch):
        value = value.to(like) if isinstance(value, torch.Tensor) else like.new_tensor(value)
        if value.ndim == 0:
            value = value.expand(batch)
        if value.shape != (batch,) or not bool(torch.isfinite(value).all()):
            raise ValueError("finite scalar or [batch] control required")
        return value

    def validate_state(self, state, batch, dtype, device):
        c, n = self.config, self.config.bins+self.config.stages+1
        dtype = torch.float64 if c.transport_precision == "float64" else dtype
        if (not isinstance(state, FlowState) or state.config != c
                or type(state.time_micros) is not int or not 0 <= state.time_micros < 2**63
                or state.density.shape != (batch, 1+c.content_size, n) or state.boundary.shape != (batch,)
                or any(t.dtype != dtype or t.device != device or not bool(torch.isfinite(t).all())
                       for t in (state.density, state.boundary))):
            raise ValueError("incompatible complete adaptive state")
        p = state.density[:, :1]
        tolerance = 3e-5 if dtype == torch.float32 else 1e-10
        if (bool((p < -tolerance).any()) or bool((state.density[:, 1:].abs() > p+tolerance).any())
                or not bool(torch.allclose(p.sum(-1), torch.ones_like(p.sum(-1)), rtol=0, atol=tolerance))
                or bool((state.boundary.abs() > c.boundary_limit).any())):
            raise ValueError("probability, signed-content, or boundary invariant failed")
        if c.upper_mode == "reflecting" and bool((state.density[..., -1].abs() > tolerance).any()):
            raise ValueError("reflecting state must not contain an escaped population")

    def _remap(self, state, boundary):
        """Conservative cell-average projection, differentiable away from grid knots."""
        n = self.config.bins
        shift = boundary-state.boundary
        old_lo, old_hi = self.edges[:-1], self.edges[1:]
        widths = old_hi-old_lo
        new_lo, new_hi = shift[:, None]+old_lo, shift[:, None]+old_hi
        overlap = (torch.minimum(old_hi[None, :, None], new_hi[:, None, :])
                   - torch.maximum(old_lo[None, :, None], new_lo[:, None, :])).clamp_min(0)/widths[None, :, None]
        lower = ((shift[:, None]-old_lo)/widths).clamp(0, 1)
        upper = ((old_hi-shift[:, None]-self.config.extent)/widths).clamp(0, 1)
        active = state.density[..., :n]
        hit, escaped = (active*lower[:, None]).sum(-1), (active*upper[:, None]).sum(-1)
        retained = active @ overlap
        upper_account = state.density[..., -1]+escaped
        if self.config.upper_mode == "reflecting":
            last = torch.zeros_like(retained)
            last[..., -1] = 1
            retained = retained+escaped[..., None]*last
            upper_account = state.density[..., -1]
        phase = state.density[..., n:-1]
        first = torch.zeros_like(phase)
        first[..., 0] = 1
        density = torch.cat((retained, phase+hit[..., None]*first, upper_account[..., None]), -1)
        return density, retained[:, 0], hit, escaped

    def _generator(self, drift):
        c, b = self.config, len(drift)
        spatial = finite_volume_generator(self.edges, drift[:, None].expand(b, c.bins+1), c.sigma)
        q, lower, upper = spatial[:, :c.bins, :c.bins], spatial[:, :c.bins, c.bins], spatial[:, :c.bins, -1]
        if c.upper_mode == "reflecting":
            q, upper = q+torch.diag_embed(upper), torch.zeros_like(upper)
            spatial = torch.cat((torch.cat((q, lower[..., None], upper[..., None]), -1),
                                 drift.new_zeros(b, 2, c.bins+2)), -2)
        eye = torch.eye(c.stages, dtype=drift.dtype, device=drift.device)
        rate = c.stages/c.refractory
        phase = -rate*eye
        if c.stages > 1:
            phase = phase+torch.diag(drift.new_full((c.stages-1,), rate), diagonal=1)
        top = torch.cat((q, lower[..., None]*eye[0], upper[..., None]), -1)
        bottom = torch.cat((rate*eye[:, -1:]*self.reset[None], phase, drift.new_zeros(c.stages, 1)), -1)
        generator = torch.cat((top, bottom.expand(b, -1, -1), drift.new_zeros(b, 1, c.bins+c.stages+1)), -2)
        event = torch.cat((lower, drift.new_zeros(b, c.stages+1)), -1)
        return generator, event, spatial

    def step(self, inputs, state=None, *, dt=None, drift_override=None, boundary_override=None, feature_mask=None):
        c = self.config
        if (inputs.ndim != 2 or inputs.shape[1] != c.input_size or not 1 <= len(inputs) <= c.max_batch
                or inputs.dtype not in (torch.float32, torch.float64) or not bool(torch.isfinite(inputs).all())
                or inputs.dtype != self.drive.weight.dtype or inputs.device != self.drive.weight.device):
            raise ValueError("finite matching FP32/FP64 [batch,input_size] required")
        duration = c.dt if dt is None else dt
        if type(duration) not in (int, float) or not math.isfinite(duration) or duration <= 0:
            raise ValueError("positive finite scalar dt required")
        micros = round(duration*1_000_000)
        if not 1 <= micros <= 10**9 or not math.isclose(duration*1_000_000, micros, rel_tol=0, abs_tol=1e-6):
            raise ValueError("dt must be an integer number of microseconds")
        state = self.initial_state(len(inputs), like=inputs) if state is None else state
        self.validate_state(state, len(inputs), inputs.dtype, inputs.device)
        if state.time_micros+micros >= 2**63:
            raise ValueError("adaptive clock capacity exceeded")
        work = inputs.to(dtype=self.edges.dtype)
        boundary = state.boundary if boundary_override is None else self._batch_value(boundary_override, work, len(inputs))
        drift = (c.base_drift+c.drift_scale*self.drive(inputs).squeeze(-1).tanh()
                 if drift_override is None else self._batch_value(drift_override, work, len(inputs))).to(work)
        if bool((boundary.abs() > c.boundary_limit).any()) or bool((drift.abs() > c.drift_limit).any()):
            raise ValueError("control exceeds the configured physical domain")
        density, alive_for_risk, jump, projected = self._remap(state, boundary)
        mark = self.writer(inputs).tanh().to(work)
        active_content = ((1-c.write_fraction)*density[:, 1:, :c.bins]
                          + c.write_fraction*mark[..., None]*density[:, :1, :c.bins])
        written = torch.cat((density[:, :1], torch.cat((active_content, density[:, 1:, c.bins:]), -1)), 1)
        content_write = (written[:, 1:]-density[:, 1:]).sum(-1)
        generator, event, spatial = self._generator(drift)
        batch, size = event.shape
        active_indicator = torch.cat((work.new_ones(c.bins), work.new_zeros(c.stages+1)))
        weights = torch.stack((event, active_indicator.expand_as(event)), -1)
        augmented = torch.cat((torch.cat((generator, weights), -1), work.new_zeros(batch, 2, size+2)), -2)
        action = torch.matrix_exp(augmented*duration)
        transitioned = written @ action[:, :size, :size]
        increments = written @ action[:, :size, size:]
        hits = jump+increments[..., 0]
        first_hit = torch.matrix_exp(spatial*duration)[:, :c.bins, c.bins]
        risk = jump[:, 0]+(alive_for_risk*first_hit).sum(-1)
        reward = torch.cat((c.gain*(boundary[:, None]+self.centers)-c.maintenance,
                            work.new_zeros(batch, c.stages+1)), -1)-c.spike_cost*event
        value = torch.linalg.solve(c.discount*torch.eye(size, dtype=work.dtype, device=inputs.device)-generator,
                                   reward[..., None]).squeeze(-1)
        p = transitioned[:, 0]
        margin = (p[:, :c.bins]*self.centers).sum(-1)/c.extent
        call = (p*value).sum(-1)
        features = torch.cat((hits, torch.stack((risk, margin, increments[:, 0, 1]/duration, call), -1)), -1).to(inputs)
        if feature_mask is not None:
            mask = torch.as_tensor(feature_mask, dtype=inputs.dtype, device=inputs.device)
            if mask.shape != (len(self.feature_names),) or not bool(((mask == 0) | (mask == 1)).all()):
                raise ValueError("feature mask must contain one zero/one per channel")
            features = features*mask
        updated = FlowState(transitioned, boundary, state.time_micros+micros, c)
        self.validate_state(updated, batch, inputs.dtype, inputs.device)
        if not bool(torch.isfinite(features).all()):
            raise FloatingPointError("nonfinite adaptive features")
        diagnostics = {"drift": drift, "boundary_jump_hits": jump[:, 0], "active_mass": p[:, :c.bins].sum(-1),
                       "upper_projection_mass": projected[:, 0], "upper_projection_content": projected[:, 1:],
                       "upper_projection_destination": "last_cell" if c.upper_mode == "reflecting" else "escape",
                       "mass_error": p.sum(-1)-1, "content_balance_error": transitioned[:, 1:].sum(-1)
                       -state.density[:, 1:].sum(-1)-content_write,
                       "generator_row_error": generator.sum(-1).abs().amax(-1),
                       "transport_dtype": str(work.dtype), "output_dtype": str(inputs.dtype),
                       "refractory_variance": c.refractory**2/c.stages,
                       "call_kind": "frozen_finite_policy_continuation"}
        return features, updated, diagnostics

    def forward(self, sequence, state=None):
        if sequence.ndim != 3 or not len(sequence):
            raise ValueError("nonempty [time,batch,input_size] sequence required")
        outputs = []
        for inputs in sequence:
            features, state, _ = self.step(inputs, state)
            outputs.append(features)
        return torch.stack(outputs), state
