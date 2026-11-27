"""Train-fitted output verifier; calibration is not a true-risk guarantee."""

import hashlib
import json
from pathlib import Path
import time

import numpy as np


SCHEMA = "hepta.ndu.generated-output-verifier.v1"
FEATURES = (
    "mean_base_logprob", "min_base_logprob", "mean_controlled_logprob",
    "min_controlled_logprob", "token_count", "unique_box_count",
    "unique_area_sum", "largest_area", "smallest_area",
    "duplicate_count", "invalid_geometry_count", "incomplete_generation",
)
PENALTIES = [1 + FEATURES.index(name) for name in ("duplicate_count", "invalid_geometry_count")]


def _sigmoid(value):
    return 1.0 / (1.0 + np.exp(-np.clip(value, -30, 30)))


def _digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def visible_features(generated):
    """Read only emitted geometry/tokens/probabilities; extra gold keys are ignored."""
    logs = []
    for key in ("base_logprob", "controlled_logprob"):
        values = []
        for step in generated.get("controls", []):
            value = float(step.get(key, -30.0))
            values.append(float(np.clip(value, -30, 0)) if np.isfinite(value) else -30.0)
        values = values or [-30.0]
        logs.extend((float(np.mean(values)) / 30, min(values) / 30))
    unique, seen, duplicate, invalid = [], set(), 0, 0
    for box in generated.get("boxes", []):
        try:
            values = np.asarray(box, dtype=float)
            if values.shape != (4,) or not np.isfinite(values).all():
                raise ValueError("invalid box")
            x1, y1, x2, y2 = values.tolist()
            if not (0 <= x1 < x2 <= 1 and 0 <= y1 < y2 <= 1):
                raise ValueError("invalid geometry")
        except (TypeError, ValueError):
            invalid += 1
            continue
        identity = tuple(np.round(values, 6))
        if identity in seen:
            duplicate += 1
        else:
            seen.add(identity)
            unique.append((x2 - x1) * (y2 - y1))
    return np.asarray(logs + [
        min(max(len(generated.get("tokens", [])) - 1, 0), 64) / 64,
        min(len(unique), 16) / 16, min(sum(unique), 4) / 4,
        max(unique, default=0), min(unique, default=0),
        min(duplicate, 8) / 8, min(invalid, 8) / 8,
        float(generated.get("termination") != "eos"),
    ], dtype=float)


def _rows(records, split, need_quality):
    if not records:
        raise ValueError("verifier needs labelled records")
    if any(row.get("split", split) != split for row in records):
        raise ValueError(f"only {split} records are accepted by this method")
    x = np.stack([visible_features(row["generated"]) for row in records])
    severe = np.asarray([row["severe"] for row in records], dtype=float)
    quality = np.asarray([row["quality"] for row in records], dtype=float) if need_quality else None
    for labels in (severe, quality):
        if labels is not None and (not np.isfinite(labels).all() or ((labels < 0) | (labels > 1)).any()):
            raise ValueError("quality and severe labels must be finite values in [0, 1]")
    return x, quality, severe


