#!/usr/bin/env python3
"""Explicit, offline model adapter; cannot authorize Hepta production use.

Install the independently reviewed Laya/SentenceTransformers runtime on a
named test host. Model directories and file digests must already be provisioned.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import random
import time
from pathlib import Path

import bakeoff

os.environ["HF_HUB_OFFLINE"] = "1"
os.environ["TRANSFORMERS_OFFLINE"] = "1"


def verified_local_model(path: Path, entry: dict) -> Path:
    root = path.resolve(strict=True)
    bakeoff.require(root.is_dir(), "checkpoint must be an existing local directory")
    entries = entry.get("files_sha256")
    bakeoff.require(isinstance(entries, dict) and entries, "complete pinned local file inventory required")
    discovered = {str(p.relative_to(root)) for p in root.rglob("*") if p.is_file()}
    bakeoff.require(discovered == set(entries), "unlisted/missing checkpoint files")
    for rel, expected in entries.items():
        f = root / rel
        bakeoff.require(f.resolve().is_relative_to(root) and not f.is_symlink(), "checkpoint path escape or symlink")
        bakeoff.require(bakeoff.is_hex(expected) and bakeoff.digest(f) == expected, f"artifact mismatch: {rel}")
    weights = sorted((key, value) for key, value in entries.items()
                     if key.endswith((".safetensors", ".bin", ".pt")))
    bakeoff.require(bool(weights), "no weight files")
    canonical = json.dumps(weights, separators=(",", ":"), ensure_ascii=True).encode("ascii")
    bakeoff.require(hashlib.sha256(canonical).hexdigest() == entry["weights_sha256"],
                    "weight inventory SHA-256 mismatch")
    return root


def blind_rows(path: Path) -> list[dict]:
    rows = bakeoff.jsonl(path)
    ids = set()
    for row in rows:
        bakeoff.require(set(row) <= {"id", "state", "options", "language", "instructions", "split"},
                        "blind inference file contains gold or unknown fields")
        bakeoff.require(isinstance(row.get("id"), str) and row["id"] not in ids, "duplicate blind id")
        bakeoff.require(row.get("split") in ("calibration", "future_1", "future_2"), "wrong inference split")
        bakeoff.require(isinstance(row.get("state"), str) and 0 < len(row["state"]) <= 32768,
                        "invalid source state")
        bakeoff.require(isinstance(row.get("options"), list) and 2 <= len(row["options"]) <= 32,
                        "invalid options")
        ids.add(row["id"])
    return rows


def load_encoder(root: Path, *, reviewed_remote_code: bool):
    from sentence_transformers import SentenceTransformer
    return SentenceTransformer(str(root), trust_remote_code=reviewed_remote_code)


def vector(model, value):
    import numpy as np
    v = np.asarray(model.encode([value], convert_to_numpy=True)[0], dtype=np.float64)
    bakeoff.require(v.ndim == 1 and 1 <= v.size <= 2048 and np.isfinite(v).all(), "bad embedding")
    norm = np.linalg.norm(v)
    bakeoff.require(norm > 1e-12, "empty embedding")
    return v / norm


def option_features(model, state: str, options: list[str]):
    import numpy as np
    source = vector(model, state)
    return np.stack([source * vector(model, option) for option in options])


def fit_encoder_head(entry: dict, root: Path, gold: Path, out: Path, reviewed_remote_code: bool):
    import numpy as np
    bakeoff.require(bakeoff.digest(gold) == entry.get("train_data_sha256"), "training corpus SHA mismatch")
    data = bakeoff.validate_data(bakeoff.jsonl(gold))
    train = [r for r in data.values() if r["split"] == "train"]
    bakeoff.require(train and all(isinstance(r.get("state"), str) for r in train), "train split has no states")
    bakeoff.require(entry.get("head_optimizer") == "sgd", "fixed-budget reference supports only SGD")
    steps, seed, lr = entry.get("head_steps"), entry.get("head_seed"), entry.get("head_lr")
    bakeoff.require(type(steps) is int and 1 <= steps <= 100000, "missing bounded training steps")
    bakeoff.require(type(seed) is int and type(lr) in (int, float) and 0 < lr <= 1, "invalid head hyperparameters")
    model = load_encoder(root, reviewed_remote_code=reviewed_remote_code)
    samples = [(option_features(model, r["state"], r["options"]), r["options"].index(r["label"]))
               for r in train]
    w = np.zeros(samples[0][0].shape[1], dtype=np.float64)
    bakeoff.require(all(x.shape[1] == w.size for x, _ in samples), "feature width drift")
    rng = random.Random(seed)
    for _ in range(steps):
        x, label = samples[rng.randrange(len(samples))]
        logits = x @ w
        probs = np.exp(logits - logits.max())
        probs /= probs.sum()
        probs[label] -= 1
        w -= lr * (x.T @ probs + 0.0001 * w)
    artifact = {"schema": "hepta.cell.bakeoff.head.v1", "model": entry["name"],
                "revision": entry["revision"], "weights_sha256": entry["weights_sha256"],
                "train_dataset_sha256": bakeoff.digest(gold), "steps": steps, "seed": seed,
                "learning_rate": lr, "optimizer": "sgd", "weights": w.tolist()}
    out.write_text(json.dumps(artifact, sort_keys=True, separators=(",", ":")) + "\n", encoding="utf-8")
    print(json.dumps({"head_file": str(out), "head_sha256": bakeoff.digest(out), "steps": steps}))


def run_predictions(entry: dict, root: Path, rows: list[dict], out: Path,
                    head: Path | None, reviewed_remote_code: bool):
    name = entry["name"]
    if entry["kind"] == "typed":
        bakeoff.require(name.startswith("laya-"), "typed backend not registered")
        import laya
        agent = laya.load(str(root), expected_sha256=entry["files_sha256"])
    else:
        bakeoff.require(head is not None and bakeoff.digest(head) == entry["head_sha256"],
                        "trained encoder head missing or hash mismatch")
        learned = json.loads(head.read_text(encoding="utf-8"))
        bakeoff.require(learned["revision"] == entry["revision"] and
                        learned["weights_sha256"] == entry["weights_sha256"] and
                        learned["model"] == name, "encoder head lineage mismatch")
        import numpy as np
        w = np.asarray(learned["weights"], dtype=np.float64)
        bakeoff.require(w.ndim == 1 and 1 <= len(w) <= 2048 and np.isfinite(w).all(), "invalid head")
        agent = load_encoder(root, reviewed_remote_code=reviewed_remote_code)
    with out.open("w", encoding="utf-8") as f:
        for row in rows:
            started = time.perf_counter_ns()
            if entry["kind"] == "typed":
                instructions = row.get("instructions") or "Select the best matching decision label."
                result = agent.system_one(row["state"], {"decision": {"type": "choice",
                                          "instructions": instructions,
                                          "criteria": {key: key for key in row["options"]}}},
                                          lang=row.get("language"))
                probs = result["answers"]["decision"]["probabilities"]
                bakeoff.require(set(probs) == set(row["options"]), "Laya returned different options")
                # The SDK rounds probabilities. Normalize only rounding-level deviation.
                scale = sum(probs.values())
                bakeoff.require(0.999 <= scale <= 1.001, "Laya probabilities not normalized")
                probs = {key: value / scale for key, value in probs.items()}
            else:
                import numpy as np
                x = option_features(agent, row["state"], row["options"])
                bakeoff.require(x.shape[1] == len(w), "encoder/head dimension drift")
                logits = x @ w
                v = np.exp(logits - logits.max())
                v /= v.sum()
                probs = dict(zip(row["options"], v.tolist()))
            elapsed = (time.perf_counter_ns() - started) / 1_000_000
            observation = {"model": name, "id": row["id"], "revision": entry["revision"],
                           "weights_sha256": entry["weights_sha256"], "probabilities": probs,
                           "abstain": False, "latency_ms": elapsed, "origin": "live-model-observation"}
            f.write(json.dumps(observation, sort_keys=True) + "\n")
    print(json.dumps({"observations": len(rows), "output": str(out), "sha256": bakeoff.digest(out)}))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("fit", "predict"))
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--model", choices=bakeoff.MODEL_NAMES, required=True)
    parser.add_argument("--checkpoint", type=Path, required=True)
    parser.add_argument("--gold", type=Path, help="training data, allowed only for fit")
    parser.add_argument("--blind", type=Path, help="no gold labels allowed")
    parser.add_argument("--head", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--allow-reviewed-remote-code", action="store_true")
    args = parser.parse_args()
    try:
        raw_plan = json.loads(args.plan.read_text(encoding="utf-8"))
        entry = next(m for m in raw_plan["models"] if m["name"] == args.model)
        if args.mode == "predict":
            bakeoff.load_plan(args.plan)
            bakeoff.require(args.gold is None and args.blind is not None, "predict requires blind-only data")
        else:
            bakeoff.require(args.blind is None and args.gold is not None and entry["kind"] == "encoder-head",
                            "fit only supports encoder-head train split")
        root = verified_local_model(args.checkpoint, entry)
        if args.mode == "fit":
            fit_encoder_head(entry, root, args.gold, args.output, args.allow_reviewed_remote_code)
        else:
            run_predictions(entry, root, blind_rows(args.blind), args.output, args.head,
                            args.allow_reviewed_remote_code)
    except (bakeoff.EvidenceError, OSError, KeyError, StopIteration, ValueError) as exc:
        parser.exit(2, f"CELL-BAKEOFF INFERENCE BLOCKED: {exc}\n")


if __name__ == "__main__":
    main()
