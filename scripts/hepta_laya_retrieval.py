#!/usr/bin/env python3
"""Pinned, offline Laya retrieval experiment; not a production execution owner.

This leaf consumes already-authorized immutable records and returns only scores.
Inference reservation/recovery, source authorization/revocation, artifact adoption
and final context revalidation remain with the existing native owners. There is
no daemon, durable store, authority token, tool call or automatic retry here.
"""
from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
import hashlib
from importlib import metadata
import json
import math
import os
from pathlib import Path
import re
import stat
import sys
import time
from typing import Any, Callable, Mapping, Protocol

SDK_VERSION = "0.3.20"
OBSERVED_MODEL_REVISION = "55cf4c4ebb4ebe31b2550e8bdf3bd21b99753851"
FORMAT = "hepta.laya.retrieval.v1"
QUESTION = "Which source best supports answering the query? Abstain if none does."
REQUIRED_FILES = frozenset({
    "model.safetensors", "encoder/config.json", "rl_agent_config.json",
    "tokenizer/tokenizer.json", "tokenizer/tokenizer_config.json",
})
PACKAGES = ("laya", "torch", "transformers", "tokenizers", "safetensors", "numpy", "huggingface_hub")


class Rejected(ValueError):
    """No valid result was produced; the caller must not fabricate success."""


def canonical(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
                      allow_nan=False).encode("utf-8")


def digest(value: Any) -> str:
    return hashlib.sha256(canonical(value)).hexdigest()


def require_digest(value: str) -> None:
    if not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{64}", value) or value == "0" * 64:
        raise Rejected("invalid SHA-256")


def identity(value: str) -> None:
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:/-]{0,127}", value):
        raise Rejected("invalid identity")


def integer(value: int, low: int, high: int) -> None:
    if type(value) is not int or not low <= value <= high:
        raise Rejected("integer outside profile")


def strict_json(data: str | bytes) -> Any:
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise Rejected("duplicate JSON key")
            result[key] = value
        return result
    def constant(_):
        raise Rejected("non-finite JSON")
    return json.loads(data, object_pairs_hook=pairs, parse_constant=constant)


@dataclass(frozen=True)
class Source:
    source_id: str
    revision: int
    content_sha256: str
    text: str

    def validate(self) -> None:
        identity(self.source_id)
        integer(self.revision, 1, 2**63 - 1)
        require_digest(self.content_sha256)
        if not isinstance(self.text, str) or not self.text or len(self.text.encode("utf-8")) > 2048:
            raise Rejected("source text outside profile")
        if hashlib.sha256(self.text.encode("utf-8")).hexdigest() != self.content_sha256:
            raise Rejected("source bytes changed")


@dataclass(frozen=True)
class Request:
    operation_id: str
    workspace_id: str
    generation: int
    objective_digest: str
    observation_digest: str
    bundle_digest: str
    deadline_ms: int
    query: str
    sources: tuple[Source, ...]

    def validate(self, now_ms: int) -> None:
        identity(self.operation_id)
        identity(self.workspace_id)
        integer(self.generation, 1, 2**63 - 1)
        integer(self.deadline_ms, 1, 2**63 - 1)
        integer(now_ms, 0, 2**63 - 1)
        for value in (self.objective_digest, self.observation_digest, self.bundle_digest):
            require_digest(value)
        if now_ms >= self.deadline_ms:
            raise Rejected("expired before dispatch")
        if not isinstance(self.query, str) or not self.query or len(self.query.encode("utf-8")) > 2048:
            raise Rejected("query outside profile")
        if not isinstance(self.sources, tuple) or not 1 <= len(self.sources) <= 15:
            raise Rejected("source count outside profile")
        for source in self.sources:
            source.validate()
        if len({s.source_id for s in self.sources}) != len(self.sources):
            raise Rejected("duplicate source")


def encode(request: Request) -> tuple[str, dict[str, Any], tuple[str | None, ...]]:
    # Owner order remains bound in the request digest. Model order is canonical,
    # and includes a real abstain option, never a post-hoc fabricated score.
    sources = sorted(request.sources, key=lambda s: s.source_id)
    labels: tuple[str | None, ...] = (None, *(s.source_id for s in sources))
    criteria = {"c0": "No source supports answering the query."}
    criteria.update({f"c{i}": source.text for i, source in enumerate(sources, 1)})
    state = canonical({"query": request.query}).decode("utf-8")
    questions = {"source": {"type": "choice", "instructions": QUESTION, "criteria": criteria}}
    return state, questions, labels


