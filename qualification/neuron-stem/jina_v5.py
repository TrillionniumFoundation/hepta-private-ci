#!/usr/bin/env python3
"""SHA-pinned, adapter-aware Jina v5 shadow-only embedding substrate.

No module import downloads weights or imports model code. The explicit caller
must authorize remote-code loading after reviewing the pinned revision.
Nothing in this module is a production model owner or authority receipt.
"""
from collections import OrderedDict
from dataclasses import dataclass
import hashlib
import json
import math
import re
import time

TASKS = ("retrieval", "classification", "text-matching", "clustering")
INTENTS = ("query", "document")
MODALITIES = ("text", "vision", "audio", "omni")


@dataclass(frozen=True)
class ModelSpec:
    repository: str
    family: str
    parameters: int
    dimensions: int
    max_tokens: int
    omni: bool


MODELS = {
    "jina-v5-text-nano": ModelSpec("jinaai/jina-embeddings-v5-text-nano", "nano", 239000000, 768, 8192, False),
    "jina-v5-text-small": ModelSpec("jinaai/jina-embeddings-v5-text-small", "small", 677000000, 1024, 32768, False),
    "jina-v5-omni-nano": ModelSpec("jinaai/jina-embeddings-v5-omni-nano", "nano", 1040000000, 768, 8192, True),
    "jina-v5-omni-small": ModelSpec("jinaai/jina-embeddings-v5-omni-small", "small", 1740000000, 1024, 32768, True),
}


def sha256_record(record):
    return hashlib.sha256(json.dumps(record, sort_keys=True, ensure_ascii=False,
                                    separators=(",", ":")).encode("utf-8")).hexdigest()


def research_environment():
    """Reproducibility metadata; never include usernames, machine IDs or secrets."""
    import importlib.metadata
    import os
    import platform
    import sys

    packages = {}
    for package in ("torch", "transformers", "sentence-transformers",
                    "peft", "psutil", "numpy"):
        try:
            packages[package] = importlib.metadata.version(package)
        except importlib.metadata.PackageNotFoundError:
            packages[package] = None
    return {
        "python": sys.version.split()[0],
        "os": platform.system(),
        "machine_arch": platform.machine(),
        "logical_cpu_count": os.cpu_count(),
        "dependency_versions": packages,
        "target_host_hardware_qualified": False,
    }


def validate_identity(model_id, revision, task, dimension, modality, max_tokens):
    if model_id not in MODELS:
        raise ValueError("unregistered Jina v5 model")
    if not isinstance(revision, str) or not re.fullmatch(r"[0-9a-f]{40}", revision):
        raise ValueError("model revision must be an immutable full 40-character lowercase SHA")
    if task not in TASKS:
        raise ValueError("unsupported v5 task adapter")
    spec = MODELS[model_id]
    if dimension not in (128, 256, 512, spec.dimensions) or dimension > spec.dimensions:
        raise ValueError("unsupported Matryoshka output dimension")
    if modality not in MODALITIES or (not spec.omni and modality != "text"):
        raise ValueError("modality is not available for model")
    if not isinstance(max_tokens, int) or not (16 <= max_tokens <= spec.max_tokens):
        raise ValueError("token limit exceeds verified model profile")
    return spec


def verify_vector_matrix(raw, count, original_dim, truncated_dim):
    """Verify full-width official embeddings before deterministic MRL truncate."""
    if hasattr(raw, "tolist"):
        raw = raw.tolist()
    if count == 1 and isinstance(raw, (list, tuple)) and raw and isinstance(raw[0], (int, float)):
        raw = [raw]
    if not isinstance(raw, (list, tuple)) or len(raw) != count:
        raise ValueError("model returned incorrect batch shape")
    result = []
    for vector in raw:
        if not isinstance(vector, (list, tuple)) or len(vector) != original_dim:
            raise ValueError("model returned unexpected embedding dimension")
        if not all(type(x) in (float, int) and math.isfinite(x) for x in vector):
            raise ValueError("non-finite embedding")
        selected = [float(x) for x in vector[:truncated_dim]]
        norm = math.sqrt(sum(x * x for x in selected))
        if not math.isfinite(norm) or norm < 1e-12:
            raise ValueError("zero/invalid embedding norm")
        result.append(tuple(x / norm for x in selected))
    return result


