"""Offline same-head control for frozen EmbeddingGemma2 text-only vs text+image.

Use the same 769 parameter architecture, exact initialization, TRAIN labels,
optimizer, step count and source census. This is research only, DENY_ALL;
the Encoder forwards/snapshot are supplied by the original pinned owner.
"""
from __future__ import annotations

import hashlib
import json
import math

SCHEMA = "hepta.e3.native-gemma2-same-head-contrast.v1"

class MatchedHeadError(ValueError):
    pass


def check(value, reason):
    if not value:
        raise MatchedHeadError(reason)


def freeze_features(query, choices):
    import torch
    check(type(query) is torch.Tensor and type(choices) is torch.Tensor,
          "actual tensors required")
    check(query.ndim == 2 and query.shape[1] == 256 and
          choices.shape == (query.shape[0], 4, 256) and
          torch.isfinite(query).all().item() and torch.isfinite(choices).all().item(),
          "invalid frozen native feature bank")
    q = query.detach().float().cpu().unsqueeze(1).expand(-1, 4, -1)
    c = choices.detach().float().cpu()
    x = torch.cat((q, c, q*c), dim=-1).contiguous()
    check(x.shape == (len(query), 4, 768), "unequal complete private Head input width")
    return x


def _weights(model):
    h = hashlib.sha256()
    for name, tensor in sorted(model.state_dict().items()):
        raw = tensor.detach().float().contiguous().numpy().tobytes()
        h.update(name.encode("utf8") + b"\0" + raw)
    return h.hexdigest()


def train_pair(text, joint, choices, train_indices, train_labels, held_indices,
               *, steps=80, seed=20261016):
    import torch
    import torch.nn.functional as F
    check(type(steps) is int and 1 <= steps <= 256 and type(seed) is int,
          "unregistered optimizer budget")
    check(type(train_indices) in (list,tuple) and type(held_indices) in (list,tuple),
          "original source/held indices required")
    n = len(text)
    check(text.shape == joint.shape == (n, 256), "source-complete embedding banks")
    check(len(train_indices) > 0 and len(held_indices) > 0 and
          len(set(train_indices)) == len(train_indices) and
          len(set(held_indices)) == len(held_indices) and
          set(train_indices).isdisjoint(held_indices) and
          all(type(i) is int and 0 <= i < n for i in list(train_indices)+list(held_indices)),
          "source partitions not disjoint")
    labels = torch.as_tensor(train_labels, dtype=torch.long)
    check(labels.shape == (len(train_indices),) and
          bool(((labels >= 0) & (labels < 4)).all()),
          "TRAIN-only labels cardinality/range")
    # Freeze and detach the true pretrained Encoder's features. No backwards
    # path to its weight owner, even during the two local Head optimizations.
    banks = (freeze_features(text, choices), freeze_features(joint, choices))
    torch.manual_seed(seed)
    original = torch.nn.Linear(768,1,dtype=torch.float32)
    heads = (original, torch.nn.Linear(768,1,dtype=torch.float32))
    heads[1].load_state_dict(heads[0].state_dict())
    initial = (_weights(heads[0]),_weights(heads[1]))
    check(initial[0] == initial[1] and
          all(sum(x.numel() for x in h.parameters()) == 769 for h in heads),
          "unmatched complete 769-scalar private Heads")
    for x, head in zip(banks, heads):
        optimizer = torch.optim.AdamW(head.parameters(),lr=.01,weight_decay=0.)
        for _ in range(steps):
            optimizer.zero_grad(set_to_none=True)
            logits = head(x[train_indices]).squeeze(-1) * 8
            loss = F.cross_entropy(logits, labels)
            check(bool(torch.isfinite(loss).item()), "nonfinite train-only Head loss")
            loss.backward()
            optimizer.step()
    result=[]
    with torch.inference_mode():
        for head,x in zip(heads,banks):
            logits=head(x[held_indices]).squeeze(-1)*8
            probabilities=torch.softmax(logits,dim=-1)
            check(probabilities.shape == (len(held_indices),4) and
                  bool(torch.isfinite(probabilities).all()), "invalid matched Head probabilities")
            result.append(probabilities.detach().cpu().tolist())
    return {"schema":SCHEMA,
            "heads_complete_trainable_params_each":769,
            "train_steps_each":steps,
            "train_examples":len(train_indices),
            "test_examples":len(held_indices),
            "initial_same_head_digest":initial[0],
            "text_trained_head_digest":_weights(heads[0]),
            "joint_trained_head_digest":_weights(heads[1]),
            "text_only_probabilities":result[0],
            "joint_text_image_probabilities":result[1],
            "same_initialization":True,
            "identical_optimizer_schedule":True,
            "held_labels_visible_during_fit":False,
            "cost_matched":False,
            "production_accepted":False,"authority":"DENY_ALL"}