def probability_ppm(raw: Mapping[str, Any], labels: tuple[str | None, ...]) -> tuple[int, ...]:
    expected = [f"c{i}" for i in range(len(labels))]
    if not isinstance(raw, dict) or set(raw) != set(expected):
        raise Rejected("incomplete or unknown model options")
    values = [raw[key] for key in expected]
    if any(type(v) not in (int, float) or not math.isfinite(v) or not 0 <= v <= 1 for v in values):
        raise Rejected("invalid model probability")
    total = math.fsum(values)
    # Laya 0.3.20 rounds each marginal to four decimal places.
    if total <= 0 or abs(total - 1) > len(values) * 0.0000501:
        raise Rejected("probability mass is not normalized")
    scaled = [v / total * 1_000_000 for v in values]
    result = [math.floor(v) for v in scaled]
    remainder = 1_000_000 - sum(result)
    for index in sorted(range(len(values)), key=lambda i: (-(scaled[i] - result[i]), i))[:remainder]:
        result[index] += 1
    return tuple(result)


class PredictionPort(Protocol):
    """Score one bounded request; a test double is never a real-model receipt."""

    bundle_digest: str

    def predict(self, state: str, questions: dict[str, Any]) -> dict[str, Any]: ...


def score(request: Request, port: PredictionPort, *, now_ms: Callable[[], int],
          current: Callable[[Request], bool]) -> dict[str, Any]:
    """Return an advisory result only after owner-currentness checks at both ends.

    `current` must be supplied by the embedding source/registry owner, not the
    model. This callback is not a sealed capability or production authorization.
    The native consumer must revalidate again at final use, including on replay.
    """
    request.validate(now_ms())
    if port.bundle_digest != request.bundle_digest:
        raise Rejected("inference port belongs to another model bundle")
    if current(request) is not True:
        raise Rejected("source or bundle withdrawn before inference")
    state, questions, labels = encode(request)
    start = time.perf_counter_ns()
    raw = port.predict(state, questions)
    elapsed_us = (time.perf_counter_ns() - start) // 1000
    # Never turn timeout, exception, drift or withdrawal into an empty success.
    if now_ms() >= request.deadline_ms:
        raise Rejected("deadline exceeded; inference cost must still be reconciled")
    if current(request) is not True:
        raise Rejected("source or bundle withdrawn during inference")
    try:
        answer = raw["answers"]["source"]
        if answer["type"] != "choice":
            raise Rejected("wrong model answer type")
        probabilities = probability_ppm(answer["probabilities"], labels)
        # Deterministic policy is separately recorded, not the prediction q.
        selected = max(range(len(labels)), key=lambda i: (probabilities[i], -i))
        if answer["choice"] not in answer["probabilities"]:
            raise Rejected("unknown selected model option")
        usage = raw["usage"]
        integer(usage["input_tokens"], 1, 131072)
        integer(usage["output_tokens"], 0, 131072)
    except (KeyError, TypeError, IndexError) as error:
        raise Rejected("malformed model result") from error
    result = {
        "schema": FORMAT,
        "operation_id": request.operation_id,
        "request_digest": digest(asdict(request)),
        "observation_digest": request.observation_digest,
        "bundle_digest": request.bundle_digest,
        "generation": request.generation,
        "workspace_id": request.workspace_id,
        "model_input_digest": digest({"state": state, "questions": questions}),
        "labels": labels,
        "prediction_ppm": probabilities,
        "selected_source": labels[selected],
        "behavior_policy": "canonical_argmax_abstain_tie_v1",
        "selected_behavior_propensity_ppm": 1_000_000,
        "latency_us": elapsed_us,
        "input_tokens": usage["input_tokens"],
        "output_tokens": usage["output_tokens"],
        "production_authority": False,
    }
    result["result_digest"] = digest(result)
    return result


def file_digests(root: Path) -> dict[str, str]:
    if root.is_symlink() or not root.is_dir():
        raise Rejected("model root must be a materialized local directory")
    # Tokenizer and encoder loaders can consume optional configuration files.
    # Bind every file in both subtrees, not just the five mandatory artifacts.
    names = set(REQUIRED_FILES)
    for directory in (root / "tokenizer", root / "encoder"):
        if directory.is_symlink():
            raise Rejected("model symlink is not a pinned materialized bundle")
        for entry in directory.rglob("*"):
            if entry.is_symlink():
                raise Rejected("model symlink is not a pinned materialized bundle")
            if not entry.is_dir():
                names.add(entry.relative_to(root).as_posix())
            if len(names) > 64:
                raise Rejected("too many model artifacts")
    result = {}
    for name in sorted(names):
        path = root / name
        if any(p.is_symlink() for p in (path, *path.parents)):
            raise Rejected("model symlink is not a pinned materialized bundle")
        if not stat.S_ISREG(path.stat().st_mode):
            raise Rejected("model artifact is not a regular file")
        with path.open("rb") as stream:
            before = os.fstat(stream.fileno())
            if not stat.S_ISREG(before.st_mode) or before.st_size > 4 * 1024**3:
                raise Rejected("model artifact outside file profile")
            checksum = hashlib.sha256()
            for block in iter(lambda: stream.read(1024 * 1024), b""):
                checksum.update(block)
            after = os.fstat(stream.fileno())
            if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
                raise Rejected("model artifact changed while hashing")
            result[name] = checksum.hexdigest()
    return result


