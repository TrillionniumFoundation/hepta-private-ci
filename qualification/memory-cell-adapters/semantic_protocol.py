"""Shared, fixed label order and scalar-f32 reference for the semantic candidate.

The encoder consumes the original text without masking.  Registered names are
resolved independently; this module never supplies memory values or authority.
"""
import hashlib
import json
import re

import numpy as np

ENCODER_DIGEST = "4bff7b22bc544468dca828c404026aaa5d011ce83e305d056c14a24658955faf"
FEATURE_PROFILE = "hepta.memory.inventory-raw-minilm-384.v1"
INTENTS = ("semantic", "skill", "compose", "reject:mutation", "reject:external",
           "reject:prediction", "reject:negation", "reject:other")
SHAPES = ("policy_tuple", "program", "computed_integer", "unsupported")
SCHEMA = "hepta.memory.inventory-semantic-router.v1"
ASCII_LOWER = str.maketrans("ABCDEFGHIJKLMNOPQRSTUVWXYZ", "abcdefghijklmnopqrstuvwxyz")


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def digest(value):
    return hashlib.sha256(value if isinstance(value, bytes) else canonical(value)).hexdigest()


def address(text, aliases):
    if not isinstance(text, str) or not text.strip() or len(text.encode()) > 8192:
        return None
    normalized = " " + " ".join(re.findall(r"[a-z0-9_]+", text.translate(ASCII_LOWER))) + " "
    found = {"entity": set(), "workflow": set()}
    for alias in aliases:
        for phrase in alias["phrases"]:
            phrase = " ".join(re.findall(r"[a-z0-9_]+", phrase.translate(ASCII_LOWER)))
            if " " + phrase + " " in normalized:
                found[alias["kind"]].add(alias["key"])
    if any(len(values) > 1 for values in found.values()) or not any(found.values()):
        return None
    return {kind: next(iter(values), None) for kind, values in found.items()}


def softmax(logits):
    values = np.exp(logits - max(logits)).astype(np.float32)
    total = np.float32(0)
    for value in values:
        total = np.float32(total + value)
    return values / total


def hypothesis(model, features):
    """Mirror the Rust f32 operation order, independently of quality scoring."""
    probabilities = []
    for name in ("intent", "shape"):
        rows = np.asarray(model[name + "_weights"], dtype=np.float32)
        bias = np.asarray(model[name + "_bias"], dtype=np.float32)
        logits = np.zeros(len(rows), dtype=np.float32)
        for i, row in enumerate(rows):
            total = np.float32(0)
            for weight, feature in zip(row, features, strict=True):
                total = np.float32(total + np.float32(weight * feature))
            logits[i] = np.float32(total + bias[i])
        probabilities.append(softmax(logits))
    intent, shape = probabilities
    scores = np.empty(4, dtype=np.float32)
    scores[:3] = intent[:3] * shape[:3]
    rejection = np.float32(0)
    for value in intent[3:]:
        rejection = np.float32(rejection + value)
    scores[3] = np.float32(rejection + shape[3])
    total = np.float32(0)
    for value in scores:
        total = np.float32(total + value)
    scores /= total
    order = sorted(range(4), key=lambda i: (-float(scores[i]), i))
    return order[0], float(scores[order[0]]), float(np.float32(scores[order[0]] - scores[order[1]]))


def route(model, text, features, *, threshold=None, margin=None):
    keys = address(text, model["aliases"])
    if keys is None or features is None:
        return None
    winner, score, gap = hypothesis(model, features)
    if winner == 3 or score < float(np.float32(model["threshold"] if threshold is None else threshold)) \
            or gap < float(np.float32(model["minimum_margin"] if margin is None else margin)):
        return None
    if (keys["entity"] is not None, keys["workflow"] is not None) != ((True, False), (False, True), (True, True))[winner]:
        return None
    return {"operation": ("semantic", "procedure", "apply")[winner], **keys}


def gold(row):
    if row["role"] == "unknown":
        return None
    return {"operation": {"semantic": "semantic", "skill": "procedure", "compose": "apply"}[row["role"]],
            "entity": None if row["entity"] is None else f"inventory:entity:{row['entity']}",
            "workflow": None if row["workflow"] is None else f"inventory:workflow:{row['workflow']}"}


def intent_label(row):
    if row["role"] != "unknown":
        return row["role"]
    parts = row["id"].split(":")
    phase, wording = parts[0], int(parts[2])
    # This mapping labels the already-frozen train/development text.  It does
    # not inspect any held/challenge text or derive targets from model scores.
    groups = {
        "train": ("prediction", "other", "mutation", "external", "mutation", "mutation"),
        "development": ("external", "other"),
        "negative-train": ("mutation", "mutation", "mutation", "mutation", "external", "external",
                           "negation", "negation", "other", "prediction", "mutation", "mutation",
                           "mutation", "other", "mutation", "external", "other", "other", "other", "other"),
        "negative-calibration": ("mutation", "mutation", "prediction", "negation", "external", "other", "mutation", "external"),
    }
    return "reject:" + groups[phase][wording]
