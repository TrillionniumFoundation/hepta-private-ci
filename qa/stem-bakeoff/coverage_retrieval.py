"""Training-source-only top-k controls for the bounded input diagnostic."""

from collections import Counter
import re
import time
import unicodedata

import numpy as np

from cell_learning_metrics import calibrate_temperature, probabilities
from cell_learning_baselines import retained_state_bytes


def unit(features):
    values = np.asarray(features, dtype=np.float64)
    if values.ndim != 2 or not np.isfinite(values).all():
        raise ValueError("finite feature matrix required")
    return values / np.maximum(np.linalg.norm(values, axis=1, keepdims=True), 1e-12)


def tokens(text):
    if type(text) is not str or not text.strip() or len(text.encode()) > 1024**2:
        raise ValueError("bounded full source text required")
    return re.findall(r"\w+", unicodedata.normalize("NFKC", text).casefold())


class CoverageRetrieval:
    def __init__(self, features, labels, texts):
        start, cpu = time.perf_counter_ns(), time.process_time_ns()
        self.x = unit(features)
        self.y = np.asarray(labels, dtype=np.int64).copy()
        if len(self.x) != len(self.y) or len(texts) != len(self.y) or set(self.y) != {0, 1}:
            raise ValueError("matched training sources with both classes required")
        counts = [Counter(tokens(text)) for text in texts]
        self.source_utf8_bytes = sum(len(text.encode()) for text in texts)
        lengths = np.asarray([sum(c.values()) for c in counts])
        penalty = 1.2 * (0.25 + 0.75 * lengths / max(float(lengths.mean()), 1))
        entries = {}
        for i, count in enumerate(counts):
            for token, frequency in count.items():
                entries.setdefault(token, []).append((i, frequency))
        self.postings = {}
        for token, rows in entries.items():
            indices = np.asarray([r[0] for r in rows], dtype=np.int32)
            frequency = np.asarray([r[1] for r in rows])
            idf = np.log1p((len(self.y) - len(indices) + 0.5) / (len(indices) + 0.5))
            self.postings[token] = (indices, idf * frequency * 2.2 / (frequency + penalty[indices]))
        self.centroids = unit(np.stack([self.x[self.y == c].mean(axis=0) for c in (0, 1)]))
        self.fit_cost = {"wall_ns": time.perf_counter_ns() - start,
                         "cpu_ns": time.process_time_ns() - cpu}
        self.memory = retained_state_bytes({"x": self.x, "y": self.y,
            "postings": self.postings, "centroids": self.centroids})

    def similarities(self, arm, features, texts):
        start, cpu = time.perf_counter_ns(), time.process_time_ns()
        if arm == "dense_topk":
            matrix = unit(features) @ self.x.T
        elif arm == "bm25_topk":
            matrix = np.zeros((len(texts), len(self.y)))
            for i, text in enumerate(texts):
                for token in set(tokens(text)):
                    if token in self.postings:
                        indices, weight = self.postings[token]
                        matrix[i, indices] += weight
        else:
            raise ValueError("unknown retrieval arm")
        return matrix, {"wall_ns": time.perf_counter_ns() - start,
            "cpu_ns": time.process_time_ns() - cpu, "queries": len(texts),
            "training_sources": len(self.y), "source_utf8_bytes": self.source_utf8_bytes,
            "query_utf8_bytes": sum(len(text.encode()) for text in texts),
            "encoder_calls": 0, **self.memory}

    def logits(self, similarity, k):
        if k not in (1, 3, 7, 15) or k > len(self.y):
            raise ValueError("unknown fixed retrieval budget")
        neighbors = np.argsort(-similarity, axis=1, kind="stable")[:, :k]
        positive = self.y[neighbors].sum(axis=1)
        # Symmetric half-observation smoothing; no test prevalence enters votes.
        return np.log(np.stack([k - positive + 0.5, positive + 0.5], axis=1) / (k + 1))

    def calibrate(self, similarity, labels):
        choices = []
        for k in (1, 3, 7, 15):
            temperature, report = calibrate_temperature(self.logits(similarity, k), labels)
            choices.append((report["nll"], k, temperature, report))
        _, k, temperature, report = min(choices, key=lambda c: (c[0], c[1], c[2]))
        return {"k": k, "temperature": temperature, "temperature_report": report,
                "selection": "minimum calibration NLL; ties prefer smaller k",
                "candidates": [{"k": c[1], "temperature": c[2], "nll": c[0]} for c in choices]}

    def predict(self, similarity, calibrated):
        return probabilities(self.logits(similarity, calibrated["k"]), calibrated["temperature"])

    def prototype_logits(self, features):
        return 20 * unit(features) @ self.centroids.T
