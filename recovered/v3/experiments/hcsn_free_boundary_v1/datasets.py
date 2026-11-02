"""Frozen, source-disjoint content tasks for regenerative-cell comparisons."""

import argparse
import hashlib
import json
from pathlib import Path

import numpy as np

from experiments.continuous_spiking_network.data import (
    FSDD_COMMIT, SPEAKER_SPLITS, _mnist, _real_split, audio_features, prepare_audio_features,
)


TASKS = ("selective_copy", "mqar", "irregular", "mnist", "fsdd", "multimodal_select")
SIZES = {"train": 1024, "val": 256, "test": 512, "ood": 512}
DATA_SEED = 912201


def file_hash(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def synthetic(task, size, split, length=32, seed=DATA_SEED):
    """Labels appear only on query steps; all answers depend on earlier input."""
    split_id = ("train", "val", "test", "ood").index(split)
    rng = np.random.default_rng(np.random.SeedSequence([seed, split_id, TASKS.index(task)]))
    x = np.zeros((size, length, 64), dtype=np.float32)
    dt = rng.uniform(0.5, 1.5, (size, length)).astype(np.float32)
    y = np.full((size, length), -100, dtype=np.int64)
    for row in range(size):
        if task == "selective_copy":
            values = rng.integers(0, 8, length - 4)
            x[row, np.arange(length - 4), values] = 1
            selected = np.sort(rng.choice(length - 8, 4, replace=False))
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
            # Distractors carry independent symbols in a separate input channel.
            x[row, :length - 4, 18:26] = np.eye(8)[rng.integers(0, 8, length - 4)]
            query_order = rng.permutation(4)
            x[row, np.arange(length - 4, length), keys[query_order]] = 1
            x[row, -4:, 17] = 1
            y[row, -4:] = values[query_order]
        elif task == "irregular":
            dt[row] = rng.uniform(0.2, 1.2, length) * (3.0 if split == "ood" else 1.0)
            values = rng.normal(size=length - 1)
            x[row, :-1, 0] = values
            x[row, :-1, 1] = 1
            x[row, -1, 2] = 1
            memory = 0.0
            for step, value in enumerate(values):
                keep = np.exp(-0.2 * float(dt[row, step]))
                memory = keep * memory + (1 - keep) * value
            y[row, -1] = int(memory > 0)
        else:
            raise ValueError(f"Unknown synthetic task {task}")
    ids = [f"{task}:{seed}:{split}:{i}" for i in range(size)]
    return x, dt, y, {"episode_ids": ids, "source_kind": "synthetic",
                      "supervised_tokens": int((y >= 0).sum()),
                      "label_contract": {"selective_copy": "four selected tokens in chronological order",
                                         "mqar": "four queried early key-value bindings",
                                         "irregular": "sign of exact leaky integral with rate 0.2"}[task]}


def validated_audio(cache):
    """Bind each consumed feature row to its recording, label and speaker."""
    cache = Path(cache)
    path = cache / "fsdd_features_v1.npz"
    if not path.exists():
        prepare_audio_features(cache)
    with np.load(path, allow_pickle=False) as archive:
        audio = {key: archive[key] for key in archive.files}
    paths = sorted((cache / "fsdd" / "recordings").glob("*.wav"))
    if len(audio["ids"]) != len(paths) or len(set(audio["ids"].tolist())) != len(paths):
        raise ValueError("Feature cache rows must match unique source recordings")
    lookup = {str(identifier): row for row, identifier in enumerate(audio["ids"])}
    for recording in paths:
        identifier = f"fsdd:{FSDD_COMMIT}:{recording.name}"
        if identifier not in lookup:
            raise ValueError(f"Missing feature row: {identifier}")
        row = lookup[identifier]
        label, speaker, _ = recording.stem.split("_")
        features, duration = audio_features(recording)
        if (int(audio["y"][row]) != int(label) or str(audio["speakers"][row]) != speaker
                or float(audio["duration"][row]) != duration
                or not np.array_equal(audio["x"][row], features)):
            raise ValueError(f"Feature cache does not reproduce recording: {identifier}")
    receipt = {"path": path.name, "sha256": file_hash(path), "rows": len(paths),
               "verification": "all rows recomputed from WAV; exact features/duration and filename label/speaker",
               "feature_function": "experiments.continuous_spiking_network.data.audio_features",
               "feature_source_sha256": file_hash(Path(__file__).parents[1] / "continuous_spiking_network" / "data.py")}
    return audio, receipt


def real_bundle(task, cache, sizes, verified_audio=None):
    images = _mnist(cache)
    audio = None
    if task != "mnist":
        audio = validated_audio(cache)[0] if verified_audio is None else verified_audio
    output, metadata = {}, {}
    for split in ("train", "val", "test"):
        data = _real_split(task, sizes[split], split, DATA_SEED, 32, images, audio)
        target = np.full(data.dt.shape, -100, dtype=np.int64)
        target[:, -1] = data.y
        output[split] = (data.x, data.dt, target)
        metadata[split] = {**data.metadata, "episode_ids": data.sample_ids.tolist()}
    # Transform fitted only on training observations, separately by modality.
    train = output["train"][0]
    transforms = []
    for start, stop, presence in ((0, 28, 48), (28, 48, 49)):
        selected = train[..., presence] > 0
        values = train[..., start:stop][selected]
        if len(values):
            mean = values.mean(0, dtype=np.float64).astype(np.float32)
            std = values.std(0, dtype=np.float64).clip(1e-4).astype(np.float32)
        else:
            mean, std = np.zeros(stop - start, np.float32), np.ones(stop - start, np.float32)
        transforms.append({"columns": [start, stop], "presence_column": presence,
                           "mean": mean.tolist(), "std": std.tolist(), "fit_split": "train"})
        for x, _, _ in output.values():
            present = x[..., presence:presence + 1] > 0
            x[..., start:stop] = np.where(present, (x[..., start:stop] - mean) / std, 0)
    for field in ("image_source_ids", "audio_source_ids"):
        sets = [set(metadata[split][field]) - {""} for split in ("train", "val", "test")]
        if any(sets[i] & sets[j] for i in range(3) for j in range(i + 1, 3)):
            raise ValueError(f"Source split leakage in {field}")
    return output, metadata, transforms


def prepare(output, cache, sizes=None):
    output, cache = Path(output), Path(cache)
    sizes = SIZES if sizes is None else sizes
    output.mkdir(parents=True, exist_ok=True)
    audio, audio_receipt = validated_audio(cache)
    source_files = sorted((cache / "mnist").glob("*.gz"))
    source_files += sorted((cache / "fsdd" / "recordings").glob("*.wav"))
    sources = [{"path": str(p.relative_to(cache)), "bytes": p.stat().st_size,
                "sha256": file_hash(p)} for p in source_files]
    source_identity = hashlib.sha256(json.dumps(sources, sort_keys=True).encode()).hexdigest()
    inventory = {}
    for task in TASKS:
        path = output / f"{task}.npz"
        if path.exists():
            raise FileExistsError(f"Refuse to replace frozen data: {path}")
        if task in TASKS[:3]:
            arrays, metadata = {}, {}
            for split, count in sizes.items():
                x, dt, y, meta = synthetic(task, count, split, 64 if split == "ood" else 32)
                arrays[split] = (x, dt, y)
                metadata[split] = meta
            transforms = []
            classes = 2 if task == "irregular" else 8
        else:
            arrays, metadata, transforms = real_bundle(task, cache, sizes, audio)
            classes = 10
        flat = {f"{split}_{field}": value for split, values in arrays.items()
                for field, value in zip(("x", "dt", "y"), values, strict=True)}
        for value in flat.values():
            if not np.isfinite(value).all():
                raise ValueError("Nonfinite task data")
        np.savez_compressed(path, **flat)
        manifest = {"schema": "hcsn-free-boundary-data.v1", "task": task,
                    "input_dim": 64, "output_dim": classes, "seed": DATA_SEED,
                    "sha256": file_hash(path), "source_manifest_sha256": source_identity,
                    "audio_feature_cache": audio_receipt if task in ("fsdd", "multimodal_select") else None,
                    "splits": metadata, "transforms": transforms,
                    "limitations": ["FSDD is a speaker-disjoint 600-recording subset, not official benchmark split",
                                    "Audio repeated across episodes; unique recording counts are reported",
                                    "Audio features use complete utterances; no raw causal microphone claim",
                                    "Four fixed query tokens do not test natural-language understanding"]
                    if task in TASKS[3:] else ["Synthetic task; no natural-data or foundation-model claim"]}
        path.with_suffix(".json").write_text(json.dumps(manifest, indent=2) + "\n")
        inventory[task] = {"path": path.name, "sha256": manifest["sha256"],
                           "sizes": {split: len(values[0]) for split, values in arrays.items()},
                           "output_dim": classes}
    source_manifest = {"schema": "hcsn-data-sources.v1", "files": sources,
                       "sha256": source_identity, "fsdd_commit": FSDD_COMMIT,
                       "audio_feature_cache": audio_receipt,
                       "fsdd_indices": list(range(10)), "speaker_splits": SPEAKER_SPLITS,
                       "fsdd_license": "CC-BY-SA-4.0",
                       "fsdd_attribution": "Jakobovski/free-spoken-digit-dataset and its contributors",
                       "fsdd_url": f"https://github.com/Jakobovski/free-spoken-digit-dataset/tree/{FSDD_COMMIT}",
                       "mnist_url": "https://yann.lecun.com/exdb/mnist/",
                       "mnist_origin": "Unmodified original MNIST IDX files recovered from prior user experiment; byte hashes retained"}
    # Source URLs are informational; raw bytes and hashes define this run.
    (output / "SOURCES.json").write_text(json.dumps(source_manifest, indent=2) + "\n")
    (output / "INDEX.json").write_text(json.dumps(inventory, indent=2) + "\n")
    return inventory


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--cache", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(prepare(args.output, args.cache), indent=2))


if __name__ == "__main__":
    main()
