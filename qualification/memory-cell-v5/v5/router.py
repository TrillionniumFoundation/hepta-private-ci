"""Learned n-gram router with explicit numerical artifacts and no target table."""

from dataclasses import dataclass
import io
import json
from pathlib import Path

import numpy as np

from .artifacts import bounded_decompress, compressed_json, load_payload, store_payload
from .config import NEGATIVE_TRAINING_FAMILIES
from .contracts import INTENTS, LABELS, REJECT, canonical, file_identity, normalized_request, sha256, write_json
from .features import FeatureBlock, combine


def softmax(scores):
    shifted = scores - scores.max(axis=1, keepdims=True)
    values = np.exp(shifted)
    return values / values.sum(axis=1, keepdims=True)


def decisions_from_scores(scores, calibration):
    scores = np.asarray(scores, dtype=np.float64)
    if scores.ndim != 2 or scores.shape[1] != len(LABELS) or not np.isfinite(scores).all():
        raise ValueError("router scores must be finite rows over the declared labels")
    probabilities = softmax(scores)
    order = np.argsort(-probabilities, axis=1, kind="stable")
    output = []
    for index, row in enumerate(probabilities):
        top, second = (int(x) for x in order[index, :2])
        confidence = float(row[top])
        margin = float(row[top] - row[second])
        raw = LABELS[top]
        accepted = (
            raw != REJECT
            and not calibration["reject_all"]
            and confidence >= calibration["minimum_confidence"]
            and margin >= calibration["minimum_margin"]
        )
        output.append({
            "raw_label": raw,
            "accepted_intent": raw if accepted else None,
            "accepted": bool(accepted),
            "confidence": confidence,
            "margin": margin,
            "normalized_scores": [float(x) for x in row],
            "linear_scores": [float(x) for x in scores[index]],
            "reason": "accepted" if accepted else "learned-reject-class" if raw == REJECT else "selection-calibrated-abstention",
        })
    return output