def lock_bundle(root: Path, revision: str, max_len: int, head_max_len: int) -> dict[str, Any]:
    if not re.fullmatch(r"[0-9a-f]{40}", revision) or revision == "0" * 40:
        raise Rejected("an exact upstream model revision is required")
    integer(max_len, 64, 8192)
    integer(head_max_len, 32, max_len - 8)
    versions = {name: metadata.version(name) for name in PACKAGES}
    if versions["laya"] != SDK_VERSION:
        raise Rejected("unsupported Laya SDK revision")
    return {"schema": "hepta.laya.bundle.v1", "upstream_revision": revision,
            "files": file_digests(root), "packages": versions, "device": "cpu",
            "dtype": "float32", "max_len": max_len, "head_max_len": head_max_len,
            "input_format": FORMAT, "question_digest": digest(QUESTION)}


class PinnedLaya:
    """CPU-only experimental driver; no router, hidden model switch or retries.

    The caller must supply an immutable local bundle and offline runtime. This
    does not attest the host, measure power, or authorize production model use.
    A private SDK encoding API is intentionally pinned to 0.3.20; an SDK change
    needs new conformance, not a permissive fallback.
    """

    def __init__(self, root: Path, pin: dict[str, Any], expected_digest: str):
        require_digest(expected_digest)
        if digest(pin) != expected_digest:
            raise Rejected("bundle manifest digest mismatch")
        if set(pin) != {"schema", "upstream_revision", "files", "packages", "device", "dtype",
                        "max_len", "head_max_len", "input_format", "question_digest"}:
            raise Rejected("unknown or missing bundle fields")
        if pin != lock_bundle(root, pin["upstream_revision"], pin["max_len"], pin["head_max_len"]):
            raise Rejected("runtime or model artifact differs from the fixed bundle")
        if os.environ.get("HF_HUB_OFFLINE") != "1" or os.environ.get("TRANSFORMERS_OFFLINE") != "1":
            raise Rejected("offline environment must be set before loading the SDK")
        config = strict_json((root / "tokenizer/tokenizer_config.json").read_bytes())
        if config.get("tokenizer_class") in (None, "TokenizersBackend") or isinstance(config.get("extra_special_tokens"), list):
            raise Rejected("SDK would rewrite tokenizer; normalize a separate bundle then repin it")
        from laya import Agent
        self._agent = Agent(str(root.resolve()), device="cpu", fast=False, compile=False,
                            expected_sha256=pin["files"])
        if file_digests(root) != pin["files"]:
            raise Rejected("SDK changed a pinned artifact during loading")
        if str(self._agent.device) != "cpu" or str(self._agent.dtype) != "torch.float32" or self._agent.amp_enabled:
            raise Rejected("unexpected runtime device or numerical mode")
        self._agent.model.requires_grad_(False)
        self._agent.model.eval()
        self.bundle_digest = expected_digest
        self.maximum_input_tokens = pin["max_len"]
        self._max_len = pin["max_len"]
        self._head_max_len = pin["head_max_len"]

    def predict(self, state: str, questions: dict[str, Any]) -> dict[str, Any]:
        import torch
        for key, question in questions.items():
            self._agent._check_question(key, question)
        internal = {key: self._agent._to_internal(value) for key, value in questions.items()}
        ids = list(questions)
        # Compare the complete encoding against the admitted bounded encoding.
        # Refuse silent truncation of either state or options before any forward.
        unbounded_limit = len(canonical({"state": state, "questions": questions})) * 4 + 1024
        if unbounded_limit > 262144:
            raise Rejected("encoded input preflight exceeds capacity")
        full = self._agent._encode_state(state, ids, internal, unbounded_limit, unbounded_limit // 2)
        bounded = self._agent._encode_state(state, ids, internal, self._max_len, self._head_max_len)
        if full != bounded:
            raise Rejected("input or candidate options would be truncated")
        with torch.inference_mode():
            return self._agent.system_one(state, questions, max_len=self._max_len,
                                          head_max_len=self._head_max_len)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model-root", required=True, type=Path)
    parser.add_argument("--revision", required=True)
    parser.add_argument("--max-len", type=int, default=512)
    parser.add_argument("--head-max-len", type=int, default=192)
    args = parser.parse_args()
    # Locking measures local files. It does not download or authenticate their
    # origin, authorize them, or grant independent model acceptance.
    print(canonical(lock_bundle(args.model_root, args.revision, args.max_len,
                                args.head_max_len)).decode("utf-8"))


if __name__ == "__main__":
    try:
        main()
    except (Rejected, OSError, metadata.PackageNotFoundError) as error:
        print(f"Laya profile unavailable: {error}", file=sys.stderr)
        raise SystemExit(2) from error
