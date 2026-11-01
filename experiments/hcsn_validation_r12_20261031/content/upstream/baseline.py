"""Trainable sequence baselines with shared [batch, time, width] interfaces.

Mamba1CPU is a real-valued CPU reference of the official Mamba-1 mixer,
adapted from state-spaces/mamba at e0761ece1db07e0949dd88b4f4cd440420a19fd9.
Copyright (c) 2023, Tri Dao, Albert Gu. Licensed under Apache-2.0; see
BASELINES.md for the complete license and the changes made here.
"""

import math
from importlib.metadata import version

import torch
from torch import nn
from torch.nn import functional as F


MAMBA_COMMIT = "e0761ece1db07e0949dd88b4f4cd440420a19fd9"
BASELINE_NAMES = (
    "lif_snn",
    "continuous_rnn",
    "two_gates",
    "cfc",
    "mamba1",
    "transformer",
)


class _SurrogateSpike(torch.autograd.Function):
    """Hard forward spike; fast-sigmoid surrogate derivative, slope 5."""

    @staticmethod
    def forward(ctx, margin):
        ctx.save_for_backward(margin)
        return (margin >= 0).to(margin.dtype)

    @staticmethod
    def backward(ctx, grad):
        (margin,) = ctx.saved_tensors
        return grad / (1.0 + 5.0 * margin.abs()).square()


class LIFCell(nn.Module):
    """Current-based recurrent LIF, exponential leak, detached subtract reset."""

    def __init__(self, width):
        super().__init__()
        self.input = nn.Linear(width, width)
        self.recurrent = nn.Linear(width, width, bias=False)
        self.log_rate = nn.Parameter(torch.zeros(width))
        self.raw_threshold = nn.Parameter(torch.full((width,), -0.43275213))

    def step(self, x, state, dt):
        membrane, previous_spike = state
        decay = torch.exp(-F.softplus(self.log_rate) * dt)
        current = self.input(x) + self.recurrent(previous_spike)
        membrane = decay * membrane + (1.0 - decay) * current
        threshold = F.softplus(self.raw_threshold) + 1e-4
        spike = _SurrogateSpike.apply(membrane - threshold)
        membrane = membrane - spike.detach() * threshold
        return spike, (membrane, spike)


class ContinuousRNNCell(nn.Module):
    """Exponential-relaxation tanh RNN; frozen-target step, not exact nonlinear flow."""

    def __init__(self, width):
        super().__init__()
        self.candidate = nn.Linear(2 * width, width)
        self.log_rate = nn.Parameter(torch.zeros(width))

    def step(self, x, state, dt):
        target = torch.tanh(self.candidate(torch.cat((x, state), dim=-1)))
        update = -torch.expm1(-F.softplus(self.log_rate) * dt)
        state = state + update * (target - state)
        return state, state


class TwoGateCell(nn.Module):
    """Ordinary retention and input sigmoid gates; no financial/value operator."""

    def __init__(self, width):
        super().__init__()
        self.candidate = nn.Linear(2 * width, width)
        self.retention = nn.Linear(2 * width, width)
        self.input_gate = nn.Linear(2 * width, width)

    def step(self, x, state, dt):
        joint = torch.cat((x, state), dim=-1)
        # sigmoid(logit)**dt, evaluated without log(sigmoid(logit)) cancellation.
        keep = torch.exp(-dt * F.softplus(-self.retention(joint)))
        write = torch.sigmoid(self.input_gate(joint))
        target = torch.tanh(self.candidate(joint))
        state = keep * state + (1.0 - keep) * write * target
        return state, state


class RecurrentBlock(nn.Module):
    def __init__(self, cell, width, kind):
        super().__init__()
        self.cell, self.width, self.kind = cell, width, kind

    def forward(self, x, dt):
        state = x.new_zeros((x.shape[0], self.width))
        if self.kind == "lif_snn":
            state = (state, torch.zeros_like(state))
        outputs = []
        for t in range(x.shape[1]):
            elapsed = dt[:, t : t + 1]
            if self.kind == "cfc":
                output, state = self.cell(x[:, t], state, elapsed)
            else:
                output, state = self.cell.step(x[:, t], state, elapsed)
            outputs.append(output)
        return torch.stack(outputs, dim=1)


def selective_scan_cpu(u, delta, A, B, C, D, z, delta_bias):
    """Mamba-1 real variable-B/C scan: inputs B,T,D; B/C have B,T,N.

    Accumulates in float32, matching the pinned upstream selective_scan_ref.
    This serial torch reference does not claim CUDA selective-scan performance.
    """
    dtype = u.dtype
    u, delta, B, C = (v.float() for v in (u, delta, B, C))
    delta = F.softplus(delta + delta_bias.float())
    state = A.new_zeros((u.shape[0], A.shape[0], A.shape[1]))
    outputs = []
    for t in range(u.shape[1]):
        step = delta[:, t, :, None]
        transition = torch.exp(step * A[None])
        injection = step * B[:, t, None, :] * u[:, t, :, None]
        state = transition * state + injection
        outputs.append((state * C[:, t, None, :]).sum(dim=-1))
    output = torch.stack(outputs, dim=1) + u * D.float()
    return (output * F.silu(z)).to(dtype)


