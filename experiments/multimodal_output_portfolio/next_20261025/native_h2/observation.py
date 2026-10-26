"""Target-free runtime observation by the existing deployable public sensor."""

import torch

from ...v6.observer import CAPTION
from ...abc_next.observability import PublicDigitSensor


@torch.inference_mode()
def observe_public(model, pixels, caption):
    if not isinstance(model, PublicDigitSensor) or model.training or any(p.requires_grad for p in model.parameters()):
        raise ValueError('Only the existing frozen public sensor is allowed online')
    if pixels.shape != (1, 1, 28, 56) or not torch.isfinite(pixels).all() or pixels.min() < 0 or pixels.max() > 1:
        raise ValueError('Invalid actual decoded output')
    panels = torch.stack((pixels[:, :, :, :28], pixels[:, :, :, 28:]), 1).flatten(0, 1)
    image_digits = model(panels, torch.ones_like(panels)).argmax(1).tolist()
    match = CAPTION.fullmatch(caption.strip())
    parsed = [int(match[1]), int(match[2])] if match else None
    disagreement = sum(a != b for a, b in zip(parsed, image_digits)) / 2 if match else 1.
    # This bounded, publicly observable proxy is deliberately separate from the
    # truth-dependent research utility. It may reward consistent wrong outputs.
    proxy = 1 - (float(match is None) + disagreement)
    return {'caption_valid': match is not None, 'image_digits': image_digits,
            'caption_digits': parsed, 'caption_relation': match[3] if match else None,
            'crossmodal_disagreement': disagreement, 'public_utility': proxy,
            'public_utility_definition': '1 - invalid_caption - image_text_disagreement',
            'target_supplied': False, 'factual_correctness_claimed': False}
