#!/usr/bin/env python3
"""Opt-in real local-weight inference. Never downloads, deploys or authorizes."""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import platform
import random
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

from bakeoff import (
    CANDIDATES, MODEL_REPOS, REVISION, SCHEMA, file_hash, load_jsonl,
    require, validate_dataset,
)

HEAD_DIM = 256
HEAD_SEED = 1729
HEAD_EPOCHS = 6
HEAD_LR = 0.025
HEAD_L2 = 0.005


def inventory_digest(paths: list[Path], root: Path) -> str:
    require(bool(paths), "model artifact files absent")
    h = hashlib.sha256()
    for path in sorted(paths):
        # Hugging Face cache symlinks may point to sibling blobs/, never outside
        # this exact repository cache.
        require(path.is_file() and path.resolve(strict=True).is_relative_to(root.parent.parent),
                f"symlink/absent/escaped model file: {path}")
        name = str(path.relative_to(root)).encode()
        h.update(len(name).to_bytes(4, "big"))
        h.update(name)
        h.update(bytes.fromhex(file_hash(path)))
    return h.hexdigest()


def model_inventory(root: Path) -> dict[str, str]:
    weights = list(root.rglob("*.safetensors"))
    tokenizers = [
        p for p in root.rglob("*")
        if p.is_file() and (
            p.name.startswith("tokenizer") or p.name in (
                "vocab.txt", "vocab.json", "merges.txt", "sentencepiece.bpe.model",
            )
        )
    ]
    return {
        "weights": inventory_digest(weights, root),
        "tokenizer": inventory_digest(tokenizers, root),
    }


def normalize(values: dict[str, float]) -> dict[str, float]:
    require(values and all(math.isfinite(v) and v >= 0 for v in values.values()), "invalid probability")
    total = sum(values.values())
    require(total > 0, "empty probability mass")
    return {k: float(v / total) for k, v in values.items()}


def calibrate(probs: dict[str, float], temperature: float) -> dict[str, float]:
    return normalize({k: math.exp(math.log(max(v, 1e-8)) / temperature) for k, v in probs.items()})


def choose_temperature(records: list[tuple[dict[str, float], str]]) -> float:
    require(bool(records), "calibration partition is empty")
    best = (float("inf"), 1.0)
    for temp in (0.5, 0.625, 0.8, 1.0, 1.25, 1.6, 2.0, 2.5, 3.2, 4.0):
        loss = sum(-math.log(max(calibrate(p, temp)[label], 1e-12)) for p, label in records) / len(records)
        if loss < best[0]:
            best = (loss, temp)
    return best[1]


def precision_manifest(model: Any) -> str:
    import torch

    descriptors = sorted(
        [name, list(parameter.shape), str(parameter.dtype), str(parameter.device)]
        for name, parameter in model.named_parameters()
    )
    require(bool(descriptors), "loaded model has no trainable/registered parameters")
    return hashlib.sha256(json.dumps(descriptors, sort_keys=True).encode()).hexdigest()


def device_kind(device: Any) -> str:
    return str(device).split(":", 1)[0]


def laya_scores(
    snapshot: Path, rows: list[dict[str, Any]], expected_device: str,
) -> tuple[dict[str, dict[str, float]], dict[str, Any]]:
    import laya

    started = time.perf_counter()
    agent = laya.load(str(snapshot), device=expected_device)
    load_ms = (time.perf_counter() - started) * 1000
    require(device_kind(agent.device) == expected_device, "Laya silent load-device fallback")
    precision_sha = precision_manifest(agent.model)
    output: dict[str, dict[str, float]] = {}
    for row in rows:
        options = row["options"]
        question = {
            "decision": {
                "type": "choice", "instructions": row["question"],
                "criteria": {key: key for key in options},
            },
        }
        answer = agent.predict(row["state"], question)["answers"]["decision"]
        require(device_kind(agent.device) == expected_device, "Laya silent inference CPU fallback")
        probs = answer.get("probabilities")
        require(isinstance(probs, dict) and set(probs) == set(options),
                "Laya decision did not emit a complete distribution")
        output[row["id"]] = normalize({x: float(probs[x]) for x in options})
    return output, {
        "backend": "laya-sdk", "load_ms": load_ms,
        "selected_device": expected_device,
        "parameter_precision_sha256": precision_sha,
    }