class Mamba1CPU(nn.Module):
    """Official Mamba-1 architecture with a serial PyTorch reference scan.

    Includes expansion, causal depthwise convolution, input-selective delta/B/C,
    A=-exp(A_log), D skip, SiLU output gate and output projection. External dt
    is deliberately not substituted for the learned selective delta.
    """

    def __init__(self, width, d_state=16, d_conv=4, expand=2):
        super().__init__()
        self.d_model, self.d_state, self.d_conv = width, d_state, d_conv
        self.d_inner, self.dt_rank = int(expand * width), math.ceil(width / 16)
        inner = self.d_inner
        self.in_proj = nn.Linear(width, 2 * inner, bias=False)
        self.conv1d = nn.Conv1d(inner, inner, d_conv, groups=inner, padding=d_conv - 1)
        self.x_proj = nn.Linear(inner, self.dt_rank + 2 * d_state, bias=False)
        self.dt_proj = nn.Linear(self.dt_rank, inner, bias=True)
        nn.init.uniform_(self.dt_proj.weight, -(self.dt_rank**-0.5), self.dt_rank**-0.5)
        initial_dt = torch.exp(torch.rand(inner) * math.log(100.0) + math.log(0.001))
        with torch.no_grad():
            self.dt_proj.bias.copy_(initial_dt + torch.log(-torch.expm1(-initial_dt)))
        self.dt_proj.bias._no_reinit = True
        self.A_log = nn.Parameter(
            torch.arange(1, d_state + 1).float().log().repeat(inner, 1)
        )
        self.D = nn.Parameter(torch.ones(inner))
        self.A_log._no_weight_decay = True
        self.D._no_weight_decay = True
        self.out_proj = nn.Linear(inner, width, bias=False)

    def forward(self, x):
        u, z = self.in_proj(x).chunk(2, dim=-1)
        u = F.silu(self.conv1d(u.transpose(1, 2))[..., : x.shape[1]]).transpose(1, 2)
        delta, B, C = self.x_proj(u).split(
            (self.dt_rank, self.d_state, self.d_state), dim=-1
        )
        delta = F.linear(delta, self.dt_proj.weight)
        y = selective_scan_cpu(
            u, delta, -self.A_log.float().exp(), B, C, self.D, z, self.dt_proj.bias
        )
        return self.out_proj(y)


class MambaResidualBlock(nn.Module):
    def __init__(self, width, d_state=16, expand=2):
        super().__init__()
        self.norm = nn.RMSNorm(width, eps=1e-5)
        self.mixer = Mamba1CPU(width, d_state=d_state, expand=expand)

    def forward(self, x, dt):
        return x + self.mixer(self.norm(x))


class SDPABlock(nn.Module):
    """Causal pre-norm Transformer with torch SDPA dispatch and a 4H FFN."""

    def __init__(self, width, heads=None):
        super().__init__()
        self.heads = heads or max(
            h for h in range(1, min(4, width) + 1) if width % h == 0
        )
        if width % self.heads:
            raise ValueError("width must be divisible by attention heads")
        self.norm1, self.norm2 = nn.LayerNorm(width), nn.LayerNorm(width)
        self.qkv = nn.Linear(width, 3 * width)
        self.proj = nn.Linear(width, width)
        self.ffn = nn.Sequential(
            nn.Linear(width, 4 * width), nn.GELU(), nn.Linear(4 * width, width)
        )

    def forward(self, x, dt):
        batch, length, width = x.shape
        qkv = self.qkv(self.norm1(x)).reshape(
            batch, length, 3, self.heads, width // self.heads
        )
        q, k, v = qkv.permute(2, 0, 3, 1, 4).unbind(0)
        y = F.scaled_dot_product_attention(q, k, v, dropout_p=0.0, is_causal=True)
        x = x + self.proj(y.transpose(1, 2).reshape(batch, length, width))
        return x + self.ffn(self.norm2(x))


def _time_encoding(dt, width):
    time = dt.cumsum(dim=1)
    frequencies = torch.exp(
        torch.arange(0, width, 2, device=dt.device, dtype=dt.dtype)
        * (-math.log(10000.0) / width)
    )
    phase = time[..., None] * frequencies
    return torch.stack((phase.sin(), phase.cos()), dim=-1).flatten(-2)[..., :width]


