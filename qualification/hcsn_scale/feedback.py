"""Bounded marked-content controls and physical-duration feature pooling.

The content summary includes active and refractory cohorts, excludes escaped
mass, and is not normalized by surviving mass. Thus each coordinate stays in
[-1, 1], including when the live population vanishes. The feedback sees the
previous state; the current observation is written by the flow only afterwards.
"""

import math

import torch
from torch import nn


FEEDBACK_MODES = {
    "none": (0, 0, 0),
    "drift": (1, 0, 0),
    "boundary": (0, 1, 0),
    "reward": (0, 0, 1),
    "all": (1, 1, 1),
}
FEATURE_BANKS = ("same_generator", "drop_value_risk", "ordinary_tanh")
POOLING_MODES = ("legacy", "exposure")


class ContentFeedback(nn.Module):
    """Map previous bounded marks to drift/boundary logits and a reward gain."""

    def __init__(self, width, mode, gain):
        super().__init__()
        if mode not in FEEDBACK_MODES or not math.isfinite(gain) or not 0 < gain <= 4:
            raise ValueError(
                "declared feedback mode and bounded positive gain required"
            )
        self.gain = gain
        self.projection = nn.Linear(width, 3, bias=False)
        # The ablation switch belongs to config, not transferred trainable state.
        self.register_buffer(
            "routes",
            torch.tensor(FEEDBACK_MODES[mode], dtype=torch.float64),
            persistent=False,
        )

    def forward(self, state, inputs):
        if state is None:
            content = inputs.new_zeros(len(inputs), self.projection.in_features)
        else:
            content = state.density[:, 1:, :-1].sum(-1).to(inputs)
            if content.shape != (len(inputs), self.projection.in_features):
                raise ValueError("feedback must match the complete marked state")
        return self.gain * self.projection(content).tanh() * self.routes.to(inputs)


def select_feature_bank(features, ordinary, names, bank):
    """Keep feature width fixed; all arms pay for the complete flow computation.

    The ordinary controls reuse the existing input drive/boundary maps, so this
    readout ablation introduces no extra parameters. It is not a standalone RNN.
    """
    if bank not in FEATURE_BANKS:
        raise ValueError("unknown feature bank")
    if bank == "same_generator":
        return features
    columns = [
        names.index("risk" if "risk" in names else "first_event_probability"),
        names.index("call" if "call" in names else "continuation_value"),
    ]
    output = features.clone()
    output[:, columns] = 0 if bank == "drop_value_risk" else ordinary.tanh()
    return output


def pool_features(values, intervals, names, mode):
    """Last/pooled features with interval increments expressed per second.

    Exposure pooling sums event/mark increments over physical time and weights
    state observables by duration. Sum(interval first-hit probability)/total time
    is an exposure statistic, not an instantaneous hazard or a window first-hit
    probability. Endpoint quadrature is not exactly subdivision invariant.
    """
    dt = torch.as_tensor(intervals, dtype=values.dtype, device=values.device)
    if (
        mode not in POOLING_MODES
        or values.ndim != 2
        or len(values) < 1
        or values.shape[1] != len(names)
        or dt.shape != (len(values),)
        or not bool(torch.isfinite(values).all())
        or not bool(torch.isfinite(dt).all())
        or bool((dt <= 0).any())
    ):
        raise ValueError(
            "finite features and positive matching physical intervals required"
        )
    if mode == "legacy":
        return torch.cat((values[-1], values.mean(0)))
    total = dt.sum()
    last = values[-1].clone()
    average = (values * dt[:, None]).sum(0) / total
    increments = [
        i
        for i, name in enumerate(names)
        if name in ("event", "expected_event_count")
        or name.startswith(("content_", "marked_event_count_"))
    ]
    last[increments] = values[-1, increments] / dt[-1]
    average[increments] = values[:, increments].sum(0) / total
    # Interval first-hit probabilities are not additive counts. This is only
    # a declared exposure summary and changes when interval boundaries change.
    risk = [
        i for i, name in enumerate(names) if name in ("risk", "first_event_probability")
    ]
    last[risk] = values[-1, risk] / dt[-1]
    average[risk] = values[:, risk].sum(0) / total
    return torch.cat((last, average))


def pooled_feature_names(names, mode):
    if mode == "legacy":
        return [f"{pool}.{name}" for pool in ("last", "mean") for name in names]
    renamed = []
    for name in names:
        if name in ("event", "expected_event_count"):
            name = "expected_event_rate_per_second"
        elif name.startswith(("content_", "marked_event_count_")):
            name = "marked_event_rate_per_second_" + name.rsplit("_", 1)[1]
        elif name in ("risk", "first_event_probability"):
            name = "interval_first_hit_exposure_per_second"
        renamed.append(name)
    return [f"{pool}.{name}" for pool in ("last", "duration_pool") for name in renamed]
