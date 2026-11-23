"""Last-layer low-rank query/value editing and an antisymmetric answer score."""
import math

import numpy as np
import torch
from torch import nn


class LowRank(nn.Module):
    def __init__(self, original):
        super().__init__()
        self.original = original
        self.down = nn.Linear(original.in_features, 4, bias=False)
        self.up = nn.Linear(4, original.out_features, bias=False)
        nn.init.kaiming_uniform_(self.down.weight, a=math.sqrt(5))
        nn.init.zeros_(self.up.weight)

    def forward(self, x):
        return self.original(x) + 2.0 * self.up(self.down(x))


class Student:
    def __init__(self, encoder):
        self.encoder = encoder
        self.attention = encoder.model.encoder.layer[-1].attention.self
        for parameter in encoder.model.parameters():
            parameter.requires_grad_(False)
        self.attention.query = LowRank(self.attention.query)
        self.attention.value = LowRank(self.attention.value)
        width = encoder.model.config.hidden_size
        self.head = nn.Parameter(torch.empty(width))
        nn.init.normal_(self.head, std=0.02)
        self.trainable = {"head": self.head}
        for name in ("query", "value"):
            layer = getattr(self.attention, name)
            for factor in ("up", "down"):
                self.trainable[name+"_"+factor] = getattr(layer, factor).weight

    def margins(self, rows):
        queries = [r["query"] for r in rows for _ in r["candidates"]]
        answers = [a for r in rows for a in r["candidates"]]
        enc = self.encoder.tokenizer(queries, answers, return_tensors="pt",
                                     padding=True, truncation=False)
        mask = enc["attention_mask"]
        assert mask.shape[1] <= 160
        hidden = self.encoder.model(**enc).last_hidden_state
        means = (hidden * mask.unsqueeze(-1)).sum(1) / mask.sum(1, keepdim=True)
        emb = torch.nn.functional.normalize(means, p=2, dim=1)
        logits = (emb @ self.head).view(-1, 2)
        return logits[:, 1] - logits[:, 0], int(mask.sum())

    def save(self, path):
        np.savez_compressed(path, **{n:p.detach().numpy() for n,p in self.trainable.items()})

    def restore(self, path):
        with torch.no_grad(), np.load(path, allow_pickle=False) as weights:
            assert set(weights.files) == set(self.trainable)
            for name,p in self.trainable.items():
                assert weights[name].shape == tuple(p.size())
                p.copy_(torch.from_numpy(weights[name]))

    def detach(self):
        self.attention.query = self.attention.query.original
        self.attention.value = self.attention.value.original
