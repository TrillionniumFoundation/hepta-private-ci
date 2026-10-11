"""Offline, *real-weight* joint-input Stem batch forward for P0 qualification.

Never downloads model weights or authorizes production use. A literal local
snapshot tree with all files SHA-256 pinned is required. Hugging Face models
whose architecture requires remote code fail closed. Intended targets are
mmBERT-small and ModernBERT-base; Jina v5 has a separate reviewed adapter.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import time
from pathlib import Path
from typing import Any

Q24 = 1 << 24
MAX_Q24 = 8 * Q24
MAX_BATCH = 32
MAX_INPUT_TOKENS = 8192
ALLOWLIST = {"jhu-clsp/mmBERT-small", "answerdotai/ModernBERT-base"}


class StemQualificationError(ValueError):
    """A missing artifact, ambiguous identity or incompatible output."""


def canonical_bytes(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def digest(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def rust_feature_digest_q24(features: list[int]) -> str:
    """Exactly codex_hepta_infer_core::shared_feature_v2::feature_content_digest_v2."""
    if not 1 <= len(features) <= 512 or any(abs(x) > MAX_Q24 for x in features):
        raise StemQualificationError("invalid feature for snapshot identity")
    payload = b"hepta.infer.shared-feature-content.v2"
    payload += len(features).to_bytes(8, "big")
    payload += b"".join(int(v).to_bytes(8, "big", signed=True) for v in features)
    return digest(payload)


def _is_safe_id(value: Any) -> bool:
    return isinstance(value, str) and bool(re.fullmatch(r"[a-zA-Z0-9_.:-]{1,128}", value))


def load_pinned_snapshot(manifest_path: Path) -> tuple[dict[str, Any], Path, str]:
    """Checks ALL local snapshot files (not only weights) before model loading.

    Snapshot symlinks, undeclared files, unreviewed Python and paths escaping
    the manifest directory are rejected. This manifest is not a signed CAS.
    """
    manifest_path = manifest_path.resolve(strict=True)
    root = manifest_path.parent
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if set(manifest) != {"model_id", "revision", "snapshot", "files", "max_tokens", "runtime"}:
        raise StemQualificationError("unexpected manifest fields")
    runtime = manifest["runtime"]
    if not isinstance(runtime, dict) or set(runtime) != {"torch", "transformers", "tokenizers", "safetensors"}:
        raise StemQualificationError("complete pinned Python inference runtime is required")
    if any(not isinstance(v, str) or not 1 <= len(v) <= 64
           or not re.fullmatch(r"[a-zA-Z0-9.+_-]+", v) for v in runtime.values()):
        raise StemQualificationError("invalid Python package revision")
    if manifest["model_id"] not in ALLOWLIST:
        raise StemQualificationError("model architecture not approved")
    if not isinstance(manifest["revision"], str) or not re.fullmatch("[0-9a-f]{40}", manifest["revision"]):
        raise StemQualificationError("exact 40-hex git revision required")
    if not isinstance(manifest["max_tokens"], int) or not 1 <= manifest["max_tokens"] <= MAX_INPUT_TOKENS:
        raise StemQualificationError("invalid declared token budget")
    relative = manifest["snapshot"]
    if not isinstance(relative, str) or not relative or Path(relative).is_absolute() or ".." in Path(relative).parts:
        raise StemQualificationError("snapshot path must be relative")
    snapshot = root / relative
    if snapshot.is_symlink():
        raise StemQualificationError("snapshot may not be a symlink")
    snapshot = snapshot.resolve(strict=True)
    if not snapshot.is_dir() or not snapshot.is_relative_to(root):
        raise StemQualificationError("snapshot outside manifest root")
    files = manifest["files"]
    if not isinstance(files, dict) or not files:
        raise StemQualificationError("nonempty file hash manifest required")
    expected: set[str] = set()
    weights = 0
    for name, expected_sha in files.items():
        if not isinstance(name, str) or Path(name).is_absolute() or ".." in Path(name).parts or "\\" in name:
            raise StemQualificationError("invalid artifact path")
        if not isinstance(expected_sha, str) or not re.fullmatch("[0-9a-f]{64}", expected_sha):
            raise StemQualificationError("invalid artifact digest")
        path = snapshot / name
        if not path.is_file() or path.is_symlink() or not path.resolve().is_relative_to(snapshot):
            raise StemQualificationError("unsafe or missing artifact")
        if path.suffix == ".py":
            raise StemQualificationError("custom model code requires a separate reviewed adapter")
        h = hashlib.sha256()
        with path.open("rb") as stream:
            for block in iter(lambda: stream.read(1024 * 1024), b""):
                h.update(block)
        if h.hexdigest() != expected_sha:
            raise StemQualificationError("artifact checksum mismatch")
        expected.add(name)
        if name.endswith(".safetensors"):
            weights += 1
    actual: set[str] = set()
    for item in snapshot.rglob("*"):
        if item.is_symlink():
            raise StemQualificationError("symlink inside snapshot")
        if item.is_file():
            actual.add(item.relative_to(snapshot).as_posix())
    if actual != expected or weights == 0:
        raise StemQualificationError("unlisted/missing snapshot files or safetensors")
    pipeline_digest = digest(
        b"hepta.stem.offline.pipeline.v1" + canonical_bytes({
            "model_id": manifest["model_id"],
            "revision": manifest["revision"],
            "files": files,
            "max_tokens": manifest["max_tokens"],
            "runtime": runtime,
            "pooling": "attention-mask-mean-v1",
            "quantization": "ties-even-q24-v1",
        })
    )
    return manifest, snapshot, pipeline_digest


def joint_text(sample: dict[str, Any]) -> str:
    if set(sample) != {"question", "options", "state"}:
        raise StemQualificationError("joint question/options/state required")
    question, options, state = sample["question"], sample["options"], sample["state"]
    if not isinstance(question, str) or not question or len(question) > 30_000:
        raise StemQualificationError("bad question")
    if not isinstance(options, list) or not 1 <= len(options) <= 32:
        raise StemQualificationError("bad option count")
    if any(not isinstance(item, str) or not item or len(item) > 4_000 for item in options):
        raise StemQualificationError("bad option")
    if not isinstance(state, str) or len(state) > 30_000:
        raise StemQualificationError("bad state")
    # Typed canonical JSON prevents ambiguous concatenation and option loss.
    return canonical_bytes(sample).decode("utf-8")


def verify_request(request: dict[str, Any]) -> tuple[tuple[Any, ...], str]:
    required = {"scope_id", "principal_id", "purpose_id", "cell_id", "generation",
                "authority_epoch", "input"}
    if not isinstance(request, dict) or set(request) != required:
        raise StemQualificationError("exact request envelope required")
    for field in ("scope_id", "principal_id", "purpose_id", "cell_id"):
        if not _is_safe_id(request[field]):
            raise StemQualificationError("invalid identity")
    for field in ("generation", "authority_epoch"):
        if type(request[field]) is not int or request[field] < 1:
            raise StemQualificationError("invalid generation or authority epoch")
    text = joint_text(request["input"])
    # No cross-principal, purpose, generation or authority-epoch alias.
    key = (
        request["scope_id"], request["principal_id"], request["purpose_id"],
        request["generation"], request["authority_epoch"],
        digest(canonical_bytes(request["input"])),
    )
    return key, text


def quantize_q24(features: list[float]) -> list[int]:
    import math
    values = []
    if not 1 <= len(features) <= 512:
        raise StemQualificationError("requires an explicitly compatible <=512-d feature")
    for feature in features:
        if not isinstance(feature, (int, float)) or not math.isfinite(feature) or abs(feature) > 8:
            raise StemQualificationError("nonfinite or out-of-bound feature")
        # Python round has ties-to-even; Rust Q24 uses the same rule.
        value = round(feature * Q24)
        if abs(value) > MAX_Q24:
            raise StemQualificationError("Q24 bounds")
        values.append(value)
    return values


class OfflineSharedStem:
    """One loaded model, one physical forward per distinct-input batch."""

    def __init__(self, manifest_path: Path):
        self.manifest, self.snapshot, self.pipeline_digest = load_pinned_snapshot(manifest_path)
        os.environ["HF_HUB_OFFLINE"] = "1"
        os.environ["TRANSFORMERS_OFFLINE"] = "1"
        try:
            from importlib import metadata
            for package, expected in self.manifest["runtime"].items():
                if metadata.version(package) != expected:
                    raise StemQualificationError(f"unapproved {package} runtime version")
            import torch
            from transformers import AutoModel, AutoTokenizer
        except (ImportError, metadata.PackageNotFoundError) as exc:
            raise StemQualificationError("pinned offline Torch/Transformers runtime unavailable") from exc
        self.torch = torch
        self.tokenizer = AutoTokenizer.from_pretrained(
            str(self.snapshot), local_files_only=True, trust_remote_code=False
        )
        self.model = AutoModel.from_pretrained(
            str(self.snapshot), local_files_only=True, trust_remote_code=False,
            use_safetensors=True
        )
        self.model.eval()
        self.model.to("cpu")
        self.forward_calls = 0

    def _encode_unique(self, inputs: list[str]) -> list[list[int]]:
        if not 1 <= len(inputs) <= MAX_BATCH:
            raise StemQualificationError("batch cardinality exceeds bound")
        tokens = self.tokenizer(
            inputs, return_tensors="pt", padding=True, truncation=False
        )
        if "attention_mask" not in tokens or tokens["input_ids"].shape[1] > self.manifest["max_tokens"]:
            raise StemQualificationError("input exceeds pinned model token ceiling")
        attention_mask = tokens["attention_mask"]
        if not bool(self.torch.all(attention_mask.sum(dim=1) > 0)):
            raise StemQualificationError("empty encoded sample")
        with self.torch.inference_mode():
            result = self.model(**tokens)
            self.forward_calls += 1
            embeddings = result.last_hidden_state
            # Correct for both left and right padding.
            mask = attention_mask.unsqueeze(-1).to(dtype=embeddings.dtype)
            pooled = (embeddings * mask).sum(dim=1) / mask.sum(dim=1)
            pooled = pooled.float().cpu()
        if pooled.ndim != 2 or pooled.shape[0] != len(inputs):
            raise StemQualificationError("unexpected physical backend output")
        if pooled.shape[1] > 512:  # no silent 768 -> 512 truncation
            raise StemQualificationError("incompatible width; registered projection required")
        return [quantize_q24(row.tolist()) for row in pooled]

    def encode_fanout(self, requests: list[dict[str, Any]]) -> dict[str, Any]:
        if not 1 <= len(requests) <= MAX_BATCH:
            raise StemQualificationError("unbounded request fanout")
        started = time.perf_counter_ns()
        # Do not mix trust domains in one physical Transformer forward.
        # The caller must partition independently admitted batches by owner.
        first = requests[0]
        domain = (
            first["scope_id"], first["principal_id"], first["purpose_id"],
            first["generation"], first["authority_epoch"],
        )
        seen_cells: set[tuple[str, str, str]] = set()
        keys: list[tuple[Any, ...]] = []
        unique: dict[tuple[Any, ...], str] = {}
        for request in requests:
            key, text = verify_request(request)
            if (
                request["scope_id"], request["principal_id"], request["purpose_id"],
                request["generation"], request["authority_epoch"],
            ) != domain:
                raise StemQualificationError("mixed authority domain in one physical forward")
            cell_key = (request["scope_id"], request["principal_id"], request["cell_id"])
            if cell_key in seen_cells:
                raise StemQualificationError("duplicate Cell use in one batch")
            seen_cells.add(cell_key)
            keys.append(key)
            unique.setdefault(key, text)
        feature_by_key: dict[tuple[Any, ...], list[int]] = {}
        entries = list(unique.items())
        # Each chunk invokes a REAL pretrained Transformer forward. No
        # inference credit is assigned to mere driver calls or fake logits.
        for start in range(0, len(entries), MAX_BATCH):
            batch = entries[start:start + MAX_BATCH]
            vectors = self._encode_unique([text for _, text in batch])
            if len(vectors) != len(batch):
                raise StemQualificationError("backend result cardinality mismatch")
            feature_by_key.update(zip((key for key, _ in batch), vectors))
        rows = []
        for request, key in zip(requests, keys):
            feature = feature_by_key[key]
            rows.append({
                "cell_id": request["cell_id"],
                "scope_id": request["scope_id"],
                "principal_id": request["principal_id"],
                "purpose_id": request["purpose_id"],
                "generation": request["generation"],
                "authority_epoch": request["authority_epoch"],
                "input_digest": key[-1],
                "features_q24": feature,
                "feature_digest": rust_feature_digest_q24(feature),
                "pipeline_digest": self.pipeline_digest,
                "authority": "DENY_ALL",
            })
        return {
            "mode": "shadow_only",
            "actual_pretrained_forward_calls": self.forward_calls,
            "distinct_inputs": len(unique),
            "total_cell_requests": len(requests),
            "encoder_latency_micros": (time.perf_counter_ns() - started) // 1000,
            "rows": rows,
        }


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Offline pinned real-weight Stem qualification")
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--requests", required=True, help="path or - (stdin JSON)")
    args = parser.parse_args()
    runner = OfflineSharedStem(args.manifest)
    if args.requests == "-":
        import sys
        requests = json.load(sys.stdin)
    else:
        requests = json.loads(Path(args.requests).read_text(encoding="utf-8"))
    print(json.dumps(runner.encode_fanout(requests), ensure_ascii=False, sort_keys=True))