@dataclass
class Router:
    blocks: list
    coefficients: np.ndarray
    intercept: np.ndarray
    calibration: dict
    candidate: dict
    training_identity: dict
    model_labels: tuple = LABELS

    def model_scores(self, requests):
        if not requests:
            raise ValueError("empty serving batch")
        texts = [normalized_request(row) for row in requests]
        matrix = combine([block.transform(texts) for block in self.blocks])
        return np.asarray(matrix @ self.coefficients.T + self.intercept, dtype=np.float64)

    def canonical_scores(self, model_scores):
        if self.model_labels == LABELS:
            return model_scores
        return np.column_stack([model_scores[:, :len(INTENTS)], model_scores[:, len(INTENTS):].max(axis=1)])

    def scores(self, requests):
        return self.canonical_scores(self.model_scores(requests))

    def decisions(self, requests):
        model_scores = self.model_scores(requests)
        decisions = decisions_from_scores(self.canonical_scores(model_scores), self.calibration)
        for index, decision in enumerate(decisions):
            decision["score_kind"] = "multinomial-logistic-softmax" if self.candidate["learner"] == "logistic" else "normalized-svm-scores-not-calibrated-probabilities"
            if self.model_labels != LABELS:
                decision["score_kind"] = "negative-subclass-max-mapped-normalized-scores-not-calibrated-probabilities"
                decision["model_label"] = self.model_labels[int(np.argmax(model_scores[index]))]
                decision["model_labels"] = list(self.model_labels)
                decision["model_linear_scores"] = [float(value) for value in model_scores[index]]
        return decisions

    def numeric_parameter_bytes(self):
        return int(self.coefficients.nbytes + self.intercept.nbytes + sum(block.model.idf_.nbytes for block in self.blocks))

    def save(self, directory):
        path = Path(directory)
        path.mkdir(parents=True, exist_ok=False)
        arrays = {"coefficients": self.coefficients, "intercept": self.intercept}
        for block in self.blocks:
            arrays["idf_" + block.name] = np.asarray(block.model.idf_, dtype=np.float64)
        archive = io.BytesIO()
        np.savez_compressed(archive, **arrays)
        weights = store_payload(path, "weights.npz", archive.getvalue())
        features = compressed_json(path, "features.json.zlib", {
            "schema": "memory-cell-v5.tfidf-features.v1",
            "normalization": "NFKC,casefold,explicit-series-and-date-replacement,whitespace",
            "blocks": [block.descriptor() for block in self.blocks],
            "block_scale": len(self.blocks) ** -0.5,
        })
        manifest = {
            "schema": "memory-cell-v5.learned-router.v1",
            "labels": list(LABELS),
            "model_labels": list(self.model_labels),
            "negative_subclass_mapping": "maximum-score-then-unified-reject" if self.model_labels != LABELS else "single-reject-class",
            "candidate": self.candidate,
            "calibration": self.calibration,
            "training_identity": self.training_identity,
            "numeric_parameter_bytes": self.numeric_parameter_bytes(),
            "feature_dimensions": self.coefficients.shape[1],
            "payloads": {"weights": weights, "features": features},
            "files": {**weights["files"], **features["files"]},
            "raw_training_examples_present": False,
            "answer_table_present": False,
            "pretrained_encoder_bytes": 0,
            "scope": "new-V5-author-synthetic-routing-study; not reconstructed V4 source",
        }
        write_json(path / "manifest.json", manifest)
        files = {name: file_identity(path / name) for name in (*manifest["files"], "manifest.json")}
        return {"files": files, "bytes": sum(x["bytes"] for x in files.values()), "parameter_bytes": self.numeric_parameter_bytes()}

    @classmethod
    def load(cls, directory, expected_manifest_sha256=None):
        path = Path(directory)
        for name in ("manifest.json",):
            item = path / name
            if item.is_symlink() or not item.is_file() or item.stat().st_size > 16000000:
                raise ValueError("missing, linked or oversized router artifact")
        raw = (path / "manifest.json").read_bytes()
        if expected_manifest_sha256 is not None and sha256(raw) != expected_manifest_sha256:
            raise ValueError("router manifest differs from its external binding")
        manifest = json.loads(raw)
        if manifest["schema"] != "memory-cell-v5.learned-router.v1" or manifest["labels"] != list(LABELS):
            raise ValueError("router schema or labels differ")
        model_labels = tuple(manifest.get("model_labels", LABELS))
        subclass_labels = (*INTENTS, *(REJECT + "::" + family for family in NEGATIVE_TRAINING_FAMILIES))
        if model_labels not in (LABELS, subclass_labels):
            raise ValueError("undeclared learned model labels")
        expected_mapping = "maximum-score-then-unified-reject" if model_labels != LABELS else "single-reject-class"
        if manifest.get("negative_subclass_mapping", "single-reject-class") != expected_mapping:
            raise ValueError("learned model label mapping differs")
        payloads = manifest["payloads"]
        if set(payloads) != {"weights", "features"} or manifest["files"] != {**payloads["weights"]["files"], **payloads["features"]["files"]}:
            raise ValueError("router artifact inventory differs")
        weights_raw = load_payload(path, "weights.npz", payloads["weights"])
        features_raw = bounded_decompress(load_payload(path, "features.json.zlib", payloads["features"]), 8000000)
        if len(features_raw) != payloads["features"]["uncompressed_bytes"] or sha256(features_raw) != payloads["features"]["uncompressed_sha256"]:
            raise ValueError("decompressed feature identity differs")
        features = json.loads(features_raw)
        if features["schema"] != "memory-cell-v5.tfidf-features.v1":
            raise ValueError("feature schema differs")
        with np.load(io.BytesIO(weights_raw), allow_pickle=False) as stored:
            arrays = {name: stored[name] for name in stored.files}
        expected_arrays = {"coefficients", "intercept"} | {block["idf_array"] for block in features["blocks"]}
        if set(arrays) != expected_arrays:
            raise ValueError("numeric artifact inventory differs")
        blocks = [FeatureBlock.load(block, arrays) for block in features["blocks"]]
        if len(blocks) not in (1, 2) or features["block_scale"] != len(blocks) ** -0.5:
            raise ValueError("feature block scale differs")
        nfeatures = sum(len(block.model.vocabulary_) for block in blocks)
        coefficients, intercept = arrays["coefficients"], arrays["intercept"]
        if coefficients.shape != (len(model_labels), nfeatures) or intercept.shape != (len(model_labels),):
            raise ValueError("numeric parameter shapes differ")
        if any(array.dtype != np.float64 or not np.isfinite(array).all() for array in (coefficients, intercept)):
            raise ValueError("invalid parameter values or precision")
        calibration = manifest["calibration"]
        if set(calibration) != {"minimum_confidence", "minimum_margin", "reject_all"}:
            raise ValueError("invalid calibration fields")
        if type(calibration["reject_all"]) is not bool or any(not 0 <= calibration[key] <= 1 for key in ("minimum_confidence", "minimum_margin")):
            raise ValueError("calibration outside bounds")
        router = cls(blocks, coefficients, intercept, calibration, manifest["candidate"], manifest["training_identity"], model_labels)
        if router.numeric_parameter_bytes() != manifest["numeric_parameter_bytes"] or nfeatures != manifest["feature_dimensions"]:
            raise ValueError("numeric cost receipt differs from artifact")
        return router


def parameter_digest(router):
    state = {
        "coef": sha256(router.coefficients.tobytes()),
        "intercept": sha256(router.intercept.tobytes()),
        "idf": [sha256(block.model.idf_.tobytes()) for block in router.blocks],
        "calibration": router.calibration,
    }
    if router.model_labels != LABELS:
        state["model_labels"] = list(router.model_labels)
    return sha256(canonical(state))
