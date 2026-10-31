"""A fixed probability ensemble of separately trained audio ingress classifiers."""

import torch
from torch import nn

from ....closure_20261025.media.coherent import MelSpeech


class EnsembleIngress(nn.Module):
    def __init__(self, member_count):
        super().__init__()
        if member_count not in (1, 3):
            raise ValueError("The registered candidates contain one or three members")
        self.members = nn.ModuleList(MelSpeech() for _ in range(member_count))

    def forward(self, spectra):
        features = self.members[0].front_end(spectra)
        probabilities = torch.stack([member.features(features).softmax(-1) for member in self.members]).mean(0)
        return probabilities.clamp_min(1e-8).log()


def load_ingress(path):
    record = torch.load(path, map_location="cpu", weights_only=True)
    model = EnsembleIngress(record["member_count"])
    model.load_state_dict(record["state_dict"], strict=True)
    for member in model.members[1:]:
        if not torch.equal(member.mel_bank, model.members[0].mel_bank):
            raise ValueError("Ensemble members do not share the frozen auditory transform")
    return model.eval().requires_grad_(False)
