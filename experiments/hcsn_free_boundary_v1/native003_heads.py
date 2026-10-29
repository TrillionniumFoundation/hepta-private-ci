"""Small, same-information stopping heads for the separate native003 study."""

import math

import torch
from torch import nn
from torch.nn import functional as F


FAMILIES = ("value_maxout", "ordinary_mlp", "risk_threshold")
FEATURES = ("continuation", "margin", "risk", "activity", "elapsed_over_32", "read_price")
Q = 1 << 24


class StopHead(nn.Module):
    """Positive score means KEEP; zero/negative means STOP.

    value_maxout and ordinary_mlp each have 33 actual trainable scalars.
    The maxout head selects among four scaled softplus branches. Its branch
    nonlinearity is explicit: it is not advertised as max-of-affine maxout.
    The risk threshold is a two-parameter, price-conditioned restricted control.
    """

    def __init__(self, family, mean, std, seed=440031):
        super().__init__()
        if family not in FAMILIES:
            raise ValueError("Unknown native003 head")
        self.config = {"family": family, "seed": seed}
        self.family = family
        self.register_buffer("feature_mean", torch.as_tensor(mean, dtype=torch.float32).clone())
        self.register_buffer("feature_std", torch.as_tensor(std, dtype=torch.float32).clone())
        if self.feature_mean.shape != (6,) or self.feature_std.shape != (6,) or (self.feature_std <= 0).any():
            raise ValueError("Require six finite, positive-scale normalization coordinates")
        with torch.random.fork_rng():
            torch.manual_seed(seed)
            if family == "risk_threshold":
                self.threshold_logit = nn.Parameter(torch.zeros(()))
                self.price_coefficient = nn.Parameter(torch.zeros(()))
            else:
                self.hidden = nn.Linear(6, 4)
                nn.init.normal_(self.hidden.weight, std=0.1)
                nn.init.zeros_(self.hidden.bias)
                if family == "value_maxout":
                    self.branch_scale = nn.Parameter(torch.full((4,), math.log(math.expm1(1.0))))
                    self.output_bias = nn.Parameter(torch.tensor(-0.5))
                else:
                    self.readout = nn.Linear(4, 1)
                    nn.init.normal_(self.readout.weight, std=0.1)
                    nn.init.constant_(self.readout.bias, 0.2)

    def forward(self, features, return_branches=False):
        if features.shape[-1] != 6:
            raise ValueError("Expected six public observed inputs")
        if self.family == "risk_threshold":
            threshold = torch.sigmoid(self.threshold_logit + self.price_coefficient * features[..., 5] / 0.05)
            score = features[..., 2] - threshold
            return (score, None) if return_branches else score
        standardized = (features - self.feature_mean) / self.feature_std
        hidden = self.hidden(standardized)
        if self.family == "value_maxout":
            branches = F.softplus(hidden) * F.softplus(self.branch_scale)
            score = branches.max(-1).values + self.output_bias
            return (score, branches) if return_branches else score
        score = self.readout(torch.tanh(hidden)).squeeze(-1)
        return (score, None) if return_branches else score

    def parameter_count(self):
        return sum(parameter.numel() for parameter in self.parameters() if parameter.requires_grad)


def append_price(observed, price):
    """observed[...,5] holds four cell/task features and observed elapsed time."""
    if observed.shape[-1] != 5:
        raise ValueError("Expected five non-price observed features")
    price = torch.as_tensor(price, dtype=observed.dtype, device=observed.device)
    return torch.cat((observed, torch.broadcast_to(price, observed.shape[:-1]).unsqueeze(-1)), -1)


def observed_features(logits, aux, elapsed):
    """Preserve every batch/time axis; never average across different episodes."""
    return torch.stack((torch.tanh(aux["continuation"].mean(-1)),
                        torch.tanh(aux["margin"].mean(-1)),
                        1 - logits.softmax(-1).amax(-1),
                        aux["event_probability"].mean(-1), elapsed / 32.0), -1)


def soft_utility(scores, correctness, prices, temperature=0.1):
    """Expected utility of a first-stop distribution, with mandatory horizon.

    Every observed prefix is paid, including the first and terminal observation.
    The final prefix terminates even if its head would request KEEP.
    """
    if scores.ndim != 2 or correctness.shape != scores.shape or temperature <= 0:
        raise ValueError("Expected score/correctness[B,T] and positive temperature")
    log_continue = F.logsigmoid(scores / temperature)
    log_survival = torch.cat((torch.zeros_like(scores[:, :1]),
                              log_continue[:, :-1].cumsum(1)), 1)
    stop = torch.cat((torch.sigmoid(-scores[:, :-1] / temperature), torch.ones_like(scores[:, -1:])), 1)
    mass = log_survival.exp() * stop
    reads = torch.arange(1, scores.shape[1] + 1, dtype=scores.dtype, device=scores.device)
    reward = correctness - prices[:, None] * reads
    return (mass * reward).sum(1), mass


def hard_decisions(scores, correctness, prices):
    """Match native Q24 transport: tanh then ties-to-even quantization; STOP ties."""
    q24 = torch.round(torch.tanh(scores) * Q).to(torch.int64)
    stops = q24 <= 0
    stops = torch.cat((stops[:, :-1], torch.ones_like(stops[:, -1:])), 1)
    indices = stops.to(torch.int64).argmax(1)
    correct = correctness.gather(1, indices[:, None]).squeeze(1)
    reads = indices + 1
    utility = correct - prices * reads
    return {"correct": correct, "reads": reads, "utility": utility,
            "zero_q24": q24 == 0, "chosen_index": indices}
