#!/usr/bin/env python3
"""Frozen Hugging Face Stem + locally trained Head shadow experiment.

This is a research runner, not the Hepta inference authority or production
Cell training owner. It never modifies a selected model or a runtime artifact.
"""
import argparse
import hashlib
import json
import math
import random
import re
import time
from collections import OrderedDict
from pathlib import Path

from qualified_eval import HEADS, MODES, audit_dataset, digest, read_jsonl, write_json

STEMS = {
    "mmbert-small": "jhu-clsp/mmBERT-small",
    "modernbert-base": "answerdotai/ModernBERT-base",
    "jina-v2-base-zh": "jinaai/jina-embeddings-v2-base-zh",
    "bge-small-zh": "BAAI/bge-small-zh-v1.5",
}


def make_head(torch, nn, kind, width, classes, budget):
    class Film(nn.Module):
        def __init__(self):
            super().__init__()
            self.gate = nn.Linear(width, width)
            self.output = nn.Linear(width, classes)

        def forward(self, x):
            return self.output(x * torch.sigmoid(self.gate(x)))

    class SwiGLU(nn.Module):
        def __init__(self, inner):
            super().__init__()
            self.left = nn.Linear(width, inner)
            self.right = nn.Linear(width, inner)
            self.output = nn.Linear(inner, classes)

        def forward(self, x):
            return self.output(torch.nn.functional.silu(self.left(x)) * self.right(x))

    if kind == "linear":
        module = nn.Linear(width, classes)
    elif kind == "film":
        module = Film()
    elif kind in ("rank8", "rank16"):
        rank = 8 if kind == "rank8" else 16
        module = nn.Sequential(nn.Linear(width, rank), nn.SiLU(), nn.Linear(rank, classes))
    elif kind in ("mlp", "swiglu"):
        # Largest hidden dimension under the exact head parameter ceiling.
        best = None
        for inner in range(1, 4097):
            candidate = (nn.Sequential(nn.Linear(width, inner), nn.GELU(),
                                       nn.Linear(inner, classes)) if kind == "mlp"
                         else SwiGLU(inner))
            if sum(p.numel() for p in candidate.parameters()) > budget:
                break
            best = candidate
        if best is None:
            raise ValueError("budget too small for this head")
        module = best
    else:
        raise ValueError(f"unknown head: {kind}")
    parameters = sum(p.numel() for p in module.parameters())
    if parameters > budget:
        raise ValueError(f"{kind} needs {parameters} parameters, budget={budget}")
    return module, parameters


