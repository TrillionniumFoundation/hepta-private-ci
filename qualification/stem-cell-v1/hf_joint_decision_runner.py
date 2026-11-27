#!/usr/bin/env python3
"""Real local-weight HF joint Decision Head training; SHADOW ONLY.

The two raw pretraining models have no pretrained typed-decision Head.
Consequently only the equal-budget stage is supported here. A random
new Head is never emitted as a fake zero-shot checkpoint comparator.
No automatic downloads, arbitrary remote code, owner authority or NDU.
"""
import argparse
import hashlib
import json
import math
import os
import platform
import random
import sys
import time
from collections.abc import Mapping
from pathlib import Path

from decision_421m import (SOURCES, audit_dataset, check_sha,
                           input_fingerprint, read_strict_jsonl, sha256_file)
from hf_encoder_kernel import (snapshot_digest, render_joint, head_width, build_head,
                               head_sha256, train_head, validate_encoder_loading_info,
                               verify_loaded_safetensors, vectorize_case, vectorize_scope_batch)

HF_KEYS = frozenset(("deberta_v3_large", "modernbert_large"))
MAX_FEATURE_BYTES = 1 << 28  # explicit 256 MiB cache/feature budget


def snapshot_validation(args):
    if args.model_key not in HF_KEYS:
        raise ValueError("only DeBERTa-v3-large/ModernBERT-large HF Head arms supported")
    if not check_sha(args.upstream_revision, 40):
        raise ValueError("source revision must be pinned 40-hex Git SHA")
    if not check_sha(args.expected_snapshot_sha256):
        raise ValueError("checkpoint tree must have a SHA-256 digest")
    if not check_sha(args.expected_dataset_sha256):
        raise ValueError("approved dataset bytes require SHA-256")
    if args.license_approved is not True or args.adapter_reviewed is not True:
        raise ValueError("independent license and typed-adapter review required")
    if args.dtype not in ("fp32", "bf16", "fp16"):
        raise ValueError("unsupported floating-point precision")
    if any(type(value) is not int or value <= 0 for value in
           (args.train_steps, args.batch_size, args.context_tokens,
            args.trainable_budget, args.seed)):
        raise ValueError("invalid frozen training/runtime limits")
    path = Path(args.snapshot).resolve()
    if snapshot_digest(path) != args.expected_snapshot_sha256:
        raise ValueError("checkpoint snapshot changed from reviewed artifact")
    # Microsoft's official DeBERTa-v3-large checkpoint currently distributes
    # legacy pytorch_model.bin. This research runner NEVER unpickles it.
    # Approved model operators must first produce and content-pin a reviewed,
    # self-contained safetensors conversion in an isolated trust boundary.
    if not any(item.is_file() for item in path.rglob("*.safetensors")):
        raise ValueError(
            "reviewed local safetensors weights missing; raw PyTorch .bin "
            "may not be loaded or automatically converted in this runner")
    if sha256_file(args.dataset) != args.expected_dataset_sha256:
        raise ValueError("approved dataset content changed")
    if Path(args.output).exists() or Path(str(args.output) + ".run.json").exists():
        raise FileExistsError("append-only qualification result already exists")
    return path


