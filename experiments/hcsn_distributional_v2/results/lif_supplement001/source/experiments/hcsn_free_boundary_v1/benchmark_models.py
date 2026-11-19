"""Paired frontend/readout models and active-parameter budget matching."""

from functools import lru_cache

import torch
from torch import nn

from ..continuous_spiking_network.baseline import RecurrentBlock, build_baseline
from ..continuous_spiking_network.cell import ContinuousSpikingBlock
from .model import HCSNClassifier, parameter_count
from .vendor.cfc_cell import CfCCell


HCSN_VARIANTS = {
    "free_dual": ("free", "dual"),
    "fixed_dual": ("fixed", "dual"),
    "direct_dual": ("direct", "dual"),
    "free_margin": ("free", "margin"),
    "free_continuation": ("free", "continuation"),
    "free_ordinary": ("free", "ordinary"),
}
BASELINE_NAMES = ("legacy_hcsn", "two_gates", "continuous_rnn", "cfc",
                  "mamba1", "transformer", "lif_snn")
MODEL_NAMES = tuple(HCSN_VARIANTS) + BASELINE_NAMES


class _ProjectedResearchBackbone(nn.Module):
    """Active projections permit genuine size matching for legacy HCSN/CfC."""

    def __init__(self, name, width, depth, hidden):
        super().__init__()
        self.name, self.hidden_width = name, hidden
        self.input_proj = nn.Identity() if hidden == width else nn.Linear(width, hidden)
        self.output_proj = nn.Identity() if hidden == width else nn.Linear(hidden, width)
        if name == "legacy_hcsn":
            self.core = ContinuousSpikingBlock(hidden, depth, mode="dual", boundary_mode="direct")
        elif name == "cfc":
            self.core = nn.ModuleList([
                RecurrentBlock(CfCCell(hidden, hidden, mode="default",
                                       backbone_units=hidden, backbone_layers=1,
                                       backbone_dropout=0.0), hidden, "cfc")
                for _ in range(depth)])
        else:
            raise ValueError(name)

    def forward(self, x, dt):
        sequence = self.input_proj(x)
        if self.name == "legacy_hcsn":
            sequence, aux = self.core(sequence, dt)
        else:
            for block in self.core:
                sequence = block(sequence, dt)
            aux = {"architecture": "cfc", "implementation": "pinned_official_cell"}
        return self.output_proj(sequence), aux


def _backbone(name, width, depth, hidden):
    if name in {"legacy_hcsn", "cfc"}:
        return _ProjectedResearchBackbone(name, width, depth, hidden)
    return build_baseline(name, width, depth, hidden_width=hidden)


@lru_cache(maxsize=128)
def matched_backbone_configuration(name, width, depth):
    """Nearest actual trainable size; report any failure of the 5% tolerance."""
    with torch.random.fork_rng(devices=[]):
        torch.manual_seed(433)
        target = parameter_count(HCSNClassifier(1, 1, width=width, depth=depth).layers)
        candidates = []
        for hidden in range(1, 4 * width + 1):
            count = parameter_count(_backbone(name, width, depth, hidden))
            candidates.append((abs(count - target), count, hidden))
    gap, count, hidden = min(candidates)
    return dict(hidden_width=hidden, target_parameters=target,
                n_parameters=count, relative_gap=gap / target,
                within_five_percent=gap <= 0.05 * target,
                parameter_padding=False)


class BenchmarkClassifier(nn.Module):
    """Use exactly the same feature/time encoder and readout initialization."""

    def __init__(self, name, input_dim, output_dim, width=32, depth=1, seed=0):
        super().__init__()
        if name not in BASELINE_NAMES:
            raise ValueError(f"Unknown baseline: {name}")
        self.config = dict(name=name, input_dim=input_dim, output_dim=output_dim,
                           width=width, depth=depth, seed=seed)
        self.match_receipt = dict(matched_backbone_configuration(name, width, depth))
        with torch.random.fork_rng():
            torch.manual_seed(seed)
            self.frontend = nn.Sequential(nn.Linear(input_dim + 2, width),
                                          nn.LayerNorm(width), nn.Tanh())
            self.readout = nn.Linear(width, output_dim)
        with torch.random.fork_rng():
            torch.manual_seed(seed + 100003)
            self.backbone = _backbone(name, width, depth, self.match_receipt["hidden_width"])

    def forward(self, x, dt, return_sequence=False, return_aux=True):
        if x.ndim != 3 or dt.shape != x.shape[:2]:
            raise ValueError("Expected x[B,T,I] and dt[B,T]")
        common = torch.cat((x, dt.unsqueeze(-1) / 32,
                            dt.cumsum(1).unsqueeze(-1) / 32), dim=-1)
        sequence, aux = self.backbone(self.frontend(common), dt)
        logits = self.readout(sequence)
        result = logits if return_sequence else logits[:, -1]
        return (result, aux) if return_aux else result

    def parameter_groups(self):
        return {name: [(f"{name}.{key}", parameter)
                       for key, parameter in getattr(self, name).named_parameters()]
                for name in ("frontend", "backbone", "readout")}

    def counts(self):
        return dict(total=parameter_count(self), frontend=parameter_count(self.frontend),
                    backbone=parameter_count(self.backbone), readout=parameter_count(self.readout),
                    matching=dict(self.match_receipt))


def build_model(name, input_dim, output_dim, width=32, depth=1, seed=0):
    if name in HCSN_VARIANTS:
        boundary, channels = HCSN_VARIANTS[name]
        return HCSNClassifier(input_dim, output_dim, width=width, depth=depth,
                               boundary_mode=boundary, channels=channels, seed=seed)
    return BenchmarkClassifier(name, input_dim, output_dim, width=width,
                                depth=depth, seed=seed)
