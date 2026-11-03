"""Explicit routing baselines and a bounded learned text router.

Typed routing consumes admitted domain metadata. Literal and learned routing read
only query text at inference. Softmax scores are uncalibrated; threshold zero
does not provide unknown-domain detection. Vocabulary and router weights are
separate memory costs, never hidden in the cells' equal-parameter comparison.
"""

import hashlib
from pathlib import Path
import re
import time
import unicodedata

import numpy as np

from .encoding import FrozenEncoder, canonical_bytes
from .model import MemoryCell


def _domains(values):
    if not isinstance(values, (list, tuple)) or not 1 <= len(values) <= 64:
        raise ValueError("routing requires a bounded list of domains")
    if any(
        not isinstance(value, str)
        or not 1 <= len(value) <= 128
        or not re.fullmatch(r"[\w.-]+", value)
        for value in values
    ):
        raise ValueError("invalid domain identifier")
    normalized = [unicodedata.normalize("NFKC", value).casefold() for value in values]
    if len(set(normalized)) != len(values):
        raise ValueError("duplicate or normalization-colliding domains")
    return tuple(values)


def _queries(values):
    if not isinstance(values, (list, tuple)) or len(values) > 65536:
        raise ValueError("queries must be a bounded list or tuple")
    return values


class TypedRouter:
    """Exact domain metadata routing; its accuracy is a typed-interface baseline."""

    def __init__(self, domains):
        self.domains = _domains(domains)
        self.parameter_bytes = 0

    def route(self, queries):
        allowed = set(self.domains)
        return [
            query.domain if query.domain in allowed else None
            for query in _queries(queries)
        ]

    def manifest(self):
        return {
            "schema": "hepta.memory-cell.router.v1",
            "kind": "typed-domain",
            "domains": list(self.domains),
            "domain_vocabulary_bytes": len(canonical_bytes(self.domains)),
            "parameter_bytes": 0,
            "inference_inputs": ["query.domain"],
            "calibrated": False,
            "unknown_domain_policy": "abstain",
        }

    def save(self, directory):
        directory = Path(directory)
        directory.mkdir(parents=True, exist_ok=False)
        manifest = self.manifest()
        payload = canonical_bytes(manifest) + b"\n"
        (directory / "router.json").write_bytes(payload)
        return {
            "manifest": manifest,
            "manifest_bytes": len(payload),
            "manifest_sha256": hashlib.sha256(payload).hexdigest(),
        }


class LiteralRouter(TypedRouter):
    """Find one whole domain identifier in text; ambiguity and absence abstain."""

    def __init__(self, domains):
        super().__init__(domains)
        self.patterns = [
            (
                name,
                re.compile(
                    r"(?<![\w.-])"
                    + re.escape(unicodedata.normalize("NFKC", name).casefold())
                    + r"(?![\w.-])"
                ),
            )
            for name in self.domains
        ]

    def route(self, queries):
        result = []
        for query in _queries(queries):
            text = query.text
            if not isinstance(text, str) or not text.strip() or len(text) > 16384:
                raise ValueError("each text must contain 1..16384 characters")
            normalized = unicodedata.normalize("NFKC", text).casefold()
            matches = [
                name for name, pattern in self.patterns if pattern.search(normalized)
            ]
            result.append(matches[0] if len(matches) == 1 else None)
        return result

    def manifest(self):
        manifest = super().manifest()
        manifest.update(
            kind="literal-domain-parser",
            inference_inputs=["query.text"],
            unknown_domain_policy="abstain-on-absence-or-ambiguity",
            normalization="NFKC-casefold-whole-identifier",
        )
        return manifest


class LearnedRouter:
    """A small text classifier trained only on write-time domain labels."""

    def __init__(self, domains, encoder=None, rank=4, seed=0, threshold=0.0):
        self.domains = _domains(domains)
        if len(self.domains) < 2:
            raise ValueError("learned routing requires at least two domains")
        if not np.isfinite(threshold) or not 0 <= threshold <= 1:
            raise ValueError("threshold must be finite and in [0, 1]")
        self.encoder = FrozenEncoder(128, seed) if encoder is None else encoder
        self.model = MemoryCell(self.encoder.dim, rank, len(self.domains), seed)
        self.threshold = float(threshold)
        self.training_query_digest = None

    @property
    def parameter_bytes(self):
        return self.model.parameter_bytes

    def fit(self, train_queries, steps=600, lr=0.03):
        queries = _queries(train_queries)
        if not queries:
            raise ValueError("training queries are required")
        if any(getattr(query, "split", "train") != "train" for query in queries):
            raise ValueError("router fit only accepts training queries")
        indices = {domain: index for index, domain in enumerate(self.domains)}
        labels = [query.domain for query in queries]
        if set(labels) != set(self.domains):
            raise ValueError("declared domains must match training labels")
        texts = [query.text for query in queries]
        started = time.perf_counter()
        features = self.encoder.encode(texts)
        encoding_seconds = time.perf_counter() - started
        targets = np.array([indices[label] for label in labels], dtype=np.int64)
        receipt = self.model.fit(features, targets, steps=steps, lr=lr)
        self.training_query_digest = hashlib.sha256(
            canonical_bytes(
                [{"text": text, "domain": label} for text, label in zip(texts, labels)]
            )
        ).hexdigest()
        receipt.update(
            encoding_seconds=encoding_seconds,
            training_query_digest=self.training_query_digest,
            training_labels="domain-only",
            domain_vocabulary_bytes=len(canonical_bytes(self.domains)),
            calibrated=False,
        )
        return receipt

    def scores(self, queries):
        """Uncalibrated softmax scores; no oracle domain or memory answer is read."""
        texts = [query.text for query in _queries(queries)]
        return self.model.proba(self.encoder.encode(texts))

    def route(self, queries):
        result = []
        for row in self.scores(queries):
            index = int(row.argmax())
            result.append(self.domains[index] if row[index] >= self.threshold else None)
        return result

    def manifest(self):
        return {
            "schema": "hepta.memory-cell.router.v1",
            "kind": "learned-text-domain",
            "domains": list(self.domains),
            "domain_vocabulary_bytes": len(canonical_bytes(self.domains)),
            "encoder": self.encoder.manifest(),
            "encoder_digest": self.encoder.digest,
            "rank": self.model.rank,
            "trainable_params": self.model.trainable_params,
            "parameter_bytes": self.parameter_bytes,
            "threshold": self.threshold,
            "training_query_digest": self.training_query_digest,
            "inference_inputs": ["query.text"],
            "calibrated": False,
            "unknown_domain_policy": "no-guarantee-uncalibrated-score-threshold",
        }

    def save(self, directory):
        directory = Path(directory)
        directory.mkdir(parents=True, exist_ok=False)
        lineage = (
            {}
            if self.training_query_digest is None
            else {"dataset": self.training_query_digest}
        )
        model_manifest = self.model.save(
            directory / "model",
            encoder_manifest=self.encoder.manifest(),
            lineage=lineage,
        )
        manifest = self.manifest()
        manifest["model_manifest_sha256"] = model_manifest["manifest_sha256"]
        payload = canonical_bytes(manifest) + b"\n"
        (directory / "router.json").write_bytes(payload)
        return {
            "manifest": manifest,
            "manifest_bytes": len(payload),
            "manifest_sha256": hashlib.sha256(payload).hexdigest(),
            "model_manifest": model_manifest,
        }
