"""Portable n-gram student and deterministic routing at inference time (stdlib only)."""

import json
import math
import re
import struct
import zipfile
from collections import Counter

TOKEN = re.compile(r"[a-z]+|[0-9]+|[^\w\s]")


def terms(text):
    words = TOKEN.findall(text.lower())
    features = ["w:" + w for w in words]
    features.extend("p:" + a + "_" + b for a, b in zip(words, words[1:]))
    for w in words:
        padded = "^" + w + "$"
        features.extend("c:" + padded[i : i + 3] for i in range(len(padded) - 2))
    return Counter(features)


def encode(text, vocabulary):
    counts = {
        vocabulary[t]: 1 + math.log(n)
        for t, n in terms(text).items()
        if t in vocabulary
    }
    norm = math.sqrt(sum(v * v for v in counts.values())) or 1
    return {i: v / norm for i, v in counts.items()}


def score(weight, x):
    return math.fsum(weight[i] * v for i, v in x.items())


def load_bundle(path):
    with zipfile.ZipFile(path) as files:
        meta = json.loads(files.read("state.json"))
        words = meta.pop("vocabulary")
        weights = {}
        for arm in ("parent", "t5", "smol", "mix", "gate"):
            weights[arm] = struct.unpack(
                "<" + "d" * len(words), files.read(arm + ".f64")
            )
    return {word: i for i, word in enumerate(words)}, weights, meta


def predict(arm, prompt, domain, vocabulary, weights, meta):
    x = encode(prompt, vocabulary)
    gate_evaluations = 0
    if arm == "fixed":
        expert = meta["fixed_route"].get(domain, meta["best_single"])
    elif arm == "sparse":
        expert = "smol" if score(weights["gate"], x) > 0 else "t5"
        gate_evaluations = 1
    elif arm == "best_single":
        expert = meta["best_single"]
    else:
        expert = arm
    z = score(weights[expert], x)
    return {
        "answer": int(z > 0),
        "expert": expert,
        "score": z,
        "expert_evaluations": 1,
        "gate_evaluations": gate_evaluations,
    }
