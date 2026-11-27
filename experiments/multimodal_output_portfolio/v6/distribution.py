"""Bounded public-state location/scale forecasts with empirical residuals.

Scale models out-of-fold prediction error, not a certified aleatoric variance.
The finite law assumes a common standardized residual shape. Neither that
assumption nor conditional/adaptive-policy coverage is guaranteed by calibration.
"""

from copy import deepcopy
import hashlib
import json
from pathlib import Path

import torch

from .data import DIGIT_OFFSET, Observation, VOCAB
from .forecast import ForecastBackend, RidgeHead
from .neural import ACTIONS, parameter_hash
from .observer import METRIC_DIGEST


SCHEMA = "hepta.ndu-v6.heteroskedastic-terminal.v1"
VIEWS = ("clean", "occlusion", "missing", "heavy_noise", "wrong_hint", "missing_no_hint")
PROFILE = {
    "kind": "heteroskedastic_terminal_v1", "source_pair_folds": 4,
    "scale_range": [.02, 2.0], "ridge_regularization": 4.0,
    "views": list(VIEWS), "calibration": "one presampled endpoint per source pair",
    "endpoint_lottery": "uniform view, uniform initialization, uniform registered endpoint",
    "public_features": ["visible_left", "visible_right", "hint_left", "hint_right",
                        "pixel_variation_left", "pixel_variation_right"],
    "forecast_work_units": .5, "public_summary_work_units": .25,
    "common_standardized_shape_assumption": True, "conditional_coverage_claim": False,
}


@torch.inference_mode()
def public_features(observation):
    """Six observable summaries; corruption names and hidden truth are absent."""
    if not isinstance(observation, Observation):
        raise TypeError("Forecast conditioning accepts Observation only")
    pixels, mask = observation.pixels.detach().cpu(), observation.mask.detach().cpu()
    tokens = observation.text_tokens.detach().cpu()
    if (pixels.ndim != 4 or pixels.shape[1:] != (1, 28, 56) or mask.shape != pixels.shape
            or tokens.shape != (len(pixels), 8)):
        raise ValueError("Malformed public multimodal observation")
    if any(not torch.isfinite(value).all() or torch.any((value < 0) | (value > 1)) for value in (pixels, mask)):
        raise ValueError("Public pixels and missingness must be finite in [0,1]")
    visible, variation = [], []
    for start in (0, 28):
        x, m = pixels[..., start:start + 28], mask[..., start:start + 28]
        horizontal, vertical = m[..., 1:] * m[..., :-1], m[:, :, 1:] * m[:, :, :-1]
        numerator = ((x[..., 1:] - x[..., :-1]).abs() * horizontal).flatten(1).sum(1)
        numerator += ((x[:, :, 1:] - x[:, :, :-1]).abs() * vertical).flatten(1).sum(1)
        denominator = horizontal.flatten(1).sum(1) + vertical.flatten(1).sum(1)
        visible.append(m.flatten(1).mean(1))
        variation.append(numerator / denominator.clamp_min(1))
    hint = ((tokens[:, [3, 5]] >= DIGIT_OFFSET) & (tokens[:, [3, 5]] < len(VOCAB))).double()
    return torch.stack((*visible, hint[:, 0], hint[:, 1], *variation), 1).double()


