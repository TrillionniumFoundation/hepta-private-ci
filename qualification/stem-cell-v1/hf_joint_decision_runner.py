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
from model_runner import snapshot_digest

HF_KEYS = frozenset(("deberta_v3_large", "modernbert_large"))
MAX_FEATURE_BYTES = 1 << 28  # explicit 256 MiB cache/feature budget


def render_joint(row):
    if not isinstance(row.get("state"), str) or not isinstance(row.get("question"), str):
        raise ValueError("typed model state/question required")
    if not row["state"] or not row["question"]:
        raise ValueError("empty state or question")
    if not isinstance(row.get("options"), list) or not 2 <= len(row["options"]) <= 16:
        raise ValueError("ordered legal options required")
    if any(not isinstance(opt, str) or not opt for opt in row["options"]):
        raise ValueError("empty legal option")
    # The label is intentionally NEVER interpolated into the model source.
    return "\n".join(["[STATE]", row["state"], "[QUESTION]", row["question"],
                      "[ALL ORDERED OPTIONS]", *[
                          f"Option {i}: {value}" for i, value in enumerate(row["options"])]]).strip()


def head_width(hidden, classes, ceiling, max_width=256):
    if (any(type(v) is not int for v in (hidden, classes, ceiling)) or
            hidden < 1 or not 2 <= classes <= 16 or ceiling <= classes):
        raise ValueError("invalid dimensions or parameter budget ceiling")
    width = min(max_width, (ceiling - classes) // (hidden + classes + 1))
    if width < 1:
        raise ValueError("head cannot fit the registered parameter budget")
    count = hidden * width + width + width * classes + classes
    if count > ceiling:
        raise ValueError("miscomputed physical Head parameter budget")
    return width, count


def build_head(torch, hidden, classes, ceiling):
    from torch import nn
    width, expected = head_width(hidden, classes, ceiling)
    head = nn.Sequential(nn.Linear(hidden, width), nn.GELU(),
                         nn.Linear(width, classes))
    actual = sum(p.numel() for p in head.parameters())
    if actual != expected:
        raise ValueError("unaccounted trainable Head tensor")
    return head, actual


def head_sha256(head):
    import torch
    digest = hashlib.sha256(b"hepta.typed-hf-joint-head.v1\x00")
    for name, tensor in sorted(head.state_dict().items()):
        values = tensor.detach().to(device="cpu", dtype=torch.float32).contiguous()
        pieces = (name.encode("utf-8"),
                  json.dumps(list(values.shape), separators=(",", ":")).encode("utf-8"),
                  values.numpy().tobytes())
        for part in pieces:
            digest.update(len(part).to_bytes(8, "big"))
            digest.update(part)
    return digest.hexdigest()


def train_head(torch, head, features, labels, *, batch_size, steps, seed):
    if any(type(v) is not int or v < 1 for v in (batch_size, steps)):
        raise ValueError("training steps/batch must be positive")
    if features.ndim != 2 or labels.ndim != 1 or features.shape[0] != labels.shape[0]:
        raise ValueError("training feature/label shape mismatch")
    rng = torch.Generator(device="cpu").manual_seed(seed)
    opt = torch.optim.AdamW(head.parameters(), lr=0.001, weight_decay=0.01)
    head.train()
    for _ in range(steps):
        chosen = torch.randint(len(labels), (min(batch_size, len(labels)),),
                               generator=rng).to(features.device)
        logits = head(features[chosen])
        loss = torch.nn.functional.cross_entropy(logits, labels[chosen])
        opt.zero_grad(set_to_none=True)
        loss.backward()
        torch.nn.utils.clip_grad_norm_(head.parameters(), 1.0)
        opt.step()
        if not all(torch.isfinite(p).all().item() for p in head.parameters()):
            raise ValueError("invalid trained weights")
    head.eval()
    return head_sha256(head)


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


def validate_encoder_loading_info(info):
    """Refuse missing/randomly initialized or silently ignored pretrained tensors.

    A safetensors file and checkpoint SHA alone do not guarantee that AutoModel
    successfully loaded every intended pretrained parameter. Model-specific
    intentional drops must be resolved by a reviewed base-model conversion
    before this qualification lane, not suppressed in this evaluator.
    """
    required = ("missing_keys", "unexpected_keys", "mismatched_keys", "error_msgs")
    if not isinstance(info, Mapping) or any(key not in info for key in required):
        raise ValueError("pretrained Encoder missing complete loading report")
    problems = {}
    for key in required:
        values = info[key]
        if not isinstance(values, (list, tuple)):
            raise ValueError("pretrained Encoder loading report has invalid field: " + key)
        if values:
            problems[key] = len(values)
    if problems:
        raise ValueError(
            "pretrained Encoder partially initialized or ignored weights: "
            + json.dumps(problems, sort_keys=True))
    return {
        "schema": "hepta.local-hf-encoder-weight-load.v1",
        "complete": True,
        "missing_keys": 0,
        "unexpected_keys": 0,
        "mismatched_keys": 0,
        "error_msgs": 0,
    }


def verify_loaded_safetensors(torch, model, root):
    """Exact, read-only tensor comparison against every pinned safetensors key.

    Transformers loading_info is advisory for some version/architecture
    combinations; a clean list by itself is NOT sufficient. Require that
    the locally admitted, base-only safetensors inventory equals the actual
    model.state_dict() inventory and every tensor value after the requested
    model dtype conversion matches. Reject aliases/partial architecture
    conversions until a separate audited canonical model artifact exists.
    """
    from safetensors import safe_open

    files = sorted(Path(root).rglob("*.safetensors"))
    if not files or len(files) > 64:
        raise ValueError("empty or excessive safetensors shard inventory")
    if sum(p.stat().st_size for p in files) > 2_500_000_000:
        raise ValueError("pretrained safetensors exceed local research weight envelope")
    stored = model.state_dict()
    if not isinstance(stored, Mapping) or not stored or len(stored) > 250_000:
        raise ValueError("unsupported pretrained model tensor inventory")
    seen = set()
    elements = 0
    for file in files:
        with safe_open(str(file), framework="pt", device="cpu") as handle:
            for key in handle.keys():
                if key in seen or key not in stored:
                    raise ValueError("duplicate or unexpected safetensors parameter key")
                observed = stored[key]
                expected = handle.get_tensor(key)
                if (not hasattr(observed, "shape") or
                        tuple(observed.shape) != tuple(expected.shape) or
                        observed.device.type == "meta"):
                    raise ValueError("safetensors tensor shape or materialization mismatch")
                # Loading at bf16/fp16 legitimately casts source values.
                # Compare at the exact dtype actually held by the model.
                source = expected.to(dtype=observed.dtype, device="cpu")
                actual = observed.detach().to(device="cpu")
                if not torch.equal(source, actual):
                    raise ValueError("loaded pretrained tensor differs from pinned safetensors")
                elements += int(expected.numel())
                seen.add(key)
    if seen != set(stored):
        raise ValueError("incomplete safetensors inventory for loaded Encoder")
    return {
        "schema": "hepta.local-hf-exact-tensor-materialization.v1",
        "complete": True,
        "all_state_dict_tensors_compared": True,
        "tensor_count": len(seen),
        "tensor_elements": elements,
        "safetensors_shards": len(files),
        "production_authorization": False,
    }


def vectorize_case(torch, model, tokenizer, row, device, *, max_tokens):
    text = render_joint(row)
    tokens = tokenizer(text, return_tensors="pt", truncation=False)
    if not isinstance(tokens, Mapping) or "input_ids" not in tokens or "attention_mask" not in tokens:
        raise ValueError("tokenizer did not produce input IDs and padding mask")
    mask = tokens["attention_mask"]
    if mask.ndim != 2 or mask.shape[0] != 1:
        raise ValueError("unexpected token mask shape")
    seq_len = int(mask.sum().item())
    if not 1 <= seq_len <= max_tokens:
        raise ValueError("input exceeds shared token budget, no silent truncation")
    args = {name: tensor.to(device) for name, tensor in tokens.items()}
    with torch.inference_mode():
        states = model(**args).last_hidden_state
        weights = args["attention_mask"].unsqueeze(-1).to(states.dtype)
        if states.ndim != 3 or states.shape[0] != 1 or states.shape[1] != weights.shape[1]:
            raise ValueError("unsupported encoder hidden-state layout")
        pooled = (states * weights).sum(1) / weights.sum(1).clamp_min(1)
        feature = pooled[0].to(torch.float32).detach().cpu()
    if not torch.isfinite(feature).all().item():
        raise ValueError("nonfinite encoder feature")
    return feature, seq_len


def vectorize_scope_batch(torch, model, tokenizer, rows, device, *, max_tokens):
    """One genuine HF forward for 2..32 same-Scope joint decision cases.

    No model weights are fetched, no source labels reach the Encoder, and
    unrelated Scopes are never coalesced by the shadow microbatch scheduler.
    """
    if not 2 <= len(rows) <= 32:
        raise ValueError("physical Encoder microbatch requires 2..32 inputs")
    if len({row["scope"] for row in rows}) != 1:
        raise ValueError("cross-Scope Encoder batch is forbidden")
    encoded, lengths = [], []
    for row in rows:
        tokens = tokenizer(render_joint(row), return_tensors="pt",
                           truncation=False)
        if (not isinstance(tokens, Mapping) or
                "input_ids" not in tokens or "attention_mask" not in tokens):
            raise ValueError("incomplete joint tokenizer output")
        mask = tokens["attention_mask"]
        if mask.ndim != 2 or mask.shape[0] != 1:
            raise ValueError("invalid per-case Encoder mask")
        count = int(mask.sum().item())
        if not 1 <= count <= max_tokens:
            raise ValueError("Encoder batch would silently truncate input")
        sample = {}
        for name, tensor in tokens.items():
            if (tensor.ndim != 2 or tensor.shape[0] != 1 or
                    tensor.shape[1] != mask.shape[1]):
                raise ValueError("tokenizer emitted incompatible per-case tensor")
            sample[name] = tensor[0].tolist()
        encoded.append(sample)
        lengths.append(count)
    padded = tokenizer.pad(encoded, padding=True, return_tensors="pt")
    if (not isinstance(padded, Mapping) or
            "attention_mask" not in padded or
            padded["attention_mask"].ndim != 2 or
            padded["attention_mask"].shape[0] != len(rows)):
        raise ValueError("incompatible physical Encoder padding layout")
    masks = padded["attention_mask"]
    if masks.shape[1] * len(rows) > max_tokens * 32:
        raise ValueError("physical Encoder batch exceeds joint token memory envelope")
    if [int(mask.sum().item()) for mask in masks] != lengths:
        raise ValueError("Encoder padding changed original token identities")
    args = {name: value.to(device) for name, value in padded.items()}
    with torch.inference_mode():
        states = model(**args).last_hidden_state
        weights = args["attention_mask"].unsqueeze(-1).to(states.dtype)
        if (states.ndim != 3 or states.shape[0] != len(rows) or
                states.shape[1] != weights.shape[1]):
            raise ValueError("physical Encoder batch returned invalid hidden geometry")
        pooled = (states * weights).sum(dim=1) / weights.sum(dim=1).clamp_min(1)
        features = pooled.to(torch.float32).detach().cpu()
    if not torch.isfinite(features).all().item():
        raise ValueError("nonfinite physical Encoder batch output")
    return [(features[j], lengths[j]) for j in range(len(rows))]


def run(args):
    checkpoint = snapshot_validation(args)
    rows = list(read_strict_jsonl(args.dataset))
    indexed, classes, groups_digest = audit_dataset(rows)
    import torch
    import transformers
    from transformers import AutoModel, AutoTokenizer
    for key in ("HF_HUB_OFFLINE", "TRANSFORMERS_OFFLINE", "HF_DATASETS_OFFLINE"):
        os.environ[key] = "1"
    torch.manual_seed(args.seed)
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
    torch.manual_seed(args.seed + 1)
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
    target = Path(args.output)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("x", encoding="utf-8") as stream:
        for prediction in predictions:
            stream.write(json.dumps(prediction, sort_keys=True,
                                    ensure_ascii=False, allow_nan=False) + "\n")
    try:
        import psutil
        rss = psutil.Process().memory_info().rss
    except ImportError:
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
