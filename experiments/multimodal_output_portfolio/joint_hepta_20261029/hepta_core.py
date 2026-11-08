"""Source-bound Hepta continuous first-passage tensor backbone.

Adapted from hepta-private-ci commit 68eb16caa9c14c7b5729585c86d9c293018a987c:
  experiments/continuous_spiking_network/{cell.py,kernels.py}
  experiments/continuous_spiking_followup/stream_layers.py::_continuous_step

The scalar Brownian first-passage probability and killed first moment are exact
within a frozen interval. Hit mass resets to zero at the END of that interval;
recurrent propagation of this mean is an approximation. This profile has no
sampled spikes, continuous renewal, refractory timer, or endogenous value
boundary. Its high-dimensional semantic content is distinct from voltage.
"""

import math

import torch
from torch import Tensor, nn
from torch.nn import functional as F


SOURCE_COMMIT = "68eb16caa9c14c7b5729585c86d9c293018a987c"
SOURCE_BLOBS = {
    "cell.py": "23521afecbb4e69f40a7d930d2802a479ae7d426",
    "kernels.py": "f9222deb2443af064346ff67a16b1cd8bec05b8d",
    "stream_layers.py": "adbfb96f5c6b7ffae80e2f79067d1a6eee8dce65",
}
PROFILE = "hepta.output-portfolio.interval-end-mean.v1"
STATE_FIELDS = ("content", "voltage", "adaptation", "event")


def first_passage_terms(
    distance: Tensor, drift: Tensor, diffusion: Tensor, horizon: Tensor
) -> dict[str, Tensor]:
    """Upper-barrier Brownian hitting probability, survival, reflected mass.

    ``distance = barrier - initial_voltage`` and ``diffusion`` is the positive
    standard deviation per square root of time. A reached boundary has a unit
    atom at zero, including horizon zero. Only interior derivatives are used.
    """
    distance, drift, diffusion, horizon = torch.broadcast_tensors(
        distance, drift, diffusion, horizon
    )
    values = (distance, drift, diffusion, horizon)
    if any(x.dtype not in (torch.float32, torch.float64) for x in values):
        raise ValueError("first passage requires float32 or float64 tensors")
    if any(not bool(torch.isfinite(x).all()) for x in values):
        raise ValueError("first-passage inputs must be finite")
    if bool((diffusion <= 0).any()) or bool((horizon < 0).any()):
        raise ValueError("diffusion must be positive and horizon nonnegative")
    # Inactive rows use benign interior arguments. This avoids undefined
    # derivatives in an unselected torch.where branch at a boundary atom.
    d = torch.where(distance > 0, distance, torch.ones_like(distance))
    t = torch.where(horizon > 0, horizon, torch.ones_like(horizon))
    scale = diffusion * t.sqrt()
    z = (drift * t - d) / scale
    reflected_z = (-drift * t - d) / scale
    log_image_mills = (
        -math.log(2.0)
        - 0.5 * z.square()
        + torch.special.erfcx((-reflected_z / math.sqrt(2.0)).clamp_min(0)).log()
    )
    log_image_direct = (
        2 * drift * d / diffusion.square() + torch.special.log_ndtr(reflected_z)
    )
    log_image = torch.where(reflected_z <= 0, log_image_mills, log_image_direct)
    log_cdf = torch.logaddexp(torch.special.log_ndtr(z), log_image).clamp_max(0)
    active = (distance > 0) & (horizon > 0)
    cdf = torch.where(active, log_cdf.exp(), (distance <= 0).to(distance.dtype))
    survival = torch.where(
        active, -torch.expm1(log_cdf), (distance > 0).to(distance.dtype)
    )
    image = torch.where(active, log_image.exp(), torch.zeros_like(distance))
    return {"cdf": cdf, "survival": survival, "image_mass": image}


def reset_at_interval_end_mean(
    state: Tensor,
    boundary: Tensor,
    drift: Tensor,
    diffusion: Tensor,
    horizon: Tensor,
    reset: float = 0.0,
) -> tuple[Tensor, dict[str, Tensor]]:
    """Killed first moment plus hit mass at reset; no post-hit evolution."""
    if not math.isfinite(reset):
        raise ValueError("reset must be finite")
    distance = boundary - state
    terms = first_passage_terms(distance, drift, diffusion, horizon)
    mean = (
        (state + drift * horizon) * terms["survival"]
        - 2 * distance.clamp_min(0) * terms["image_mass"]
        + reset * terms["cdf"]
    )
    return mean, terms


