"""Sequence baselines and named, explicit optional official implementations."""

import math

import torch
from torch import nn
from torch.nn import functional as F

from .cells import ValueKernelCell


class UnavailableBaseline(RuntimeError):
    """The requested baseline has no usable implementation in this environment."""


class GRUEncoder(nn.Module):
    def __init__(self, input_size, hidden_size):
        super().__init__()
        self.gru = nn.GRU(input_size, hidden_size, batch_first=True)

    def forward(self, x, dt=0.1):
        return self.gru(x)[0]


class AttentionBlock(nn.Module):
    """Causal scaled_dot_product_attention; PyTorch selects the available kernel."""
    def __init__(self, hidden_size, heads=2):
        super().__init__()
        if hidden_size % heads:
            raise ValueError("attention width must be divisible by heads")
        self.heads = heads
        self.norm1 = nn.LayerNorm(hidden_size)
        self.norm2 = nn.LayerNorm(hidden_size)
        self.qkv = nn.Linear(hidden_size, 3*hidden_size)
        self.output = nn.Linear(hidden_size, hidden_size)
        self.ff = nn.Sequential(nn.Linear(hidden_size, 2*hidden_size), nn.GELU(),
                                nn.Linear(2*hidden_size, hidden_size))

    def forward(self, x):
        batch, time, width = x.shape
        qkv = self.qkv(self.norm1(x)).reshape(batch, time, 3, self.heads, width//self.heads)
        q, k, v = qkv.unbind(2)
        attended = F.scaled_dot_product_attention(q.transpose(1, 2), k.transpose(1, 2),
                                                  v.transpose(1, 2), is_causal=True)
        x = x + self.output(attended.transpose(1, 2).reshape(batch, time, width))
        return x + self.ff(self.norm2(x))


class TransformerEncoder(nn.Module):
    def __init__(self, input_size, hidden_size, *, preceding=None):
        super().__init__()
        self.preceding = preceding
        self.input = nn.Linear(input_size, hidden_size) if preceding is None else nn.Identity()
        self.blocks = nn.ModuleList([AttentionBlock(hidden_size) for _ in range(2)])

    def forward(self, x, dt=0.1):
        x = self.input(x) if self.preceding is None else self.preceding(x, dt)
        positions = torch.arange(x.shape[1], device=x.device, dtype=x.dtype)[:, None]
        frequencies = torch.exp(torch.arange(0, x.shape[-1], 2, device=x.device, dtype=x.dtype)
                                *(-math.log(10000.0)/x.shape[-1]))
        pos = torch.stack((torch.sin(positions*frequencies),
                           torch.cos(positions*frequencies)), dim=-1).flatten(-2)
        x = x + pos[None, :, :]
        for block in self.blocks:
            x = block(x)
        return x


class LIFEncoder(nn.Module):
    """Exact leaky integration between discrete threshold checks, hard forward reset.

    Gradients use a logistic surrogate. Events are detected at step boundaries;
    this baseline is not an exact continuous event-time solver.
    """
    def __init__(self, input_size, hidden_size, *, adaptive=False):
        super().__init__()
        self.hidden_size, self.adaptive = hidden_size, adaptive
        self.input = nn.Linear(input_size, hidden_size)
        self.recurrent = nn.Linear(hidden_size, hidden_size, bias=False)
        self.raw_tau = nn.Parameter(torch.zeros(hidden_size))

    def forward(self, x, dt=0.1):
        if dt <= 0:
            raise ValueError("spiking baselines require dt>0")
        voltage = x.new_zeros(x.shape[0], self.hidden_size)
        trace, adaptation = torch.zeros_like(voltage), torch.zeros_like(voltage)
        refractory = torch.zeros_like(voltage, dtype=torch.long)
        output, delay = [], max(1, math.ceil(0.2/dt))
        decay = torch.exp(-dt/(0.05+0.45*torch.sigmoid(self.raw_tau)))
        for inputs in x.unbind(1):
            active = refractory == 0
            drive = 2*torch.sigmoid(self.input(inputs) + self.recurrent(trace))
            voltage = torch.where(active, decay*voltage+(1-decay)*drive, torch.zeros_like(voltage))
            threshold = 1 + (0.5*adaptation if self.adaptive else 0)
            surrogate = torch.sigmoid(10*(voltage-threshold))
            hard = ((voltage >= threshold) & active).to(x.dtype)
            spike = surrogate + (hard-surrogate).detach()
            spike = spike*active.to(x.dtype)
            voltage = voltage*(1-spike)
            refractory = torch.where(hard.bool(), torch.full_like(refractory, delay),
                                     (refractory-1).clamp_min(0))
            trace = math.exp(-dt/0.5)*trace + (1-math.exp(-dt/0.5))*spike/dt
            adaptation = math.exp(-dt/1.5)*adaptation + spike
            output.append(trace)
        return torch.stack(output, dim=1)


class PIFEncoder(nn.Module):
    """Finite-volume perfect-integrate-and-fire population, reset at the lower end.

    Upwind drift/diffusion rates define a conservative Markov discretization.
    Substeps obey its positivity bound. There is no leak or refractory period.
    It is a population baseline, not the exact HX killed-transition model.
    """
    def __init__(self, input_size, hidden_size, bins=16):
        super().__init__()
        self.hidden_size, self.bins = hidden_size, bins
        self.input = nn.Linear(input_size, hidden_size)
        self.recurrent = nn.Linear(hidden_size, hidden_size, bias=False)

    def forward(self, x, dt=0.1):
        if dt <= 0:
            raise ValueError("population baselines require dt>0")
        mass = x.new_zeros(x.shape[0], self.hidden_size, self.bins)
        mass[..., 0] = 1
        trace = x.new_zeros(x.shape[0], self.hidden_size)
        dx, diffusion = 1/self.bins, 0.02
        substeps = max(1, math.ceil(dt*(1.5/dx+2*diffusion/dx**2)))
        subdt, output = dt/substeps, []
        for inputs in x.unbind(1):
            drift = 1.5*torch.sigmoid(self.input(inputs)+self.recurrent(trace))
            right = subdt*(drift[..., None]/dx+diffusion/dx**2)
            left = subdt*diffusion/dx**2
            event_mass = torch.zeros_like(trace)
            for _ in range(substeps):
                outward = mass*right
                inward = mass*left
                # Lower boundary is reflecting except for reset reinjection;
                # upper outgoing probability is the threshold firing mass.
                lost = outward[..., -1]
                remaining = mass-outward-inward
                to_right = F.pad(outward[..., :-1], (1, 0))
                to_left = F.pad(inward[..., 1:], (0, 1))
                lower = F.pad((lost+inward[..., 0]).unsqueeze(-1), (0, self.bins-1))
                mass = remaining+to_right+to_left+lower
                event_mass = event_mass+lost
            trace = math.exp(-dt/0.5)*trace + (1-math.exp(-dt/0.5))*event_mass/dt
            output.append(trace)
        return torch.stack(output, dim=1)


class PopulationFluxEncoder(nn.Module):
    """Version B: actual killed-population absorption, renewal reset and recovery.

    The readout filters the measured absorbed mass/dt. It does not replace
    population state with a marginal risk feature. The numerical grid and
    step size are recorded in every experiment using this encoder.
    """
    def __init__(self, input_size, hidden_size, *, dt=0.1, recovery=True):
        super().__init__()
        from .population import PopulationConfig
        from .population_torch import TorchPopulation
        self.hidden_size = hidden_size
        self.input = nn.Linear(input_size, hidden_size)
        self.recurrent = nn.Linear(hidden_size, hidden_size, bias=False)
        self.population = TorchPopulation(PopulationConfig(
            bins=32, dt=dt, recovery_strength=0.2 if recovery else 0.0))

    def forward(self, x, dt=0.1):
        if not math.isclose(dt, self.population.config.dt, rel_tol=0, abs_tol=1e-12):
            raise ValueError("forward dt must equal the configured population step")
        state = self.population.initial_state((x.shape[0], self.hidden_size))
        trace = x.new_zeros(x.shape[0], self.hidden_size)
        outputs = []
        for inputs in x.unbind(1):
            drive = 6*torch.sigmoid(self.input(inputs)+self.recurrent(trace))
            step = self.population(state, drive=drive)
            state = step.state
            trace = math.exp(-dt/0.5)*trace+(1-math.exp(-dt/0.5))*step.rate
            outputs.append(trace)
        return torch.stack(outputs, dim=1)


class OfficialCfC(nn.Module):
    def __init__(self, input_size, hidden_size):
        super().__init__()
        try:
            from ncps.torch import CfC
        except ImportError as exc:
            raise UnavailableBaseline("official ncps.torch.CfC is not installed") from exc
        self.model = CfC(input_size, hidden_size, batch_first=True)

    def forward(self, x, dt=0.1):
        return self.model(x, timespans=x.new_full(x.shape[:2], dt))[0]


class OfficialMamba2(nn.Module):
    def __init__(self, input_size, hidden_size, device):
        super().__init__()
        if torch.device(device).type != "cuda":
            raise UnavailableBaseline("official Mamba-2 CUDA benchmark requires a CUDA device")
        try:
            from mamba_ssm import Mamba2
        except ImportError as exc:
            raise UnavailableBaseline("official mamba_ssm.Mamba2 is not installed") from exc
        if hidden_size*2 % 16:
            raise UnavailableBaseline("Mamba-2 requires twice hidden_size divisible by headdim=16")
        self.input = nn.Linear(input_size, hidden_size)
        self.model = Mamba2(d_model=hidden_size, d_state=16, d_conv=4, expand=2, headdim=16)

    def forward(self, x, dt=0.1):
        return self.model(self.input(x))


def make_encoder(name, input_size, hidden_size, device="cpu", dt=0.1):
    """Return the requested implementation, never a substituted optional baseline."""
    variants = {"hx_dual": {}, "hx_fixed": {"boundary": "fixed"},
                "hx_call": {"channel": "call"}, "hx_risk": {"channel": "risk"},
                "no_rollover": {"kernel": "no_rollover"}, "softplus": {"kernel": "softplus"},
                "no_recovery": {"recovery": False}}
    if name in variants:
        return ValueKernelCell(input_size, hidden_size, **variants[name])
    if name == "hx_attention":
        return TransformerEncoder(input_size, hidden_size,
                                  preceding=ValueKernelCell(input_size, hidden_size))
    if name in {"population_flux", "population_flux_no_recovery"}:
        return PopulationFluxEncoder(input_size, hidden_size, dt=dt, recovery=name == "population_flux")
    if name == "gru":
        return GRUEncoder(input_size, hidden_size)
    if name == "transformer":
        return TransformerEncoder(input_size, hidden_size)
    if name in {"lif", "adaptive_lif"}:
        return LIFEncoder(input_size, hidden_size, adaptive=name == "adaptive_lif")
    if name == "pif":
        return PIFEncoder(input_size, hidden_size)
    if name == "cfc":
        return OfficialCfC(input_size, hidden_size)
    if name == "mamba2":
        return OfficialMamba2(input_size, hidden_size, device)
    raise ValueError(f"unknown encoder {name!r}")
