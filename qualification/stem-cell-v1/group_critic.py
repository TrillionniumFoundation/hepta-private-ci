"""Frozen one-step correctness critic fitted on disjoint validation groups.

Calibration radii are observed maximum residuals, NOT confidence intervals or
guaranteed future support. No task target enters ``row_features`` or ``predict``.
This is a CPU float32 logistic model, not a general NDU/FBSDE estimator.
"""
import copy
import math
import time

import torch
from torch import nn

from hf_encoder_kernel import head_sha256
from next_round_matrix import _digest


def _features(values, width=None):
    if (not isinstance(values, (list, tuple)) or not 1 <= len(values) <= 32
            or width is not None and len(values) != width
            or any(type(v) not in (float, int) or not math.isfinite(v) or abs(v) > 1e6
                   for v in values)):
        raise ValueError("bounded finite critic features required")
    return [float(v) for v in values]


def row_features(state, logits, step, max_steps):
    """Six observable features; tensors describe one decision, never a target."""
    if (type(step) is not int or type(max_steps) is not int
            or not 1 <= step <= max_steps <= 64):
        raise ValueError("bounded decision step required")
    if (not isinstance(state, torch.Tensor) or not isinstance(logits, torch.Tensor)
            or state.numel() > 8192 or not 1 <= state.numel()
            or not 2 <= logits.numel() <= 256
            or state.ndim > 2 or logits.ndim > 2
            or state.ndim == 2 and state.shape[0] != 1
            or logits.ndim == 2 and logits.shape[0] != 1
            or state.device.type != "cpu" or logits.device.type != "cpu"
            or state.dtype != torch.float32 or logits.dtype != torch.float32
            or not torch.isfinite(state).all() or not torch.isfinite(logits).all()):
        raise ValueError("one finite CPU float32 state and class vector required")
    with torch.no_grad():
        p = logits.detach().reshape(-1).softmax(0)
        ordered = p.sort(descending=True).values
        entropy = -(p * p.clamp_min(1e-12).log()).sum() / math.log(p.numel())
        rms = (state.detach() * state.detach()).mean().sqrt()
        return _features([entropy.item(), (ordered[0] - ordered[1]).item(),
                          ordered[0].item(), rms.item(), step / max_steps,
                          (max_steps - step) / max_steps])


class _Logistic(nn.Module):
    def __init__(self, width, seed):
        super().__init__()
        rng = torch.Generator(device="cpu").manual_seed(seed)
        self.weight = nn.Parameter(torch.empty(width, 2).uniform_(-.05, .05, generator=rng))
        self.bias = nn.Parameter(torch.zeros(2))

    def forward(self, x):
        # Explicit sigmoid uses the existing scalar-equivalent work profile.
        return 1 / (1 + torch.exp(-(torch.mm(x, self.weight) + self.bias)))


class FrozenCritic:
    """Read-only predictor; weight or training-mode substitution rejects."""

    def __init__(self, model, metadata):
        self.model = model.eval().requires_grad_(False)
        self._params_sha256 = head_sha256(model)
        self._metadata = {**metadata, "params_sha256": self._params_sha256}

    @property
    def params_sha256(self):
        return self._params_sha256

    @property
    def metadata(self):
        return copy.deepcopy(self._metadata)

    def assert_frozen(self):
        if (self.model.training or any(p.requires_grad for p in self.model.parameters())
                or head_sha256(self.model) != self._params_sha256):
            raise ValueError("frozen critic artifact changed")

    def predict(self, features):
        self.assert_frozen()
        x = torch.tensor([_features(features, self.model.weight.shape[0])], dtype=torch.float32)
        with torch.no_grad():
            stop, continuation = self.model(x)[0].tolist()
        self.assert_frozen()
        if any(not math.isfinite(p) for p in (stop, continuation)):
            raise ValueError("nonfinite critic prediction")
        a, b = self._metadata["empirical_max_absolute_residual"]
        return {"stop_upper": min(1., stop + a),
                "continue_lower": max(0., continuation - b),
                "stop_probability": stop, "continue_probability": continuation}