class _HeptaLayer(nn.Module):
    def __init__(self, width: int, mode: str, boundary_mode: str):
        super().__init__()
        self.width, self.mode, self.boundary_mode = width, mode, boundary_mode
        raw = lambda value: math.log(math.expm1(value))
        self.drift_input = nn.Linear(width, width, bias=False)
        self.drift_bias = nn.Parameter(torch.full((width,), 0.35))
        self.raw_diffusion = nn.Parameter(torch.full((width,), raw(0.7)))
        self.channel_gates = nn.Linear(
            2 * width, width if mode == "single" else 2 * width
        )
        self.raw_recovery = nn.Parameter(torch.full((width,), raw(0.7)))
        for name, value, enabled in (
            ("raw_regeneration", 0.7, mode != "single"),
            ("raw_adaptation", 0.2, mode != "no_adaptation"),
            ("raw_adaptation_decay", 0.3, mode != "no_adaptation"),
        ):
            initial = torch.full((width,), raw(value))
            if enabled:
                self.register_parameter(name, nn.Parameter(initial))
            else:
                self.register_buffer(name, initial)
        self.raw_content_rate = nn.Parameter(torch.full((width,), raw(0.2)))
        self.content_input = nn.Linear(width, width)
        self.content_state = nn.Linear(width, width, bias=False)
        self.output = nn.Linear(width, width, bias=False)
        self.norm = nn.LayerNorm(width)
        if boundary_mode == "direct":
            self.raw_boundary = nn.Parameter(torch.full((width,), raw(1.0)))
        else:
            self.register_buffer("fixed_boundary", torch.ones(width))

    def step(self, x, duration, state):
        content, voltage = state["content"], state["voltage"]
        adaptation, previous_event = state["adaptation"], state["event"]
        diffusion = F.softplus(self.raw_diffusion) + 1e-4
        boundary = (
            F.softplus(self.raw_boundary) + 1e-4
            if self.boundary_mode == "direct"
            else self.fixed_boundary
        )
        signal = self.norm(x)
        gates = self.channel_gates(torch.cat((signal, content), dim=-1)).sigmoid()
        if self.mode == "single":
            recovery_gate, regeneration_gate = gates, torch.zeros_like(gates)
        else:
            recovery_gate, regeneration_gate = gates.chunk(2, dim=-1)
        recovery = F.softplus(self.raw_recovery) * recovery_gate
        regeneration = F.softplus(self.raw_regeneration) * regeneration_gate
        drift = (
            self.drift_bias
            + self.drift_input(signal).tanh()
            - recovery * voltage
            + regeneration * previous_event
            - adaptation
        )
        pre_reset_mean = voltage + duration * drift
        if self.mode == "ordinary":
            event = torch.sigmoid(
                (duration * drift - (boundary - voltage))
                / (diffusion * duration.clamp_min(1e-8).sqrt())
            )
            next_voltage = (1 - event) * pre_reset_mean
        else:
            next_voltage, terms = reset_at_interval_end_mean(
                voltage, boundary, drift, diffusion, duration
            )
            event = terms["cdf"]
        active = duration > 0
        event = torch.where(active, event, torch.zeros_like(event))
        next_adaptation = adaptation
        if self.mode != "no_adaptation":
            next_adaptation = (
                adaptation * torch.exp(-F.softplus(self.raw_adaptation_decay) * duration)
                + F.softplus(self.raw_adaptation) * event
            )
        candidate = torch.tanh(
            self.content_input(signal) + self.content_state(content)
        )
        write = 1 - (1 - event) * torch.exp(
            -F.softplus(self.raw_content_rate) * duration
        )
        next_content = (1 - write) * content + write * candidate
        # Duration zero is an execution mask. It does not consume a boundary
        # atom or reset the previous event. Runtime clocks remain caller-owned.
        next_state = {
            "content": torch.where(active, next_content, content),
            "voltage": torch.where(active, next_voltage, voltage),
            "adaptation": torch.where(active, next_adaptation, adaptation),
            "event": torch.where(active, event, previous_event),
        }
        aux = {
            **next_state,
            "event_probability": event,
            "recovery": recovery,
            "regeneration": regeneration,
            "drift": drift,
            "pre_reset_mean": pre_reset_mean,
            "diffusion": diffusion,
            "boundary": boundary,
            "margin": boundary - next_state["voltage"],
        }
        return x + self.output(next_state["content"]), next_state, aux


