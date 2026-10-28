"""Portable, bounded, trained Cell semantic addressing with abstention."""

import base64
import hashlib
import json
from pathlib import Path
import sys
import zlib

import numpy as np

BASE = Path(__file__).resolve().parent.parent / "memory-cell-v5"
sys.path.insert(0, str(BASE))
from v5.contracts import INTENTS, LABELS, REJECT, canonical, normalized_request
from v5.router import decisions_from_scores
from compact_features import Encoder, deterministic_label


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


class CompactRouter:
    def __init__(self, encoder, coefficients, intercept, calibration, identity):
        self.encoder = encoder
        self.coefficients = np.asarray(coefficients, dtype=np.float64)
        self.intercept = np.asarray(intercept, dtype=np.float64)
        self.calibration = calibration
        self.identity = identity

    def scores(self, requests):
        texts = [normalized_request(request) for request in requests]
        return np.asarray(self.encoder.transform(texts) @ self.coefficients.T + self.intercept)

    def decisions(self, requests):
        return decisions_from_scores(self.scores(requests), self.calibration)

    def state(self):
        return {"schema": "hepta.compact-cell-router.v1", "labels": list(LABELS),
            "encoder": self.encoder.descriptor(), "coefficients": self.coefficients.tolist(),
            "intercept": self.intercept.tolist(), "calibration": self.calibration,
            "identity": self.identity}

    def save(self, path):
        raw = canonical(self.state())
        envelope = {"encoding": "zlib-base64", "decoded_bytes": len(raw),
            "decoded_sha256": digest(raw), "payload": base64.b64encode(zlib.compress(raw, 9)).decode("ascii")}
        encoded = canonical(envelope) + b"\n"
        Path(path).write_bytes(encoded)
        return {"bytes": len(encoded), "sha256": digest(encoded),
            "numeric_parameter_bytes": self.coefficients.nbytes + self.intercept.nbytes,
            "encoder_idf_bytes": self.encoder.word.idf_.nbytes if self.encoder.word else 0,
            "feature_dimensions": int(self.coefficients.shape[1]), "decoded_bytes": len(raw)}

    @classmethod
    def load(cls, path, expected_sha256):
        path = Path(path)
        if path.stat().st_size > 2 * 1024 * 1024:
            raise ValueError("artifact exceeds 2 MiB bound")
        encoded = path.read_bytes()
        if digest(encoded) != expected_sha256:
            raise ValueError("artifact does not match frozen identity")
        envelope = json.loads(encoded)
        if envelope["encoding"] != "zlib-base64" or not 0 < envelope["decoded_bytes"] <= 8 * 1024 * 1024:
            raise ValueError("unsupported or excessive model envelope")
        decompressor = zlib.decompressobj()
        raw = decompressor.decompress(base64.b64decode(envelope["payload"], validate=True), envelope["decoded_bytes"] + 1)
        if len(raw) != envelope["decoded_bytes"] or not decompressor.eof or decompressor.unused_data or digest(raw) != envelope["decoded_sha256"]:
            raise ValueError("invalid compressed model identity")
        value = json.loads(raw)
        if value["schema"] != "hepta.compact-cell-router.v1" or value["labels"] != list(LABELS):
            raise ValueError("model contract changed")
        instance = cls(Encoder.restore(value["encoder"]), value["coefficients"], value["intercept"], value["calibration"], value["identity"])
        dimensions = instance.encoder.transform(["[series] [date]"]).shape[1]
        if dimensions > 4096 or instance.coefficients.shape != (len(LABELS), dimensions) or instance.intercept.shape != (len(LABELS),):
            raise ValueError("model dimensions outside contract")
        if not np.isfinite(instance.coefficients).all() or not np.isfinite(instance.intercept).all():
            raise ValueError("model contains nonfinite weights")
        for key in ("minimum_confidence", "minimum_margin"):
            if not 0 <= instance.calibration[key] <= 1:
                raise ValueError("invalid acceptance threshold")
        return instance


def deterministic_decisions(requests):
    decisions = []
    for request in requests:
        label = deterministic_label(normalized_request(request))
        decisions.append({"raw_label": label, "accepted_intent": label if label in INTENTS else None,
            "accepted": label in INTENTS, "confidence": 1.0, "margin": 1.0,
            "reason": "hand-authored finite contract parser; confidence is an indicator, not probability"})
    return decisions
