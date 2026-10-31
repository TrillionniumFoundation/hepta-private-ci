"""Fresh deterministic data splits; preparation has no model predictions."""

import hashlib
import json
from pathlib import Path

import numpy as np


SPLITS = ("dev_train", "dev_val", "train", "val", "test", "ood")
TASKS = ("selective_copy", "mqar")


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def generate(task, split, count, length, seed):
    rng = np.random.default_rng(np.random.SeedSequence([seed, SPLITS.index(split), TASKS.index(task)]))
    x = np.zeros((count, length, 64), np.float32)
    dt = rng.uniform(0.5, 1.5, (count, length)).astype(np.float32)
    y = np.full((count, length), -100, np.int64)
    for row in range(count):
        if task == "selective_copy":
            values = rng.integers(0, 8, length - 4)
            selected = np.sort(rng.choice(length - 8, 4, replace=False))
            x[row, np.arange(length - 4), values] = 1
            x[row, selected, 8] = 1
            x[row, -4:, 9] = 1
            y[row, -4:] = values[selected]
        elif task == "mqar":
            keys = rng.choice(8, 4, replace=False)
            values = rng.integers(0, 8, 4)
            positions = np.sort(rng.choice(length // 2, 4, replace=False))
            x[row, positions, keys] = 1
            x[row, positions, 8 + values] = 1
            x[row, positions, 16] = 1
            x[row, :length - 4, 18:26] = np.eye(8)[rng.integers(0, 8, length - 4)]
            order = rng.permutation(4)
            x[row, np.arange(length - 4, length), keys[order]] = 1
            x[row, -4:, 17] = 1
            y[row, -4:] = values[order]
        else:
            raise ValueError(task)
    return dict(x=x, dt=dt, y=y)


def prepare(design, output):
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    manifest = {}
    for task in design["tasks"]:
        manifest[task] = {}
        episode_fingerprints = {}
        for split in SPLITS:
            length = design["ood_length"] if split == "ood" else design["length"]
            arrays = generate(task, split, design["data_sizes"][split], length, design["data_seed"])
            fingerprints = [hashlib.sha256(arrays["x"][i].tobytes() +
                arrays["dt"][i].tobytes()).hexdigest() for i in range(len(arrays["x"]))]
            for other, seen in episode_fingerprints.items():
                if seen.intersection(fingerprints):
                    raise RuntimeError("Duplicate episode across " + split + " and " + other)
            episode_fingerprints[split] = set(fingerprints)
            path = output / (task + "_" + split + ".npz")
            np.savez_compressed(path, **arrays)
            manifest[task][split] = dict(file=path.name, sha256=sha256(path),
                episodes=len(arrays["x"]), supervised_tokens=int((arrays["y"] >= 0).sum()),
                length=length, episode_fingerprints_sha256=hashlib.sha256(
                    json.dumps(fingerprints, separators=(",", ":")).encode()).hexdigest())
    (output / "MANIFEST.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    return manifest
