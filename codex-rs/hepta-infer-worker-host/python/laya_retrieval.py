"""Experimental read-only Laya driver. No server, dispatcher, trainer or authority.

The existing inference owner must schedule/cancel the worker, bind its operation,
verify source access, and persist the returned observation before publication.
This module deliberately does not implement an alternative execution journal.
"""
from __future__ import annotations

import hashlib
import importlib.metadata
import json
import math
import os
from pathlib import Path
import re
import threading
import time
from typing import Any, Protocol

FORMAT = "hepta.laya.retrieval.v1"
INSTRUCTION = "Which source best supports answering the query? Select abstain when none does."
REQUIRED_FILES = {"model.safetensors", "rl_agent_config.json", "encoder/config.json",
                  "tokenizer/tokenizer.json", "tokenizer/tokenizer_config.json"}
REQUIRED_PACKAGES = {"laya", "torch", "transformers", "tokenizers", "safetensors"}
HEX64 = re.compile(r"[0-9a-f]{64}\Z")
ID = re.compile(r"[A-Za-z0-9_.:-]{1,128}\Z")


class Rejected(ValueError):
    """Malformed, unsupported or stale work; never an execution success."""


class EnteredFailure(RuntimeError):
    """Model entry occurred. The owner must not classify this as unused work."""
    def __init__(self, reason: str, elapsed: float):
        super().__init__(reason)
        self.elapsed_seconds = elapsed


class Agent(Protocol):
    """Only a preloaded, owner-selected Laya predictor may implement this port."""
    tok: Any
    cfg: dict[str, Any]

    def predict(self, state: str, questions: dict[str, Any], **kwargs: Any) -> dict[str, Any]: ...


def encoded(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"),
                      allow_nan=False).encode("utf-8")


def digest(value: Any) -> str:
    return hashlib.sha256(encoded(value)).hexdigest()


def object_keys(value: Any, keys: set[str]) -> None:
    if not isinstance(value, dict) or set(value) != keys:
        raise Rejected("unknown or missing critical fields")


def text(value: Any, limit: int) -> str:
    if not isinstance(value, str) or not value or len(value.encode("utf-8")) > limit:
        raise Rejected("invalid text or byte bound")
    return value


def identifier(value: Any) -> str:
    if not isinstance(value, str) or not ID.fullmatch(value):
        raise Rejected("invalid identity")
    return value


def sha256(value: Any) -> str:
    if not isinstance(value, str) or not HEX64.fullmatch(value) or value == "0" * 64:
        raise Rejected("invalid SHA-256 identity")
    return value


def checkpoint_identity(root: Path, pins: dict[str, Any]) -> str:
    """Check all bytes, not only weights. Pins are identity, not artifact authority.

    The host must supply an immutable, isolated artifact directory. Path checks
    and before/after hashing are not a sandbox against concurrent hostile writers.
    """
    object_keys(pins, {"repository", "revision", "files", "runtime_versions", "format"})
    if pins["format"] != FORMAT or pins["repository"] != "convaiinnovations/laya":
        raise Rejected("unsupported model or format")
    if not isinstance(pins["revision"], str) or not re.fullmatch(r"[0-9a-f]{40}", pins["revision"]):
        raise Rejected("checkpoint requires an immutable revision")
    files = pins["files"]
    if not isinstance(files, dict) or not REQUIRED_FILES <= set(files) or len(files) > 128:
        raise Rejected("incomplete or excessive checkpoint inventory")
    if root.is_symlink() or not root.is_dir() or root.resolve() != root:
        raise Rejected("checkpoint must be an absolute canonical directory")
    actual = set()
    total_bytes = 0
    for index, path in enumerate(root.rglob("*")):
        if index >= 256:
            raise Rejected("checkpoint entry bound")
        if path.is_symlink() or (not path.is_file() and not path.is_dir()):
            raise Rejected("checkpoint contains a link or special file")
        if path.is_file():
            total_bytes += path.stat().st_size
            if total_bytes > 4 * 1024**3:
                raise Rejected("checkpoint byte bound")
            actual.add(path.relative_to(root).as_posix())
    if actual != set(files):
        raise Rejected("checkpoint inventory drift")
    for name, expected in files.items():
        sha256(expected)
        # Inventory equality above rejects absolute paths, traversal and aliases.
        with (root / name).open("rb") as stream:
            value = hashlib.file_digest(stream, "sha256").hexdigest()
        if value != expected:
            raise Rejected("checkpoint byte drift")
    versions = pins["runtime_versions"]
    if not isinstance(versions, dict) or set(versions) != REQUIRED_PACKAGES:
        raise Rejected("incomplete runtime version profile")
    for name, version in versions.items():
        if importlib.metadata.version(name) != version:
            raise Rejected("runtime version drift")
    if versions["laya"] != "0.3.20":
        raise Rejected("unsupported Laya API version")
    return digest(pins)


