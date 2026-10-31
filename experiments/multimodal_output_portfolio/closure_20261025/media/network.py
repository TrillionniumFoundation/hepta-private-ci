"""Real acoustic/video ingress into the existing shared generation state."""

import torch
from torch import nn

from ...v7.model import State
from ...v7_media.models import validate_probabilities


class VideoInput(nn.Module):
    """A learned frame CNN and temporal GRU for two public one-second events."""

    def __init__(self):
        super().__init__()
        self.frames = nn.Sequential(nn.Conv2d(1, 8, 5, stride=2, padding=2), nn.ReLU(),
                                    nn.Conv2d(8, 16, 3, stride=2, padding=1), nn.ReLU(),
                                    nn.Flatten(), nn.Linear(16 * 7 * 7, 32), nn.Tanh())
        self.temporal = nn.GRU(32, 32, batch_first=True)
        self.head = nn.Linear(32, 10)

    def forward(self, pixels):
        if pixels.ndim != 5 or pixels.shape[1:] != (20, 1, 28, 28):
            raise ValueError("Video ingress requires twenty actual ordered frames")
        if not torch.isfinite(pixels).all() or pixels.min() < 0 or pixels.max() > 1:
            raise ValueError("Invalid observed video")
        features = self.frames(pixels.flatten(0, 1)).reshape(len(pixels) * 2, 10, 32)
        states, _ = self.temporal(features)
        return self.head(states[:, -1]).reshape(-1, 2, 10)


def ingress_state(generator, probabilities):
    """Use neural input posteriors, never target classes or fabricated pictures.

    The fixed digit-domain model already learned missing-image hint embeddings.
    A posterior-weighted embedding extends that exact shared fusion to actual
    audio/video encoder observations. This is a declared soft semantic bridge,
    not a claim of end-to-end co-training of the original generator.
    """
    validate_probabilities(probabilities, paired=True)
    p = probabilities.reshape(-1, 10)
    blank = p.new_zeros((len(p), 2, 28, 28))
    visual = generator.pixel_encoder(blank)
    hint = p @ generator.token_embedding.weight[14:24]
    reliability = generator.reliability_embedding(torch.ones(len(p), dtype=torch.long))
    slots = generator.fuse(torch.cat((visual, hint, reliability, p.new_zeros((len(p), 1))), 1))
    routing = generator.command_attention(torch.zeros(len(probabilities), dtype=torch.long))
    context = torch.bmm(routing.reshape(-1, 2, 2).softmax(-1), slots.reshape(-1, 2, 48)).flatten(1)
    slot_state = context.reshape(-1, 48)
    return State(context, generator.initial_image(slot_state).tanh().reshape(-1, 96),
                 generator.initial_text(slot_state).tanh().reshape(-1, 96), context)