class SequenceBaseline(nn.Module):
    def __init__(
        self, name, width, depth=1, hidden_width=None, d_state=16, expand=2, heads=None
    ):
        super().__init__()
        if min(width, depth, hidden_width or width, d_state, expand) < 1:
            raise ValueError(
                "width, depth, hidden_width, d_state and expand must be positive"
            )
        hidden = hidden_width or width
        self.name, self.width, self.hidden_width = name, width, hidden
        self.input_proj = nn.Identity() if hidden == width else nn.Linear(width, hidden)
        self.output_proj = (
            nn.Identity() if hidden == width else nn.Linear(hidden, width)
        )
        blocks = []
        cells = {
            "lif_snn": LIFCell,
            "continuous_rnn": ContinuousRNNCell,
            "two_gates": TwoGateCell,
        }
        for _ in range(depth):
            if name in cells:
                blocks.append(RecurrentBlock(cells[name](hidden), hidden, name))
            elif name == "cfc":
                try:
                    from ncps.torch import CfCCell
                except ImportError as error:
                    raise ImportError(
                        "CfC baseline requires ncps==1.0.1; no silent substitute"
                    ) from error
                cell = CfCCell(
                    hidden,
                    hidden,
                    mode="default",
                    backbone_units=hidden,
                    backbone_layers=1,
                    backbone_dropout=0.0,
                )
                blocks.append(RecurrentBlock(cell, hidden, name))
            elif name == "mamba1":
                blocks.append(MambaResidualBlock(hidden, d_state, expand))
            elif name == "transformer":
                blocks.append(SDPABlock(hidden, heads))
            else:
                raise ValueError(
                    f"Unknown baseline {name!r}; choose from {BASELINE_NAMES}"
                )
        self.blocks = nn.ModuleList(blocks)

    def forward(self, x, dt, context=None):
        if x.ndim != 3 or x.shape[-1] != self.width or x.shape[1] == 0:
            raise ValueError("x must have nonempty shape [batch,time,width]")
        if dt.shape != x.shape[:2] or not torch.isfinite(dt).all() or (dt < 0).any():
            raise ValueError(
                "dt must be finite, nonnegative and have shape [batch,time]"
            )
        dt = dt.to(device=x.device, dtype=x.dtype)
        sequence = self.input_proj(x)
        if self.name == "transformer":
            sequence = sequence + _time_encoding(dt, self.hidden_width)
        event_count = x.new_zeros(())
        for block in self.blocks:
            sequence = block(sequence, dt)
            if self.name == "lif_snn":
                event_count = event_count + sequence.detach().sum()
        sequence = self.output_proj(sequence)
        aux = {
            "architecture": self.name,
            "context_used": False,
            "implementation": "cpu_reference" if self.name == "mamba1" else "torch",
            "event_count": event_count,
            "n_parameters": parameter_count(self),
        }
        return sequence, aux


def build_baseline(name, width, depth=1, **kwargs):
    """Build a real trainable model; hidden_width adds active input/output projections."""
    aliases = {
        "snn": "lif_snn",
        "lif": "lif_snn",
        "rnn": "continuous_rnn",
        "gates": "two_gates",
        "mamba": "mamba1",
        "sdpa": "transformer",
    }
    return SequenceBaseline(
        aliases.get(name.lower(), name.lower()), width, depth, **kwargs
    )


def parameter_count(module):
    return sum(p.numel() for p in module.parameters() if p.requires_grad)


def match_parameter_budget(
    name, width, target_parameters, depth=1, candidates=None, **kwargs
):
    """Pick the nearest real hidden width, preserving the caller's RNG state.

    Returns a configuration and the actual gap; an exact match is not promised.
    Every counted parameter participates in forward computation (no padding).
    """
    if target_parameters <= 0:
        raise ValueError("target_parameters must be positive")
    candidates = list(candidates if candidates is not None else range(1, 4 * width + 1))
    if not candidates:
        raise ValueError("at least one candidate hidden width is required")
    records = []
    with torch.random.fork_rng(devices=[]):
        for hidden in candidates:
            module = build_baseline(name, width, depth, hidden_width=hidden, **kwargs)
            count = parameter_count(module)
            records.append((abs(count - target_parameters), count, hidden))
    gap, count, hidden = min(records)
    return {
        "hidden_width": hidden,
        "n_parameters": count,
        "target_parameters": target_parameters,
        "relative_gap": gap / target_parameters,
    }


def profile_sdpa_operators(model, x, dt):
    """Report the operators actually selected by this runtime, never infer CUDA use."""
    activities = [torch.profiler.ProfilerActivity.CPU]
    if x.is_cuda:
        activities.append(torch.profiler.ProfilerActivity.CUDA)
    with torch.no_grad(), torch.profiler.profile(activities=activities) as trace:
        model(x, dt)
    return sorted(
        {
            event.key
            for event in trace.key_averages()
            if "scaled_dot_product" in event.key or "flash_attention" in event.key
        }
    )


def baseline_provenance():
    """Machine-readable runtime provenance for experiment reports."""
    return {
        "torch_version": torch.__version__,
        "cuda_available": torch.cuda.is_available(),
        "ncps_version": version("ncps"),
        "mamba_commit": MAMBA_COMMIT,
        "mamba_implementation": "real-valued serial PyTorch CPU reference; not fused CUDA",
        "source": "BASELINES.md",
        "baseline_names": list(BASELINE_NAMES),
    }
