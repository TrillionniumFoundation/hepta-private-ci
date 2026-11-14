#!/usr/bin/env python3
"""Reference-only weight-backed execution, not Hepta's native model consumer.

External dependencies (in the target model host): numpy, huggingface_hub,
Laya and torch for Laya checkpoints, or sentence-transformers for encoders.
"""
import argparse
import hashlib
import json
from pathlib import Path
import platform
import subprocess
import sys
import time

from evaluate import HEX40, EvidenceError, require, rows, sha256, validate_dataset, validate_plan


def verify_source_head(expected):
    root = Path(__file__).resolve().parents[2]
    try:
        actual = subprocess.check_output(["git", "-C", str(root), "rev-parse", "HEAD"], text=True).strip()
        dirty = subprocess.check_output(["git", "-C", str(root), "status", "--porcelain", "--untracked-files=no"], text=True).strip()
    except (OSError, subprocess.CalledProcessError) as exc:
        raise EvidenceError("running outside pinned Git checkout") from exc
    require(actual == expected and not dirty, "source SHA or tracked source bytes drifted")


def verify_snapshot(root, pinned_hashes):
    require(isinstance(pinned_hashes, dict) and pinned_hashes, "no pinned model file hashes")
    require(any("safetensors" in p for p in pinned_hashes), "model weights must be in pin inventory")
    require(any("tokenizer" in p for p in pinned_hashes), "tokenizer must be in pin inventory")
    for name, expected in pinned_hashes.items():
        path = (root / name).resolve()
        require(path.is_relative_to(root.resolve()) and path.is_file(), f"model artifact missing or escapes snapshot: {name}")
        require(sha256(path) == expected, f"model artifact digest mismatch: {name}")


def question(row):
    return {"type": "choice", "instructions": row["instructions"], "criteria": row["criteria"]}


