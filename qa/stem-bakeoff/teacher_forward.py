#!/usr/bin/env python3
"""Local-only, research-only HF teacher forward for Hepta Stem bake-off.

Supports EmbeddingGemma 2 mixed text/image/audio/video records and T5Gemma 2
text Encoder records. Inputs, weights and revisions must be supplied offline.
No network, remote code, teacher training, capability claims, Cell action or
production authorization. The model hook counts MODULE forward calls, not
physical GPU kernels or independent execution evidence.
"""
from __future__ import annotations

import argparse
from collections.abc import Mapping
import hashlib
import json
import os
from pathlib import Path
import re
import time
from typing import Any

from teacher_snapshot import MODEL_TYPES, TeacherSnapshotError, verify_snapshot

MODALITIES = ("text", "image", "audio", "video")
MEDIA = frozenset(("image", "audio", "video"))
MAX_RECORDS = 8
MAX_MEDIA_BYTES = 128 * 1024 * 1024
MAX_TEXT_CHARS = 16_384
MAX_SEQUENCE = 8192


class TeacherForwardError(ValueError):
    pass


def validate_records(records: object, media_root: str | Path, candidate: str) -> tuple[list, str]:
    """Check local media and preserve ordered modality sources without URLs."""
    root = Path(media_root).absolute()
    if not root.is_dir() or root.is_symlink():
        raise TeacherForwardError("media_root must be a real local directory")
    if (not isinstance(records, list) or not 1 <= len(records) <= MAX_RECORDS
            or candidate not in MODEL_TYPES):
        raise TeacherForwardError("unregistered model or invalid batch size")
    conversations = []
    receipts = []
    for record in records:
        if not isinstance(record, dict) or not record or not set(record).issubset(MODALITIES):
            raise TeacherForwardError("unknown or missing modality")
        if candidate == "t5gemma2_encoder_270m" and set(record) != {"text"}:
            raise TeacherForwardError("T5Gemma 2 text Encoder probe does not attest vision")
        content = []
        sources = []
        for modality in MODALITIES:
            if modality not in record:
                continue
            value = record[modality]
            if modality == "text":
                if not isinstance(value, str) or not value.strip() or len(value) > MAX_TEXT_CHARS:
                    raise TeacherForwardError("invalid bounded text")
                content.append({"type": "text", "text": value})
                sources.append((modality, hashlib.sha256(value.encode("utf-8")).hexdigest()))
                continue
            if (not isinstance(value, str) or not value or "\x00" in value
                    or re.match(r"^[a-zA-Z]+://", value)
                    or Path(value).is_absolute()
                    or ".." in Path(value).parts):
                raise TeacherForwardError("media must be a local relative path, not a URL")
            path = root / value
            if not path.is_file() or path.is_symlink() or not path.resolve().is_relative_to(root.resolve()):
                raise TeacherForwardError("missing, linked or escaped local media")
            if any(parent.is_symlink() for parent in list(path.parents) if parent != root and
                   root in parent.parents):
                raise TeacherForwardError("media path may not traverse symlinks")
            if not 0 < path.stat().st_size <= MAX_MEDIA_BYTES:
                raise TeacherForwardError("media file size outside bounds")
            digest = hashlib.sha256()
            with path.open("rb") as stream:
                while chunk := stream.read(1024 * 1024):
                    digest.update(chunk)
            content.append({"type": modality, "url": str(path)})
            sources.append((modality, digest.hexdigest()))
        if not content:
            raise TeacherForwardError("empty modality content")
        conversations.append([{"role": "user", "content": content}])
        receipts.append(sources)
    digest = hashlib.sha256(json.dumps(receipts, separators=(",", ":"), sort_keys=True).encode()).hexdigest()
    return conversations, digest


