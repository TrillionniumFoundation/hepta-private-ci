"""Public tensors and private preference truth have separate persisted records."""

import json
from pathlib import Path

import numpy as np
import torch

from ...v6.data import Observation, Target, make_batch
from .adapter import PublicTask
from .protocol import PROTOCOL as P, digest, write


def make_tasks(corpus, split, count, offset=0, assigned=None):
    rng = np.random.default_rng(P["seed"] + {"train": 1, "validation": 2, "test": 3}[split])
    preferences = rng.permutation(np.tile([0, 1], (count + 1) // 2))[:count]
    contexts = [(condition, expiry, budget) for condition in P["conditions"]
                for expiry in (6, 7) for budget in (1, 2)]
    assignment = rng.permutation(np.arange(count) % len(contexts))
    tasks = []
    for i in range(count):
        condition, expiry, budget = contexts[int(assignment[i])]
        batch = make_batch(corpus, split, 1, P["seed"] + i * 31 + offset,
                           corruption=condition, offset=offset + i)
        source = corpus.splits[split]
        original = source.images[2 * (offset + i):2 * (offset + i) + 2].float() / 255
        source_labels = source.labels[2 * (offset + i):2 * (offset + i) + 2]
        target = original if preferences[i] == 0 else original.flip(0)
        labels = source_labels if preferences[i] == 0 else source_labels.flip(0)
        target_pixels = torch.cat((target[0:1], target[1:2]), dim=3)
        target_tokens = batch.target.text_tokens.clone()
        target_tokens[0, 2], target_tokens[0, 4] = labels[0] + 14, labels[1] + 14
        target_tokens[0, 6] = torch.sign(labels[0] - labels[1]) + 7
        private = Target(target_pixels, target_tokens, labels[None])
        tokens = batch.observation.text_tokens.clone()
        tokens[:, 1] = 9
        public = PublicTask(Observation(batch.observation.pixels, batch.observation.mask, tokens), P["seed"] + i * 1009)
        tasks.append({"index": i, "condition": condition, "expires": expiry, "budget": budget,
            "public": public, "private": private, "preference": int(preferences[i]),
            "source_ids": list(batch.source_ids[0])})
    return tasks


def persist_tasks(tasks, directory):
    directory = Path(directory)
    directory.mkdir()
    public = {"pixels": torch.cat([t["public"].observation.pixels for t in tasks]),
        "mask": torch.cat([t["public"].observation.mask for t in tasks]),
        "tokens": torch.cat([t["public"].observation.text_tokens for t in tasks]),
        "noise_seeds": [t["public"].noise_seed for t in tasks]}
    private = {"pixels": torch.cat([t["private"].pixels for t in tasks]),
        "tokens": torch.cat([t["private"].text_tokens for t in tasks]),
        "labels": torch.cat([t["private"].labels for t in tasks]),
        "preferences": [t["preference"] for t in tasks]}
    torch.save(public, directory / "PUBLIC.pt")
    torch.save(private, directory / "PRIVATE.pt")
    metadata = [{k: t[k] for k in ("index", "condition", "expires", "budget", "source_ids")} for t in tasks]
    write(directory / "SOURCES.json", metadata)
    return digest(metadata)


def load_tasks(directory):
    directory = Path(directory)
    public = torch.load(directory / "PUBLIC.pt", weights_only=True)
    private = torch.load(directory / "PRIVATE.pt", weights_only=True)
    metadata = json.loads((directory / "SOURCES.json").read_text())
    tasks = []
    for i, record in enumerate(metadata):
        tasks.append({**record, "public": PublicTask(Observation(public["pixels"][i:i + 1],
            public["mask"][i:i + 1], public["tokens"][i:i + 1]), public["noise_seeds"][i]),
            "private": Target(private["pixels"][i:i + 1], private["tokens"][i:i + 1], private["labels"][i:i + 1]),
            "preference": private["preferences"][i]})
    return tasks
