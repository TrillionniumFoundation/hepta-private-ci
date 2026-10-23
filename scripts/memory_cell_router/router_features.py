"""Deterministic question-only features for a fitted research router."""

import hashlib
import math
import re

import numpy as np


DEFAULT_CONFIG = {
    "dimension": 512,
    "seed": 2718,
    "epochs": 400,
    "learning_rate": 2.0,
    "l2": 0.0001,
    "min_utility": 0.5,
    "min_confidence": 0.55,
    "min_margin": 0.05,
}
FEATURE_RECIPE = "signed-blake2b-word-bigram-char34-l2-v1"
MAX_QUESTION_BYTES = 4096


def normalized_question(question):
    if (
        type(question) is not str
        or not 1 <= len(question.encode("utf-8")) <= MAX_QUESTION_BYTES
        or not question.strip()
    ):
        raise ValueError("bounded nonempty question text required")
    return " ".join(question.casefold().split())


def checked_config(config=None):
    result = dict(DEFAULT_CONFIG)
    if config is not None:
        if type(config) is not dict or not set(config) <= set(result):
            raise ValueError("unregistered router configuration field")
        result.update(config)
    bounds = {
        "dimension": (64, 8192),
        "seed": (0, 2**32 - 1),
        "epochs": (1, 2000),
    }
    for field, (low, high) in bounds.items():
        if type(result[field]) is not int or not low <= result[field] <= high:
            raise ValueError("invalid integer router configuration")
    for field in set(result) - set(bounds):
        value = result[field]
        if type(value) not in (int, float) or not math.isfinite(value):
            raise ValueError("finite router configuration required")
        maximum = 10.0 if field == "learning_rate" else 1.0
        if not 0 <= value <= maximum:
            raise ValueError("router configuration outside registered bounds")
        result[field] = float(value)
    if result["learning_rate"] == 0 or result["min_confidence"] <= 0.5:
        raise ValueError("positive learning rate and majority confidence required")
    return result


def features(questions, config):
    matrix = np.zeros((len(questions), config["dimension"] + 1), dtype=np.float64)
    key = config["seed"].to_bytes(4, "little")
    for row, question in enumerate(questions):
        text = normalized_question(question)
        tokens = re.findall(r"\w+", text)
        if not tokens:
            raise ValueError("question requires lexical content")
        weighted = [("w:" + token, 1.0) for token in tokens]
        weighted += [
            ("b:" + left + "/" + right, 0.5) for left, right in zip(tokens, tokens[1:])
        ]
        padded = " " + " ".join(tokens) + " "
        weighted += [
            (f"c{size}:" + padded[i : i + size], 0.15)
            for size in (3, 4)
            for i in range(len(padded) - size + 1)
        ]
        for token, weight in weighted:
            hashed = hashlib.blake2b(token.encode(), key=key, digest_size=8).digest()
            bucket = int.from_bytes(hashed[:4], "little") % config["dimension"]
            matrix[row, bucket] += weight if hashed[4] & 1 else -weight
        norm = np.linalg.norm(matrix[row, :-1])
        if norm:
            matrix[row, :-1] /= norm
        matrix[row, -1] = 1.0
    return matrix


def verify_question_splits(partitions):
    """Reject normalized question overlap; this does not establish fact independence."""
    if type(partitions) is not dict or len(partitions) < 2:
        raise ValueError("at least two declared question partitions required")
    seen = set()
    counts = {}
    for name, questions in partitions.items():
        if type(name) is not str or type(questions) is not list or not questions:
            raise ValueError("named nonempty question lists required")
        normalized = [normalized_question(question) for question in questions]
        if len(set(normalized)) != len(normalized) or seen & set(normalized):
            raise ValueError("duplicate question within or between partitions")
        seen.update(normalized)
        counts[name] = len(normalized)
    return counts