def embedding_scores(
    snapshot: Path, rows: list[dict[str, Any]], expected_device: str,
) -> tuple[dict[str, dict[str, float]], dict[str, Any], str]:
    import numpy as np
    from sentence_transformers import SentenceTransformer

    started = time.perf_counter()
    model = SentenceTransformer(
        str(snapshot), trust_remote_code=False, local_files_only=True, device=expected_device,
    )
    load_ms = (time.perf_counter() - started) * 1000
    require(device_kind(model.device) == expected_device, "Encoder device fallback")
    precision_sha = precision_manifest(model)
    texts: list[str] = []
    positions: dict[str, tuple[int, int]] = {}
    for row in rows:
        start = len(texts)
        for option in row["options"]:
            texts.append(f"State: {row['state']}\nQuestion: {row['question']}\nOption: {option}")
        positions[row["id"]] = (start, len(texts))
    started = time.perf_counter()
    embeddings = model.encode(
        texts, batch_size=16, normalize_embeddings=True,
        convert_to_numpy=True, show_progress_bar=False,
    )
    encode_ms = (time.perf_counter() - started) * 1000
    require(device_kind(model.device) == expected_device, "Encoder device changed")
    require(embeddings.ndim == 2 and embeddings.shape[1] >= HEAD_DIM and np.isfinite(embeddings).all(),
            "invalid real embeddings")
    rng = np.random.default_rng(HEAD_SEED)
    projection = rng.normal(
        0, 1 / math.sqrt(HEAD_DIM), size=(embeddings.shape[1], HEAD_DIM),
    ).astype(np.float32)
    features = np.asarray(embeddings, dtype=np.float32) @ projection
    features /= np.maximum(np.linalg.norm(features, axis=1, keepdims=True), 1e-8)
    weights = np.zeros(HEAD_DIM, dtype=np.float32)
    training = [r for r in rows if r["split"] == "train"]
    require(bool(training), "training partition missing")
    rng_train = random.Random(HEAD_SEED)
    updates = 0
    for _epoch in range(HEAD_EPOCHS):
        indexes = list(range(len(training)))
        rng_train.shuffle(indexes)
        for index in indexes:
            row = training[index]
            lo, hi = positions[row["id"]]
            matrix = features[lo:hi]
            logits = matrix @ weights
            exp = np.exp(logits - float(logits.max()))
            p = exp / exp.sum()
            p[row["options"].index(row["gold"])] -= 1.0
            weights -= HEAD_LR * (matrix.T @ p + HEAD_L2 * weights)
            updates += 1
    head_digest = hashlib.sha256(weights.tobytes()).hexdigest()
    output = {}
    for row in rows:
        lo, hi = positions[row["id"]]
        logits = features[lo:hi] @ weights
        exp = np.exp(logits - float(logits.max()))
        output[row["id"]] = normalize(dict(zip(row["options"], map(float, exp / exp.sum()))))
    return output, {
        "backend": "sentence-transformers", "load_ms": load_ms,
        "embedding_forward_ms": encode_ms,
        "selected_device": expected_device, "parameter_precision_sha256": precision_sha,
        "head_trainable_parameters": HEAD_DIM,
        "head_epochs": HEAD_EPOCHS,
        "head_training_steps": updates,
        "head_learning_rate": HEAD_LR, "head_l2": HEAD_L2,
        "head_seed": HEAD_SEED, "projection": "seeded_gaussian_256",
        "projection_sha256": hashlib.sha256(projection.tobytes()).hexdigest(),
    }, head_digest