def mean_pool(tokens: Any, mask: Any, *, truncate_dim: int | None = None):
    """Float32, mask-aware, post-truncation unit-normalized retrieval features."""
    import torch
    from torch.nn import functional as F
    if (tokens.ndim != 3 or mask.ndim != 2 or tuple(tokens.shape[:2]) != tuple(mask.shape)
            or not tokens.is_floating_point() or not bool(torch.isfinite(tokens).all())
            or tokens.shape[1] == 0):
        raise TeacherForwardError("nonfinite/incompatible teacher token states")
    if not bool(torch.isin(mask, torch.tensor([0, 1], device=mask.device)).all()):
        raise TeacherForwardError("attention mask must be binary")
    if not bool((mask.sum(dim=1) > 0).all()):
        raise TeacherForwardError("at least one token per sample is required")
    m = mask.unsqueeze(-1).to(torch.float32)
    pooled = (tokens.float() * m).sum(dim=1) / m.sum(dim=1).clamp(min=1)
    if truncate_dim is not None:
        if (type(truncate_dim) is not int or truncate_dim not in (128, 256, 512, 768)
                or truncate_dim > pooled.shape[-1]):
            raise TeacherForwardError("invalid EmbeddingGemma2 Matryoshka dimension")
        pooled = pooled[:, :truncate_dim]
    return F.normalize(pooled, p=2, dim=-1, eps=1e-8)


