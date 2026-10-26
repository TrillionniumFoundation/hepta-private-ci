"""Separately registered proper-log-score posterior repair; old Brier candidate stays frozen."""

import json
from pathlib import Path

import torch

from .model import SemanticAdapter


class LogScoreAdapter(SemanticAdapter):
    """The same native ABI with one of two prospectively registered bounds."""

    def __init__(self, residual_bound):
        if residual_bound not in (2., 8.):
            raise ValueError("Only the two registered old-development capacities are allowed")
        super().__init__()
        self.residual_bound = float(residual_bound)

    def forward(self, features, raw_probabilities, text_mask=None):
        residual = self.residual_bound * self.last(self.first(features).tanh()).tanh()
        probability = (raw_probabilities.clamp_min(1e-8).log() + residual).softmax(-1)
        if text_mask is not None:
            probability = torch.where(text_mask[:, None, None], raw_probabilities, probability)
        return probability

    def export_native(self, endpoint, path):
        record = super().export_native(endpoint, path)
        record["residual_bound"] = self.residual_bound
        record["training_objective"] = "proper categorical log score plus registered posterior anchor"
        Path(path).write_text(json.dumps(record, sort_keys=True, indent=2) + "\n")
        return record


def load_adapter(path):
    record = torch.load(path, map_location="cpu", weights_only=True)
    if record["schema"] != "hepta.advance.semantic-adapter-nll.v1":
        raise ValueError("Unexpected learned-adapter candidate identity")
    model = LogScoreAdapter(record["residual_bound"])
    model.load_state_dict(record["state_dict"], strict=True)
    return model.eval().requires_grad_(False)
