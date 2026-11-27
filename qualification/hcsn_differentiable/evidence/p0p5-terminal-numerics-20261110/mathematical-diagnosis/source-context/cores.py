"""Same frontend/head, explicit temporal cores for ABC/D development.

The event-time LIF is an analytic piecewise-constant-current reference, not an
implementation of EventProp. Its derivatives are valid within a fixed event
active set. HCSN construction never grants numerical/scientific admission.
"""

import hashlib
import math
from dataclasses import asdict, fields
from pathlib import Path
import sys

import torch
from torch import nn

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "proposals/localization-v2"))
from models import _official_s4, _require_version  # noqa: E402 - pinned local adapter bootstrap

ARMS = ("gru", "cfc", "snn_plif", "event_time_lif", "ssm_s4d", "attention", "hcsn")


def explicit_hcsn_grid(configuration):
    """Require the entire fixed geometry; omitted defaults hide domain changes."""
    from qualification.hcsn_differentiable.contract import GridSpec

    names = {field.name for field in fields(GridSpec)}
    if not isinstance(configuration, dict) or set(configuration) != names:
        raise ValueError(
            f"HCSN requires exactly these GridSpec fields: {sorted(names)}"
        )
    return GridSpec(**configuration)


def explicit_plif_configuration(configuration):
    """Checkpoint-carried dynamics/readout; threshold is not a tensor buffer."""
    names = {"init_tau", "threshold", "input_weight_gain", "readout", "trace_decay"}
    if not isinstance(configuration, dict) or set(configuration) != names:
        raise ValueError(f"PLIF requires exactly these fields: {sorted(names)}")
    result = dict(configuration)
    for key in names - {"readout"}:
        if isinstance(result[key], bool) or not isinstance(result[key], (int, float)):
            raise ValueError(f"PLIF {key} must be a finite real")
        result[key] = float(result[key])
        if not math.isfinite(result[key]):
            raise ValueError(f"PLIF {key} must be a finite real")
    if (result["init_tau"] <= 1 or result["threshold"] <= 0
            or result["input_weight_gain"] <= 0 or not 0 <= result["trace_decay"] < 1
            or result["readout"] not in {"spikes", "membrane", "spike_trace"}):
        raise ValueError("PLIF configuration outside the declared domain")
    return result


def tensor_digest(module):
    digest = hashlib.sha256()
    for name, value in sorted(module.state_dict().items()):
        digest.update(name.encode())
        digest.update(str((tuple(value.shape), value.dtype)).encode())
        digest.update(value.detach().cpu().contiguous().numpy().tobytes())
    return digest.hexdigest()


def event_lif_step(voltage, trace, current, dt, tau, trace_tau):
    """Exact end-state and event-time trace for threshold 1, reset 0.

    Current is constant on this interval; no refractory delay. The final trace
    sums exp(-(dt-t_k)/trace_tau) over every actual crossing, including multiple
    spikes. Integer count is locally constant, so AD differentiates analytic
    event times, not a surrogate spike derivative. Grazing/count changes are
    explicitly outside this derivative's smooth domain.
    """
    positive = current > 1
    safe_current = torch.where(positive, current, torch.full_like(current, 2.0))
    first = tau * torch.log1p((1 - voltage) / (safe_current - 1))
    period = tau * torch.log1p(1 / (safe_current - 1))
    hit = positive & (first <= dt)
    count = torch.where(
        hit, torch.floor((dt - first) / period) + 1, torch.zeros_like(first)
    )
    if not bool(torch.isfinite(count).all()) or bool((count > 1000000).any()):
        raise FloatingPointError(
            "event count exceeds the analytic reference's declared numeric domain"
        )
    residual = torch.where(
        hit, dt - first - (count - 1) * period, torch.zeros_like(first)
    )
    free_voltage = current + (voltage - current) * torch.exp(-dt / tau)
    reset_voltage = current * (-torch.expm1(-residual / tau))
    spike_trace = (
        torch.exp(-residual / trace_tau)
        * (-torch.expm1(-count * period / trace_tau))
        / (-torch.expm1(-period / trace_tau))
    )
    return (
        torch.where(hit, reset_voltage, free_voltage),
        trace * torch.exp(-dt / trace_tau) + spike_trace,
        count,
    )


class CfCCore(nn.Module):
    def __init__(self, width):
        super().__init__()
        _require_version("ncps", "1.0.1")
        from ncps.torch.cfc_cell import CfCCell

        self.cell = CfCCell(
            width,
            width,
            mode="default",
            backbone_units=4 * width,
            backbone_layers=1,
            backbone_dropout=0.0,
        )

    def forward(self, x, dt):
        state, rows = torch.zeros_like(x[:, 0]), []
        for t in range(x.shape[1]):
            value, state = self.cell(x[:, t], state, dt[:, t, None])
            rows.append(value)
        return torch.stack(rows, 1)


