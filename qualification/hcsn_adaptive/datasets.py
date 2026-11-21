"""Independent synthetic splits and a small explicit external-data contract."""

import hashlib
import json
from pathlib import Path

import numpy as np


def file_digest(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def make_synthetic(directory, *, task="future_return", seed=20261121,
                   train=64, dev=32, test=32, length=12):
    """Future labels are generated after the visible window, independently per split."""
    if task not in ("future_return", "delayed_recall") or min(train, dev, test, length) < 2:
        raise ValueError("unsupported task or too-small dataset")
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    if any((directory / (split + ".npz")).exists() for split in ("train", "dev", "test")):
        raise FileExistsError("synthetic split files are immutable; choose a new directory")
    metadata = {"schema": "hepta.adaptive.dataset.v1", "task": task, "seed": seed,
                "reward_definition": "-(observed_state-0.5)^2; reset utility=-0.25",
                "target_scope": "forecast future utility; reset-control critic is an auxiliary surrogate",
                "split_seeds": {}, "length": length}
    for split, count, offset in (("train", train, 0), ("dev", dev, 1_000_003), ("test", test, 2_000_033)):
        split_seed = seed + offset
        rng = np.random.default_rng(split_seed)
        x = np.empty((count, length, 2), dtype=np.float64)
        if task == "future_return":
            z = rng.uniform(-1.2, 1.2, count)
            context = rng.choice([-1.0, 1.0], count)
            future_rewards = []
            for step in range(length + 6):
                if step < length:
                    x[:, step, 0], x[:, step, 1] = z, context
                else:
                    future_rewards.append(-(z - 0.5) ** 2)
                flips = rng.uniform(size=count) < 0.1
                context = np.where(flips, -context, context)
                z = np.clip(0.85 * z + 0.12 * context + rng.normal(0, 0.2, count), -1.5, 1.5)
            y = np.stack(future_rewards, 1).mean(1, keepdims=True)
        else:
            x[:, :, 0] = rng.normal(0, 0.35, (count, length))
            x[:, :, 1] = 0
            x[:, 0, 1] = rng.uniform(-1, 1, count)
            y = x[:, 0, 1:2].copy()
            metadata["target_scope"] = "initial observed cue; quadratic utility critic is an auxiliary surrogate"
        path = directory / (split + ".npz")
        np.savez(path, x=x, y=y, dt=np.full((count, length), 0.1),
                 ids=np.asarray([f"{task}:{split_seed}:{i}" for i in range(count)]),
                 running_rewards=-(x[:, :, 0] - 0.5) ** 2)
        metadata["split_seeds"][split] = split_seed
    (directory / "dataset.json").write_text(json.dumps(metadata, indent=2) + "\n")
    return metadata


def inspect_splits(directory):
    """Inspect IDs and byte hashes only; final holdout labels remain unopened."""
    result, seen = {}, set()
    for split in ("train", "dev", "test"):
        path = Path(directory) / (split + ".npz")
        with np.load(path, allow_pickle=False) as data:
            if not {"x", "y", "ids"}.issubset(data.files):
                raise ValueError("each split requires x, y and stable independent ids")
            ids = data["ids"].astype(str).tolist()
        if len(set(ids)) != len(ids) or set(ids) & seen:
            raise ValueError("split identifiers overlap or repeat")
        seen.update(ids)
        result[split] = {"sha256": file_digest(path), "samples": len(ids),
                         "id_digest": hashlib.sha256(json.dumps(ids).encode()).hexdigest()}
    metadata = Path(directory) / "dataset.json"
    result["metadata_sha256"] = file_digest(metadata) if metadata.exists() else None
    adapter_manifest = Path(directory) / "manifest.json"
    result["adapter_manifest_sha256"] = file_digest(adapter_manifest) if adapter_manifest.exists() else None
    return result


def load_split(directory, split, expected):
    path = Path(directory) / (split + ".npz")
    if file_digest(path) != expected[split]["sha256"]:
        raise ValueError("immutable dataset bytes changed")
    with np.load(path, allow_pickle=False) as archive:
        data = {key: archive[key] for key in archive.files}
    if (data["x"].ndim != 3 or data["y"].ndim != 2
            or len(data["x"]) != len(data["y"]) or len(data["x"]) != len(data["ids"])
            or not np.isfinite(data["x"]).all() or not np.isfinite(data["y"]).all()):
        raise ValueError("invalid observation/target shapes or nonfinite values")
    return data
