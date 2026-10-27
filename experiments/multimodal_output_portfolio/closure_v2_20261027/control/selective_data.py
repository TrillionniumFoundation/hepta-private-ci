"""Source-separated candidate calibration with distinct split random streams."""

import numpy as np
import torch

from ...v6.data import Observation, Target, make_batch
from .adapter import PublicTask
from .selective_protocol import SPEC


def tasks(corpus, split, count, offset, role, declared_ood, seed=None):
    seed = SPEC["new_random_namespaces"][role] if seed is None else int(seed)
    rng = np.random.default_rng(seed)
    preference = rng.permutation(np.resize([0, 1], count))
    contexts = [(condition, expires, budget) for condition in ("clean", "occlusion", "missing", "heavy_noise")
                for expires in (6, 7) for budget in (1, 2)]
    assignment = rng.permutation(np.arange(count) % len(contexts))
    result = []
    source = corpus.splits[split]
    for index in range(count):
        condition, expires, budget = contexts[int(assignment[index])]
        batch = make_batch(corpus, split, 1, seed * 1009 + index, corruption=condition, offset=offset + index)
        tokens = batch.observation.text_tokens.clone()
        tokens[:, 1] = 9
        observation = Observation(batch.observation.pixels, batch.observation.mask, tokens)
        if declared_ood:
            tokens[:, 3] = tokens[:, 5] = 11
            observation = Observation(torch.zeros_like(observation.pixels), torch.zeros_like(observation.mask), tokens)
        chosen = torch.arange(2 * (offset + index), 2 * (offset + index) + 2)
        if preference[index]:
            chosen = chosen.flip(0)
        pixels = source.images[chosen].float() / 255
        labels = source.labels[chosen][None]
        text = torch.tensor([[1, 3, int(labels[0, 0]) + 14, 4, int(labels[0, 1]) + 14, 5,
                              int(torch.sign(labels[0, 0] - labels[0, 1])) + 7, 2]])
        private = Target(torch.cat((pixels[0:1], pixels[1:2]), dim=3), text, labels)
        result.append({"index": index, "role": role, "condition": "both_missing" if declared_ood else condition,
            "expires": expires, "budget": budget, "preference": int(preference[index]), "declared_ood": declared_ood,
            "source_ids": list(batch.source_ids[0]), "private": private,
            "public": PublicTask(observation, seed * 100003 + index)})
    return result
