"""Ordinary controls using exactly the admitted training text or encoder features.

No baseline reads task fixtures, oracle test labels, or guessed domain labels.
Similarity scores are ranking scores, not calibrated correctness probabilities.
"""

import math
import re
from collections import Counter

import numpy as np

from tasks import SKILLS, resolve_profile


def _training(rows):
    if not rows or any(row.get("split") not in ("train", "registry") for row in rows):
        raise ValueError("fit accepts training examples and public registry only")
    return np.asarray([row["label"] for row in rows], dtype=np.int64)


def _normalize(features):
    values = np.asarray(features, dtype=np.float64)
    if values.ndim == 1:
        values = values[None, :]
    if values.ndim != 2 or not np.isfinite(values).all():
        raise ValueError("finite feature matrix required")
    norms = np.linalg.norm(values, axis=1, keepdims=True)
    if (norms == 0).any():
        raise ValueError("zero encoder feature")
    return values / norms


class BM25:
    """BM25 over full training requests; pick the highest scoring example."""

    def __init__(self, rows, k1=1.5, b=0.75):
        self.labels = _training(rows)
        self.documents = [Counter(self.tokens(row["text"])) for row in rows]
        self.k1, self.b = k1, b
        self.lengths = [sum(doc.values()) for doc in self.documents]
        self.average_length = sum(self.lengths) / len(rows)
        frequency = Counter(token for doc in self.documents for token in doc)
        self.idf = {token: math.log(1 + (len(rows) - count + 0.5) / (count + 0.5))
                    for token, count in frequency.items()}

    @staticmethod
    def tokens(text):
        return re.findall(r"\w+", text.casefold())

    def predict(self, text):
        tokens = self.tokens(text)
        scores = []
        for doc, length in zip(self.documents, self.lengths):
            norm = self.k1 * (1 - self.b + self.b * length / self.average_length)
            scores.append(sum(self.idf.get(token, 0) * doc[token] * (self.k1 + 1)
                              / (doc[token] + norm) for token in tokens))
        best = max(range(len(scores)), key=lambda i: (scores[i], -i))
        return int(self.labels[best]), float(scores[best])

    def batch_predict(self, texts, features=None):
        return [self.predict(text)[0] for text in texts]


class NearestExample:
    """Cosine nearest training request under the shared frozen encoder."""

    def __init__(self, rows, features):
        self.labels = _training(rows)
        self.features = _normalize(features)
        if len(self.labels) != len(self.features):
            raise ValueError("row/feature length mismatch")

    def predict(self, feature):
        scores = self.features @ _normalize(feature)[0]
        best = int(np.argmax(scores))
        return int(self.labels[best]), float(scores[best])

    def batch_predict(self, texts, features=None):
        if features is None or len(texts) != len(features):
            raise ValueError("query features required")
        return [self.predict(feature)[0] for feature in features]


class Centroid:
    """Normalized per-class mean of the same admitted training embeddings."""

    def __init__(self, rows, features):
        labels = _training(rows)
        values = _normalize(features)
        if len(labels) != len(values):
            raise ValueError("row/feature length mismatch")
        self.labels = np.unique(labels)
        self.features = _normalize(np.stack([values[labels == label].mean(axis=0)
                                            for label in self.labels]))

    def predict(self, feature):
        scores = self.features @ _normalize(feature)[0]
        best = int(np.argmax(scores))
        return int(self.labels[best]), float(scores[best])

    def batch_predict(self, texts, features=None):
        if features is None or len(texts) != len(features):
            raise ValueError("query features required")
        return [self.predict(feature)[0] for feature in features]


class ExactStore:
    """Exact normalized-request storage, with abstention when no key exists.

This is an addressing/coverage control, not a competitive semantic retriever.
The nearest-example and BM25 controls supply semantic and lexical retrieval.
"""

    def __init__(self, rows):
        labels = _training(rows)
        self.entries = {}
        for row, label in zip(rows, labels):
            key = " ".join(row["text"].casefold().split())
            if key in self.entries and self.entries[key] != int(label):
                self.entries[key] = None
            else:
                self.entries[key] = int(label)

    def predict(self, text):
        key = " ".join(text.casefold().split())
        label = self.entries.get(key)
        return label, float(label is not None)

    def batch_predict(self, texts, features=None):
        return [self.predict(text)[0] for text in texts]


class ProfileExactStore:
    """Strong project-key lookup of explicit source operation bindings.

It reads the same permitted journal observations used to create training labels.
Its runtime source read is charged; it does not infer an unseen project rule.
"""

    def __init__(self, journal, frontier):
        self.journal = [dict(row) for row in journal if row["sequence"] <= frontier]
        self.frontier = frontier
        self.projects = sorted({row["project"] for row in self.journal})

    def predict(self, text):
        names = [name for name in self.projects
                 if re.search(r"\b" + re.escape(name) + r"\b", text, re.IGNORECASE)]
        if len(names) != 1:
            return None, 0.0
        source = resolve_profile(self.journal, names[0], self.frontier)
        return SKILLS.index(source["operation_id"]), 1.0

    def batch_predict(self, texts, features=None):
        return [self.predict(text)[0] for text in texts]


def wording_audit(train_rows, evaluation_rows):
    """Descriptive overlap audit only; never edits or selects examples."""
    train_tokens = [set(BM25.tokens(row["text"])) for row in train_rows]
    train_keys = {" ".join(row["text"].casefold().split()) for row in train_rows}
    similarities, exact, aligned = [], [], []
    for row in evaluation_rows:
        tokens = set(BM25.tokens(row["text"]))
        scores = [len(tokens & old) / max(1, len(tokens | old)) for old in train_tokens]
        best = int(np.argmax(scores))
        similarities.append(scores[best])
        exact.append(" ".join(row["text"].casefold().split()) in train_keys)
        aligned.append(dict(id=row["id"], nearest_train_id=train_rows[best]["id"],
                            token_jaccard=scores[best], exact_normalized=exact[-1]))
    return {"query_count": len(evaluation_rows), "exact_normalized_matches": sum(exact),
            "maximum_token_jaccard": max(similarities, default=0),
            "mean_maximum_token_jaccard": float(np.mean(similarities)) if similarities else 0,
            "pairs": aligned,
            "interpretation": "Authored independent wording; overlap is not an independence proof. No data selection uses this audit."}
