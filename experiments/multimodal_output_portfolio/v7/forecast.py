"""Action-conditioned categorical utilities, independent of inference truth.

The categorical shape varies with public state and the declared continuation.
Risk-neutral and entropic controllers consume the same probabilities. A finite
family calibration radius is a separate diagnostic; it does not turn these
estimates into a general dynamically calibrated FBSDE solution.
"""

from copy import deepcopy
from dataclasses import asdict, dataclass
import hashlib
from itertools import product
import math
from pathlib import Path

import torch
from torch import nn

from ..v6.neural import ACTIONS, parameter_hash, read_checkpoint
from .metric import MetricContract
from .model import State, observation_digest, validate_observation
from .plans import ControlledState
from .sources import canonical, digest, is_digest


SCHEMA = "hepta.ndu-v7.categorical-forecast.v1"
CONTINUATIONS = ((),) + tuple((action,) for action in ACTIONS) + tuple(product(ACTIONS, repeat=2))
PUBLIC_DIM = 9
FEATURE_DIM = 384 + PUBLIC_DIM + 5 + 1


def public_summary(observation):
    validate_observation(observation)
    mask = observation.mask.reshape(-1, 28, 56)
    pixels = observation.pixels.reshape(-1, 28, 56)
    visibility = torch.stack((mask[:, :, :28].mean((1, 2)), mask[:, :, 28:].mean((1, 2))), 1)
    variation = torch.stack((pixels[:, :, :28].std((1, 2), unbiased=False),
                             pixels[:, :, 28:].std((1, 2), unbiased=False)), 1)
    hint_present = (observation.text_tokens[:, (3, 5)] >= 14).float()
    reliable = (observation.text_tokens[:, (2, 4)] != 11).float()
    command = (observation.text_tokens[:, 1:2] - 9).float()
    return torch.cat((visibility, variation, hint_present, reliable, command), 1)


def state_features(state, summary):
    if not isinstance(state, (State, ControlledState)):
        raise TypeError("Forecast accepts generation state, never Target")
    neural = state.neural if isinstance(state, ControlledState) else state
    if (type(neural.step_count) is not int or not 0 <= neural.step_count <= 4
            or type(neural.content_control) is not bool or not is_digest(neural.source_digest)
            or summary.shape != (len(neural.h), PUBLIC_DIM)):
        raise ValueError("Invalid forecast state/summary profile")
    values = [getattr(neural, name) for name in ("h", "image", "text", "context")]
    if any(value.dtype != torch.float32 or value.shape != (len(neural.h), 96)
           or not torch.isfinite(value).all() for value in values):
        raise ValueError("Forecast state must contain four finite float32 blocks")
    step = torch.zeros(len(neural.h), 5)
    step[:, neural.step_count] = 1
    control = torch.full((len(neural.h), 1), float(neural.content_control))
    return torch.cat((*values, summary, step, control), 1)


class DistributionHead(nn.Module):
    def __init__(self, hidden=96, bins=201):
        super().__init__()
        if hidden != 96 or bins != 201:
            raise ValueError("Unregistered categorical distribution shape")
        self.config = {"hidden": hidden, "bins": bins, "features": FEATURE_DIM,
                       "continuations": CONTINUATIONS}
        self.net = nn.Sequential(nn.Linear(FEATURE_DIM, hidden), nn.Tanh(),
                                 nn.Linear(hidden, len(CONTINUATIONS) * bins))

    def forward(self, features):
        return self.net(features).reshape(-1, len(CONTINUATIONS), self.config["bins"])


@dataclass(frozen=True)
class BoundObservation:
    """Local immutable cache, not an external authorization credential."""

    forecast_digest: str
    snapshot_digest: str
    public_digest: str
    summary: tuple[tuple[float, ...], ...]