def run_forward(*, candidate: str, snapshot: str | Path, media_root: str | Path,
                records: list, revision: str, expected_inventory_sha256: str,
                operator_accepted_terms: bool, device: str = "cpu",
                truncate_dim: int | None = None,
                feature_output_dir: str | Path | None = None) -> dict:
    """Actually load a locally pinned checkpoint and execute ONE model/encoder call."""
    verified = verify_snapshot(
        snapshot, candidate=candidate, revision=revision,
        expected_inventory_sha256=expected_inventory_sha256,
        operator_accepted_terms=operator_accepted_terms,
    )
    conversations, source_digest = validate_records(records, media_root, candidate)
    if device not in ("cpu", "cuda"):
        raise TeacherForwardError("device must be cpu or cuda")
    if truncate_dim is not None and candidate != "embeddinggemma2_740m":
        raise TeacherForwardError("Matryoshka truncation is EmbeddingGemma2-only")

    # Set before importing Hugging Face. No 'trust_remote_code' override.
    os.environ["HF_HUB_OFFLINE"] = "1"
    os.environ["TRANSFORMERS_OFFLINE"] = "1"
    import torch
    from transformers import AutoModel, AutoModelForSeq2SeqLM, AutoProcessor, AutoTokenizer
    if device == "cuda" and not torch.cuda.is_available():
        raise TeacherForwardError("CUDA requested but unavailable")
    dtype = torch.bfloat16 if device == "cuda" else torch.float32
    root = str(Path(snapshot).absolute())
    if candidate == "embeddinggemma2_740m":
        processor = AutoProcessor.from_pretrained(root, local_files_only=True,
                                                  trust_remote_code=False)
        model = AutoModel.from_pretrained(root, local_files_only=True,
                                          trust_remote_code=False, dtype=dtype).to(device).eval()
        inputs = processor.apply_chat_template(conversations, tokenize=True,
                                               return_dict=True, return_tensors="pt")
        observed_module = model
    else:
        tokenizer = AutoTokenizer.from_pretrained(root, local_files_only=True,
                                                  trust_remote_code=False)
        model = AutoModelForSeq2SeqLM.from_pretrained(
            root, local_files_only=True, trust_remote_code=False, dtype=dtype
        ).to(device).eval()
        inputs = tokenizer([row["text"] for row in records], padding=True,
                           truncation=True, max_length=MAX_SEQUENCE, return_tensors="pt")
        observed_module = model.get_encoder()
    if (not isinstance(inputs, Mapping) or "attention_mask" not in inputs
            or inputs["attention_mask"].ndim != 2
            or inputs["attention_mask"].shape[1] > MAX_SEQUENCE):
        raise TeacherForwardError("missing or unbounded teacher attention mask")
    inputs = {key: val.to(device) if isinstance(val, torch.Tensor) else val
              for key, val in inputs.items()}
    module_calls = [0]
    def hook(_module, _inputs, _outputs):
        module_calls[0] += 1
    handle = observed_module.register_forward_hook(hook)
    start = time.perf_counter()
    try:
        with torch.inference_mode():
            if candidate == "embeddinggemma2_740m":
                tokens = model(**inputs).last_hidden_state
            else:
                tokens = observed_module(input_ids=inputs["input_ids"],
                                         attention_mask=inputs["attention_mask"]).last_hidden_state
            pooled = mean_pool(tokens, inputs["attention_mask"], truncate_dim=truncate_dim)
        if device == "cuda":
            torch.cuda.synchronize()
    finally:
        handle.remove()
    elapsed_ms = (time.perf_counter() - start) * 1000
    if module_calls[0] != 1 or pooled.ndim != 2 or pooled.shape[0] != len(records):
        raise TeacherForwardError("one model/encoder forward was not observed")
    if candidate == "embeddinggemma2_740m" and pooled.shape[-1] != (truncate_dim or 768):
        raise TeacherForwardError("EmbeddingGemma 2 expected 768-wide projection")
    binary = pooled.detach().contiguous().cpu().numpy().tobytes()
    feature_sha256 = hashlib.sha256(binary).hexdigest()
    export_receipt = None
    if feature_output_dir is not None:
        # Explicitly optional: embeddings remain local, encrypted-at-rest
        # policy is the operator's responsibility; never add to Git.
        from feature_shard import write_shard

        export_receipt = write_shard(
            feature_output_dir, pooled, candidate=candidate,
            revision=verified["revision"],
            checkpoint_inventory_sha256=verified["inventory_sha256"],
            ordered_source_manifest_sha256=source_digest,
        )
        if export_receipt["raw_feature_sha256"] != feature_sha256:
            raise TeacherForwardError("offline feature shard digest mismatch")
    return {
        "schema": "hepta.teacher-local-forward.v1",
        "candidate": candidate,
        "revision": verified["revision"],
        "inventory_sha256": verified["inventory_sha256"],
        "ordered_source_manifest_sha256": source_digest,
        "batch_size": len(records),
        "feature_width": int(pooled.shape[-1]),
        "feature_sha256": feature_sha256,
        "feature_export": export_receipt,
        "owner_model_forward_hook_calls": module_calls[0],
        "physical_backend_kernel_count_attested": False,
        "elapsed_ms_one_unqualified_sample": round(elapsed_ms, 3),
        "source_disjoint_holdout_verified": False,
        "model_performance_qualified": False,
        "producer_attested_independently": False,
        "authority": "DENY_ALL",
        "mode": "SHADOW_ONLY",
        "production_activation_allowed": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate", required=True, choices=sorted(MODEL_TYPES))
    parser.add_argument("--snapshot", required=True)
    parser.add_argument("--media-root", required=True)
    parser.add_argument("--records-json", required=True)
    parser.add_argument("--revision", required=True)
    parser.add_argument("--expected-inventory-sha256", required=True)
    parser.add_argument("--operator-accepted-terms", action="store_true")
    parser.add_argument("--device", choices=("cpu", "cuda"), default="cpu")
    parser.add_argument("--truncate-dim", type=int)
    parser.add_argument("--feature-output-dir",
                        help="new owner-private feature shard directory outside Git checkout")
    args = parser.parse_args()
    try:
        records = json.loads(Path(args.records_json).read_text(encoding="utf-8"))
        result = run_forward(
            candidate=args.candidate, snapshot=args.snapshot, media_root=args.media_root,
            records=records, revision=args.revision,
            expected_inventory_sha256=args.expected_inventory_sha256,
            operator_accepted_terms=args.operator_accepted_terms,
            device=args.device, truncate_dim=args.truncate_dim,
            feature_output_dir=args.feature_output_dir,
        )
    except (TeacherSnapshotError, TeacherForwardError, OSError, ValueError,
            ImportError, RuntimeError) as error:
        print(json.dumps({"status": "REJECTED", "reason": str(error),
                          "authority": "DENY_ALL"}))
        return 2
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