def run(args):
    checkpoint = snapshot_validation(args)
    rows = list(read_strict_jsonl(args.dataset))
    indexed, classes, groups_digest = audit_dataset(rows)
    import torch
    import transformers
    from transformers import AutoModel, AutoTokenizer
    for key in ("HF_HUB_OFFLINE", "TRANSFORMERS_OFFLINE", "HF_DATASETS_OFFLINE"):
        os.environ[key] = "1"
    torch.random.default_generator.manual_seed(args.seed)
    random.seed(args.seed)
    torch.set_num_threads(max(1, min(8, os.cpu_count() or 1)))
    torch.use_deterministic_algorithms(True)
    dtype = {"fp32": torch.float32, "bf16": torch.bfloat16,
             "fp16": torch.float16}[args.dtype]
    tokenizer = AutoTokenizer.from_pretrained(
        str(checkpoint), local_files_only=True, trust_remote_code=False)
    began = time.perf_counter()
    loaded = AutoModel.from_pretrained(
        str(checkpoint), local_files_only=True, trust_remote_code=False,
        use_safetensors=True, output_loading_info=True,
        torch_dtype=dtype)
    if not isinstance(loaded, tuple) or len(loaded) != 2:
        raise ValueError("HF backend did not provide audited pretrained loading report")
    model, loading_info = loaded
    loading_receipt = validate_encoder_loading_info(loading_info)
    model = model.to(args.device).eval()
    tensor_materialization = verify_loaded_safetensors(torch, model, checkpoint)
    load_seconds = time.perf_counter() - began
    for parameter in model.parameters():
        parameter.requires_grad_(False)
    encoder_params = sum(p.numel() for p in model.parameters())
    nominal = SOURCES[args.model_key][1]
    if (not 350_000_000 <= encoder_params <= 480_000_000 or
            abs(encoder_params - nominal) / nominal > .10):
        raise ValueError("actual pretrained Encoder parameter count not comparable")
    width = getattr(model.config, "hidden_size", None)
    if type(width) is not int or width <= 0:
        raise ValueError("no pinned Transformer hidden-size declaration")
    position_limit = getattr(model.config, "max_position_embeddings", None)
    if type(position_limit) is int and args.context_tokens > position_limit:
        raise ValueError("model position budget smaller than registered context")

    microbatch = getattr(args, "encoder_microbatch_size", 1)
    if type(microbatch) is not int or not 1 <= microbatch <= 32:
        raise ValueError("physical shared Encoder batch size must be 1..32")
    vectors, encode_ms, lengths = {}, {}, {}
    feature_bytes = 0
    encoder_forward_calls, batch_sizes = 0, []
    cursor = 0
    while cursor < len(rows):
        scope = rows[cursor]["scope"]
        selected = []
        while (cursor < len(rows) and len(selected) < microbatch and
               rows[cursor]["scope"] == scope):
            selected.append(rows[cursor])
            cursor += 1
        if args.device.startswith("cuda"):
            torch.cuda.synchronize()
        start = time.perf_counter_ns()
        if len(selected) == 1:
            measurements = [vectorize_case(
                torch, model, tokenizer, selected[0], args.device,
                max_tokens=args.context_tokens)]
        else:
            measurements = vectorize_scope_batch(
                torch, model, tokenizer, selected, args.device,
                max_tokens=args.context_tokens)
        if args.device.startswith("cuda"):
            torch.cuda.synchronize()
        duration = (time.perf_counter_ns() - start) / 1e6
        encoder_forward_calls += 1
        batch_sizes.append(len(selected))
        for row, (feature, n_tokens) in zip(selected, measurements):
            feature_bytes += feature.numel() * feature.element_size()
            if feature_bytes > MAX_FEATURE_BYTES:
                raise ValueError("frozen feature materialization exceeds strict memory budget")
            if feature.numel() != width:
                raise ValueError("encoder hidden width differs from pinned manifest")
            sid = row["sample_id"]
            # Report full physical batch duration for each Cell, never divide
            # by batch size and misrepresent this as production p99.
            vectors[sid], encode_ms[sid], lengths[sid] = feature, duration, n_tokens

    # Loading different pretrained architectures may consume different RNG.
    # Reset exactly before Head initialization so matched-width Head arms
    # receive genuinely matched initialization and minibatch ordering.
    torch.random.default_generator.manual_seed(args.seed + 1)
    head, head_parameters = build_head(torch, width, classes, args.trainable_budget)
    head = head.to(args.device)
    train_rows = sorted((r for r in rows if r["split"] == "train"),
                        key=lambda r: r["sample_id"])
    x = torch.stack([vectors[r["sample_id"]] for r in train_rows]).to(args.device)
    y = torch.tensor([r["label"] for r in train_rows], device=args.device)
    started = time.perf_counter()
    head_digest = train_head(torch, head, x, y, batch_size=args.batch_size,
                             steps=args.train_steps, seed=args.seed)
    train_seconds = time.perf_counter() - started

    predictions = []
    with torch.inference_mode():
        for row in rows:
            if row["split"] == "train":
                continue
            sid = row["sample_id"]
            start = time.perf_counter_ns()
            logits = head(vectors[sid].to(args.device).unsqueeze(0))[0]
            if args.device.startswith("cuda"):
                torch.cuda.synchronize()
            head_ms = (time.perf_counter_ns() - start) / 1e6
            if not torch.isfinite(logits).all().item():
                raise ValueError("trained decision logits are nonfinite")
            predictions.append({
                "arm": f"{args.model_key}:equal_budget", "sample_id": sid,
                "input_digest": input_fingerprint(row),
                "logits": logits.to(torch.float32).cpu().tolist(),
                "weights_sha256": head_digest,
                "latency_ms": encode_ms[sid] + head_ms,
                "token_count": lengths[sid],
                "backend_kind": "offline_local_hf_frozen_backbone_trainable_decision_head",
            })
    # A pre-load hash is not a valid post-inference provenance receipt when
    # the operator-controlled checkpoint or approved dataset could have
    # changed while the model was being loaded or Head training was running.
    # Check both physical inputs again BEFORE materializing any scored output.
    # This still is not a signed owner attestation or defense against an
    # adversary who changes and restores bytes between our observations.
    if snapshot_digest(checkpoint) != args.expected_snapshot_sha256:
        raise ValueError("checkpoint snapshot changed during Encoder execution")
    if sha256_file(args.dataset) != args.expected_dataset_sha256:
        raise ValueError("approved dataset bytes changed during Encoder execution")

    target = Path(args.output)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("x", encoding="utf-8") as stream:
        for prediction in predictions:
            stream.write(json.dumps(prediction, sort_keys=True,
                                    ensure_ascii=False, allow_nan=False) + "\n")
    try:
        import psutil
        rss = psutil.Process(__import__("os").getpid()).memory_info().rss
    except Exception:
        # Resource collection is observational; never fail a model run or
        # substitute an estimate when the container hides its own PID.
        rss = None

    result = {
        "schema": "hepta.stem-cell-actual-hf-joint-decision.v1",
        "arm": f"{args.model_key}:equal_budget",
        "checkpoint_sha256": args.expected_snapshot_sha256,
        "weights_sha256": head_digest,
        "upstream_revision": args.upstream_revision,
        "model_source": SOURCES[args.model_key][0],
        "dataset_sha256": args.expected_dataset_sha256,
        "training_sample_groups_sha256": groups_digest,
        "runner_source_sha256": sha256_file(__file__),
        "runtime_profile": {
            "device": args.device, "dtype": args.dtype,
            "batch_size": args.batch_size, "context_tokens": args.context_tokens},
        "seed": args.seed, "truncated_input_count": 0,
        "input_contract": "state_question_all_ordered_options",
        "optimizer": "adamw", "training_split": "train",
        "train_steps": args.train_steps, "trainable_parameters": head_parameters,
        "frozen_encoder_parameters": encoder_params,
        "physical_encoder_forward_calls": encoder_forward_calls,
        "physical_encoder_microbatch_ceiling": microbatch,
        "observed_physical_encoder_batch_sizes": batch_sizes,
        "per_case_latency_conservatively_charged_full_batch": True,
        "production_microbatch_qualified": False,
        "verified_encoder_loading": loading_receipt,
        "verified_exact_tensor_materialization": tensor_materialization,
        "model_load_seconds": load_seconds, "training_seconds": train_seconds,
        "feature_bytes": feature_bytes, "process_rss_after_bytes": rss,
        "output_predictions_sha256": sha256_file(target),
        "sample_count": len(indexed), "scored_count": len(predictions),
        "encoder_requires_only_local_weights": True,
        "checkpoint_and_dataset_reverified_before_scoring_output": True,
        "pretrained_typed_decision_head_existed": False,
        "checkpoint_zero_shot_score_emitted": False,
        "production_promotion_permitted": False,
        "independent_ndu_signature_verified": False,
        "source_and_license_review_operator_attested_only": True,
        "limitations": [
            "Only local frozen pretrained Encoder plus bounded learned Head",
            "The initial raw HF checkpoint has no pretrained typed Decision Head",
            "Offline row encoding latency is not native Worker batch p99",
            "Laya baseline, external NDU, Artifact CAS/final-use/recovery unverified",
        ],
        "runtime_environment": {
            "python": platform.python_version(),
            "torch": torch.__version__, "transformers": transformers.__version__},
    }
    with Path(str(args.output) + ".run.json").open("x", encoding="utf-8") as stream:
        stream.write(json.dumps(result, sort_keys=True, indent=2,
                                ensure_ascii=False, allow_nan=False) + "\n")
    return result


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--dataset", required=True)
    p.add_argument("--expected-dataset-sha256", required=True)
    p.add_argument("--model-key", required=True, choices=sorted(HF_KEYS))
    p.add_argument("--snapshot", required=True)
    p.add_argument("--expected-snapshot-sha256", required=True)
    p.add_argument("--upstream-revision", required=True)
    p.add_argument("--license-approved", action="store_true")
    p.add_argument("--adapter-reviewed", action="store_true")
    p.add_argument("--train-steps", type=int, required=True)
    p.add_argument("--trainable-budget", type=int, default=262144)
    p.add_argument("--batch-size", type=int, default=16)
    p.add_argument("--encoder-microbatch-size", type=int, default=1,
                   help="real same-Scope HF microbatch 1..32; never a native Worker receipt")
    p.add_argument("--context-tokens", type=int, default=512)
    p.add_argument("--seed", type=int, default=7347)
    p.add_argument("--device", default="cpu")
    p.add_argument("--dtype", choices=("fp32", "bf16", "fp16"), default="fp32")
    p.add_argument("--output", required=True)
    args = p.parse_args()
    result = run(args)
    print(json.dumps({"arm": result["arm"],
                      "production_promotion_permitted": False}, sort_keys=True))


if __name__ == "__main__":
    main()