class FrozenStem:
    """Scope-separated, bounded cache of frozen contextual states.

    No principal, scope or model revision is permitted to borrow another's
    computed features. The question-conditioned joint path caches only exact
    full inputs; state-only paths intentionally lose cross-token reasoning.
    """

    def __init__(self, model_id, revision, device, max_tokens,
                 allow_remote_code=False, cache_entries=256):
        if model_id not in STEMS:
            raise ValueError("only the four pinned research stems are supported")
        if not re.fullmatch(r"[0-9a-f]{40}", revision):
            raise ValueError("a full, immutable Hugging Face commit SHA is required")
        if model_id == "jina-v2-base-zh" and not allow_remote_code:
            raise ValueError("Jina requires explicit opt-in for pinned remote model code")
        if cache_entries < 1 or max_tokens < 16 or max_tokens > 512:
            raise ValueError("research profile requires 16..512 tokens and bounded cache")
        import torch
        from transformers import AutoModel, AutoTokenizer

        self.torch = torch
        self.model_id = model_id
        self.revision = revision
        self.device = device
        self.max_tokens = max_tokens
        self.cache_entries = cache_entries
        self.cache = OrderedDict()
        self.total_encoder_calls = 0
        self.total_cache_hits = 0
        self.truncated_examples = 0
        self.load_start_ns = time.perf_counter_ns()
        name = STEMS[model_id]
        self.tokenizer = AutoTokenizer.from_pretrained(
            name, revision=revision, trust_remote_code=allow_remote_code)
        self.model = AutoModel.from_pretrained(
            name, revision=revision, trust_remote_code=allow_remote_code).to(device).eval()
        for parameter in self.model.parameters():
            parameter.requires_grad_(False)
        self.load_ms = (time.perf_counter_ns() - self.load_start_ns) / 1e6
        self.width = self.model.config.hidden_size

    def _run(self, text):
        torch = self.torch
        raw = self.tokenizer(text, return_tensors="pt", truncation=False)
        if raw["input_ids"].shape[1] > self.max_tokens:
            self.truncated_examples += 1
        tokens = self.tokenizer(text, return_tensors="pt", truncation=True,
                                max_length=self.max_tokens)
        tokens = {k: v.to(self.device) for k, v in tokens.items()}
        with torch.inference_mode():
            states = self.model(**tokens).last_hidden_state[0].float()
        self.total_encoder_calls += 1
        return states.detach().cpu()

    def _query(self, text):
        torch = self.torch
        ids = self.tokenizer(text, return_tensors="pt", truncation=True,
                             max_length=self.max_tokens)["input_ids"].to(self.device)
        with torch.inference_mode():
            embedding = self.model.get_input_embeddings()(ids)[0].float().mean(dim=0)
        return embedding.detach().cpu()

    def encode(self, row, mode):
        if mode not in MODES:
            raise ValueError(f"invalid encoding mode: {mode}")
        scope = row["scope_id"]
        options = " | ".join(f"{i}: {v}" for i, v in enumerate(row["options"]))
        condition = f"Question: {row['question']}\nOptions: {options}"
        text = (f"State: {row['state']}\n{condition}" if mode == "joint"
                else f"State: {row['state']}")
        key = digest([scope, self.model_id, self.revision, self.max_tokens, text])
        start = time.perf_counter_ns()
        hit = key in self.cache
        if hit:
            self.total_cache_hits += 1
            states = self.cache.pop(key)
        else:
            states = self._run(text)
        self.cache[key] = states
        if len(self.cache) > self.cache_entries:
            self.cache.popitem(last=False)
        torch = self.torch
        if mode in ("joint", "sentence"):
            feature = states.mean(dim=0)
        else:
            # Deterministic uniform token landmarks, not oracle selection.
            indices = torch.linspace(0, states.shape[0] - 1,
                                     steps=min(8, states.shape[0])).long()
            landmarks = states[indices]
            query = self._query(condition)
            if mode == "landmark":
                context = landmarks.mean(dim=0)
            else:
                # Cheap, question-conditioned token attention; NO Transformer
                # recomputation and NO claim of full joint-reasoning parity.
                weights = torch.softmax((landmarks @ query) / math.sqrt(self.width), dim=0)
                context = (landmarks * weights.unsqueeze(-1)).sum(dim=0)
            feature = torch.cat((context, query))
        elapsed = (time.perf_counter_ns() - start) / 1e6
        return feature, ("cache_hit_head" if hit else "encoder_warm"), elapsed