def fit_critic(train_rows, calibration_rows, *, cutoff_ns, steps=80, seed=0):
    """Fit two logistic outputs by full-batch SGD; freeze before calibration.

    Both sets must be validation-only and have disjoint source groups. Optional
    row timestamps must not exceed the supplied training/calibration cutoff.
    Timing covers admission, actual optimization, freezing and calibration.
    """
    started_wall, started_cpu = time.perf_counter_ns(), time.process_time_ns()
    if (type(cutoff_ns) is not int or cutoff_ns < 1 or type(steps) is not int
            or not 1 <= steps <= 10000 or type(seed) is not int or not 0 <= seed < 2**63):
        raise ValueError("bounded training protocol and cutoff required")
    admitted, groups, width = [], [], None
    for rows, split in ((train_rows, "validation_fit"),
                        (calibration_rows, "validation_calibration")):
        if not isinstance(rows, (list, tuple)) or not 1 <= len(rows) <= 16384:
            raise ValueError("nonempty bounded validation rows required")
        copied, sources = [], set()
        for row in rows:
            if (not isinstance(row, dict) or row.get("split") != split
                    or type(row.get("stop_success")) is not bool
                    or type(row.get("continue_success")) is not bool):
                raise ValueError("validation-only typed outcome rows required")
            group = row.get("source_group")
            if not isinstance(group, str) or not 1 <= len(group.encode()) <= 256:
                raise ValueError("bounded source group required")
            observed = row.get("observed_at_ns", cutoff_ns)
            if type(observed) is not int or not 0 < observed <= cutoff_ns:
                raise ValueError("critic cannot consume future observations")
            features = _features(row.get("features"), width)
            width = len(features)
            copied.append(dict(features=features, stop_success=row["stop_success"],
                               continue_success=row["continue_success"], split=split,
                               source_group=group, observed_at_ns=observed))
            sources.add(group)
        admitted.append(copied)
        groups.append(sources)
    if groups[0] & groups[1]:
        raise ValueError("critic fit and calibration source groups overlap")
    tensors = [(torch.tensor([r["features"] for r in rows], dtype=torch.float32),
                torch.tensor([[r["stop_success"], r["continue_success"]] for r in rows],
                             dtype=torch.float32)) for rows in admitted]
    model = _Logistic(width, seed)
    x, y = tensors[0]
    initial_sha = head_sha256(model)
    # Exact full-batch logistic-loss gradient; these are real tensor SGD updates.
    with torch.no_grad():
        for _ in range(steps):
            error = (model(x) - y) / len(x)
            model.weight.add_(torch.mm(x.t(), error), alpha=-.1)
            model.bias.add_(error.sum(0), alpha=-.1)
    model.eval().requires_grad_(False)
    with torch.no_grad():
        prediction = model(tensors[1][0])
        radii = (prediction - tensors[1][1]).abs().amax(dim=0).tolist()
    if not all(math.isfinite(v) for v in radii):
        raise ValueError("critic training produced nonfinite parameters")
    metadata = dict(schema="hepta.group.frozen-critic.v1", cutoff_ns=cutoff_ns,
                    feature_width=width, steps=steps, seed=seed,
                    optimizer="full_batch_logistic_sgd_lr_0.1", initial_params_sha256=initial_sha,
                    train_rows=len(admitted[0]), calibration_rows=len(admitted[1]),
                    source_groups={"fit": sorted(groups[0]), "calibration": sorted(groups[1])},
                    rows_sha256=_digest(admitted),
                    empirical_max_absolute_residual=radii,
                    calibration_profile="observed_max_residual_not_future_support.v1",
                    confidence_bound_established=False, future_support_guaranteed=False,
                    trainable_params=sum(p.numel() for p in model.parameters()),
                    training_wall_ns=time.perf_counter_ns() - started_wall,
                    training_cpu_ns=time.process_time_ns() - started_cpu)
    return FrozenCritic(model, metadata)
