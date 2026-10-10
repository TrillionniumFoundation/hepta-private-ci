#!/usr/bin/env python3
"""Real frozen Jina v5 + strictly cell-local head shadow experiment.

Uses official task adapters and document encoding, not raw hidden-state mean
pooling. Results are predictions and measured research costs, never approval to
install a model or change runtime weights.
"""
import argparse
import copy
import hashlib
import json
import random
import time
from pathlib import Path

from hf_trial import make_head
from jina_v5 import FrozenJinaV5, MODELS, research_environment, sha256_record, validate_identity
from qualified_eval import audit_dataset, read_jsonl, write_json
from q24_bridge import Q24, quantize_q24


def render_case(row, representation):
    if representation not in ("joint", "state"):
        raise ValueError("only actual joint/state embeddings are supported")
    if representation == "state":
        return "State: " + row["state"]
    options = " | ".join(f"{i}: {s}" for i, s in enumerate(row["options"]))
    return f"State: {row['state']}\nQuestion: {row['question']}\nOptions: {options}"


def choose_train_rows(rows, task_id, shots, seed):
    task = [row for row in rows if row["task_id"] == task_id]
    if not task or any(not any(x["split"] == split for x in task) for split in
                       ("train", "calibration", "test", "future", "ood")):
        raise ValueError("selected task must cover all five leakage-audited splits")
    groups = {}
    for row in task:
        if row["split"] == "train":
            groups.setdefault((row["scope_id"], row["group_id"]), []).append(row)
    if type(shots) is not int or shots <= 0 or len(groups) < shots:
        raise ValueError("insufficient independent train groups")
    rng = random.Random(seed)
    selected = [rng.choice(sorted(groups[group], key=lambda r: r["case_id"]))
                for group in rng.sample(sorted(groups), shots)]
    return task, selected


def effective_weights_digest(layer):
    result = hashlib.sha256(b"hepta.jina-v5-cell-head-weights.v1")
    for key, value in sorted(layer.state_dict().items()):
        result.update(key.encode("utf-8"))
        result.update(value.detach().cpu().contiguous().numpy().tobytes())
    return result.hexdigest()


