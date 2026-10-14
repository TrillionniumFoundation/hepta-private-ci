#!/usr/bin/env python3
"""Offline frozen-feature, per-Cell tiny gated Head experiment. No authority.

Trains *only* on pre-produced Q24 features with labels available by cutoff.
Prediction rows must contain no labels and declared outcomes must be future.
Does not load Encoder weights, install Head, grant runtime access or sign receipts.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import re
import sys
import time

Q = 1 << 24
WIDTH = 384
RANKS = {2048: 1, 8192: 8, 16384: 16}
HEX40 = re.compile(r"^[a-f0-9]{40}$")
HEX64 = re.compile(r"^[a-f0-9]{64}$")


def require(predicate, reason):
    if not predicate:
        raise ValueError(reason)


def at(value):
    require(type(value) is str and value.endswith("Z"), "UTC timestamp required")
    try:
        return datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as exc:
        raise ValueError("malformed timestamp") from exc


def read_rows(path):
    rows = []
    def unique_pairs(pairs):
        value = {}
        for key, item in pairs:
            require(key not in value, "duplicate JSON key")
            value[key] = item
        return value
    with Path(path).open(encoding="utf-8") as stream:
        for line in stream:
            if line.strip():
                row = json.loads(
                    line, object_pairs_hook=unique_pairs,
                    parse_constant=lambda x: (_ for _ in ()).throw(
                        ValueError("nonfinite JSON constant")
                    ),
                )
                require(type(row) is dict, "row must be object")
                rows.append(row)
                require(len(rows) <= 8192, "Q24 Head input cohort exceeds safety bound")
    require(rows, "empty feature dataset")
    return rows


def validate_packets(training, predict, cutoff, now):
    cutoff, now = at(cutoff), at(now)
    require(cutoff < now, "training freeze must precede prediction time")
    require(2 <= len(training) <= 8192 and 2 <= len(predict) <= 8192,
            "train/predict cohort exceeds bounded experimental limit")
    records = training + predict
    frozen_identity = None
    names = set()
    groups = {}
    for index, row in enumerate(records):
        identity = tuple(row.get(k) for k in (
            "scope_id", "task_id", "encoder_digest", "model_revision",
            "tokenizer_digest", "normalization_digest",
            "quantization_digest", "generation", "fence",
        ))
        require(all(type(v) is str and bool(v) for v in identity[:2]),
                "missing scope/task")
        require(type(identity[2]) is str and bool(HEX64.fullmatch(identity[2])),
                "invalid Encoder digest")
        require(type(identity[3]) is str and bool(HEX40.fullmatch(identity[3])),
                "unfixed model revision")
        require(all(
            type(v) is str and bool(HEX64.fullmatch(v)) for v in identity[4:7]
        ), "missing tokenizer/normalizer/quantizer digest")
        require(type(identity[7]) is int and identity[7] > 0
                and type(identity[8]) is int and identity[8] > 0,
                "missing generation/fence")
        if frozen_identity is None:
            frozen_identity = identity
        require(identity == frozen_identity,
                "mixed scope or Encoder generation/fence")
        key = row.get("case_id")
        require(type(key) is str and bool(key) and key not in names,
                "duplicate case")
        names.add(key)
        group = row.get("group_id")
        require(type(group) is str and bool(group), "missing group")
        features = row.get("feature_q24")
        require(type(features) is list and len(features) == WIDTH and all(
            type(v) is int and -8 * Q <= v <= 8 * Q for v in features
        ), "feature dimension or Q24 value invalid")
        event = at(row.get("event_time"))
        released = at(row.get("label_available_at"))
        require(event < released, "label release before event")
        if index < len(training):
            require(row.get("split") == "train" and type(row.get("label")) is int
                    and row["label"] in (0, 1), "train needs binary label")
            require(event < cutoff and released <= cutoff,
                    "train label after cutoff")
            groups.setdefault(group, set()).add("train")
        else:
            require(row.get("split") in ("future", "old", "ood")
                    and "label" not in row,
                    "heldout labels forbidden in runner memory")
            require(cutoff < event <= now < released,
                    "heldout event/label not yet sealable")
            groups.setdefault(group, set()).add("future")
    require(all(len(partitions) == 1 for partitions in groups.values()),
            "train/heldout group leakage")
    require(len(training) >= 2 and len(predict) >= 2,
            "too few train/prediction rows")
    return frozen_identity


def head_type(torch, nn, rank):
    class GatedHead(nn.Module):
        def __init__(self):
            super().__init__()
            self.down = nn.Linear(WIDTH, rank, bias=False)
            self.up = nn.Linear(rank, WIDTH, bias=False)
            self.gate = nn.Linear(WIDTH, 1)
            self.out = nn.Linear(WIDTH, 2)

        def forward(self, x):
            z = x + torch.sigmoid(self.gate(x)) * self.up(self.down(x))
            return self.out(z)

    return GatedHead()


def train(train_rows, predict_rows, *, budget, seed, steps, cutoff, now,
          learning_rate=.005, optimizer_kind="adamw"):
    require(type(budget) is int and budget in RANKS,
            "budget must be 2048/8192/16384")
    require(type(seed) is int and 0 <= seed < 2**32,
            "invalid deterministic seed")
    require(type(steps) is int and 1 <= steps <= 2048,
            "bounded steps required")
    require(type(learning_rate) in (int, float)
            and 0 < learning_rate <= .1 and math.isfinite(learning_rate),
            "invalid learning rate")
    require(optimizer_kind in ("adamw", "sgd"), "invalid optimizer arm")
    identity = validate_packets(train_rows, predict_rows, cutoff, now)
    import torch
    from torch import nn
    torch.set_num_threads(1)
    torch.manual_seed(seed)
    rank = RANKS[budget]
    model = head_type(torch, nn, rank)
    actual_parameters = sum(
        p.numel() for p in model.parameters() if p.requires_grad
    )
    require(actual_parameters == 2 * WIDTH * rank + 3 * WIDTH + 3
            and actual_parameters <= budget,
            "unaccounted Head parameters")
    optimizer = (
        torch.optim.AdamW(model.parameters(), lr=learning_rate)
        if optimizer_kind == "adamw"
        else torch.optim.SGD(model.parameters(), lr=learning_rate, momentum=0)
    )
    x = torch.tensor(
        [[v / Q for v in r["feature_q24"]] for r in train_rows],
        dtype=torch.float32,
    )
    y = torch.tensor([r["label"] for r in train_rows], dtype=torch.long)
    frozen = head_type(torch, nn, rank)
    frozen.load_state_dict(model.state_dict())
    frozen.eval()
    model.train()
    for _ in range(steps):
        optimizer.zero_grad(set_to_none=True)
        nn.functional.cross_entropy(model(x), y).backward()
        optimizer.step()
    model.eval()
    head_parameter_bytes = sum(
        parameter.numel() * parameter.element_size()
        for parameter in model.parameters()
    )
    optimizer_tensor_bytes = sum(
        value.numel() * value.element_size()
        for state in optimizer.state.values()
        for value in state.values()
        if isinstance(value, torch.Tensor)
    )
    # Shape-accounted tensor payload only. This is NOT a process RSS,
    # Q24 state, tensor allocator, or GPU driver measurement.
    assert head_parameter_bytes == actual_parameters * 4

    def model_hash(m):
        # A research-only SHA256, NOT a Hepta artifact CAS or authenticated receipt.
        payload = hashlib.sha256(b"hepta.research.gated-head-fp32.v1")
        for key, value in sorted(m.state_dict().items()):
            payload.update(key.encode("utf-8") + b"\0")
            payload.update(
                value.detach().cpu().contiguous().numpy().tobytes()
            )
        return payload.hexdigest()

    def predictions(m):
        weights = model_hash(m)
        results = []
        for row in predict_rows:
            vector = torch.tensor(
                [v / Q for v in row["feature_q24"]], dtype=torch.float32
            )[None]
            started = time.perf_counter_ns()
            with torch.inference_mode():
                probability = float(
                    m(vector).softmax(dim=-1)[0, 1]
                )
            micros = max(1, (time.perf_counter_ns() - started) // 1000)
            require(math.isfinite(probability), "nonfinite Head output")
            committed = datetime.now(timezone.utc).isoformat(
                timespec="microseconds"
            ).replace("+00:00", "Z")
            require(
                at(row["event_time"]) <= at(committed)
                < at(row["label_available_at"]),
                "prediction label became available before actual prediction",
            )
            results.append({
                "case_id": row["case_id"],
                "scope_id": identity[0], "task_id": identity[1],
                "split": row["split"], "abstain": False,
                "probability_positive": probability,
                "prediction_committed_at": committed,
                "encoder_digest": identity[2],
                "model_revision": identity[3],
                "head_digest": weights, "weights_digest": weights,
                "runtime_generation": identity[7],
                "execution_receipt_id": "RESEARCH_ONLY_UNVERIFIED_" + weights[:16],
                "latency_micros": micros,
                "resident_bytes": 0, "transient_bytes": 0,
            })
        return results

    result = {
        "schema": "hepta.shared-encoder-gated-head-shadow.v1",
        "status": "HEAD_TRAINED_RESEARCH_ONLY",
        "authority": "DENY_ALL",
        "production_promotion_permitted": False,
        "independent_ndu_verified": False,
        "encoder_execution_verified": False,
        "original_feature_provenance_verified": False,
        "runtime_worker_receipts_verified": False,
        "resource_memory_verified": False,
        "optimizer_kind": optimizer_kind,
        "head_rank": rank, "head_parameter_ceiling": budget,
        "trainable_head_parameters": actual_parameters,
        "head_fp32_parameter_payload_bytes": head_parameter_bytes,
        "optimizer_tensor_payload_bytes": optimizer_tensor_bytes,
        "head_plus_optimizer_tensor_payload_bytes": (
            head_parameter_bytes + optimizer_tensor_bytes
        ),
        "tensor_payload_excludes_runtime_and_q24_state": True,
        "torch_version": str(torch.__version__),
        "trainable_encoder_parameters": 0,
        "seed": seed, "steps": steps,
        "train_sample_count": len(train_rows),
        "prediction_sample_count": len(predict_rows),
        "source_identity": {
            "scope_id": identity[0], "task_id": identity[1],
            "encoder_digest": identity[2], "model_revision": identity[3],
            "generation": identity[7], "fence": identity[8],
        },
        "frozen_head_sha256": model_hash(frozen),
        "trained_head_sha256": model_hash(model),
        "warning": "Features, timestamps and runtime identities are not independently authenticated.",
    }
    return result, predictions(model), predictions(frozen)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    for field in ("train", "predict", "train-cutoff", "output-prefix"):
        parser.add_argument("--" + field, required=True)
    parser.add_argument("--budget", type=int, choices=sorted(RANKS), default=2048)
    parser.add_argument("--seed", type=int, default=17)
    parser.add_argument("--steps", type=int, default=30)
    parser.add_argument("--optimizer", choices=("adamw", "sgd"), default="adamw")
    args = parser.parse_args(argv)
    now = datetime.now(timezone.utc).isoformat(
        timespec="microseconds"
    ).replace("+00:00", "Z")
    prefix = Path(args.output_prefix)
    paths = [
        Path(str(prefix) + ext)
        for ext in (".manifest.json", ".learned.jsonl", ".frozen.jsonl")
    ]
    try:
        if any(path.exists() for path in paths):
            raise FileExistsError("refuse to overwrite existing evidence files")
        manifest, learned, frozen = train(
            read_rows(args.train), read_rows(args.predict),
            budget=args.budget, seed=args.seed, steps=args.steps,
            cutoff=args.train_cutoff, now=now, optimizer_kind=args.optimizer,
        )
        for path, data in zip(paths, (manifest, learned, frozen)):
            with path.open("x", encoding="utf-8") as stream:
                if isinstance(data, list):
                    for row in data:
                        stream.write(json.dumps(row, sort_keys=True) + "\n")
                else:
                    stream.write(json.dumps(data, indent=2, sort_keys=True) + "\n")
    except (ValueError, OSError, ImportError) as exc:
        print(f"Head shadow failed closed: {exc}", file=sys.stderr)
        return 2
    print(
        f"Wrote research-only Head artifacts to prefix {prefix}; "
        "NOT production approved"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