def load_pinned(root: Path, pins: dict[str, Any]) -> tuple[Agent, str]:
    """Load only owner-prepared local artifacts, without mutable Hub selection."""
    if os.environ.get("HF_HUB_OFFLINE") != "1" or os.environ.get("TRANSFORMERS_OFFLINE") != "1":
        raise Rejected("worker must be launched in offline mode")
    identity = checkpoint_identity(root, pins)
    tokenizer_config = json.loads((root / "tokenizer/tokenizer_config.json").read_text())
    if tokenizer_config.get("tokenizer_class") in (None, "TokenizersBackend") or isinstance(
            tokenizer_config.get("extra_special_tokens"), list):
        raise Rejected("tokenizer needs an explicitly versioned preparation, not load-time rewriting")
    import laya
    agent = laya.load(str(root), device="cpu", fast=False)
    if checkpoint_identity(root, pins) != identity:
        raise Rejected("loader changed selected artifacts")
    agent.model.eval()
    return agent, identity


def prepare(raw: bytes) -> tuple[dict[str, Any], str, dict[str, Any]]:
    if not isinstance(raw, bytes) or not 1 <= len(raw) <= 32_768:
        raise Rejected("request byte bound")
    def pairs(items: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in items:
            if key in result:
                raise Rejected("duplicate JSON field")
            result[key] = value
        return result
    def invalid_constant(_: str) -> None:
        raise Rejected("non-finite JSON number")
    try:
        request = json.loads(raw, object_pairs_hook=pairs, parse_constant=invalid_constant)
    except (UnicodeError, json.JSONDecodeError, RecursionError) as error:
        raise Rejected("invalid request JSON") from error
    object_keys(request, {"format", "operation_id", "scope", "objective_digest",
                          "snapshot_digest", "query", "candidates"})
    if request["format"] != FORMAT:
        raise Rejected("unsupported request format")
    identifier(request["operation_id"])
    identifier(request["scope"])
    sha256(request["objective_digest"])
    sha256(request["snapshot_digest"])
    text(request["query"], 4096)
    candidates = request["candidates"]
    if not isinstance(candidates, list) or not 1 <= len(candidates) <= 8:
        raise Rejected("candidate count outside pilot bounds")
    seen = set()
    criteria = {"abstain": "No listed source supports the query."}
    for candidate in candidates:
        object_keys(candidate, {"id", "source_digest", "excerpt"})
        key = identifier(candidate["id"])
        if key == "abstain" or key in seen:
            raise Rejected("duplicate or reserved candidate identity")
        seen.add(key)
        sha256(candidate["source_digest"])
        # The owner deliberately selects bounded excerpts; this driver never
        # shortlists, silently clips or pretends the excerpt is the whole source.
        criteria[key] = text(candidate["excerpt"], 2048)
    return request, request["query"], {"source": {"type": "choice", "instructions": INSTRUCTION,
                                                "criteria": criteria}}


def token_budget(agent: Agent, state: str, question: dict[str, Any],
                 max_len: int, head_max_len: int) -> int:
    """Reject every truncation site in pinned Laya common.build_sequence."""
    if type(max_len) is not int or type(head_max_len) is not int or not (
            32 <= head_max_len < max_len <= 4096):
        raise Rejected("invalid token profile")
    if max_len > agent.cfg.get("max_len", 512) or head_max_len > agent.cfg.get("head_max_len", 192):
        raise Rejected("profile exceeds checkpoint limits")
    tok = agent.tok
    mask = tok.mask_token
    def count(value: str) -> int:
        if not isinstance(mask, str) or mask in value:
            raise Rejected("mask-token substitution is not admitted")
        return len(tok(value, add_special_tokens=False, truncation=False)["input_ids"])
    head = count("choice question: " + question["instructions"])
    options = [count(" " + key + ": " + value) for key, value in question["criteria"].items()]
    if any(value > 48 for value in options):
        raise Rejected("option would be truncated")
    option_total = sum(value + 1 for value in options)
    if head_max_len - option_total < max(16, head):
        raise Rejected("question or options would be truncated")
    total = 4 + head + option_total + count(state)
    if total > max_len:
        raise Rejected("query would be truncated")
    return total


class RetrievalDriver:
    """Serialized prediction only; no claim of cross-process resource fencing."""
    def __init__(self, agent: Agent, model_digest: str, max_len: int, head_max_len: int):
        self._agent = agent
        self._model_digest = sha256(model_digest)
        self._max_len = max_len
        self._head_max_len = head_max_len
        self._lock = threading.Lock()

    def predict(self, raw: bytes, deadline: float) -> dict[str, Any]:
        # Deadline is a host-supplied monotonic absolute deadline, not a field
        # supplied by model input or a timeout reset on each retry.
        if not isinstance(deadline, (int, float)) or not math.isfinite(deadline):
            raise Rejected("invalid deadline")
        request, state, questions = prepare(raw)
        if time.monotonic() >= deadline:
            raise Rejected("expired before inference")
        if not self._lock.acquire(blocking=False):
            raise Rejected("worker capacity occupied")
        started = None
        try:
            tokens = token_budget(self._agent, state, questions["source"],
                                  self._max_len, self._head_max_len)
            if time.monotonic() >= deadline:
                raise Rejected("expired before model entry")
            started = time.monotonic()
            result = self._agent.predict(state, questions, max_len=self._max_len,
                                         head_max_len=self._head_max_len)
            elapsed = time.monotonic() - started
            if time.monotonic() >= deadline:
                # Work may have consumed resources; the host must record it and
                # reconcile. Do not release a durable reservation as unexecuted.
                raise TimeoutError("inference entered; result arrived after deadline")
            answer = result["answers"]["source"]
            probabilities = answer["probabilities"]
            if not isinstance(probabilities, dict) or set(probabilities) != set(questions["source"]["criteria"]):
                raise Rejected("model changed the complete candidate set")
            if any(type(p) not in (int, float) or not math.isfinite(p) or not 0 <= p <= 1
                   for p in probabilities.values()) or abs(sum(probabilities.values()) - 1) > 0.002:
                raise Rejected("invalid prediction distribution")
            if answer["choice"] not in probabilities:
                raise Rejected("unknown model selection")
            # The host policy owns deterministic tie-breaking in admitted order.
            selected = max(questions["source"]["criteria"], key=probabilities.__getitem__)
            # Ignore act_probability, self-reported success and raw confidence.
            observation = {"format": FORMAT, "operation_id": request["operation_id"],
                           "scope": request["scope"], "input_digest": digest(request),
                           "model_digest": self._model_digest, "objective_digest": request["objective_digest"],
                           "snapshot_digest": request["snapshot_digest"],
                           "candidates": [{"id": item["id"], "source_digest": item["source_digest"]}
                                          for item in request["candidates"]], "selected": selected,
                           "prediction": probabilities, "behavior": "deterministic_argmax_v1",
                           "selected_propensity": 1, "input_tokens_preflight": tokens,
                           "latency_seconds": elapsed, "authority": False,
                           "calibration_verified": False, "task_success": None}
            observation["receipt_digest"] = digest(observation)
            return observation
        except Exception as error:
            if started is not None:
                raise EnteredFailure("model entered without a publishable result",
                                     time.monotonic() - started) from error
            raise
        finally:
            self._lock.release()


def main() -> None:
    """One-shot qualification entry. Production scheduling remains unwired."""
    import argparse
    import sys
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--checkpoint", type=Path, required=True)
    parser.add_argument("--pins", type=Path, required=True)
    parser.add_argument("--max-len", type=int, default=512)
    parser.add_argument("--head-max-len", type=int, default=192)
    args = parser.parse_args()
    pins_bytes = args.pins.read_bytes()
    if len(pins_bytes) > 65536:
        raise Rejected("pin manifest byte bound")
    pins = json.loads(pins_bytes)
    raw = sys.stdin.buffer.read(32769)
    prepare(raw)
    agent, identity = load_pinned(args.checkpoint, pins)
    driver = RetrievalDriver(agent, identity, args.max_len, args.head_max_len)
    # Qualification process only: the production caller supplies its conserved
    # deadline via predict(), never resets it with this one-shot test budget.
    result = driver.predict(raw, time.monotonic() + 30)
    print(encoded(result).decode("utf-8"))


if __name__ == "__main__":
    main()