class PLIFCore(nn.Module):
    def __init__(self, width, configuration=None):
        super().__init__()
        _require_version("spikingjelly", "0.0.0.0.14")
        from spikingjelly.activation_based import neuron, surrogate

        self.configuration = explicit_plif_configuration(configuration or {
            "init_tau": 2.0, "threshold": 1.0, "input_weight_gain": 1.0,
            "readout": "spikes", "trace_decay": 0.75,
        })
        self.input = nn.Linear(width, width)
        self.recurrent = nn.Linear(width, width, bias=False)
        with torch.no_grad():
            self.input.weight.mul_(self.configuration["input_weight_gain"])
        self.node = neuron.ParametricLIFNode(
            init_tau=self.configuration["init_tau"],
            decay_input=False,
            v_threshold=self.configuration["threshold"],
            v_reset=None,
            surrogate_function=surrogate.ATan(alpha=2.0),
            detach_reset=True,
            step_mode="s",
            backend="torch",
        )
        self.diagnostics = {}

    def forward(self, x, dt):
        self.node.reset()
        state, trace = torch.zeros_like(x[:, 0]), torch.zeros_like(x[:, 0])
        rows, spikes = [], []
        for observation in x.unbind(1):
            state = self.node(self.input(observation) + self.recurrent(state))
            spikes.append(state)
            decay = self.configuration["trace_decay"]
            trace = decay * trace + (1 - decay) * state
            readout = self.configuration["readout"]
            rows.append(state if readout == "spikes" else
                        self.node.v if readout == "membrane" else trace)
        result = torch.stack(rows, 1)
        spike = torch.stack(spikes, 1).detach()
        self.diagnostics = {
            "spike_fraction": float(spike.mean()),
            "spike_count": float(spike.sum()),
            "active_neurons": int((spike.sum((0, 1)) > 0).sum()),
            "tau": float(1 / self.node.w.detach().sigmoid()),
            "threshold": self.node.v_threshold,
            "readout": self.configuration["readout"],
            "trace_decay": self.configuration["trace_decay"],
            "trace_injection": 1 - self.configuration["trace_decay"],
            "trace_e_folding_event_steps": -1 / math.log(self.configuration["trace_decay"])
            if self.configuration["trace_decay"] > 0 else None,
            "trace_reciprocal_injection_event_steps": 1 / (1 - self.configuration["trace_decay"]),
            "diagnostic_scope": "all padded compute positions; loss excludes padding",
            "time_semantics": "event-indexed; physical dt also appears in common input",
        }
        return result


class EventLIFCore(nn.Module):
    def __init__(self, width):
        super().__init__()
        self.current = nn.Linear(width, width)
        self.raw_tau = nn.Parameter(torch.full((width,), -3.0))
        self.raw_trace_tau = nn.Parameter(torch.full((width,), -2.0))
        self.diagnostics = {}

    def forward(self, x, dt):
        voltage, trace = torch.zeros_like(x[:, 0]), torch.zeros_like(x[:, 0])
        tau = 0.02 + torch.nn.functional.softplus(self.raw_tau)
        trace_tau = 0.02 + torch.nn.functional.softplus(self.raw_trace_tau)
        rows, counts = [], []
        for t in range(x.shape[1]):
            current = torch.nn.functional.softplus(self.current(x[:, t]))
            voltage, trace, count = event_lif_step(
                voltage, trace, current, dt[:, t, None], tau, trace_tau
            )
            rows.append(voltage + trace)
            counts.append(count)
        self.diagnostics = {
            "events": float(torch.stack(counts).detach().sum()),
            "derivative": "analytic event-time derivative within fixed active set",
            "readout": "membrane plus exponentially decaying spike trace",
            "current_semantics": "current observation held over preceding event gap",
        }
        return torch.stack(rows, 1)


class AttentionCore(nn.Module):
    def __init__(self, width):
        super().__init__()
        self.layer = nn.TransformerEncoderLayer(
            width, 2, 4 * width, dropout=0.0, activation="gelu", batch_first=True
        )

    def forward(self, x, dt):
        elapsed = dt.cumsum(1)[..., None]
        frequency = torch.exp(
            torch.arange(0, x.shape[-1], 2, dtype=x.dtype, device=x.device)
            * (-math.log(10000.0) / x.shape[-1])
        )
        encoding = torch.zeros_like(x)
        encoding[..., 0::2], encoding[..., 1::2] = (
            torch.sin(elapsed * frequency),
            torch.cos(elapsed * frequency),
        )
        mask = torch.ones(
            x.shape[1], x.shape[1], dtype=torch.bool, device=x.device
        ).triu(1)
        return self.layer(x + encoding, src_mask=mask)