class HeptaCore(nn.Module):
    """Stateful high-dimensional HCSN block; training and inference share step.

    ``dual`` uses the source first-passage recurrence. ``ordinary`` is the
    source's parameter-matched sigmoid-gate ablation, not a Hepta efficacy
    result. Natural boundaries support only fixed/direct parameterizations;
    task-value continuation and STOP belong to the portfolio policy.
    """

    def __init__(
        self, width: int, depth: int = 1, mode: str = "dual", boundary_mode: str = "direct"
    ):
        super().__init__()
        if type(width) is not int or type(depth) is not int or min(width, depth) < 1:
            raise ValueError("width and depth must be positive integers")
        if mode not in {"dual", "single", "no_adaptation", "ordinary"}:
            raise ValueError("unknown Hepta core mode")
        if boundary_mode not in {"fixed", "direct"}:
            raise ValueError("natural boundary supports fixed/direct, not task-value")
        self.width, self.depth = width, depth
        self.mode, self.boundary_mode = mode, boundary_mode
        self.layers = nn.ModuleList(
            [_HeptaLayer(width, mode, boundary_mode) for _ in range(depth)]
        )

    def initial_state(self, batch_size, *, device=None, dtype=None, content=None):
        """Zero state, optionally conditioning the first layer with tanh(content).

        Supplied encoder content retains its autograd graph. Callers checkpoint
        these four tensors per layer in addition to the model state_dict.
        """
        if type(batch_size) is not int or batch_size < 1:
            raise ValueError("batch_size must be a positive integer")
        anchor = next(self.parameters())
        device = anchor.device if device is None else device
        dtype = anchor.dtype if dtype is None else dtype
        if dtype not in (torch.float32, torch.float64):
            raise ValueError("core state requires float32 or float64")
        states = [
            {
                name: torch.zeros(batch_size, self.width, device=device, dtype=dtype)
                for name in STATE_FIELDS
            }
            for _ in self.layers
        ]
        if content is not None:
            if content.shape != (batch_size, self.width) or not bool(torch.isfinite(content).all()):
                raise ValueError("initial content must be finite [batch,width]")
            states[0]["content"] = content.to(device=device, dtype=dtype).tanh()
        return states

    def step(self, x: Tensor, state, dt=1.0):
        """Advance [batch,width] inputs; return output, persistent state, diagnostics."""
        if x.ndim != 2 or x.shape[1] != self.width or x.shape[0] < 1:
            raise ValueError("x must have shape [nonempty_batch,width]")
        if x.dtype not in (torch.float32, torch.float64) or not bool(torch.isfinite(x).all()):
            raise ValueError("x must be finite float32 or float64")
        anchor = next(self.parameters())
        if x.dtype != anchor.dtype or x.device != anchor.device:
            raise ValueError("input dtype/device differs from model")
        duration = torch.as_tensor(dt, dtype=x.dtype, device=x.device)
        if duration.ndim == 0:
            duration = duration.expand(x.shape[0], 1)
        elif duration.shape == (x.shape[0],):
            duration = duration[:, None]
        if duration.shape != (x.shape[0], 1):
            raise ValueError("dt must be scalar, [batch], or [batch,1]")
        if not bool(torch.isfinite(duration).all()) or bool((duration < 0).any()):
            raise ValueError("dt must be finite and nonnegative")
        if len(state) != self.depth:
            raise ValueError("state depth differs from model")
        for layer_state in state:
            if set(layer_state) != set(STATE_FIELDS):
                raise ValueError("state fields differ from profile")
            for value in layer_state.values():
                if value.shape != x.shape or value.device != x.device or value.dtype != x.dtype:
                    raise ValueError("state shape/dtype/device differs from input")
                if not bool(torch.isfinite(value).all()):
                    raise ValueError("state must be finite")
        next_states, events = [], []
        for layer, layer_state in zip(self.layers, state, strict=True):
            x, next_state, aux = layer.step(x, duration, layer_state)
            next_states.append(next_state)
            events.append(aux["event_probability"])
        aux["all_event_probability"] = torch.stack(events, dim=1)
        return x, next_states, aux

    def forward(self, x: Tensor, dt, state=None):
        """Consume [batch,time,width] without discarding an optional prior state."""
        if x.ndim != 3 or x.shape[1] < 1 or x.shape[2] != self.width:
            raise ValueError("x must have shape [batch,nonempty_time,width]")
        duration = torch.as_tensor(dt, dtype=x.dtype, device=x.device)
        if duration.ndim == 0:
            duration = duration.expand(x.shape[:2])
        elif duration.shape == (*x.shape[:2], 1):
            duration = duration.squeeze(-1)
        if duration.shape != x.shape[:2]:
            raise ValueError("sequence dt must be scalar or [batch,time]")
        if state is None:
            state = self.initial_state(x.shape[0], device=x.device, dtype=x.dtype)
        outputs, records = [], {}
        for index in range(x.shape[1]):
            output, state, aux = self.step(x[:, index], state, duration[:, index])
            outputs.append(output)
            for name, value in aux.items():
                if name not in {"diffusion", "boundary"}:
                    records.setdefault(name, []).append(value)
        recorded = {name: torch.stack(values, dim=1) for name, values in records.items()}
        recorded.update({name: aux[name] for name in ("diffusion", "boundary")})
        return torch.stack(outputs, dim=1), state, recorded
