#!/usr/bin/env python3
"""Strict 384D frozen-Encoder / Q24 Cell-Head paired research trial.

No download, remote code, learned projection, promotion, final-use or NDU
verification. An external no-change prediction set is always required for an
efficacy claim; the matched frozen Head is a separate learning ablation.
"""

import argparse
import copy
import hashlib
import json
import math
import re
import time
from dataclasses import dataclass
from pathlib import Path

from hf_trial import make_head
from q24_bridge import Q24, quantize_q24, shadow_feature_digest
from qualified_eval import HEADS, audit_dataset, digest, read_jsonl


@dataclass(frozen=True)
class CompactStemSpec:
    repository: str
    parameters_estimate: int
    width: int
    pooling: str
    published_max_tokens: int
    license: str


STEMS = {
    "mmbert-small": CompactStemSpec(
        "jhu-clsp/mmBERT-small", 140_000_000, 384, "masked_mean_l2", 8192, "MIT"),
    "granite-97m-multilingual-r2": CompactStemSpec(
        "ibm-granite/granite-embedding-97m-multilingual-r2", 97_000_000,
        384, "cls_l2", 32768, "Apache-2.0"),
}
MAX_NEURON_WIDTH = 512


def validate_profile(model_id, revision, max_tokens):
    if model_id not in STEMS:
        raise ValueError("unregistered compact Stem; no arbitrary model execution")
    if not isinstance(revision, str) or not re.fullmatch(r"[0-9a-f]{40}", revision):
        raise ValueError("model revision must be a pinned 40-hex commit SHA")
    spec = STEMS[model_id]
    if (type(max_tokens) is not int or not 16 <= max_tokens <= 512
            or max_tokens > spec.published_max_tokens or spec.width > MAX_NEURON_WIDTH):
        raise ValueError("compact Stem must fit the matched <=512 token/Q24 research profile")
    return spec


def render_joint(row):
    options = " | ".join(f"{i}: {option}" for i, option in enumerate(row["options"]))
    return f"State: {row['state']}\nQuestion: {row['question']}\nOptions: {options}"


def choose_task_rows(rows, task_id, shots, seed, scope_id=None):
    import random

    audited = audit_dataset(rows)
    candidate = [row for row in rows if row["task_id"] == task_id]
    scopes = {row["scope_id"] for row in candidate}
    if not candidate or (scope_id is None and len(scopes) != 1):
        raise ValueError("task not found or spans multiple scopes; require explicit Scope")
    chosen_scope = scope_id if scope_id is not None else next(iter(scopes))
    task = [row for row in candidate if row["scope_id"] == chosen_scope]
    if {row["split"] for row in task} != {"train", "calibration", "test", "future", "ood"}:
        raise ValueError("target task requires all five independently audited splits")
    groups = {}
    for row in task:
        if row["split"] == "train":
            groups.setdefault((row["scope_id"], row["group_id"]), []).append(row)
    if type(shots) is not int or shots < 1 or shots > len(groups):
        raise ValueError("insufficient independent train groups for requested shots")
    rng = random.Random(seed)
    chosen = [rng.choice(sorted(groups[key], key=lambda r: r["case_id"]))
              for key in rng.sample(sorted(groups), shots)]
    return task, chosen, audited


def pool_states(torch, outputs, attention_mask, pooling):
    """Use each published representation family, never raw mean for Granite R2."""
    states = outputs.last_hidden_state.float()
    if states.ndim != 3 or states.shape[0] != 1 or states.shape[-1] != 384:
        raise ValueError("Encoder returned invalid batch or hidden width")
    if (attention_mask.shape != states.shape[:2]
            or not bool(torch.all(attention_mask[0] >= 0))
            or not bool(torch.any(attention_mask[0] > 0))):
        raise ValueError("invalid Encoder attention mask")
    if pooling == "cls_l2":
        vector = states[0, 0]
    elif pooling == "masked_mean_l2":
        mask = attention_mask[0].to(dtype=states.dtype)
        vector = (states[0] * mask[:, None]).sum(dim=0) / mask.sum()
    else:
        raise ValueError("unregistered pooling policy")
    if not bool(torch.isfinite(vector).all()) or float(torch.linalg.vector_norm(vector)) <= 1e-12:
        raise ValueError("nonfinite or degenerate Encoder feature")
    return torch.nn.functional.normalize(vector, p=2, dim=0)