class HCSNCore(nn.Module):
    def __init__(self, width, grid_configuration, cache_frozen_tables=False):
        super().__init__()
        from qualification.hcsn_differentiable.network import ContinuousSpikingNetwork

        grid = explicit_hcsn_grid(grid_configuration)
        operators = None
        if cache_frozen_tables:
            from frozen_tables import FrozenTableOperator

            operators = [FrozenTableOperator(grid)]
        self.network = ContinuousSpikingNetwork(
            width, width, width, layer_count=1, grid=grid, operators=operators
        )
        for layer in self.network.layers:
            layer.physics.requires_grad_(False)
        self.recorder = None
        self.record_context = None
        self.diagnostics = {}
        self.cost_geometry = {
            "grid": asdict(grid),
            "layer_count": 1,
            "probability_coefficients_per_sample": grid.state_count,
            "content_coefficients_per_sample": grid.state_count * width,
            "state_payload_fp64_bytes_per_sample": grid.state_count * (1 + width) * 8,
            "transition_matrix_coefficients_per_distinct_gap": grid.state_count**2,
            "state_payload_scope": "probability and content only; excludes clocks, snapshots, autograd and temporary work",
            "physics_trainable": False,
            "cache_frozen_tables": cache_frozen_tables,
        }

    def forward(self, x, dt, valid_mask=None):
        state = self.network.initial_state(x.shape[0])
        result = self.network(
            x,
            dt,
            state=state,
            observed=valid_mask,
            valid_mask=valid_mask,
            return_trace=self.recorder is not None,
        )
        if self.recorder is not None:
            self.recorder.capture(
                self.network,
                state,
                result,
                dt,
                valid_mask=valid_mask,
                **self.record_context,
            )
        self.diagnostics = {
            **result.diagnostics,
            "numerical_admission": "development_only_unqualified",
        }
        return result.predictions


class CoreStudyModel(nn.Module):
    def __init__(
        self,
        arm,
        *,
        width=16,
        seed=101,
        s4_repo=None,
        hcsn_grid=None,
        freeze_shared=True,
        cache_frozen_tables=False,
        learn_core_adapter=False,
        plif_configuration=None,
    ):
        super().__init__()
        if arm not in ARMS or width < 2 or width % 2:
            raise ValueError("unknown arm or invalid even width")
        if arm != "hcsn" and (hcsn_grid is not None or cache_frozen_tables):
            raise ValueError("HCSN configuration supplied to a different temporal core")
        if arm != "snn_plif" and plif_configuration is not None:
            raise ValueError("PLIF configuration supplied to a different temporal core")
        if plif_configuration is not None:
            explicit_plif_configuration(plif_configuration)
        # These RNG streams are independent of constructor RNG consumption.
        with torch.random.fork_rng():
            torch.manual_seed(seed + 1000003)
            self.frontend = nn.Sequential(nn.Linear(25, width), nn.Tanh()).double()
            torch.manual_seed(seed + 2000003)
            self.head = nn.Linear(width, 11).double()
        with torch.random.fork_rng():
            torch.manual_seed(seed)
            if arm == "gru":
                self.core = nn.GRU(width, width, batch_first=True)
            elif arm == "cfc":
                self.core = CfCCore(width)
            elif arm == "snn_plif":
                self.core = PLIFCore(width, plif_configuration)
            elif arm == "event_time_lif":
                self.core = EventLIFCore(width)
            elif arm == "ssm_s4d":
                cls, self.official_sources = _official_s4(s4_repo)
                self.core = cls(
                    d_model=width, d_state=16, dropout=0.0, transposed=False
                )
            elif arm == "attention":
                self.core = AttentionCore(width)
            else:
                self.core = HCSNCore(width, hcsn_grid, cache_frozen_tables)
        # An identical trainable output-coordinate map gives bounded/spiking
        # cores access to the same frozen common head's coordinate system.
        # Identity initialization preserves each core's initial representation.
        with torch.random.fork_rng():
            torch.manual_seed(seed + 3000003)
            self.temporal_adapter = (
                nn.Linear(width, width) if learn_core_adapter else nn.Identity()
            )
            if learn_core_adapter:
                with torch.no_grad():
                    self.temporal_adapter.weight.copy_(torch.eye(width))
                    self.temporal_adapter.bias.zero_()
        self.learn_core_adapter = learn_core_adapter
        self.construction_configuration = {
            "arm": arm, "width": width, "seed": seed,
            "s4_repo": str(s4_repo) if s4_repo is not None else None,
            "hcsn_grid": hcsn_grid, "freeze_shared": freeze_shared,
            "cache_frozen_tables": cache_frozen_tables,
            "learn_core_adapter": learn_core_adapter,
            "plif_configuration": self.core.configuration if arm == "snn_plif" else None,
        }
        self.arm, self.width = arm, width
        self.double()
        self.frontend.requires_grad_(not freeze_shared)
        self.head.requires_grad_(not freeze_shared)
        self.freeze_shared = freeze_shared
        self.initial_frontend_sha256, self.initial_head_sha256 = (
            tensor_digest(self.frontend),
            tensor_digest(self.head),
        )

    def forward(self, x, dt):
        encoded = self.frontend(x)
        if self.arm == "gru":
            value = self.core(encoded)[0]
        elif self.arm == "ssm_s4d":
            value = self.core(encoded)[0]
        elif self.arm == "hcsn":
            # Every genuine localization record has a tag's three observed
            # mask entries; the batch builder's trailing padding has none.
            value = self.core(encoded, dt, valid_mask=x[..., 12:24].bool().any(-1))
        else:
            value = self.core(encoded, dt)
        return self.head(self.temporal_adapter(value))
