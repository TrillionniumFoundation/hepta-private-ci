"""Exact/BM25 retrieval and a small learned association reranker.

Tokens are lexical, not a claimed semantic encoder. Feedback means a document
was used by a completed verified development recipe; it does not prove causal
necessity. Every arm sees the same documents, including new experience.
"""

from collections import Counter
import hashlib
import math
import re

from .contracts import corpus_documents, digest, require

WIDTH = 32
ENCODER = "repo-mdv-lexical-hash32-v1"


def tokens(text):
    return re.findall(r"[a-z0-9_]+|[\u4e00-\u9fff]", text.lower())


def features(text):
    result = [0.0] * WIDTH
    counts = Counter(tokens(text))
    for token, count in counts.items():
        raw = hashlib.sha256(token.encode()).digest()
        result[int.from_bytes(raw[:4], "big") % WIDTH] += (
            1 if raw[4] & 1 else -1
        ) * math.log1p(count)
    norm = max(1.0, math.sqrt(math.fsum(v * v for v in result)))
    return [v / norm for v in result]


def initial_state(corpus):
    docs = corpus_documents(corpus)
    return {
        "schema": "hepta.repo-mdv.memory.v1",
        "encoder": ENCODER,
        "corpus_sha256": digest(corpus),
        "document_ids": [d["id"] for d in docs],
        "weights": [[0.0] * WIDTH for _ in docs],
        "updates": 0,
        "parent_sha256": None,
        "last_feedback_sha256": None,
        "production_update": "not_requested",
        "fitting_scope": "development",
    }


def validate_state(state, corpus):
    expected = initial_state(corpus)
    for key in (
        "schema",
        "encoder",
        "corpus_sha256",
        "document_ids",
        "production_update",
        "fitting_scope",
    ):
        require(state.get(key) == expected[key], "memory binding mismatch: " + key)
    require(
        type(state.get("updates")) is int and 0 <= state["updates"] <= 10000,
        "invalid update count",
    )
    weights = state.get("weights")
    require(
        type(weights) is list and len(weights) == len(expected["weights"]),
        "invalid weights",
    )
    for row in weights:
        require(type(row) is list and len(row) == WIDTH, "invalid weight width")
        require(
            all(
                type(v) in (int, float) and math.isfinite(v) and abs(v) <= 8
                for v in row
            ),
            "invalid weight value",
        )
    require(
        state["updates"] == 0 or isinstance(state.get("last_feedback_sha256"), str),
        "missing feedback lineage",
    )


def retrieve(corpus, query, state=None):
    docs = corpus_documents(corpus)
    if state is not None:
        validate_state(state, corpus)
    terms = [Counter(tokens(doc["text"])) for doc in docs]
    query_terms = set(tokens(query))
    mean_length = max(1.0, sum(sum(t.values()) for t in terms) / len(terms))
    vector, ranked = features(query), []
    for index, (doc, counts) in enumerate(zip(docs, terms)):
        lexical = 0.0
        for term in query_terms:
            frequency = counts.get(term, 0)
            present = sum(term in other for other in terms)
            idf = math.log(1 + (len(docs) - present + 0.5) / (present + 0.5))
            lexical += (
                idf
                * frequency
                * 2.2
                / (frequency + 1.2 * (0.25 + 0.75 * sum(counts.values()) / mean_length))
            )
        exact = 2.0 if query.casefold() in doc["text"].casefold() else 0.0
        association = (
            0.0
            if state is None
            else math.fsum(a * b for a, b in zip(state["weights"][index], vector))
        )
        ranked.append(
            {
                "document_id": doc["id"],
                "bm25": lexical,
                "exact": exact,
                "learned_association": association,
                "score": lexical + exact + 0.25 * association,
            }
        )
    return sorted(ranked, key=lambda row: (-row["score"], row["document_id"]))


def update(corpus, state, query, selected_document, feedback):
    validate_state(state, corpus)
    require(selected_document in state["document_ids"], "unknown document")
    require(
        feedback.get("split") == "development" and feedback.get("terminal") == "proved",
        "unverified feedback cannot train",
    )
    require(
        feedback.get("selected_document") == selected_document
        and feedback.get("query_sha256") == digest(query),
        "feedback attribution mismatch",
    )
    checks = feedback.get("mandatory_checks", [])
    require(
        checks
        and all(
            type(row.get("returncode")) is int
            and row["returncode"] == 0
            and row.get("cleanup_complete") is True
            and row.get("error") is None
            for row in checks
        ),
        "incomplete verification cannot train",
    )
    vector = features(query)
    require(any(vector), "empty learning features")
    weights = []
    for doc_id, row in zip(state["document_ids"], state["weights"]):
        prediction = math.fsum(a * b for a, b in zip(row, vector))
        error = float(doc_id == selected_document) - prediction
        weights.append(
            [max(-8.0, min(8.0, w + 0.5 * error * x)) for w, x in zip(row, vector)]
        )
    return {
        **state,
        "weights": weights,
        "updates": state["updates"] + 1,
        "parent_sha256": digest(state),
        "last_feedback_sha256": digest(feedback),
    }