class FrozenCompactStem:
    def __init__(self, model_id, revision, *, device="cpu", max_tokens=512):
        spec = validate_profile(model_id, revision, max_tokens)
        import torch
        from transformers import AutoModel, AutoTokenizer

        self.spec = spec
        self.revision = revision
        self.model_id = model_id
        self.device = device
        self.max_tokens = max_tokens
        self.torch = torch
        begin = time.perf_counter_ns()
        # Identical pinned revisions apply to model and tokenizer. No floating
        # main, network download, pickle conversion or arbitrary remote code.
        opts = {"revision": revision, "local_files_only": True, "trust_remote_code": False}
        self.tokenizer = AutoTokenizer.from_pretrained(spec.repository, **opts)
        self.model = AutoModel.from_pretrained(
            spec.repository, use_safetensors=True, **opts).to(device).eval()
        if getattr(self.model.config, "hidden_size", None) != spec.width:
            raise ValueError("staged model hidden width disagrees with preregistered Stem")
        for parameter in self.model.parameters():
            parameter.requires_grad_(False)
        self.model_load_ms = (time.perf_counter_ns() - begin) / 1e6

    def encode(self, row, *, allow_truncation=False):
        text = render_joint(row)
        raw = self.tokenizer(text, return_tensors="pt", truncation=False)
        original_tokens = int(raw["input_ids"].shape[1])
        truncated = original_tokens > self.max_tokens
        if truncated and not allow_truncation:
            raise ValueError("tokenization exceeded matched window; no silent truncation")
        encoded = self.tokenizer(text, return_tensors="pt", truncation=True,
                                 max_length=self.max_tokens)
        encoded = {key: value.to(self.device) for key, value in encoded.items()}
        begin = time.perf_counter_ns()
        with self.torch.inference_mode():
            outputs = self.model(**encoded)
            vector = pool_states(self.torch, outputs, encoded["attention_mask"], self.spec.pooling)
        elapsed_ms = (time.perf_counter_ns() - begin) / 1e6
        # Training and evaluation both consume exactly the bounded rounded Q24
        # feature. No trainable 384->64 projector can escape the Head ceiling.
        q24 = quantize_q24(vector.detach().cpu().tolist())
        feature = self.torch.tensor([value / Q24 for value in q24], dtype=self.torch.float32)
        return feature, shadow_feature_digest([value / Q24 for value in q24]), {
            "original_tokens": original_tokens,
            "truncated": truncated,
            "encoder_forward_ms": elapsed_ms,
        }


def weights_digest(module):
    h = hashlib.sha256(b"hepta.compact-stem-head-q24.v1")
    for name, value in sorted(module.state_dict().items()):
        h.update(name.encode("utf-8") + b"\0")
        h.update(value.detach().cpu().contiguous().numpy().tobytes())
    return h.hexdigest()


