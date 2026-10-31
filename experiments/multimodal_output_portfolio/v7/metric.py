"""Offline endpoint labels with a pinned, explicit modality/metric contract.

Inference artifacts serialize the contract, never the labeler, observer or Target.
Four-modality callers may register their own frozen actual-output callback; they
must state whether it verifies quantized media payloads or full codec containers.
"""

from dataclasses import asdict, dataclass
import math

import torch

from ..v6.data import render_tokens
from ..v6.neural import parameter_hash
from ..v6.observer import METRIC_DIGEST, observe_tensors
from ..v6.plan_training import _png_roundtrip
from .sources import digest, is_digest


@dataclass(frozen=True)
class MetricContract:
    name: str
    required_output_mask: int
    forecast_metric_mask: int
    utility_min: float
    utility_max: float
    metric_sha256: str
    producer_pins: tuple[tuple[str, str], ...]
    verification_level: str

    def validate(self):
        if (not isinstance(self.name, str) or not self.name
                or type(self.required_output_mask) is not int or type(self.forecast_metric_mask) is not int
                or self.required_output_mask not in range(1, 16)
                or self.forecast_metric_mask not in range(1, 16)
                or self.forecast_metric_mask & self.required_output_mask != self.forecast_metric_mask
                or not math.isfinite(self.utility_min) or not math.isfinite(self.utility_max)
                or self.utility_min >= self.utility_max or not is_digest(self.metric_sha256)
                or not self.producer_pins or len(dict(self.producer_pins)) != len(self.producer_pins)
                or any(not name or not is_digest(pin) for name, pin in self.producer_pins)
                or self.verification_level not in {"raw_png_utf8", "quantized_media_payloads", "full_codec_containers"}):
            raise ValueError("Invalid registered endpoint metric contract")
        return digest(asdict(self))


class EndpointLabeler:
    """Training-side-only callback. Its integrity hook covers frozen producers."""

    def __init__(self, contract, callback, integrity):
        self.contract = contract
        self.contract_sha256 = contract.validate()
        self._callback, self._integrity = callback, integrity
        self._integrity()

    def verify_integrity(self):
        if self.contract.validate() != self.contract_sha256:
            raise RuntimeError("Metric contract changed")
        self._integrity()

    def label(self, snapshot, state, target):
        self.verify_integrity()
        result = self._callback(snapshot, state, target)
        if len(result) != len(snapshot.state_features(state)):
            raise ValueError("Endpoint label cardinality mismatch")
        for item in result:
            utility = item.get("utility")
            if (not isinstance(utility, (float, int)) or not math.isfinite(utility)
                    or not self.contract.utility_min <= utility <= self.contract.utility_max
                    or not isinstance(item.get("raw_sha256"), dict) or not item["raw_sha256"]
                    or any(not is_digest(pin) for pin in item["raw_sha256"].values())):
                raise ValueError("Missing or out-of-contract actual-output utility")
        self.verify_integrity()
        return result


def text_image_labeler(observer, *, observer_file_sha256):
    """Actual autoregressive UTF-8 and PNG encode/decode; no grammar repair."""
    observer_hash = parameter_hash(observer)
    contract = MetricContract("strict_mnist_pair_text_image", 3, 3, -1., 1., METRIC_DIGEST,
                              (("observer_parameters", observer_hash),
                               ("observer_file", observer_file_sha256)), "raw_png_utf8")

    def integrity():
        if (observer.training or any(p.requires_grad for p in observer.parameters())
                or parameter_hash(observer) != observer_hash):
            raise RuntimeError("Training endpoint observer is not independently frozen")

    def callback(snapshot, state, target):
        output = snapshot.decode(state)
        pixels, png_hashes = _png_roundtrip(output.image_logits.sigmoid())
        captions = [render_tokens(tokens).encode("utf-8").decode("utf-8") for tokens in output.token_ids]
        values = observe_tensors(observer, pixels, captions, target.pixels, target.labels)
        import hashlib
        return [dict(value, raw_sha256={"image": png_hash, "text": hashlib.sha256(caption.encode()).hexdigest()})
                for value, png_hash, caption in zip(values, png_hashes, captions)]

    return EndpointLabeler(contract, callback, integrity)
