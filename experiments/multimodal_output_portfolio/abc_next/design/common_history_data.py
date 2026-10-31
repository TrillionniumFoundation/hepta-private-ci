"""Public-only histories and offline finite private targets for a bounded audit."""

from dataclasses import replace
import hashlib
import json

import numpy as np
import torch

from ...v6.data import BOS, DIGIT_OFFSET, EOS, PAD, Observation, Target
from ...v6.observer import observe_tensors


def stream_seed(*parts):
    encoded = json.dumps(("hepta.abc-next.common-history.v1", *parts),
                         sort_keys=True, separators=(",", ":")).encode()
    return int.from_bytes(hashlib.sha256(encoded).digest()[:8], "big") % 2**63


def public_observation(swap):
    """No target, source identity or private pixel is an argument to this API."""
    if type(swap) is not int or swap not in (0, 1):
        raise ValueError("The public command must be swap 0 or 1")
    return Observation(torch.zeros(1, 1, 28, 56), torch.zeros(1, 1, 28, 56),
                       torch.tensor([[BOS, 9 + swap, 12, 11, 13, 11, EOS, PAD]]))


def private_targets(pool, pair_start, pair_count, swap):
    """Materialize the predeclared uniform support only on the offline side."""
    if (type(pair_start) is not int or type(pair_count) is not int
            or pair_start < 0 or pair_count < 1 or swap not in (0, 1)
            or 2 * (pair_start + pair_count) > len(pool)):
        raise ValueError("Incomplete or invalid finite target support")
    selected = slice(2 * pair_start, 2 * (pair_start + pair_count))
    pixels = pool.images[selected].float() / 255
    labels = pool.labels[selected].reshape(pair_count, 2).clone()
    left, right = pixels[::2], pixels[1::2]
    if swap:
        left, right, labels = right, left, labels.flip(1)
    captions = torch.empty(pair_count, 8, dtype=torch.long)
    captions[:, 0], captions[:, 1], captions[:, 3] = BOS, 3, 4
    captions[:, 2], captions[:, 4] = labels[:, 0] + DIGIT_OFFSET, labels[:, 1] + DIGIT_OFFSET
    captions[:, 5], captions[:, 6], captions[:, 7] = 5, torch.sign(labels[:, 0] - labels[:, 1]) + 7, EOS
    return Target(torch.cat((left, right), dim=3), captions, labels)


def replicate_public_run(run, replicas):
    """Repeat one immutable history without adding any private target field."""
    if len(run.pixels) != 1 or type(replicas) is not int or replicas < 1:
        raise ValueError("A singleton history and positive replica count are required")
    repeated = lambda value: value.repeat((replicas,) + (1,) * (value.ndim - 1))
    state = replace(run.state, **{name: repeated(getattr(run.state, name))
                                  for name in ("h", "image", "text", "context")})
    return replace(run, state=state, pixels=repeated(run.pixels), tokens=repeated(run.tokens),
                   image_log_probability=repeated(run.image_log_probability),
                   text_log_probability=repeated(run.text_log_probability),
                   anchor_h=repeated(run.anchor_h), ledger=())


def offline_utilities(observer, decoded_pixels, decoded_captions, target, replicas, action_costs):
    """Score every persisted action output against every target, never select."""
    if (len(decoded_pixels) != replicas * len(action_costs)
            or len(decoded_captions) != len(decoded_pixels)):
        raise ValueError("Actual-media census does not match actions and replicas")
    values = np.empty((len(target.labels), replicas, len(action_costs)), dtype=np.float64)
    for action, cost in enumerate(action_costs):
        chosen = slice(action * replicas, (action + 1) * replicas)
        pixels = decoded_pixels[chosen].repeat(len(target.labels), 1, 1, 1)
        captions = decoded_captions[chosen] * len(target.labels)
        target_pixels = target.pixels.repeat_interleave(replicas, dim=0)
        labels = target.labels.repeat_interleave(replicas, dim=0)
        utilities = []
        for offset in range(0, len(pixels), 256):
            block = slice(offset, offset + 256)
            metrics = observe_tensors(observer, pixels[block], captions[block], target_pixels[block], labels[block])
            utilities.extend(row["utility"] - cost for row in metrics)
        values[:, :, action] = np.asarray(utilities).reshape(len(target.labels), replicas)
    return values