def run(args):
    import psutil
    import torch
    from torch import nn

    spec = validate_profile(args.model, args.revision, args.max_tokens)
    if (args.head not in HEADS or args.budget not in (2048, 8192, 16384)
            or any(type(x) is not int or x < 1 for x in
                   (args.shots, args.steps, args.batch_size, args.threads))
            or not math.isfinite(args.learning_rate) or args.learning_rate <= 0):
        raise ValueError("invalid precommitted Head/training budget")
    output = Path(args.output)
    frozen_output = Path(str(output) + ".frozen-head.jsonl")
    manifest_output = Path(str(output) + ".manifest.json")
    if any(path.exists() for path in (output, frozen_output, manifest_output)):
        raise FileExistsError("refusing to overwrite prior prediction evidence")
    task, selected, audit = choose_task_rows(read_jsonl(args.dataset), args.task_id,
                                             args.shots, args.seed, args.scope_id)
    classes = len(task[0]["options"])
    if any(len(row["options"]) != classes for row in task):
        raise ValueError("task class width changed")
    torch.set_num_threads(args.threads)
    torch.manual_seed(args.seed)
    stem = FrozenCompactStem(args.model, args.revision, device=args.device,
                             max_tokens=args.max_tokens)
    features, metadata, feature_sha = {}, {}, {}
    to_encode = selected + [row for row in task if row["split"] != "train"]
    for row in to_encode:
        case_id = row["case_id"]
        features[case_id], fingerprint, metadata[case_id] = stem.encode(
            row, allow_truncation=args.allow_truncation)
        feature_sha[case_id] = fingerprint["research_only_feature_sha256"]
    torch.manual_seed(args.seed)  # same Head initialization independent of model loading
    head, actual_parameters = make_head(torch, nn, args.head, spec.width,
                                       classes, args.budget)
    if actual_parameters != sum(p.numel() for p in head.parameters() if p.requires_grad):
        raise ValueError("unaccounted trainable Head parameters")
    head = head.to(args.device)
    frozen_head = copy.deepcopy(head).eval()
    optimizer = torch.optim.AdamW(head.parameters(), lr=args.learning_rate)
    train_x = torch.stack([features[row["case_id"]] for row in selected]).to(args.device)
    train_y = torch.tensor([row["label"] for row in selected], dtype=torch.long,
                           device=args.device)
    generator = torch.Generator(device="cpu").manual_seed(args.seed)
    indices_sha = hashlib.sha256(b"hepta.compact-stem-minibatches.v1")
    started = time.perf_counter_ns()
    head.train()
    for _ in range(args.steps):
        indices = torch.randint(len(selected), (args.batch_size,), generator=generator)
        indices_sha.update(indices.contiguous().numpy().tobytes())
        idx = indices.to(args.device)
        loss = nn.functional.cross_entropy(head(train_x[idx]), train_y[idx])
        optimizer.zero_grad(set_to_none=True)
        loss.backward()
        optimizer.step()
    train_ms = (time.perf_counter_ns() - started) / 1e6
    head.eval()

    calibration = [row for row in task if row["split"] == "calibration"]
    temps = (.5, .75, 1., 1.25, 1.5, 2., 3., 4., 6.)
    def calibrated_temperature(module):
        with torch.inference_mode():
            logits = torch.stack([module(features[row["case_id"]].to(args.device))
                                  for row in calibration])
            truth = torch.tensor([row["label"] for row in calibration],
                                 dtype=torch.long, device=args.device)
            return min(temps, key=lambda t: nn.functional.cross_entropy(logits / t, truth).item())

    learned_temp = calibrated_temperature(head)
    frozen_temp = calibrated_temperature(frozen_head)
    learned_digest, frozen_digest = weights_digest(head), weights_digest(frozen_head)
    process = psutil.Process()
    learned_rows, frozen_rows = [], []
    encoder_identity = digest([spec.repository, args.revision, spec.pooling,
                               args.max_tokens, "l2->nearest-even-q24"])
    for row in task:
        if row["split"] == "train":
            continue
        x = features[row["case_id"]].to(args.device)
        for module, temperature, model_suffix, head_digest, bucket in (
            (head, learned_temp, "", learned_digest, learned_rows),
            (frozen_head, frozen_temp, "/frozen-head", frozen_digest, frozen_rows),
        ):
            start = time.perf_counter_ns()
            with torch.inference_mode():
                prob = torch.softmax(module(x) / temperature, dim=-1).cpu().tolist()
            head_ms = (time.perf_counter_ns() - start) / 1e6
            bucket.append({
                "case_id": row["case_id"], "scope_id": row["scope_id"],
                "model_id": args.model + model_suffix, "model_revision": args.revision,
                "encoder_digest": encoder_identity, "head_digest": head_digest,
                "runtime_generation": 1, "status": "Succeeded", "probabilities": prob,
                "execution_path": "encoder_warm",
                "latency_ms": metadata[row["case_id"]]["encoder_forward_ms"] + head_ms,
                "rss_bytes": process.memory_info().rss, "backend_batch_size": 1,
                "shadow_feature_sha256": feature_sha[row["case_id"]],
            })
    output.parent.mkdir(parents=True, exist_ok=True)
    for path, rows in ((output, learned_rows), (frozen_output, frozen_rows)):
        with path.open("x", encoding="utf-8") as handle:
            for record in rows:
                handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")
    manifest = {
        "schema": "hepta.compact-stem-head-only-shadow.v1",
        "model_id": args.model, "model_repository": spec.repository,
        "model_revision": args.revision, "estimated_encoder_parameters": spec.parameters_estimate,
        "license": spec.license, "pooling": spec.pooling, "feature_width": spec.width,
        "feature_q24_rounded": True, "trainable_shared_projection_parameters": 0,
        "trainable_encoder_parameters": 0,
        "actual_complete_trainable_head_parameters": actual_parameters,
        "head_parameter_ceiling": args.budget, "head_kind": args.head,
        "selected_train_case_digest": digest(sorted(row["case_id"] for row in selected)),
        "training_minibatch_indices_sha256": indices_sha.hexdigest(),
        "dataset_digest": audit["dataset_digest"], "scope_id": args.scope_id, "shots": args.shots,
        "steps": args.steps, "batch_size": args.batch_size, "seed": args.seed,
        "max_tokens_per_model": args.max_tokens,
        "truncated_cases": sum(int(v["truncated"]) for v in metadata.values()),
        "cross_model_nontruncated_comparability": not any(v["truncated"] for v in metadata.values()),
        "device": args.device, "threads": args.threads, "model_load_ms": stem.model_load_ms,
        "observed_total_encoder_forward_ms": sum(v["encoder_forward_ms"] for v in metadata.values()),
        "observed_head_training_ms": train_ms,
        "learned_head_sha256": learned_digest, "frozen_head_sha256": frozen_digest,
        "learned_predictions_sha256": digest(learned_rows),
        "frozen_predictions_sha256": digest(frozen_rows),
        "frozen_head_is_production_no_change": False,
        "production_no_change_supplied": False, "independent_future_ndu_verified": False,
        "publisher_weight_bytes_authenticated": False,
        "model_execution_is_research_backend_only": True,
        "production_promotion_permitted": False,
        "authority": "DENY_ALL",
    }
    with manifest_output.open("x", encoding="utf-8") as handle:
        handle.write(json.dumps(manifest, ensure_ascii=False, sort_keys=True) + "\n")
    return {"learned": str(output), "frozen": str(frozen_output),
            "manifest": str(manifest_output), "parameters": actual_parameters,
            "production_promotion_permitted": False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", required=True, choices=sorted(STEMS))
    parser.add_argument("--revision", required=True)
    parser.add_argument("--dataset", required=True)
    parser.add_argument("--task-id", required=True)
    parser.add_argument("--scope-id", required=True)
    parser.add_argument("--head", required=True, choices=HEADS)
    parser.add_argument("--budget", type=int, required=True, choices=(2048, 8192, 16384))
    parser.add_argument("--shots", type=int, default=32)
    parser.add_argument("--steps", type=int, default=100)
    parser.add_argument("--batch-size", type=int, default=16)
    parser.add_argument("--max-tokens", type=int, default=512)
    parser.add_argument("--threads", type=int, default=4)
    parser.add_argument("--seed", type=int, default=20261014)
    parser.add_argument("--learning-rate", type=float, default=0.001)
    parser.add_argument("--device", default="cpu")
    parser.add_argument("--allow-truncation", action="store_true",
                        help="diagnostic only; invalidates nontruncated comparability")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    print(json.dumps(run(args), sort_keys=True))


if __name__ == "__main__":
    main()