class ConditionalForecastBundle:
    """Frozen two-head terminal law plus a separately fitted public router."""

    public_summary_work = .25

    def __init__(self, utility_head, scale_head, action_head, residuals, snapshot_digest,
                 static_sequence, metric_digest=METRIC_DIGEST):
        self.utility_head, self.scale_head, self.action_head = (
            deepcopy(head).eval().requires_grad_(False) for head in (utility_head, scale_head, action_head))
        self.residuals = residuals.detach().cpu().double().clone().reshape(-1)
        self.snapshot_digest, self.metric_digest = snapshot_digest, metric_digest
        self.static_sequence = tuple(static_sequence)
        if (len(self.utility_head.mean) <= 6 or any(head.mean.shape != self.utility_head.mean.shape
                for head in (self.scale_head, self.action_head))
                or [head.weight.shape[1] for head in (self.utility_head, self.scale_head, self.action_head)] != [1, 1, 4]):
            raise ValueError("Conditional forecast head dimensions differ")
        for head in (self.utility_head, self.scale_head, self.action_head):
            if any(not torch.isfinite(value).all() for value in head.buffers()) or torch.any(head.scale <= 0):
                raise ValueError("Invalid conditional forecast parameters")
        if (not 2 <= len(self.residuals) <= 256 or not torch.isfinite(self.residuals).all()
                or self.residuals.abs().max() > 100 + 1e-10):
            raise ValueError("Invalid bounded standardized residual support")
        if any(action not in ACTIONS for action in self.static_sequence):
            raise ValueError("Invalid fixed continuation action")
        self.fingerprint = self._digest()

    def _digest(self):
        digest = hashlib.sha256(json.dumps({"schema": SCHEMA, "profile": PROFILE,
            "snapshot": self.snapshot_digest, "metric": self.metric_digest,
            "static_sequence": self.static_sequence}, sort_keys=True).encode())
        for head in (self.utility_head, self.scale_head, self.action_head):
            digest.update(parameter_hash(head).encode())
        digest.update(self.residuals.numpy().tobytes())
        return digest.hexdigest()

    def verify_integrity(self):
        if self._digest() != self.fingerprint:
            raise RuntimeError("Frozen conditional forecast changed")
        return self.fingerprint

    def location_scale(self, features):
        mean = self.utility_head(features).squeeze(1).clamp(-1, 1)
        scale = self.scale_head(features).squeeze(1).clamp(.02, 2)
        return mean, scale

    def scenarios(self, features):
        mean, scale = self.location_scale(features)
        return (mean[:, None] + scale[:, None] * self.residuals[None, :]).clamp(-1, 1)

    def backend(self, snapshot, context_id, observation=None):
        return ConditionalForecastBackend(snapshot, self, context_id, observation)

    def save(self, path):
        self.verify_integrity()
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        record = {"schema": SCHEMA, "profile": PROFILE, "features": len(self.utility_head.mean),
                  "heads": {name: getattr(self, name).state_dict() for name in
                            ("utility_head", "scale_head", "action_head")},
                  "residuals": self.residuals, "snapshot_digest": self.snapshot_digest,
                  "metric_digest": self.metric_digest, "static_sequence": self.static_sequence,
                  "fingerprint": self.fingerprint}
        temporary = path.with_suffix(path.suffix + ".tmp")
        torch.save(record, temporary)
        temporary.replace(path)
        return self.fingerprint

    @classmethod
    def from_record(cls, record):
        if record.get("schema") != SCHEMA or record.get("profile") != PROFILE:
            raise ValueError("Unsupported conditional forecast schema or profile")
        heads = [RidgeHead(record["features"], count) for count in (1, 1, 4)]
        for head, name in zip(heads, ("utility_head", "scale_head", "action_head")):
            head.load_state_dict(record["heads"][name], strict=True)
        bundle = cls(*heads, record["residuals"], record["snapshot_digest"],
                     record["static_sequence"], record["metric_digest"])
        if bundle.fingerprint != record["fingerprint"]:
            raise ValueError("Conditional forecast fingerprint mismatch")
        return bundle


class ConditionalForecastBackend(ForecastBackend):
    def __init__(self, snapshot, forecast, context_id, observation):
        super().__init__(snapshot, forecast, context_id)
        summaries = public_features(observation)
        if len(summaries) != 1:
            raise ValueError("One public input per controller episode is required")
        self.public_summary = tuple(summaries[0].tolist())
        self._summary_digest = hashlib.sha256(repr(self.public_summary).encode()).hexdigest()

    def identity(self, state):
        if hashlib.sha256(repr(self.public_summary).encode()).hexdigest() != self._summary_digest:
            raise RuntimeError("Public forecast conditioning changed")
        return super().identity(state) + ":" + self._summary_digest

    def _features(self, state):
        self.identity(state)
        return torch.cat((self.snapshot.state_features(state).double(),
                          torch.tensor([self.public_summary], dtype=torch.float64)), 1)

    @torch.inference_mode()
    def predict(self, state):
        values = self.forecast.scenarios(self._features(state))
        return values[0].tolist(), [1 / values.shape[1]] * values.shape[1]

    @torch.inference_mode()
    def router(self, state, admissible_actions):
        if any(action not in ACTIONS for action in admissible_actions):
            raise ValueError("Unknown public routing action")
        gains = self.forecast.action_head(self._features(state))[0].tolist()
        gain, action = max(((gains[ACTIONS.index(a)], a) for a in admissible_actions),
                           default=(0., None), key=lambda item: item[0])
        return action if gain > 0 else None

    def prediction_cost(self, state):
        self._guard_active()
        return .5