def runtime_identity() -> str:
    import importlib.metadata

    packages = {}
    for name in ("torch", "transformers", "laya", "sentence-transformers", "numpy"):
        try:
            packages[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            continue
    packages["python"] = platform.python_version()
    packages["runner_sha256"] = file_hash(Path(__file__))
    return hashlib.sha256(json.dumps(packages, sort_keys=True).encode()).hexdigest()


def device_identity() -> str:
    import torch

    gpu = []
    if torch.cuda.is_available():
        gpu = [torch.cuda.get_device_properties(i).name for i in range(torch.cuda.device_count())]
    detail = {
        "platform": platform.platform(), "host": platform.node(),
        "gpu": gpu, "torch_cuda": torch.version.cuda,
    }
    return hashlib.sha256(json.dumps(detail, sort_keys=True).encode()).hexdigest()


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--model", choices=CANDIDATES, required=True)
    p.add_argument("--snapshot", type=Path, required=True)
    p.add_argument("--revision", required=True)
    p.add_argument("--source-commit", required=True)
    p.add_argument("--dataset", type=Path, required=True)
    p.add_argument("--abstention-threshold", type=float, required=True)
    p.add_argument("--device", choices=("cpu", "cuda", "mps"), required=True)
    p.add_argument("--output-root", type=Path, required=True)
    a = p.parse_args()
    try:
        require(os.environ.get("HF_HUB_OFFLINE") == "1", "HF_HUB_OFFLINE=1 required")
        require(os.environ.get("USE_TF") == "0", "USE_TF=0 required")
        require(REVISION.fullmatch(a.revision) is not None and
                REVISION.fullmatch(a.source_commit) is not None, "exact Git SHAs required")
        commit = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
        require(commit == a.source_commit, "source commit drift")
        root = a.snapshot.resolve(strict=True)
        require(root.is_dir() and root.parent.name == "snapshots" and root.name == a.revision,
                "snapshot must be local Hugging Face cache snapshots/<exact SHA>")
        require(0 < a.abstention_threshold < 1, "invalid preregistered abstention threshold")
        import torch

        require(
            (a.device == "cpu")
            or (a.device == "cuda" and torch.cuda.is_available())
            or (
                a.device == "mps"
                and hasattr(torch.backends, "mps")
                and torch.backends.mps.is_available()
            ),
            "requested accelerator unavailable; no automatic fallback",
        )
        inventory = model_inventory(root)
        data = load_jsonl(a.dataset)
        validate_dataset(data)
        require(all(isinstance(r.get("state"), str) and isinstance(r.get("question"), str)
                    for r in data), "text state/question required")
        if a.model.startswith("laya-"):
            scores, profile = laya_scores(
                root, [r for r in data if r["split"] in ("calibration", "future_test")],
                a.device,
            )
            head_digest = inventory["weights"]
        else:
            scores, profile, head_digest = embedding_scores(
                root, [r for r in data if r["split"] in ("train", "calibration", "future_test")],
                a.device,
            )
        calibration_rows = [r for r in data if r["split"] == "calibration" and not r["ood"]]
        temp = choose_temperature([(scores[r["id"]], r["gold"]) for r in calibration_rows])
        output_dir = a.output_root / a.model
        output_dir.mkdir(parents=True, exist_ok=False)
        out_file = output_dir / "predictions.jsonl"
        with out_file.open("w", encoding="utf-8") as writer:
            for row in data:
                if row["split"] != "future_test":
                    continue
                probs = calibrate(scores[row["id"]], temp)
                writer.write(json.dumps({
                    "id": row["id"], "model": a.model, "probabilities": probs,
                    "abstained": max(probs.values()) < a.abstention_threshold,
                }, sort_keys=True, ensure_ascii=False) + "\n")
        receipt = {
            "schema": SCHEMA, "model": a.model, "repository": MODEL_REPOS[a.model],
            "revision": a.revision, "source_commit": a.source_commit,
            "role": "model_runner", "execution": "real_weights",
            "dataset_sha256": file_hash(a.dataset),
            "predictions_sha256": file_hash(out_file),
            "digests": {
                **inventory, "head": head_digest,
                "quantization": profile["parameter_precision_sha256"],
                "preprocessor": hashlib.sha256(b"hepta.choice.v1\nstate+question+option").hexdigest(),
                "runtime": runtime_identity(), "device": device_identity(),
            },
            "calibration": {
                "temperature": temp, "method": "heldout_nll_temperature_grid",
                "abstention_threshold": a.abstention_threshold,
            },
            "profile": profile, "independent_signature_verified": False,
        }
        (output_dir / "run.json").write_text(
            json.dumps(receipt, sort_keys=True, indent=2) + "\n", encoding="utf-8",
        )
        print(f"Real local inference recorded at {output_dir}; no independent acceptance")
        return 0
    except (ValueError, OSError, KeyError, RuntimeError) as exc:
        print(f"BLOCKED: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