def trial(args):
    import psutil
    import torch
    from torch import nn

    torch.manual_seed(args.seed)
    random.seed(args.seed)
    torch.set_num_threads(args.threads)
    dataset = read_jsonl(args.dataset)
    audit = audit_dataset(dataset)
    dataset = [r for r in dataset if r["task_id"] == args.task_id]
    if not dataset:
        raise ValueError(f"no examples for task {args.task_id}")
    if any(not any(r["split"] == part for r in dataset)
           for part in ("train", "calibration", "test", "future", "ood")):
        raise ValueError("selected task must cover all five splits")
    train = [r for r in dataset if r["split"] == "train"]
    if args.shots > len(train):
        raise ValueError("requested shots exceed task training examples")
    rng = random.Random(args.seed)
    selected = rng.sample(sorted(train, key=lambda r: r["case_id"]), args.shots)
    stem = FrozenStem(args.model, args.revision, args.device, args.max_tokens,
                      args.allow_pinned_remote_code, args.cache_entries)
    features = {}
    timings = {}
    for row in selected + [r for r in dataset if r["split"] != "train"]:
        vector, path, elapsed = stem.encode(row, args.mode)
        features[row["case_id"]] = vector
        timings[row["case_id"]] = (path, elapsed)
    width = len(next(iter(features.values())))
    projection = nn.Linear(width, args.organ_width).to(args.device)
    classes = len(dataset[0]["options"])
    if any(len(r["options"]) != classes for r in dataset):
        raise ValueError("mixed option widths in task")
    head, head_params = make_head(torch, nn, args.head, args.organ_width,
                                 classes, args.budget)
    head = head.to(args.device)
    optimizer = torch.optim.AdamW(list(projection.parameters()) + list(head.parameters()),
                                   lr=args.learning_rate)
    vectors = torch.stack([features[r["case_id"]] for r in selected]).to(args.device)
    labels = torch.tensor([r["label"] for r in selected], dtype=torch.long, device=args.device)
    train_start = time.perf_counter_ns()
    projection.train()
    head.train()
    for step in range(args.steps):
        gen = torch.Generator().manual_seed(args.seed + step)
        chosen = torch.randint(len(selected), (args.batch_size,), generator=gen).to(args.device)
        logits = head(projection(vectors[chosen]))
        loss = nn.functional.cross_entropy(logits, labels[chosen])
        optimizer.zero_grad(set_to_none=True)
        loss.backward()
        optimizer.step()
    train_ms = (time.perf_counter_ns() - train_start) / 1e6
    projection.eval()
    head.eval()

    def logits_for(row):
        with torch.inference_mode():
            return head(projection(features[row["case_id"]].to(args.device))).float()

    calibration = [r for r in dataset if r["split"] == "calibration"]
    # Only calibration labels choose the temperature; never tune on test/future.
    with torch.inference_mode():
        logit_stack = torch.stack([logits_for(r) for r in calibration])
        y = torch.tensor([r["label"] for r in calibration], device=args.device)
        temperatures = (.5, .75, 1., 1.25, 1.5, 2., 3., 4., 6.)
        temperature = min(temperatures,
                          key=lambda t: nn.functional.cross_entropy(logit_stack / t, y).item())
    records = []
    process = psutil.Process()
    for row in dataset:
        if row["split"] == "train":
            continue
        start = time.perf_counter_ns()
        with torch.inference_mode():
            probs = torch.softmax(logits_for(row) / temperature, dim=-1).cpu().tolist()
        head_ms = (time.perf_counter_ns() - start) / 1e6
        path, encoder_ms = timings[row["case_id"]]
        # Costs cover encoder feature preparation and Head, NOT teacher inference.
        records.append({
            "case_id": row["case_id"], "model_id": args.model,
            "model_revision": args.revision,
            "encoder_digest": digest([STEMS[args.model], args.revision, args.mode]),
            "head_digest": digest([args.head, args.budget, args.steps, args.seed,
                                   args.shots, args.task_id]),
            "runtime_generation": 1, "scope_id": row["scope_id"],
            "status": "Succeeded", "probabilities": probs,
            "execution_path": path, "latency_ms": encoder_ms + head_ms,
            "rss_bytes": process.memory_info().rss,
            "backend_batch_size": 1,
        })
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text("".join(json.dumps(r, sort_keys=True) + "\n" for r in records),
                      encoding="utf-8")
    write_json(str(output) + ".manifest.json", {
        "schema": "hepta.neuron-stem-hf-shadow.v1",
        "no_change_baseline_supplied": False,
        "production_promotion_permitted": False,
        "dataset_audit": audit,
        "selected_task": args.task_id,
        "model_id": args.model,
        "model_repository": STEMS[args.model],
        "model_revision": args.revision,
        "mode": args.mode, "head": args.head, "max_head_parameters": args.budget,
        "actual_head_parameters": head_params,
        "organ_projection_parameters": sum(p.numel() for p in projection.parameters()),
        "steps": args.steps, "shots": args.shots, "batch_size": args.batch_size,
        "seed": args.seed, "device": args.device, "threads": args.threads,
        "calibration_temperature": temperature,
        "model_load_ms": stem.load_ms, "head_training_ms": train_ms,
        "encoder_calls": stem.total_encoder_calls,
        "cache_hits": stem.total_cache_hits,
        "truncated_examples": stem.truncated_examples,
        "results_digest": digest(records),
        "warning": "Research backend timing is NOT a real Hepta worker-batch receipt."
    })


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", required=True, choices=sorted(STEMS))
    parser.add_argument("--revision", required=True)
    parser.add_argument("--dataset", required=True)
    parser.add_argument("--task-id", required=True)
    parser.add_argument("--mode", required=True, choices=MODES)
    parser.add_argument("--head", required=True, choices=HEADS)
    parser.add_argument("--budget", required=True, type=int, choices=(2048, 16384, 65536, 262144))
    parser.add_argument("--shots", type=int, default=32)
    parser.add_argument("--steps", type=int, default=100)
    parser.add_argument("--batch-size", type=int, default=16)
    parser.add_argument("--organ-width", type=int, default=64)
    parser.add_argument("--learning-rate", type=float, default=0.001)
    parser.add_argument("--max-tokens", type=int, default=512)
    parser.add_argument("--cache-entries", type=int, default=256)
    parser.add_argument("--threads", type=int, default=4)
    parser.add_argument("--seed", type=int, default=20261011)
    parser.add_argument("--device", default="cpu")
    parser.add_argument("--allow-pinned-remote-code", action="store_true")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    if any(v < 1 for v in (args.shots, args.steps, args.batch_size,
                           args.organ_width, args.threads)):
        parser.error("shots, steps, batch size, organ width and threads must be positive")
    trial(args)


if __name__ == "__main__":
    main()
