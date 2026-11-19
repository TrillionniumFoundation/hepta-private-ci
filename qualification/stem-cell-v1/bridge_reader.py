"""V6 cross-fact residual bridge and a parameter-matched local Head control.

The Encoder interface and bounded TokenReader state transition stay unchanged.
All variants start with identical base tensors and exact base predictions.
"""
import math

import torch
from torch import nn
from torch.nn import functional as F

from token_reader import TokenReader, _attention, _mean


class FactBridge(nn.Module):
    """One masked attention exchange between fact summaries, with no position IDs."""

    def __init__(self, hidden_dim):
        super().__init__()
        self.query = nn.Linear(hidden_dim, hidden_dim, bias=False)
        self.key = nn.Linear(hidden_dim, hidden_dim, bias=False)
        self.value = nn.Linear(hidden_dim, hidden_dim, bias=False)
        self.output = nn.Linear(hidden_dim, hidden_dim, bias=False)
        nn.init.zeros_(self.output.weight)

    def forward(self, relations, token_mask):
        batch, facts, _, hidden = relations.shape
        if batch * facts * facts > 64_000_000:
            raise ValueError("cross-fact attention tensor limit exceeded; reduce batch size")
        present = token_mask.any(-1)
        summaries = _mean(relations, token_mask)
        scores = torch.matmul(self.query(summaries), self.key(summaries).transpose(-1, -2))
        weights = _attention(scores / math.sqrt(hidden), present[:, None].expand_as(scores))
        message = self.output(torch.matmul(weights, self.value(summaries)))
        # Padded tokens cannot become new evidence, including entirely absent facts.
        message = message * present.unsqueeze(-1).to(message.dtype)
        return relations + message.unsqueeze(-2) * token_mask.unsqueeze(-1).to(message.dtype)


class LocalResidual(nn.Module):
    """Four square matrices confined to each candidate's existing Head hidden vector."""

    def __init__(self, hidden_dim):
        super().__init__()
        self.input = nn.Linear(hidden_dim, hidden_dim, bias=False)
        self.hidden1 = nn.Linear(hidden_dim, hidden_dim, bias=False)
        self.hidden2 = nn.Linear(hidden_dim, hidden_dim, bias=False)
        self.output = nn.Linear(hidden_dim, hidden_dim, bias=False)
        nn.init.zeros_(self.output.weight)

    def forward(self, value):
        hidden = F.gelu(self.input(value))
        hidden = F.gelu(self.hidden1(hidden))
        return self.output(F.gelu(self.hidden2(hidden)))


class ResidualHead(nn.Sequential):
    """Retain original head parameter names while adding a local residual path."""

    def __init__(self, original, hidden_dim):
        super().__init__(*original)
        self.local_residual = LocalResidual(hidden_dim)

    def forward(self, value):
        hidden = self[1](self[0](value))
        return self[2](hidden + self.local_residual(hidden))


class BridgeReader(TokenReader):
    """Exchange fact-level messages once during prepare; preserve every recurrent hop."""

    def __init__(self, input_dim=384, hidden_dim=32, max_hops=8, *, residual_seed=0):
        super().__init__(input_dim, hidden_dim, max_hops=max_hops)
        with torch.random.fork_rng(devices=[]):
            torch.manual_seed(residual_seed)
            self.fact_bridge = FactBridge(hidden_dim)
        self.reader_arm = "bridge"

    def prepare(self, facts, question, candidate, fact_mask, question_mask, candidate_mask):
        prepared = super().prepare(facts, question, candidate, fact_mask,
                                   question_mask, candidate_mask)
        relations = self.fact_bridge(prepared["relations"], prepared["fact_mask"])
        return {**prepared, "relations": relations, "token_keys": self.token_key(relations)}


class WideReader(TokenReader):
    """Equal added parameter count in the Head, without a cross-fact exchange."""

    def __init__(self, input_dim=384, hidden_dim=32, max_hops=8, *, residual_seed=0):
        super().__init__(input_dim, hidden_dim, max_hops=max_hops)
        with torch.random.fork_rng(devices=[]):
            torch.manual_seed(residual_seed)
            self.head = ResidualHead(self.head, hidden_dim)
        self.reader_arm = "wide"


def build_reader(arm, seed):
    """Construct the registered 384→32 family without consuming the caller's RNG."""
    if arm not in ("base", "bridge", "wide") or type(seed) is not int or seed < 0:
        raise ValueError("known Reader arm and nonnegative integer seed required")
    with torch.random.fork_rng(devices=[]):
        torch.manual_seed(seed)
        if arm == "base":
            model = TokenReader(384, 32, max_hops=8)
            model.reader_arm = arm
        elif arm == "bridge":
            model = BridgeReader(residual_seed=seed ^ 0x6B12)
        else:
            model = WideReader(residual_seed=seed ^ 0x6B12)
    return model


def reader_identity(model):
    """Record architecture identity separately from training and tensor digests."""
    registered = {TokenReader: "base", BridgeReader: "bridge", WideReader: "wide"}
    arm = registered.get(type(model))
    if arm is None or getattr(model, "reader_arm", None) != arm or model.interaction != "token":
        raise ValueError("registered Reader class and matching arm identity required")
    hidden, inputs = model.hidden_dim, model.input_dim
    shapes = {"project.weight": (hidden, inputs),
              "query.weight": (hidden, hidden * 4), "query.bias": (hidden,),
              "relation.weight": (hidden, hidden * 8), "relation.bias": (hidden,),
              "token_score.weight": (1, hidden), "token_key.weight": (hidden, hidden),
              "fact_score.weight": (1, hidden), "fact_key.weight": (hidden, hidden),
              "state_query.weight": (hidden, hidden * 2),
              "proposal.weight": (hidden, hidden * 3 + 4), "proposal.bias": (hidden,),
              "update_gate.weight": (hidden, hidden * 3 + 4), "update_gate.bias": (hidden,),
              "head.0.weight": (hidden, hidden * 3 + 1), "head.0.bias": (hidden,),
              "head.2.weight": (2, hidden), "head.2.bias": (2,)}
    if arm == "bridge":
        shapes.update({"fact_bridge." + name + ".weight": (hidden, hidden)
                       for name in ("query", "key", "value", "output")})
    elif arm == "wide":
        shapes.update({"head.local_residual." + name + ".weight": (hidden, hidden)
                       for name in ("input", "hidden1", "hidden2", "output")})
    if {name: tuple(value.shape) for name, value in model.state_dict().items()} != shapes:
        raise ValueError("registered Reader parameter names and shapes required")
    parameters = sum(value.numel() for value in model.parameters())
    added = 0 if arm == "base" else 4 * model.hidden_dim ** 2
    base_parameters = inputs * hidden + 25 * hidden ** 2 + 18 * hidden + 2
    if parameters != base_parameters + added:
        raise ValueError("registered Reader parameter count required")
    return {"schema": "hepta-bridge-reader-v1", "arm": arm,
            "input_dim": model.input_dim, "hidden_dim": model.hidden_dim,
            "max_hops": model.max_hops, "max_facts": model.max_facts,
            "max_tokens": model.max_tokens, "parameter_count": parameters,
            "base_parameter_count": base_parameters,
            "added_parameter_count": added,
            "residual_location": {"base": "none", "bridge": "cross_fact_prepare",
                                  "wide": "local_head_hidden"}[arm],
            "cross_fact_attention": arm == "bridge", "state_transition": "TokenReader-v4"}