class FrozenJinaV5:
    """Single loaded Stem; exact-scope bounded feature cache; no implicit promotion."""

    def __init__(self, model_id, revision, *, task="classification", dimension=256,
                 modality="text", max_tokens=512, device="cpu",
                 allow_pinned_remote_code=False, allow_download=False,
                 cache_entries=256, model_factory=None):
        spec = validate_identity(model_id, revision, task, dimension, modality, max_tokens)
        if not allow_pinned_remote_code and model_factory is None:
            raise ValueError("remote model code requires reviewed, explicit opt-in")
        if type(cache_entries) is not int or not 1 <= cache_entries <= 8192:
            raise ValueError("cache entries outside bounded profile")
        self.spec, self.model_id, self.revision = spec, model_id, revision
        self.task, self.dimension, self.modality = task, dimension, modality
        self.max_tokens, self.cache_entries = max_tokens, cache_entries
        self.cache = OrderedDict()
        self.encoder_calls = self.encoder_examples = self.cache_hits = 0
        self.manifest_digest = sha256_record({
            "schema": "hepta.jina-v5-feature-manifest.v1",
            "repository": spec.repository, "revision": revision, "task": task,
            "dimension": dimension, "modality": modality,
            "max_tokens": max_tokens, "pool": "official-last-token-mrl-l2",
            "intent": "explicit-query-or-document",
        })
        start = time.perf_counter_ns()
        if model_factory is not None:
            self.model = model_factory(spec)
        else:
            from sentence_transformers import SentenceTransformer
            options = {"default_task": task}
            if spec.omni:
                options["modality"] = modality
            self.model = SentenceTransformer(
                spec.repository, revision=revision,
                trust_remote_code=True, device=device,
                local_files_only=not allow_download, model_kwargs=options,
            )
        # Models can expose distinct sequence-length knobs. Fail if there is
        # no usable task encoder; never substitute raw mean pooling.
        if not callable(getattr(self.model, "encode_document", None)) or not callable(
                getattr(self.model, "encode_query", None)):
            raise ValueError("required official query/document encoder unavailable")
        if hasattr(self.model, "max_seq_length"):
            self.model.max_seq_length = max_tokens
        if hasattr(self.model, "eval"):
            self.model.eval()
        self.load_ms = (time.perf_counter_ns() - start) / 1e6

    def _key(self, value, scope_id, principal_id, authority_epoch, generation, intent):
        # Omni paths can change while a filename stays the same. Disable
        # path-based caching even for apparently textual inputs in an Omni
        # instance; multimedia callers must never reuse stale media features.
        if self.spec.omni and self.modality != "text":
            return None
        if not isinstance(value, str) or not value:
            return None  # Mixed-modal tuples are never cached by path.
        if not all(isinstance(x, str) and x for x in (scope_id, principal_id)):
            raise ValueError("scope and principal are required")
        if type(authority_epoch) is not int or authority_epoch < 1:
            raise ValueError("invalid authority epoch")
        if type(generation) is not int or generation < 1:
            raise ValueError("invalid generation")
        return sha256_record([self.manifest_digest, scope_id, principal_id,
                              authority_epoch, generation, intent,
                              hashlib.sha256(value.encode("utf-8")).hexdigest()])

    def encode_batch(self, values, *, scope_id, principal_id, authority_epoch=1,
                     generation=1, intent="document", batch_size=8):
        if intent not in INTENTS or type(batch_size) is not int or batch_size < 1:
            raise ValueError("invalid intent/batch size")
        if not isinstance(values, (list, tuple)) or not values:
            raise ValueError("non-empty input batch required")
        if any(not isinstance(x, (str, tuple)) or not x for x in values):
            raise ValueError("invalid feature input")
        if not self.spec.omni and any(not isinstance(x, str) for x in values):
            raise ValueError("text-only encoder rejects multimodal input")
        if self.modality == "text" and any(not isinstance(x, str) for x in values):
            raise ValueError("text-only modality rejects multimodal input")
        # Scope, principal and generation are validated even when all inputs
        # are uncached multimedia.
        if not all(isinstance(x, str) and x for x in (scope_id, principal_id)):
            raise ValueError("scope and principal are required")
        if type(authority_epoch) is not int or authority_epoch < 1 or type(generation) is not int or generation < 1:
            raise ValueError("invalid scope authority/generation")
        keys = [self._key(x, scope_id, principal_id, authority_epoch, generation, intent) for x in values]
        result = [None] * len(values)
        pending, indices, pending_keys = [], [], set()
        per_batch_keys = {}
        hits = 0
        for i, (value, key) in enumerate(zip(values, keys)):
            if key is not None and key in self.cache:
                hits += 1
                result[i] = self.cache[key]
                self.cache.move_to_end(key)
            elif key is not None and key in per_batch_keys:
                indices.append((i, per_batch_keys[key]))
            else:
                slot = len(pending)
                pending.append(value)
                indices.append((i, slot))
                if key is not None:
                    per_batch_keys[key] = slot
        began = time.perf_counter_ns()
        freshly = []
        if pending:
            fn = self.model.encode_query if intent == "query" else self.model.encode_document
            for start in range(0, len(pending), batch_size):
                chunk = pending[start:start + batch_size]
                raw = fn(chunk, batch_size=len(chunk), convert_to_numpy=True,
                         show_progress_bar=False)
                freshly.extend(verify_vector_matrix(
                    raw, len(chunk), self.spec.dimensions, self.dimension))
                self.encoder_calls += 1
                self.encoder_examples += len(chunk)
            for key, index in per_batch_keys.items():
                self.cache[key] = freshly[index]
                self.cache.move_to_end(key)
                while len(self.cache) > self.cache_entries:
                    self.cache.popitem(last=False)
        for i, slot in indices:
            result[i] = freshly[slot]
        self.cache_hits += hits
        if any(v is None for v in result):
            raise RuntimeError("missing verified feature")
        return result, {
            "cache_hits": hits,
            "encoder_examples": len(pending),
            "encoder_batch_calls": math.ceil(len(pending) / batch_size),
            "encoder_wall_ms": (time.perf_counter_ns() - began) / 1e6,
            "feature_manifest_digest": self.manifest_digest,
            "feature_dimensions": self.dimension,
            "status": "research_backend_not_production_receipt",
        }
