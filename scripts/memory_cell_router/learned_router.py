"""Source-utility-fitted lexical routing; no answer lookup or authorization.

The caller owns honest source/selection/final separation and external lifecycle
admission. This model learns a routing decision, not a memory answer, and does
not certify rejection of arbitrary unseen domains or unknown entity names.
"""

import hashlib
import json
import math
import os
from pathlib import Path
import re
import stat
import struct
from types import MappingProxyType

import numpy as np

from router_features import (
    FEATURE_RECIPE,
    checked_config,
    features,
    normalized_question,
)


SCHEMA = "hepta.parametric-memory.learned-router.v2"
MAGIC = b"HEPTA_ROUTER_V2\n"
DECISION_RULE = "expert-support-mass-and-best-versus-reject-v1"
MAX_STATE_BYTES = 2 * 1024 * 1024
MAX_TRAINING_ROWS = 4096


def _canonical(value):
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode()


def _digest(value):
    return type(value) is str and re.fullmatch(r"[0-9a-f]{64}", value) is not None


def _expert_ids(values):
    if (
        type(values) not in (list, tuple)
        or not 2 <= len(values) <= 16
        or any(
            type(value) is not str
            or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}", value) is None
            for value in values
        )
        or len(set(values)) != len(values)
    ):
        raise ValueError("two to sixteen distinct bounded expert identifiers required")
    return tuple(values)


def _softmax(logits):
    values = np.exp(logits - np.max(logits, axis=1, keepdims=True))
    return values / values.sum(axis=1, keepdims=True)


class LearnedRouter:
    """Immutable fitted weights; all public inference input is question text."""

    def __init__(
        self, *, expert_ids, config, source_sha256, training_sha256, training, weights
    ):
        self.expert_ids = _expert_ids(expert_ids)
        self.config = MappingProxyType(checked_config(dict(config)))
        if not _digest(source_sha256) or not _digest(training_sha256):
            raise ValueError("source and training SHA-256 bindings required")
        expected = (self.config["dimension"] + 1, len(self.expert_ids) + 1)
        if weights.shape != expected or not np.isfinite(weights).all():
            raise ValueError(
                "finite router matrix with exact configured shape required"
            )
        self.weights = np.array(weights, dtype="<f4", copy=True)
        self.weights.setflags(write=False)
        self.source_sha256 = source_sha256
        self.training_sha256 = training_sha256
        self.training = json.loads(_canonical(training))

    def predict(self, request):
        if type(request) is not dict or set(request) != {"question"}:
            raise ValueError("router inference accepts question text only")
        vector = features([request["question"]], self.config)
        probabilities = _softmax(vector @ self.weights)[0]
        expert_probabilities = probabilities[:-1]
        ranking = np.argsort(-expert_probabilities, kind="stable")
        top = int(ranking[0])
        expert_confidence = float(expert_probabilities[top])
        confidence = float(expert_probabilities.sum())
        reject_probability = float(probabilities[-1])
        margin = expert_confidence - reject_probability
        expert_margin = expert_confidence - float(expert_probabilities[ranking[1]])
        if reject_probability >= expert_confidence:
            reason = "learned_reject"
        elif confidence < self.config["min_confidence"]:
            reason = "low_support_confidence"
        elif margin < self.config["min_margin"]:
            reason = "low_support_margin"
        else:
            reason = "routed"
        slot = top if reason == "routed" else None
        return {
            "status": "routed" if slot is not None else "reject",
            "slot": slot,
            "expert_id": self.expert_ids[slot] if slot is not None else None,
            "confidence": confidence,
            "support_confidence": confidence,
            "expert_confidence": expert_confidence,
            "reject_probability": reject_probability,
            "margin": margin,
            "expert_margin": expert_margin,
            "ambiguous_experts": expert_margin < self.config["min_margin"],
            "probabilities": probabilities.tolist(),
            "reason": reason,
            "decision_rule": DECISION_RULE,
            "model_install_authority": False,
            "production_accepted": False,
        }

    def save(self, path):
        """Create a new pinned state artifact without overwriting prior evidence."""
        tensor = self.weights.tobytes(order="C")
        header = {
            "schema": SCHEMA,
            "feature_recipe": FEATURE_RECIPE,
            "decision_rule": DECISION_RULE,
            "expert_ids": list(self.expert_ids),
            "config": dict(self.config),
            "source_sha256": self.source_sha256,
            "training_sha256": self.training_sha256,
            "training": self.training,
            "weight_shape": list(self.weights.shape),
            "weight_dtype": "little-endian-float32",
            "weight_sha256": hashlib.sha256(tensor).hexdigest(),
            "production_accepted": False,
        }
        metadata = _canonical(header)
        payload = MAGIC + struct.pack("<I", len(metadata)) + metadata + tensor
        if len(payload) > MAX_STATE_BYTES:
            raise ValueError("router artifact exceeds byte bound")
        path = Path(path)
        with path.open("xb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        return {
            "path": str(path),
            "sha256": hashlib.sha256(payload).hexdigest(),
            "artifact_bytes": len(payload),
            "private_parameter_bytes": len(tensor),
            "parameter_count": self.weights.size,
            "source_sha256": self.source_sha256,
            "training_sha256": self.training_sha256,
            "training": self.training,
            "production_accepted": False,
        }