def statement(row):
    return json.dumps({"state": row["state"], "question": question(row)}, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def run_laya(model_dir, dataset, device, hashes):
    import laya
    start = time.perf_counter()
    agent = laya.load(str(model_dir), device=device, expected_sha256=hashes)
    load_ms = round((time.perf_counter() - start) * 1000, 2)
    result_rows = []
    for sample in dataset:
        if sample["split"] == "train":
            continue
        started = time.perf_counter()
        result = agent.predict(sample["state"], {"decision": question(sample)})
        elapsed = (time.perf_counter() - started) * 1000
        require(isinstance(result.get("answers"), dict), "Laya result has no answers")
        ans = result["answers"]["decision"]
        probabilities = ans.get("probabilities")
        require(isinstance(probabilities, dict), "Laya response lacks probability distribution")
        result_rows.append({"model": None, "id": sample["id"], "status": "ok", "probabilities": probabilities, "elapsed_ms": round(elapsed, 4), "usage": result.get("usage", {})})
    return result_rows, {"load_ms": load_ms, "library": "laya", "observed_runtime": str(getattr(laya, "__version__", "unknown"))}


def run_embedding(model_dir, dataset, device, head_cfg, head_root):
    import numpy as np
    from sentence_transformers import SentenceTransformer
    start = time.perf_counter()
    encoder = SentenceTransformer(str(model_dir), device=device, trust_remote_code=False)
    load_ms = round((time.perf_counter() - start) * 1000, 2)
    # Encode every row as ONE frozen question-conditioned input. Same batches and
    # projector rank for both candidates; neither model's retrieval scores count
    # as decision accuracy. No labels from test/OOD/retention enter the head fit.
    ds_sorted = sorted(dataset, key=lambda r: r["id"])
    encoded = encoder.encode([statement(r) for r in ds_sorted], batch_size=head_cfg["batch_size"], convert_to_numpy=True, normalize_embeddings=True, show_progress_bar=False)
    encoded = np.asarray(encoded, dtype=np.float32)
    require(encoded.ndim == 2 and encoded.shape[0] == len(ds_sorted), "embedding dimension mismatch")
    require(np.isfinite(encoded).all(), "nonfinite embedding")
    d = head_cfg["dimension"]
    rng = np.random.default_rng(head_cfg["seed"])
    projector = rng.normal(size=(encoded.shape[1], d)).astype(np.float32) / np.sqrt(d)
    z = encoded @ projector
    z /= np.maximum(1e-9, np.linalg.norm(z, axis=1, keepdims=True))
    tasks = {}
    for i, row in enumerate(ds_sorted):
        entry = tasks.setdefault(row["task"], {"labels": list(row["criteria"]), "indices": []})
        require(entry["labels"] == list(row["criteria"]), f"task {row['task']} has a changing label ontology")
        entry["indices"].append(i)
    heads = {}
    for task, value in sorted(tasks.items()):
        labels = value["labels"]
        train_ids = [i for i in value["indices"] if ds_sorted[i]["split"] == "train"]
        require(train_ids, f"no training rows for task {task}")
        require(set(ds_sorted[i]["gold"] for i in train_ids) == set(labels), f"training misses labels for task {task}")
        X = z[train_ids]
        Y = np.asarray([labels.index(ds_sorted[i]["gold"]) for i in train_ids], dtype=np.int64)
        W = np.zeros((d, len(labels)), dtype=np.float32)
        b = np.zeros(len(labels), dtype=np.float32)
        local_rng = np.random.default_rng(head_cfg["seed"])
        for _ in range(head_cfg["epochs"]):
            for ix in np.array_split(local_rng.permutation(len(train_ids)), max(1, (len(train_ids) + head_cfg["batch_size"] - 1) // head_cfg["batch_size"])):
                scores = X[ix] @ W + b
                scores -= scores.max(axis=1, keepdims=True)
                probs = np.exp(scores)
                probs /= probs.sum(axis=1, keepdims=True)
                probs[np.arange(len(ix)), Y[ix]] -= 1
                gradient = probs / len(ix)
                W -= head_cfg["learning_rate"] * (X[ix].T @ gradient + head_cfg["weight_decay"] * W)
                b -= head_cfg["learning_rate"] * gradient.sum(axis=0)
        heads[task] = (W, b, labels)
    head_root.mkdir(parents=True, exist_ok=True)
    head_bytes = []
    result_rows = []
    for task, (W, b, labels) in sorted(heads.items()):
        head_bytes.append(task.encode() + W.tobytes() + b.tobytes() + json.dumps(labels).encode())
    digest = hashlib.sha256(b"\x00".join(head_bytes) + projector.tobytes()).hexdigest()
    # Generated weights are not adopted model artifacts. Only immutable next-snapshot
    # admission through the existing registry may make them selected weights.
    np.savez_compressed(head_root / f"{digest}.npz", projector=projector, **{f"W_{i}":heads[t][0] for i, t in enumerate(sorted(heads))}, **{f"b_{i}":heads[t][1] for i, t in enumerate(sorted(heads))})
    for i, sample in enumerate(ds_sorted):
        if sample["split"] == "train":
            continue
        W, b, labels = heads[sample["task"]]
        logits = z[i] @ W + b
        logits -= logits.max()
        p = np.exp(logits)
        p /= p.sum()
        result_rows.append({"model": None, "id": sample["id"], "status": "ok", "probabilities": dict(zip(labels, [float(v) for v in p]))})
    return result_rows, {"load_ms": load_ms, "embedding_dimension": int(encoded.shape[1]), "head_sha256": digest, "head_artifact": str(head_root / f"{digest}.npz"), "head_budget": head_cfg, "library": "sentence-transformers"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", required=True)
    parser.add_argument("--dataset", required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--device", default="cpu")
    parser.add_argument("--offline", action="store_true")
    parser.add_argument("--output-dir", required=True)
    args = parser.parse_args()
    plan = validate_plan(json.loads(Path(args.plan).read_text(encoding="utf-8")))
    verify_source_head(plan["source_sha"])
    validate_dataset(rows(args.dataset))
    require(sha256(args.dataset) == plan["dataset_sha256"], "dataset does not match frozen bytes")
    require(args.model in plan["models"], "unknown model")
    info = plan["models"][args.model]
    require(isinstance(info["revision"], str) and HEX40.fullmatch(info["revision"]), "checkpoint revision must be exact 40-char SHA")
    from huggingface_hub import snapshot_download
    # snapshot_download must return the requested immutable revision rather than
    # silently following a mutable branch. Local content is separately hashed.
    root = Path(snapshot_download(repo_id=info["repo"], revision=info["revision"], local_files_only=args.offline))
    verify_snapshot(root, info["file_sha256"])
    dataset = rows(args.dataset)
    out = Path(args.output_dir)
    out.mkdir(parents=True, exist_ok=True)
    if info["kind"] == "laya":
        results, metadata = run_laya(root, dataset, args.device, info["file_sha256"])
    else:
        results, metadata = run_embedding(root, dataset, args.device, plan["head_training"], out / "heads")
    for r in results:
        r["model"] = args.model
    destination = out / f"{args.model}.predictions.jsonl"
    with destination.open("w", encoding="utf-8") as stream:
        for item in results:
            stream.write(json.dumps(item, sort_keys=True, ensure_ascii=False) + "\n")
    manifest = {"schema": "hepta.neuron.reference-model-run.v1", "model": args.model, "repo": info["repo"], "revision": info["revision"], "file_sha256": info["file_sha256"], "execution_kind": "real", "consumer": "reference_python_not_native_hepta", "dataset_sha256": sha256(args.dataset), "source_sha": plan["source_sha"], "python": platform.python_version(), "device_requested": args.device, "observations": metadata, "head_budget": plan["head_training"] if info["kind"] == "embedding" else None}
    (out / f"{args.model}.run.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"model": args.model, "predictions": str(destination), "count": len(results), "manifest": str(out / f"{args.model}.run.json")}, sort_keys=True))


if __name__ == "__main__":
    try:
        main()
    except (EvidenceError, OSError, KeyError, ValueError) as exc:
        print(f"FAILED CLOSED: {exc}", file=sys.stderr)
        sys.exit(2)