def execute(args):
    import psutil
    import torch
    from torch import nn

    if args.model not in ("jina-v5-text-nano", "jina-v5-text-small"):
        raise ValueError("use jina_v5_multimodal.py for Omni qualification")
    validate_identity(args.model, args.revision, "classification", args.dimension,
                      "text", args.max_tokens)
    if args.steps < 1 or args.batch_size < 1 or args.threads < 1:
        raise ValueError("invalid training budget")
    rows = read_jsonl(args.dataset)
    audit = audit_dataset(rows)
    task_rows, selected = choose_train_rows(rows, args.task_id, args.shots, args.seed)
    widths = {len(row["options"]) for row in task_rows}
    if len(widths) != 1:
        raise ValueError("inconsistent classification widths")
    classes = widths.pop()
    torch.manual_seed(args.seed)
    torch.set_num_threads(args.threads)
    stem = FrozenJinaV5(
        args.model, args.revision, task="classification", dimension=args.dimension,
        modality="text", max_tokens=args.max_tokens, device=args.device,
        allow_pinned_remote_code=args.allow_pinned_remote_code,
        allow_download=args.allow_model_download,
        cache_entries=args.cache_entries,
    )
    features, source_timing = {}, {}
    # Encodings are frozen. Test labels are never exposed to the trainer.
    for row in selected + [x for x in task_rows if x["split"] != "train"]:
        began = time.perf_counter_ns()
        vector, trace = stem.encode_batch(
            [render_case(row, args.representation)],
            scope_id=row["scope_id"], principal_id=args.principal_id,
            generation=args.generation, authority_epoch=args.authority_epoch,
        )
        elapsed = (time.perf_counter_ns() - began) / 1e6
        # Head training and inference see the exact same Q24-rounded
        # bounded feature envelope expected by the Neuron feature contract.
        q24 = quantize_q24(vector[0])
        features[row["case_id"]] = torch.tensor(
            [value / Q24 for value in q24], dtype=torch.float32)
        source_timing[row["case_id"]] = (
            "cache_hit_head" if trace["cache_hits"] else "encoder_warm", elapsed)
    head, params = make_head(torch, nn, args.head, args.dimension, classes, args.budget)
    head = head.to(args.device)
    frozen_head = copy.deepcopy(head).eval()
    if args.budget < params:
        raise ValueError("Cell head exceeded complete parameter ceiling")
    optimizer = torch.optim.AdamW(head.parameters(), lr=args.learning_rate)
    train_x = torch.stack([features[row["case_id"]] for row in selected]).to(args.device)
    train_y = torch.tensor([row["label"] for row in selected], dtype=torch.long,
                           device=args.device)
    train_start = time.perf_counter_ns()
    head.train()
    rng = torch.Generator().manual_seed(args.seed)
    for _ in range(args.steps):
        indices = torch.randint(len(selected), (args.batch_size,), generator=rng)
        logits = head(train_x[indices.to(args.device)])
        loss = nn.functional.cross_entropy(logits, train_y[indices.to(args.device)])
        optimizer.zero_grad(set_to_none=True)
        loss.backward()
        optimizer.step()
    train_ms = (time.perf_counter_ns() - train_start) / 1e6
    head.eval()

    def logits(row):
        return head(features[row["case_id"]].to(args.device))

    calibration = [row for row in task_rows if row["split"] == "calibration"]
    with torch.inference_mode():
        calibrated_logits = torch.stack([logits(row) for row in calibration])
        calibrated_labels = torch.tensor([row["label"] for row in calibration],
                                         dtype=torch.long, device=args.device)
        grid = (.5, .75, 1., 1.25, 1.5, 2., 3., 4., 6.)
        temperature = min(grid, key=lambda t: nn.functional.cross_entropy(
            calibrated_logits / t, calibrated_labels).item())
        frozen_logits = torch.stack([
            frozen_head(features[row["case_id"]].to(args.device)) for row in calibration])
        frozen_temperature = min(grid, key=lambda t: nn.functional.cross_entropy(
            frozen_logits / t, calibrated_labels).item())
    weights_digest = effective_weights_digest(head)
    frozen_weights_digest = effective_weights_digest(frozen_head)
    process = psutil.Process()
    predictions = []
    frozen_predictions = []
    for row in task_rows:
        if row["split"] == "train":
            continue
        began = time.perf_counter_ns()
        with torch.inference_mode():
            probabilities = torch.softmax(logits(row) / temperature,
                                          dim=-1).cpu().tolist()
        head_ms = (time.perf_counter_ns() - began) / 1e6
        execution_path, embedding_ms = source_timing[row["case_id"]]
        frozen_start = time.perf_counter_ns()
        with torch.inference_mode():
            frozen_probabilities = torch.softmax(
                frozen_head(features[row["case_id"]].to(args.device)) / frozen_temperature,
                dim=-1).cpu().tolist()
        frozen_head_ms = (time.perf_counter_ns() - frozen_start) / 1e6
        frozen_predictions.append({
            "case_id": row["case_id"], "scope_id": row["scope_id"],
            "model_id": args.model + "/frozen-head",
            "model_revision": args.revision,
            "encoder_digest": stem.manifest_digest,
            "head_digest": frozen_weights_digest,
            "runtime_generation": args.generation, "status": "Succeeded",
            "probabilities": frozen_probabilities,
            "execution_path": execution_path,
            "latency_ms": frozen_head_ms + embedding_ms,
            "rss_bytes": process.memory_info().rss,
            "backend_batch_size": 1,
        })
        predictions.append({
            "case_id": row["case_id"],
            "scope_id": row["scope_id"],
            "model_id": args.model, "model_revision": args.revision,
            "encoder_digest": stem.manifest_digest, "head_digest": weights_digest,
            "runtime_generation": args.generation, "status": "Succeeded",
            "probabilities": probabilities,
            "execution_path": execution_path,
            "latency_ms": head_ms + embedding_ms, "rss_bytes": process.memory_info().rss,
            "backend_batch_size": 1,
        })
    output = Path(args.output)
    frozen_output = Path(str(output) + ".frozen-head.jsonl")
    if any(p.exists() for p in (output, frozen_output, Path(str(output) + ".manifest.json"))):
        raise ValueError("refusing to overwrite prior qualification evidence")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text("".join(json.dumps(x, sort_keys=True) + "\n"
                              for x in predictions), encoding="utf-8")
    frozen_output.write_text("".join(json.dumps(x, sort_keys=True) + "\n"
                                     for x in frozen_predictions), encoding="utf-8")
    write_json(str(output) + ".manifest.json", {
        "schema": "hepta.jina-v5-shadow-trial.v1",
        "status": "shadow_only", "production_promotion_permitted": False,
        "signed_ndu_verified": False,
        "model": args.model, "revision": args.revision,
        "task_adapter": "classification", "intent": "document",
        "official_pooling": True,
        "q24_feature_input_enforced": True,
        "q24_conversion_receipt_signed": False,
        "representation": args.representation,
        "matryoshka_dimension": args.dimension,
        "dataset": audit, "task_id": args.task_id,
        "feature_manifest_digest": stem.manifest_digest,
        "head_parameters": params, "head_ceiling": args.budget,
        "head_digest": weights_digest,
        "frozen_head_digest": frozen_weights_digest,
        "frozen_head_predictions": str(frozen_output),
        "frozen_head_predictions_sha256": sha256_record(frozen_predictions),
        "frozen_head_temperature": frozen_temperature,
        "matched_frozen_head_ablation_produced": True,
        "no_change_production_baseline_still_required": True,
        "shared_trainable_projection_parameters": 0,
        "per_cell_trainable_parameters": params,
        "seed": args.seed, "shots": args.shots, "steps": args.steps,
        "max_tokens": args.max_tokens, "batch_size": args.batch_size,
        "device": args.device, "threads": args.threads,
        "environment": research_environment(),
        "observed_total_physical_ram_bytes": psutil.virtual_memory().total,
        "generation": args.generation, "authority_epoch": args.authority_epoch,
        "model_load_ms": stem.load_ms, "cell_head_training_ms": train_ms,
        "encoder_calls": stem.encoder_calls, "encoder_examples": stem.encoder_examples,
        "cache_hits": stem.cache_hits, "temperature": temperature,
        "predictions_sha256": sha256_record(predictions),
        "limitations": [
            "This is a research encoder, not a production worker microbatch receipt",
            "Embedding-only path cannot claim learned cross-token relational fusion",
            "No real tool outcome or independently signed NDU receipt is established",
            "Context truncation counts are not measured by this trial",
        ],
    })


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--model", required=True, choices=("jina-v5-text-nano", "jina-v5-text-small"))
    p.add_argument("--revision", required=True, help="reviewed full 40-character HF commit SHA")
    p.add_argument("--dataset", required=True)
    p.add_argument("--task-id", required=True)
    p.add_argument("--output", required=True)
    p.add_argument("--principal-id", required=True)
    p.add_argument("--representation", choices=("joint", "state"), default="joint")
    p.add_argument("--head", choices=("linear", "film", "rank8", "rank16", "mlp", "swiglu"),
                   default="linear")
    p.add_argument("--dimension", type=int, default=256)
    p.add_argument("--budget", type=int, choices=(2048, 16384, 65536, 262144),
                   default=16384)
    p.add_argument("--shots", type=int, default=32)
    p.add_argument("--steps", type=int, default=100)
    p.add_argument("--batch-size", type=int, default=16)
    p.add_argument("--learning-rate", type=float, default=0.001)
    p.add_argument("--max-tokens", type=int, default=512)
    p.add_argument("--cache-entries", type=int, default=256)
    p.add_argument("--threads", type=int, default=4)
    p.add_argument("--seed", type=int, default=20261011)
    p.add_argument("--device", default="cpu")
    p.add_argument("--generation", type=int, default=1)
    p.add_argument("--authority-epoch", type=int, default=1)
    p.add_argument("--allow-pinned-remote-code", action="store_true")
    p.add_argument("--allow-model-download", action="store_true")
    execute(p.parse_args())


if __name__ == "__main__":
    main()
