"""Training-only exact, BM25, frozen dense and prototype controls."""

import re
import sys
import time
import unicodedata

import numpy as np

from cell_learning_models import normalize_features


def normalized_text(text):
    if type(text) is not str or not text.strip() or len(text.encode()) > 32768:
        raise ValueError("bounded nonempty source text required")
    return " ".join(unicodedata.normalize("NFKC", text).casefold().split())


def retained_state_bytes(state):
    """Measure reachable Python objects and unique NumPy-owned buffers separately."""
    seen, counts = set(), {"retained_tensor_bytes": 0, "reachable_python_bytes": 0}
    def visit(value):
        if id(value) in seen:
            return
        seen.add(id(value))
        size = sys.getsizeof(value)
        if isinstance(value, np.ndarray):
            owned = value.nbytes if value.flags.owndata else 0
            counts["retained_tensor_bytes"] += owned
            counts["reachable_python_bytes"] += max(size - owned, 0)
            if value.base is not None:
                visit(value.base)
        else:
            counts["reachable_python_bytes"] += size
            if isinstance(value, dict):
                for key, item in value.items():
                    visit(key)
                    visit(item)
            elif isinstance(value, (list, tuple, set)):
                for item in value:
                    visit(item)
    visit(state)
    counts["reachable_state_bytes"] = sum(counts.values())
    return counts


class FrozenBaselines:
    """Fit once using only labelled training sources; queries have no gold fields."""

    def __init__(self, features, labels, rows, classes):
        started, cpu_started = time.perf_counter_ns(), time.process_time_ns()
        self.features = normalize_features(features) / np.sqrt(np.asarray(features).shape[1])
        self.labels = np.asarray(labels).copy()
        if (self.labels.dtype.kind not in "iu" or self.labels.shape != (len(self.features),)
                or len(rows) != len(self.features) or type(classes) is not int
                or not 2 <= classes <= 256 or np.any(self.labels < 0)
                or np.any(self.labels >= classes) or len(np.unique(self.labels)) != classes):
            raise ValueError("complete training labels required")
        self.classes = classes
        self.rows = [dict(row) for row in rows]
        for row in self.rows:
            if set(row) != {"source_id", "group_id", "text"}:
                raise ValueError("baseline source rows must not contain outcomes or gold fields")
        self.texts = [normalized_text(row["text"]) for row in rows]
        self.exact = {}
        for index, text in enumerate(self.texts):
            self.exact.setdefault(text, set()).add(int(self.labels[index]))
        postings, lengths = {}, []
        for index, text in enumerate(self.texts):
            tokens = re.findall(r"\w+", text)
            counts = {}
            for token in tokens:
                counts[token] = counts.get(token, 0) + 1
            lengths.append(len(tokens))
            for token, count in counts.items():
                postings.setdefault(token, []).append((index, count))
        lengths = np.asarray(lengths)
        penalty = 1.2 * (0.25 + 0.75 * lengths / max(float(lengths.mean()), 1.0))
        self.postings = {}
        for token, entries in postings.items():
            indices = np.array([entry[0] for entry in entries], dtype=np.int32)
            tf = np.array([entry[1] for entry in entries])
            idf = np.log(1 + (len(self.features) - len(indices) + 0.5) / (len(indices) + 0.5))
            self.postings[token] = (indices, idf * tf * 2.2 / (tf + penalty[indices]))
        self.centroids = np.stack([self.features[self.labels == k].mean(axis=0)
                                   for k in range(classes)])
        self.centroids /= np.maximum(np.linalg.norm(self.centroids, axis=1, keepdims=True), 1e-12)
        self.fit_cost = {"wall_ns": time.perf_counter_ns() - started,
                         "cpu_ns": time.process_time_ns() - cpu_started}
        self.memory = retained_state_bytes(vars(self))

    def predict(self, arm, features, rows):
        if arm not in ("exact", "bm25", "dense_nearest", "prototype"):
            raise ValueError("unknown source baseline")
        started, cpu_started = time.perf_counter_ns(), time.process_time_ns()
        query = normalize_features(features) / np.sqrt(self.features.shape[1])
        if query.shape[1] != self.features.shape[1] or len(rows) != len(query):
            raise ValueError("query feature identity shape differs")
        if any(set(row) != {"source_id", "group_id", "text"} for row in rows):
            raise ValueError("prediction input must not include labels or outcomes")
        eligible = np.ones(len(query), dtype=bool)
        logits = np.zeros((len(query), self.classes))
        selected_sources = [None] * len(query)
        if arm == "exact":
            for i, row in enumerate(rows):
                target = self.exact.get(normalized_text(row["text"]), set())
                eligible[i] = len(target) == 1
                if eligible[i]:
                    logits[i, next(iter(target))] = 20
                    match = self.texts.index(normalized_text(row["text"]))
                    selected_sources[i] = self.rows[match]["source_id"]
        elif arm == "prototype":
            logits = 20 * query @ self.centroids.T
        else:
            similarity = np.zeros((len(query), len(self.features)))
            if arm == "dense_nearest":
                similarity = query @ self.features.T
            else:
                for i, row in enumerate(rows):
                    for token in set(re.findall(r"\w+", normalized_text(row["text"]))):
                        posting = self.postings.get(token)
                        if posting is not None:
                            indices, contribution = posting
                            similarity[i, indices] += contribution
                eligible = similarity.max(axis=1) > 0
            logits = np.stack([similarity[:, self.labels == k].max(axis=1)
                               for k in range(self.classes)], axis=1)
            if arm == "dense_nearest":
                logits *= 20
            selected_sources = [self.rows[j]["source_id"] if eligible[i] else None
                                for i, j in enumerate(similarity.argmax(axis=1))]
        return {"logits": logits, "eligible": eligible, "retrieved_source_ids": selected_sources,
                "cost": {"wall_ns": time.perf_counter_ns() - started,
                         "cpu_ns": time.process_time_ns() - cpu_started,
                         "queries": len(query), "training_sources": len(self.rows),
                         "retained_feature_bytes": int(self.features.nbytes),
                         "prototype_bytes": int(self.centroids.nbytes),
                         "retained_source_utf8_bytes": sum(len(r["text"].encode()) for r in self.rows),
                         **self.memory, "fit_once_cost": self.fit_cost,
                         "state_scope": "shared baseline wrapper, excluding measurement metadata and query temporaries",
                         "python_measurement": "sys.getsizeof recursive reachable graph, not exclusive RSS",
                         "python_container_overhead_measured": True, "optimizer_steps": 0,
                         "encoder_forward_calls": 0}}
