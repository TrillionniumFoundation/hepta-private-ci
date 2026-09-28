"""Bounded, offline encoder + trained heads for the existing worker owner.

This CPU profile is stateless and advisory. The caller still owns selection,
current calibration trust, request/target identity, durable recovery and effects.
No qualification module, network download or remote model code is imported here.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import stat
import tempfile
import time
from typing import Any

import torch
from decision_cell_tensors import HeadTensorBundleV2, checked_bytes, strict_json

BASE_REPO = "microsoft/mdeberta-v3-base"
BASE_REVISION = "a0484667b22365f84929a935b5e50a51f71f159d"
BASE_FILES = frozenset(("README.md", "config.json", "pytorch_model.bin",
                        "spm.model", "tokenizer_config.json"))
MAX_BASE_BYTES = 2 * 1024**3
MAX_BATCH = 16
MAX_TEXT_BYTES = 16 * 1024
MAX_TARGET_BYTES = 4096
MAX_TOKENS = 192


def _canonical(value: Any) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":"),
                       ensure_ascii=False, allow_nan=False) + "\n").encode()


def _copy_base(source: Path, destination: Path, base: dict[str, Any]) -> None:
    """Copy admitted bytes, not paths/hardlinks, into a private loader directory."""
    if not source.is_absolute() or source.is_symlink() or not source.is_dir():
        raise ValueError("base must be an absolute non-symlink directory")
    if base.get("repo") != BASE_REPO or base.get("revision") != BASE_REVISION:
        raise ValueError("unsupported base identity")
    if base.get("trust_remote_code") is not False:
        raise ValueError("remote-code loading is not supported")
    files = base.get("files")
    if not isinstance(files, list) or len(files) != len(BASE_FILES):
        raise ValueError("incomplete base inventory")
    if hashlib.sha256(_canonical(files)).hexdigest() != base.get("snapshot_digest"):
        raise ValueError("base inventory digest mismatch")
    if any(not isinstance(row, dict) or set(row) != {"path", "bytes", "sha256"}
           for row in files):
        raise ValueError("invalid base inventory fields")
    if {row["path"] for row in files} != BASE_FILES:
        raise ValueError("unsupported or duplicate base path")
    if any(type(row["bytes"]) is not int or row["bytes"] <= 0 for row in files):
        raise ValueError("invalid base file size")
    if sum(row["bytes"] for row in files) > MAX_BASE_BYTES:
        raise ValueError("base inventory exceeds byte budget")
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
    for row in files:
        digest = hashlib.sha256()
        with os.fdopen(os.open(source / row["path"], flags), "rb") as src:
            before = os.fstat(src.fileno())
            if not stat.S_ISREG(before.st_mode) or before.st_size != row["bytes"]:
                raise ValueError("base file is not the admitted regular file")
            total = 0
            with (destination / row["path"]).open("xb") as dst:
                while chunk := src.read(min(1024**2, row["bytes"] + 1 - total)):
                    total += len(chunk)
                    if total > row["bytes"]:
                        raise ValueError("base file grew during snapshot copy")
                    digest.update(chunk)
                    dst.write(chunk)
            after = os.fstat(src.fileno())
            if (before.st_size, before.st_mtime_ns, before.st_ctime_ns) != (
                    after.st_size, after.st_mtime_ns, after.st_ctime_ns):
                raise ValueError("base changed during snapshot copy")
        if total != row["bytes"] or digest.hexdigest() != row["sha256"]:
            raise ValueError("base file content mismatch")
        (destination / row["path"]).chmod(0o400)


def _load_backbone(private_root: Path):
    from transformers import AutoModel, AutoTokenizer
    tokenizer = AutoTokenizer.from_pretrained(private_root, local_files_only=True,
                                              trust_remote_code=False, use_fast=False)
    model, loading = AutoModel.from_pretrained(private_root, local_files_only=True,
        trust_remote_code=False, weights_only=True, dtype=torch.float32, output_loading_info=True)
    expected_unused = {
        "deberta.embeddings.word_embeddings._weight",
        "lm_predictions.lm_head.LayerNorm.bias", "lm_predictions.lm_head.LayerNorm.weight",
        "lm_predictions.lm_head.bias", "lm_predictions.lm_head.dense.bias",
        "lm_predictions.lm_head.dense.weight", "mask_predictions.LayerNorm.bias",
        "mask_predictions.LayerNorm.weight", "mask_predictions.classifier.bias",
        "mask_predictions.classifier.weight", "mask_predictions.dense.bias",
        "mask_predictions.dense.weight",
    }
    if (loading.get("missing_keys") or loading.get("mismatched_keys") or
            loading.get("error_msgs") or set(loading.get("unexpected_keys", ())) != expected_unused):
        raise ValueError("backbone checkpoint load drift")
    model.to("cpu").eval().requires_grad_(False)
    return tokenizer, model


class FrozenMdebertaDecisionCellV2:
    """Real base/organ/cell/head execution; integrity is not artifact selection.

    This bounded CPU implementation has no temporal or parameter-value head.
    Deadlines prevent late publication; hard cancellation belongs to its process
    supervisor. The owner must serialize calls and supply current trusted digests.
    """
    def __init__(self, *, model_path: Path, manifest_path: Path, manifest_sha256: str,
                 weights_path: Path, weights_sha256: str, expected_base_snapshot: str,
                 expected_runtime_profile: dict[str, Any]):
        self._closed = True
        self._private = None
        self._model = None
        self._tokenizer = None
        self._heads = None
        self.forward_passes = 0
        self.base_snapshot_digest = expected_base_snapshot
        self.manifest_sha256 = manifest_sha256
        manifest = strict_json(checked_bytes(manifest_path, manifest_sha256, 256 * 1024))
        self._heads = HeadTensorBundleV2(
            manifest_path=manifest_path, manifest_sha256=manifest_sha256,
            weights_path=weights_path, weights_sha256=weights_sha256,
            expected_base_snapshot=expected_base_snapshot,
            expected_runtime_profile=expected_runtime_profile)
        try:
            self._private = tempfile.TemporaryDirectory(prefix="hepta-frozen-encoder-")
            _copy_base(model_path, Path(self._private.name), manifest["base_model"])
            self._tokenizer, self._model = _load_backbone(Path(self._private.name))
            self._closed = False
        except BaseException:
            self.close()
            raise

    def close(self) -> None:
        self._closed = True
        self._model = self._tokenizer = self._heads = None
        if self._private is not None:
            self._private.cleanup()
            self._private = None

    @staticmethod
    def _deadline(deadline_ns: int) -> None:
        if type(deadline_ns) is not int or time.monotonic_ns() >= deadline_ns:
            raise TimeoutError("DecisionCell deadline expired; no result publication")

    def _encode(self, texts: tuple[str, ...], deadline_ns: int) -> torch.Tensor:
        features = []
        for start in range(0, len(texts), 8):
            self._deadline(deadline_ns)
            encoded = self._tokenizer(list(texts[start:start + 8]), padding=True,
                                      truncation=False, return_tensors="pt")
            if encoded["input_ids"].shape[1] > MAX_TOKENS:
                raise ValueError("token budget exceeded; target text may not be truncated")
            with torch.inference_mode():
                hidden = self._model(**encoded).last_hidden_state
                mask = encoded["attention_mask"].unsqueeze(-1).to(hidden.dtype)
                pooled = (hidden * mask).sum(dim=1) / mask.sum(dim=1).clamp_min(1)
                features.append(pooled.float().cpu())
            self.forward_passes += 1
            self._deadline(deadline_ns)
        return torch.cat(features)

    def observe(self, texts: tuple[str, ...], candidates: tuple[tuple[str, ...], ...],
                *, deadline_ns: int) -> dict[str, Any]:
        """Return scored, source-bound advisory output without executing an effect."""
        if self._closed:
            raise RuntimeError("DecisionCell model session is closed")
        self._deadline(deadline_ns)
        if type(texts) is not tuple or not 1 <= len(texts) <= MAX_BATCH:
            raise ValueError("invalid immutable observation batch")
        if type(candidates) is not tuple or len(candidates) != len(texts):
            raise ValueError("candidate batch mismatch")
        if any(type(row) is not tuple or len(row) != 4 for row in candidates):
            raise ValueError("exactly four immutable candidate texts are required")
        for values, maximum in ((texts, MAX_TEXT_BYTES),
                                (tuple(c for row in candidates for c in row), MAX_TARGET_BYTES)):
            if any(type(value) is not str or not value or len(value.encode()) > maximum
                   for value in values):
                raise ValueError("invalid or oversized observation text")
        bound_input = _canonical({"projection_schema": "hepta.decision-cell-text-projection.v1",
                                  "texts": texts, "candidates": candidates})
        started = time.monotonic_ns()
        before = self.forward_passes
        state = self._encode(texts, deadline_ns)
        pairs = tuple(text + "\nCandidate under evaluation: " + candidate
                      for text, row in zip(texts, candidates) for candidate in row)
        targets = self._encode(pairs, deadline_ns).reshape(len(texts), 4, state.shape[1])
        outputs, probabilities = self._heads.observe_with_probabilities(state, targets)
        self._deadline(deadline_ns)
        return {"schema": "hepta.frozen-encoder-observation.v2",
                "input_sha256": hashlib.sha256(bound_input).hexdigest(),
                "base_snapshot_digest": self.base_snapshot_digest,
                "head_manifest_sha256": self.manifest_sha256,
                "scores": outputs, "probabilities": probabilities,
                "base_forward_passes": self.forward_passes - before,
                "latency_ns": time.monotonic_ns() - started,
                "advisory_only": True, "external_effect": False}