def fit_router(observations, *, expert_ids, source_sha256, config=None):
    """Fit only source-query observations and measured per-expert utilities.

    Each row is exactly question/utilities/reject. Positive utility ties produce
    a uniform soft target over tied experts; below-threshold rows and explicit
    unsupported examples train the additional reject class. This function never
    receives final labels. It cannot authenticate a caller's provenance claim.
    """
    expert_ids = _expert_ids(expert_ids)
    config = checked_config(config)
    if not _digest(source_sha256):
        raise ValueError("independently retained source SHA-256 required")
    if (
        type(observations) is not list
        or not 1 <= len(observations) <= MAX_TRAINING_ROWS
    ):
        raise ValueError("bounded nonempty source observations required")
    targets = np.zeros((len(observations), len(expert_ids) + 1), dtype=np.float64)
    seen, questions = set(), []
    rejected = tied = informative = 0
    for index, row in enumerate(observations):
        if type(row) is not dict or set(row) != {"question", "utilities", "reject"}:
            raise ValueError("closed source utility observation required")
        question = normalized_question(row["question"])
        if question in seen:
            raise ValueError("duplicate normalized source question")
        seen.add(question)
        questions.append(question)
        utilities = row["utilities"]
        if (
            type(row["reject"]) is not bool
            or type(utilities) is not list
            or len(utilities) != len(expert_ids)
            or any(
                type(value) not in (int, float)
                or not math.isfinite(value)
                or not 0 <= value <= 1
                for value in utilities
            )
        ):
            raise ValueError(
                "finite unit utilities aligned to declared experts required"
            )
        best = max(utilities)
        if row["reject"] or best < config["min_utility"]:
            targets[index, -1] = 1.0
            rejected += 1
        else:
            winners = [i for i, value in enumerate(utilities) if value == best]
            targets[index, winners] = 1.0 / len(winners)
            tied += len(winners) > 1
            informative += len(winners) == 1
    matrix = features(questions, config)
    weights = np.random.default_rng(config["seed"]).normal(
        scale=0.001, size=(matrix.shape[1], targets.shape[1])
    )
    loss = []
    for _ in range(config["epochs"]):
        probabilities = _softmax(matrix @ weights)
        loss.append(
            float(
                -(targets * np.log(np.maximum(probabilities, 1e-15))).sum()
                / len(targets)
            )
        )
        gradient = matrix.T @ (probabilities - targets) / len(targets)
        gradient[:-1] += config["l2"] * weights[:-1]
        weights -= config["learning_rate"] * gradient
    training = {
        "algorithm": "full-batch-soft-target-cross-entropy-gradient-descent",
        "optimizer_updates": config["epochs"],
        "source_examples": len(observations),
        "informative_expert_examples": informative,
        "tied_expert_examples": tied,
        "reject_examples": rejected,
        "first_cross_entropy": loss[0],
        "last_preupdate_cross_entropy": loss[-1],
        "final_scores_used": False,
    }
    return LearnedRouter(
        expert_ids=expert_ids,
        config=config,
        source_sha256=source_sha256,
        training_sha256=hashlib.sha256(_canonical(observations)).hexdigest(),
        training=training,
        weights=weights,
    )


def load_router(path, *, expected_sha256):
    """Verify a caller-pinned bounded regular artifact before decoding weights."""
    if not _digest(expected_sha256):
        raise ValueError("independently retained router SHA-256 required")
    path = Path(path)
    before = path.lstat()
    if not stat.S_ISREG(before.st_mode) or not 0 < before.st_size <= MAX_STATE_BYTES:
        raise ValueError("bounded regular router state required")
    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0)
    flags |= getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
    descriptor = os.open(path, flags)
    with os.fdopen(descriptor, "rb") as stream:
        opened = os.fstat(stream.fileno())
        if not stat.S_ISREG(opened.st_mode) or not os.path.samestat(before, opened):
            raise ValueError("router artifact replaced during open")
        payload = stream.read(MAX_STATE_BYTES + 1)
        after = os.fstat(stream.fileno())
    if (
        len(payload) != before.st_size
        or any(
            getattr(opened, key) != getattr(after, key)
            for key in ("st_size", "st_mtime_ns", "st_ctime_ns")
        )
        or hashlib.sha256(payload).hexdigest() != expected_sha256
    ):
        raise ValueError("router artifact content binding")
    if not payload.startswith(MAGIC) or len(payload) < len(MAGIC) + 4:
        raise ValueError("unregistered router serialization")
    start = len(MAGIC) + 4
    length = struct.unpack("<I", payload[len(MAGIC) : start])[0]
    if not 0 < length <= 32 * 1024 or start + length >= len(payload):
        raise ValueError("router header byte bound")

    def unique(pairs):
        value = {}
        for key, item in pairs:
            if key in value:
                raise ValueError("duplicate router metadata field")
            value[key] = item
        return value

    header = json.loads(payload[start : start + length], object_pairs_hook=unique)
    fields = {
        "schema",
        "feature_recipe",
        "decision_rule",
        "expert_ids",
        "config",
        "source_sha256",
        "training_sha256",
        "training",
        "weight_shape",
        "weight_dtype",
        "weight_sha256",
        "production_accepted",
    }
    if (
        type(header) is not dict
        or set(header) != fields
        or header["schema"] != SCHEMA
        or header["feature_recipe"] != FEATURE_RECIPE
        or header["decision_rule"] != DECISION_RULE
        or header["weight_dtype"] != "little-endian-float32"
        or header["production_accepted"] is not False
    ):
        raise ValueError("unregistered router metadata")
    config = checked_config(header["config"])
    experts = _expert_ids(header["expert_ids"])
    shape = [config["dimension"] + 1, len(experts) + 1]
    tensor = payload[start + length :]
    if (
        header["weight_shape"] != shape
        or len(tensor) != math.prod(shape) * 4
        or hashlib.sha256(tensor).hexdigest() != header["weight_sha256"]
    ):
        raise ValueError("router weight shape/content binding")
    return LearnedRouter(
        expert_ids=experts,
        config=config,
        source_sha256=header["source_sha256"],
        training_sha256=header["training_sha256"],
        training=header["training"],
        weights=np.frombuffer(tensor, dtype="<f4").reshape(shape),
    )