class CategoricalForecast:
    """Frozen runtime artifact: no scorer, target, corpus, or training rows."""

    def __init__(self, head, snapshot_digest, metric_contract, *, temperature=1., calibration=None, metadata=None):
        if (not is_digest(snapshot_digest) or not math.isfinite(temperature)
                or not .25 <= temperature <= 4. or type(head) is not DistributionHead
                or (metric_contract.utility_min, metric_contract.utility_max) != (-1., 1.)):
            raise ValueError("Invalid categorical forecast identity/configuration")
        self._head = deepcopy(head).cpu().eval().requires_grad_(False)
        self.snapshot_digest = snapshot_digest
        self.metric_contract = metric_contract
        self.contract_digest = metric_contract.validate()
        self.metric_digest = metric_contract.metric_sha256
        self.temperature = float(temperature)
        self.calibration = deepcopy(calibration or {})
        self.metadata = deepcopy(metadata or {})
        self._parameter_sha256 = parameter_hash(self._head)
        self.profile = {"schema": SCHEMA, "snapshot_digest": snapshot_digest,
                        "metric_contract": asdict(metric_contract), "temperature": self.temperature,
                        "head_config": deepcopy(head.config), "calibration": self.calibration,
                        "forecast_metric_mask": metric_contract.forecast_metric_mask,
                        "required_output_mask": metric_contract.required_output_mask,
                        "predict_model_calls": 1, "public_summary_model_calls": 0,
                        "risk_quantization_step": (metric_contract.utility_max - metric_contract.utility_min) / 200,
                        "native_prediction": "stop_now_endpoint_distribution",
                        "amortized_prediction": "all_registered_0_to_2_step_continuations"}
        self._profile_sha256 = digest(self.profile)
        self.fingerprint = digest({"schema": SCHEMA, "parameters": self._parameter_sha256,
                                   "profile": self._profile_sha256})

    def _check_configuration(self):
        if (digest(self.profile) != self._profile_sha256 or self.temperature != self.profile["temperature"]
                or self.snapshot_digest != self.profile["snapshot_digest"]
                or self._head.config != self.profile["head_config"]
                or self.metric_contract.validate() != self.contract_digest
                or self.metric_digest != self.metric_contract.metric_sha256):
            raise RuntimeError("Categorical forecast configuration changed")

    def verify_integrity(self):
        self._check_configuration()
        if (parameter_hash(self._head) != self._parameter_sha256
                or self.fingerprint != digest({"schema": SCHEMA, "parameters": self._parameter_sha256,
                                                "profile": self._profile_sha256})):
            raise RuntimeError("Categorical forecast parameters/identity changed")
        return self.fingerprint

    @torch.inference_mode()
    def bind_observation(self, public_observation):
        self._check_configuration()
        summary = public_summary(public_observation)
        return BoundObservation(self.fingerprint, self.snapshot_digest,
                                 observation_digest(public_observation),
                                 tuple(tuple(row) for row in summary.tolist()))

    @torch.inference_mode()
    def all_plan_distributions_bound(self, state, binding):
        self._check_configuration()
        if not isinstance(state, (State, ControlledState)) or state.snapshot_digest != self.snapshot_digest:
            raise ValueError("Forecast belongs to a different frozen generator")
        if (not isinstance(binding, BoundObservation) or binding.forecast_digest != self.fingerprint
                or binding.snapshot_digest != self.snapshot_digest or state.source_digest != binding.public_digest):
            raise ValueError("Forecast binding belongs to different public input bytes")
        features = state_features(state, torch.tensor(binding.summary, dtype=torch.float32))
        probabilities = (self._head(features).double() / self.temperature).softmax(-1)
        values = torch.linspace(self.metric_contract.utility_min, self.metric_contract.utility_max,
                                self._head.config["bins"], dtype=torch.float64)
        return values, probabilities

    @torch.inference_mode()
    def all_plan_distributions(self, state, public_observation):
        return self.all_plan_distributions_bound(state, self.bind_observation(public_observation))

    @torch.inference_mode()
    def predict(self, state, public_observation):
        return self.predict_bound(state, self.bind_observation(public_observation))

    @torch.inference_mode()
    def predict_bound(self, state, binding):
        values, probabilities = self.all_plan_distributions_bound(state, binding)
        if len(probabilities) != 1:
            raise ValueError("Native endpoint forecast requires exactly one owned state")
        return tuple(values.tolist()), tuple(probabilities[0, 0].tolist())

    def save(self, path):
        self.verify_integrity()
        record = {"schema": SCHEMA, "state_dict": self._head.state_dict(), "head_config": self._head.config,
                  "snapshot_digest": self.snapshot_digest, "metric_contract": asdict(self.metric_contract),
                  "temperature": self.temperature, "calibration": self.calibration, "metadata": self.metadata,
                  "parameter_sha256": self._parameter_sha256, "fingerprint": self.fingerprint}
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(path.suffix + ".tmp")
        torch.save(record, temporary)
        temporary.replace(path)
        return hashlib.sha256(path.read_bytes()).hexdigest()

    @classmethod
    def load(cls, path, *, expected_file_sha256=None):
        record = read_checkpoint(path, expected_file_sha256)
        if record.get("schema") != SCHEMA:
            raise ValueError("Unsupported categorical forecast schema")
        config = record["head_config"]
        head = DistributionHead(config["hidden"], config["bins"])
        if head.config != config:
            raise ValueError("Forecast feature/continuation registration changed")
        head.load_state_dict(record["state_dict"], strict=True)
        contract = MetricContract(**record["metric_contract"])
        result = cls(head, record["snapshot_digest"], contract, temperature=record["temperature"],
                     calibration=record["calibration"], metadata=record["metadata"])
        if result.fingerprint != record["fingerprint"] or result._parameter_sha256 != record["parameter_sha256"]:
            raise ValueError("Categorical forecast checkpoint identity mismatch")
        return result


def certainty_equivalent(values, probabilities, gamma=2.):
    if not math.isfinite(gamma) or gamma < 0:
        raise ValueError("Risk aversion must be finite and nonnegative")
    if gamma == 0:
        return (probabilities * values).sum(-1)
    if gamma < 1e-4:
        mean = (probabilities * values).sum(-1)
        centered = values - mean.unsqueeze(-1)
        return mean - torch.log1p((probabilities * torch.expm1(-gamma * centered)).sum(-1)) / gamma
    return -torch.logsumexp(probabilities.log() - gamma * values, -1) / gamma
