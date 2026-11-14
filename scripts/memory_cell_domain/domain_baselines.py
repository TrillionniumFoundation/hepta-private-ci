"""Actual source-only retrieval controls; targets are never inference inputs."""

from collections import Counter
import math
import re
import sqlite3

import numpy as np


def terms(text):
    words = re.findall(r"\w+", text.casefold())
    return words + [a + "/" + b for a, b in zip(words, words[1:])]


class RetrievalBaselines:
    """Exact symptom lookup, FTS5 BM25 and fitted TF-IDF nearest source."""

    def __init__(self, cases, destination):
        self.cases = cases
        self.connection = sqlite3.connect(destination)
        self.connection.execute(
            "CREATE VIRTUAL TABLE cases USING fts5(symptom, tokenize='porter unicode61')"
        )
        self.connection.executemany(
            "INSERT INTO cases VALUES (?)", [(c["symptom"],) for c in cases]
        )
        self.connection.commit()
        counts = [Counter(terms(c["symptom"])) for c in cases]
        self.idf = {
            term: math.log((len(cases) + 1) / (1 + sum(term in c for c in counts))) + 1
            for count in counts
            for term in count
        }
        self.vectors = [self._vector(count) for count in counts]

    def _vector(self, counts):
        raw = {
            term: count * self.idf[term]
            for term, count in counts.items()
            if term in self.idf
        }
        norm = math.sqrt(sum(x * x for x in raw.values())) or 1
        return {term: value / norm for term, value in raw.items()}

    def predict(self, question):
        # This structured control admits only an exact source symptom and the
        # repair operation. It is deliberately reported separately from NLP.
        matching = [c for c in self.cases if c["symptom"] in question]
        exact = (
            matching[0]["repair_id"]
            if len(matching) == 1 and "unrecorded checksum" not in question
            else "unknown"
        )
        tokens = sorted(set(re.findall(r"\w+", question.casefold())))
        query = " OR ".join('"' + word + '"' for word in tokens)
        rows = (
            self.connection.execute(
                "SELECT rowid FROM cases WHERE cases MATCH ? ORDER BY bm25(cases), rowid LIMIT 1",
                (query,),
            ).fetchall()
            if query
            else []
        )
        bm25 = self.cases[rows[0][0] - 1]["repair_id"] if rows else "unknown"
        vector = self._vector(Counter(terms(question)))
        scores = [
            sum(value * v.get(term, 0) for term, value in vector.items())
            for v in self.vectors
        ]
        slot = max(range(len(scores)), key=lambda i: (scores[i], -i))
        return {
            "exact_source": exact,
            "bm25": bm25,
            "tfidf": self.cases[slot]["repair_id"] if scores[slot] else "unknown",
        }

    def close(self):
        self.connection.close()


def dense_nearest(training, observed, answers):
    """Use actual frozen-decoder features; no heldout labels enter this function."""
    training = np.asarray(training, dtype=np.float64)
    observed = np.asarray(observed, dtype=np.float64)
    training /= np.maximum(np.linalg.norm(training, axis=1, keepdims=True), 1e-12)
    observed /= np.maximum(np.linalg.norm(observed, axis=1, keepdims=True), 1e-12)
    labels = sorted(set(answers))
    centroids = np.stack(
        [training[np.array(answers) == value].mean(axis=0) for value in labels]
    )
    centroids /= np.maximum(np.linalg.norm(centroids, axis=1, keepdims=True), 1e-12)
    return {
        "dense_nearest": [answers[i] for i in (observed @ training.T).argmax(axis=1)],
        "dense_centroid": [labels[i] for i in (observed @ centroids.T).argmax(axis=1)],
    }
