"""Common trainable frontend and readout for every temporal architecture."""

import torch
from torch import nn

from .baseline import build_baseline, match_parameter_budget
from .cell import ContinuousSpikingBlock


CELL_MODES = {
    "hcsn": "dual",
    "single": "single",
    "no_adaptation": "no_adaptation",
    "ordinary": "ordinary",
}


def parameter_count(model):
    return sum(p.numel() for p in model.parameters() if p.requires_grad)


class SequenceClassifier(nn.Module):
    """The modality features, physical time and initialization are shared."""

    def __init__(
        self,
        input_dim,
        classes,
        width,
        depth,
        architecture,
        seed,
        match_cell_budget=False,
    ):
        super().__init__()
        self.config = dict(
            input_dim=input_dim,
            classes=classes,
            width=width,
            depth=depth,
            architecture=architecture,
            seed=seed,
            match_cell_budget=match_cell_budget,
        )
        # Build both shared parts before the architecture consumes random draws.
        with torch.random.fork_rng():
            torch.manual_seed(seed)
            self.frontend = nn.Sequential(
                nn.Linear(input_dim + 2, width), nn.LayerNorm(width), nn.Tanh()
            )
            self.readout = nn.Linear(width, classes)
        self.match_receipt = None
        with torch.random.fork_rng():
            torch.manual_seed(seed + 100003)
            if architecture in CELL_MODES:
                self.backbone = ContinuousSpikingBlock(
                    width, depth, CELL_MODES[architecture], "direct"
                )
            elif match_cell_budget:
                reference = ContinuousSpikingBlock(width, depth, "dual", "direct")
                target = parameter_count(reference)
                matched = match_parameter_budget(
                    architecture, width, target, depth=depth
                )
                self.match_receipt = matched
                self.backbone = build_baseline(
                    architecture, width, depth, hidden_width=matched["hidden_width"]
                )
            else:
                self.backbone = build_baseline(architecture, width, depth)

    def forward(self, x, dt, return_sequence=False):
        elapsed = dt.cumsum(dim=1)
        common = torch.cat(
            (x, dt.unsqueeze(-1) / 32, elapsed.unsqueeze(-1) / 32), dim=-1
        )
        sequence, aux = self.backbone(self.frontend(common), dt)
        logits = self.readout(sequence)
        return (logits if return_sequence else logits[:, -1]), aux

    def counts(self):
        return {
            "total": parameter_count(self),
            "frontend": parameter_count(self.frontend),
            "backbone": parameter_count(self.backbone),
            "readout": parameter_count(self.readout),
            "matching": self.match_receipt,
        }
