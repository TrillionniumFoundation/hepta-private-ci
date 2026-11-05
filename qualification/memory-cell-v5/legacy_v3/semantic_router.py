"""Trained semantic routing on whole-utterance features with held selection.

The encoder is external and frozen. No phrase table, task header, key lookup,
target, or oracle type participates in inference. Scope authorization remains
the caller's separate owner check; this classifier does not grant permissions.
"""

from dataclasses import asdict, dataclass
import hashlib
import json
from pathlib import Path
import re
import time

import numpy as np


REJECT = "__reject__"


def canonical(value):
    return json.dumps(
        value,
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def digest(payload):
    return hashlib.sha256(payload).hexdigest()


def strict_json(payload):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("duplicate artifact metadata key")
            result[key] = value
        return result

    return json.loads(payload, object_pairs_hook=unique)


def _matrix(features, dimension=None):
    values = np.asarray(features, dtype=np.float64)
    if (
        values.ndim != 2
        or not 0 < values.shape[1] <= 4096
        or len(values) > 65536
        or not np.isfinite(values).all()
        or (dimension is not None and values.shape[1] != dimension)
    ):
        raise ValueError("invalid bounded semantic feature matrix")
    return values


@dataclass(frozen=True)
class RouteDecision:
    route: str | None
    raw_route: str
    confidence: float
    margin: float
    disposition: str


class SemanticRouter:
    """A small actually optimized softmax model, not a lexical dispatch table."""

    def __init__(self, classes, weights, bias, *, encoder_digest, steps=0):
        self.classes = tuple(classes)
        if (
            not 2 <= len(self.classes) <= 64
            or REJECT not in self.classes
            or len(set(self.classes)) != len(self.classes)
            or any(
                not isinstance(x, str) or not 1 <= len(x) <= 128 for x in self.classes
            )
            or not re.fullmatch(r"[0-9a-f]{64}", encoder_digest)
            or type(steps) is not int
            or not 0 <= steps <= 1000000
        ):
            raise ValueError("invalid semantic router identity")
        self.weights = _matrix(weights).copy()
        self.bias = np.asarray(bias, dtype=np.float64).copy()
        if (
            self.weights.shape[1] != len(self.classes)
            or not 1 <= self.weights.shape[0] <= 4096
            or self.bias.shape != (len(self.classes),)
            or not np.isfinite(self.bias).all()
        ):
            raise ValueError("invalid semantic router parameter shape")
        self.encoder_digest = encoder_digest
        self.steps = steps
        self.threshold = 0.0
        self.margin = 0.0
        self.reject_all = False

    @property
    def parameter_bytes(self):
        return self.weights.nbytes + self.bias.nbytes

    @classmethod
    def fit(
        cls,
        features,
        labels,
        *,
        classes,
        encoder_digest,
        seed,
        steps=400,
        learning_rate=0.03,
        l2=0.001,
    ):
        started = time.perf_counter()
        features = _matrix(features)
        classes = tuple(classes)
        if len(features) != len(labels) or not len(labels):
            raise ValueError("training inputs and routes differ")
        if set(labels) != set(classes):
            raise ValueError("every declared route requires training observations")
        if type(steps) is not int or not 1 <= steps <= 100000:
            raise ValueError("invalid optimizer step count")
        if not 0 < learning_rate <= 1 or not 0 <= l2 <= 1:
            raise ValueError("invalid router optimizer settings")
        y = np.asarray([classes.index(value) for value in labels])
        rng = np.random.default_rng(seed)
        model = cls(
            classes,
            rng.normal(0, 0.01, (features.shape[1], len(classes))),
            np.zeros(len(classes)),
            encoder_digest=encoder_digest,
        )
        initial_digest = digest(model.weights.tobytes() + model.bias.tobytes())
        counts = np.bincount(y, minlength=len(classes))
        sample_weights = 1.0 / counts[y]
        sample_weights /= sample_weights.sum()
        moments = [np.zeros_like(x) for x in (model.weights, model.bias)]
        variances = [np.zeros_like(x) for x in (model.weights, model.bias)]
        losses = []
        for step in range(1, steps + 1):
            probs = model.probabilities(features)
            if step in {1, steps}:
                losses.append(
                    float(
                        -np.sum(
                            sample_weights
                            * np.log(np.maximum(probs[np.arange(len(y)), y], 1e-15))
                        )
                    )
                )
            error = probs.copy()
            error[np.arange(len(y)), y] -= 1
            error *= sample_weights[:, None]
            gradients = (features.T @ error + l2 * model.weights, error.sum(axis=0))
            for parameter, grad, mean, variance in zip(
                (model.weights, model.bias), gradients, moments, variances, strict=True
            ):
                mean *= 0.9
                mean += 0.1 * grad
                variance *= 0.999
                variance += 0.001 * grad * grad
                parameter -= (
                    learning_rate
                    * (mean / (1 - 0.9**step))
                    / (np.sqrt(variance / (1 - 0.999**step)) + 1e-8)
                )
        model.steps = steps
        if not np.isfinite(model.weights).all() or not np.isfinite(model.bias).all():
            raise ValueError("semantic optimizer produced nonfinite parameters")
        final_digest = digest(model.weights.tobytes() + model.bias.tobytes())
        return model, {
            "optimizer": "class-balanced Adam softmax with L2 weights",
            "rows": len(labels),
            "steps": steps,
            "learning_rate": learning_rate,
            "l2": l2,
            "seed": seed,
            "feature_dimension": features.shape[1],
            "parameter_bytes": model.parameter_bytes,
            "first_and_last_preupdate_loss": losses,
            "initial_parameter_digest": initial_digest,
            "final_parameter_digest": final_digest,
            "parameters_changed": initial_digest != final_digest,
            "train_seconds": time.perf_counter() - started,
        }

    def probabilities(self, features):
        values = _matrix(features, self.weights.shape[0])
        logits = values @ self.weights + self.bias
        logits -= logits.max(axis=1, keepdims=True)
        exp = np.exp(logits)
        return exp / exp.sum(axis=1, keepdims=True)

    def decisions(self, features):
        rows = self.probabilities(features)
        result = []
        for row in rows:
            ordered = np.argsort(-row, kind="stable")
            winner = self.classes[int(ordered[0])]
            confidence = float(row[ordered[0]])
            margin = float(row[ordered[0]] - row[ordered[1]])
            reason = "accepted"
            if self.reject_all:
                reason = "selection_risk_fail_closed"
            elif winner == REJECT:
                reason = "learned_reject"
            elif confidence < self.threshold:
                reason = "below_selection_confidence"
            elif margin < self.margin:
                reason = "below_selection_margin"
            result.append(
                RouteDecision(
                    winner if reason == "accepted" else None,
                    winner,
                    confidence,
                    margin,
                    reason,
                )
            )
        return result

    def calibrate(
        self,
        features,
        labels,
        *,
        minimum_known_coverage=0.8,
        maximum_false_accept_rate=0.05,
        partition="selection",
    ):
        """Select only on an explicitly supplied selection fold, never test rows."""
        if partition != "selection":
            raise ValueError("hidden examples cannot calibrate semantic routing")
        if (
            len(features) != len(labels)
            or not labels
            or set(labels) - set(self.classes)
        ):
            raise ValueError("invalid selection labels")
        known = np.asarray([value != REJECT for value in labels])
        if not known.any() or known.all():
            raise ValueError("calibration needs known and unsupported intents")
        if not (
            0 <= minimum_known_coverage <= 1 and 0 <= maximum_false_accept_rate <= 1
        ):
            raise ValueError("invalid calibration constraints")
        probabilities = self.probabilities(features)
        order = np.argsort(-probabilities, axis=1, kind="stable")
        raw = np.asarray([self.classes[int(i)] for i in order[:, 0]])
        score = probabilities[np.arange(len(labels)), order[:, 0]]
        margin = score - probabilities[np.arange(len(labels)), order[:, 1]]
        target = np.asarray(labels)
        records = []
        for threshold in (0.0, 0.35, 0.5, 0.65, 0.8, 0.9, 0.95):
            for minimum_margin in (0.0, 0.05, 0.1, 0.2, 0.3):
                accepted = (
                    (raw != REJECT) & (score >= threshold) & (margin >= minimum_margin)
                )
                correct_known = float(np.mean((accepted & (raw == target))[known]))
                coverage = float(np.mean(accepted[known]))
                false_accept = float(np.mean(accepted[~known]))
                record = {
                    "threshold": threshold,
                    "margin": minimum_margin,
                    "known_correct_accepted_rate": correct_known,
                    "known_coverage": coverage,
                    "unsupported_false_accept_rate": false_accept,
                    "balanced_decision_accuracy": (correct_known + 1 - false_accept)
                    / 2,
                    "constraints_satisfied": correct_known >= minimum_known_coverage
                    and false_accept <= maximum_false_accept_rate,
                }
                records.append(record)
        feasible = [
            row
            for row in records
            if row["unsupported_false_accept_rate"] <= maximum_false_accept_rate
        ]
        selected = max(
            feasible if feasible else records,
            key=lambda x: (
                0 if feasible else -x["unsupported_false_accept_rate"],
                x["known_correct_accepted_rate"],
                -x["threshold"],
                -x["margin"],
            ),
        )
        self.threshold, self.margin = selected["threshold"], selected["margin"]
        self.reject_all = not bool(feasible)
        return {
            "partition": "selection",
            "rows": len(labels),
            "minimum_known_coverage": minimum_known_coverage,
            "coverage_constraint_counts_only_correctly_accepted_known_queries": True,
            "maximum_false_accept_rate": maximum_false_accept_rate,
            "selected": selected,
            "candidates": records,
            "declared_input_partition": partition,
            "selection_order": "OOD risk feasible first; then correct known coverage; then fixed threshold/margin order",
            "risk_feasible": bool(feasible),
            "deployment_reject_all": self.reject_all,
            "selection_unsupported_queries": int((~known).sum()),
            "zero_error_one_sided_95_percent_upper_bound": 1
            - 0.05 ** (1 / int((~known).sum()))
            if selected["unsupported_false_accept_rate"] == 0
            else None,
            "upper_bound_assumes_independent_queries": True,
        }

    def save(self, directory, *, source_commit, support_digest):
        if not re.fullmatch(r"[0-9a-f]{40}", source_commit) or not re.fullmatch(
            r"[0-9a-f]{64}", support_digest
        ):
            raise ValueError("invalid router source binding")
        raw = self.weights.astype("<f8").tobytes() + self.bias.astype("<f8").tobytes()
        manifest = {
            "schema": "memory-cell-v3.semantic-router.v1",
            "classes": list(self.classes),
            "encoder_digest": self.encoder_digest,
            "dimension": self.weights.shape[0],
            "dtype": "float64",
            "steps": self.steps,
            "threshold": self.threshold,
            "margin": self.margin,
            "reject_all": self.reject_all,
            "source_commit": source_commit,
            "support_digest": support_digest,
            "parameter_bytes": len(raw),
            "parameter_sha256": digest(raw),
        }
        manifest["manifest_sha256"] = digest(canonical(manifest))
        path = Path(directory)
        path.mkdir(parents=True, exist_ok=False)
        (path / "weights.bin").write_bytes(raw)
        (path / "manifest.json").write_bytes(canonical(manifest) + b"\n")
        return manifest

    @classmethod
    def load(cls, directory, *, expected_encoder_digest, expected_manifest_digest=None):
        path = Path(directory)
        if path.is_symlink() or not path.is_dir():
            raise ValueError("invalid semantic artifact directory")
        if {x.name for x in path.iterdir()} != {"weights.bin", "manifest.json"}:
            raise ValueError("semantic artifact inventory mismatch")
        for name in ("weights.bin", "manifest.json"):
            if (path / name).is_symlink() or not (path / name).is_file():
                raise ValueError("invalid semantic artifact file")
        if (path / "manifest.json").stat().st_size > 65536:
            raise ValueError("oversized semantic manifest")
        manifest = strict_json((path / "manifest.json").read_bytes())
        required = {
            "schema",
            "classes",
            "encoder_digest",
            "dimension",
            "dtype",
            "steps",
            "threshold",
            "margin",
            "reject_all",
            "source_commit",
            "support_digest",
            "parameter_bytes",
            "parameter_sha256",
            "manifest_sha256",
        }
        if (
            not isinstance(manifest, dict)
            or set(manifest) != required
            or manifest["schema"] != "memory-cell-v3.semantic-router.v1"
            or manifest["encoder_digest"] != expected_encoder_digest
            or manifest["dtype"] != "float64"
            or type(manifest["dimension"]) is not int
            or not 1 <= manifest["dimension"] <= 4096
            or not isinstance(manifest["classes"], list)
            or not 2 <= len(manifest["classes"]) <= 64
            or not isinstance(manifest["source_commit"], str)
            or not re.fullmatch(r"[0-9a-f]{40}", manifest["source_commit"])
            or not isinstance(manifest["support_digest"], str)
            or not re.fullmatch(r"[0-9a-f]{64}", manifest["support_digest"])
            or type(manifest["threshold"]) not in {int, float}
            or type(manifest["margin"]) not in {int, float}
            or type(manifest["reject_all"]) is not bool
            or not 0 <= manifest["threshold"] <= 1
            or not 0 <= manifest["margin"] <= 1
        ):
            raise ValueError("semantic artifact contract mismatch")
        body = {
            key: value for key, value in manifest.items() if key != "manifest_sha256"
        }
        if manifest["manifest_sha256"] != digest(canonical(body)) or (
            expected_manifest_digest is not None
            and manifest["manifest_sha256"] != expected_manifest_digest
        ):
            raise ValueError("semantic artifact manifest digest mismatch")
        count = (manifest["dimension"] + 1) * len(manifest["classes"])
        if (
            manifest["parameter_bytes"] != 8 * count
            or (path / "weights.bin").stat().st_size != 8 * count
        ):
            raise ValueError("semantic parameter length mismatch")
        raw = (path / "weights.bin").read_bytes()
        if digest(raw) != manifest["parameter_sha256"]:
            raise ValueError("semantic parameter digest mismatch")
        values = np.frombuffer(raw, dtype="<f8")
        split = manifest["dimension"] * len(manifest["classes"])
        model = cls(
            manifest["classes"],
            values[:split].reshape(manifest["dimension"], -1),
            values[split:],
            encoder_digest=expected_encoder_digest,
            steps=manifest["steps"],
        )
        model.threshold, model.margin = manifest["threshold"], manifest["margin"]
        model.reject_all = manifest["reject_all"]
        return model, manifest


def decision_records(model, features):
    return [asdict(value) for value in model.decisions(features)]
