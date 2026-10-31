"""Public observations only; outcome labels never enter this feature function."""

import torch
from torch.nn import functional as F

from ...abc_recovery.runtime import public_features


FEATURE_DIM = 508
FEATURE_PROFILE = {
    "schema": "hepta.abc3.resident-correctness-features.v1",
    "columns": ["h[96]", "context[96]", "actual-draft-generator-encoder[96]",
                "actual-caption-token-onehot[192]", "observed-mask-means[2]",
                "public-hint-onehot-including-unknown[22]", "hint-reliability[2]",
                "public-command-onehot[2]"],
    "excluded": ["target", "source-id", "view-label", "information-sufficient-label",
                 "untrusted-hint-correct", "observer-output", "future-rng"],
    "cost": "Generator draft encoding belongs to measured upstream feature preparation, outside the declared resident head.",
}


@torch.inference_mode()
def features(model, frame, observation):
    public = public_features(model, frame)
    latent_draft = torch.cat((public[:, :96], public[:, 288:672]), 1)
    mask = torch.stack((observation.mask[:, :, :, :28].mean((1, 2, 3)),
                        observation.mask[:, :, :, 28:].mean((1, 2, 3))), 1)
    hints = observation.text_tokens[:, (3, 5)]
    hints = torch.where(hints == 11, 10, hints - 14)
    hints = F.one_hot(hints, num_classes=11).flatten(1).float()
    reliable = (observation.text_tokens[:, (2, 4)] != 11).float()
    command = F.one_hot(observation.text_tokens[:, 1] - 9, num_classes=2).float()
    result = torch.cat((latent_draft, mask, hints, reliable, command), 1)
    if result.shape != (len(public), FEATURE_DIM) or not torch.isfinite(result).all():
        raise ValueError("Malformed public feature vector")
    if result.abs().max() > 8:
        raise ValueError("Native bounded feature profile exceeded")
    return result


def complete_absence(values):
    """The declared OOD mechanism is visible absence, not semantic failure."""
    return ((values[:, 480:482] == 0).all(1)
            & (values[:, 492] == 1) & (values[:, 503] == 1))