class Verifier:
    """Ridge quality regression and regularized logistic severe-error prediction."""

    @classmethod
    def fit(cls, records):
        x, quality, severe = _rows(records, "train", need_quality=True)
        self = cls()
        self.mean = x.mean(0)
        self.scale = np.maximum(x.std(0), 0.05)
        design = np.column_stack((np.ones(len(x)), (x - self.mean) / self.scale))
        ridge = np.eye(design.shape[1])
        ridge[0, 0] = 1e-6
        self.quality_weights = np.linalg.solve(design.T @ design + ridge, design.T @ quality)
        self.quality_weights[PENALTIES] = np.minimum(self.quality_weights[PENALTIES], 0)
        penalty = np.eye(design.shape[1]) * 0.05
        penalty[0, 0] = 1e-4
        weights = np.zeros(design.shape[1])
        for _ in range(40):
            probability = _sigmoid(design @ weights)
            gradient = design.T @ (probability - severe) / len(x) + penalty @ weights
            hessian = (design.T * (probability * (1 - probability))) @ design / len(x) + penalty
            step = np.linalg.solve(hessian, gradient)
            weights -= step
            weights[PENALTIES] = np.maximum(weights[PENALTIES], 0)
            if np.linalg.norm(step) < 1e-8:
                break
        self.severe_weights = weights
        self.train_count = len(records)
        self.train_digest = _digest({"features": x.tolist(), "quality": quality.tolist(), "severe": severe.tolist()})
        self.calibration = {"scale": 1.0, "offset": 0.0, "count": 0, "digest": None}
        return self

    def _design(self, features):
        return np.concatenate(([1.0], (features - self.mean) / self.scale))

    def predict(self, generated):
        started = time.perf_counter()
        features = visible_features(generated)
        design = self._design(features)
        quality = float(np.clip(design @ self.quality_weights, 0, 1))
        logit = float(design @ self.severe_weights)
        probability = float(_sigmoid(self.calibration["scale"] * logit + self.calibration["offset"]))
        return {"quality": quality, "severe_probability": probability,
                "features": dict(zip(FEATURES, features.tolist())),
                "wall_seconds": time.perf_counter() - started}

    def calibrate(self, records):
        """Fit positive Platt scale/offset only, preserving quality and risk ordering."""
        x, _, severe = _rows(records, "calibration", need_quality=False)
        logits = np.asarray([self._design(row) @ self.severe_weights for row in x])
        candidates = []
        for scale in (0.1, 0.25, 0.5, 1.0, 2.0, 4.0, 10.0):
            offset = 0.0
            for _ in range(40):
                probability = _sigmoid(scale * logits + offset)
                gradient = float(np.mean(probability - severe)) + 0.01 * offset
                curvature = float(np.mean(probability * (1 - probability))) + 0.01
                update = float(np.clip(gradient / curvature, -2, 2))
                offset -= update
                if abs(update) < 1e-8:
                    break
            adjusted = scale * logits + offset
            nll = float(np.mean(np.logaddexp(0, adjusted) - severe * adjusted))
            objective = nll + 0.005 * ((scale - 1) ** 2 + offset ** 2)
            candidates.append((objective, scale, offset, nll))
        _, scale, offset, nll = min(candidates)
        self.calibration = {
            "scale": scale, "offset": offset, "count": len(records),
            "digest": _digest({"features": x.tolist(), "severe": severe.tolist()}),
            "pre_nll": float(np.mean(np.logaddexp(0, logits) - severe * logits)),
            "post_nll": nll,
        }
        return dict(self.calibration)

    def save(self, path):
        payload = {
            "schema": SCHEMA, "feature_names": list(FEATURES),
            "mean": self.mean.tolist(), "scale": self.scale.tolist(),
            "quality_weights": self.quality_weights.tolist(), "severe_weights": self.severe_weights.tolist(),
            "train_count": self.train_count, "train_digest": self.train_digest,
            "calibration": self.calibration,
        }
        payload["artifact_sha256"] = _digest(payload)
        Path(path).write_text(json.dumps(payload, sort_keys=True, indent=2, allow_nan=False) + "\n")
        return payload["artifact_sha256"]

    @classmethod
    def load(cls, path):
        payload = json.loads(Path(path).read_text())
        digest = payload.pop("artifact_sha256")
        if _digest(payload) != digest or payload["schema"] != SCHEMA or payload["feature_names"] != list(FEATURES):
            raise ValueError("verifier artifact integrity or feature schema mismatch")
        self = cls()
        for name in ("mean", "scale", "quality_weights", "severe_weights"):
            value = np.asarray(payload[name], dtype=float)
            width = len(FEATURES) + int(name.endswith("weights"))
            if value.shape != (width,) or not np.isfinite(value).all():
                raise ValueError("invalid verifier parameter array")
            setattr(self, name, value)
        if (self.scale <= 0).any() or payload["calibration"]["scale"] <= 0:
            raise ValueError("verifier scales must be positive")
        self.train_count, self.train_digest = payload["train_count"], payload["train_digest"]
        self.calibration = payload["calibration"]
        return self
