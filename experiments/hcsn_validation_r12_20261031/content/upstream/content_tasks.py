"""Raw sequence tasks; model inputs never include labels, beliefs or posteriors."""

import hashlib
import json
from functools import lru_cache
from pathlib import Path

import numpy as np

TASKS = {
    "associative_recall": {"input_dim": 9, "classes": 3},
    "multimodal_evidence": {"input_dim": 12, "classes": 2},
    "digits_rows": {"input_dim": 8, "classes": 10},
}


def array_hash(*arrays):
    digest = hashlib.sha256()
    for array in arrays:
        array = np.ascontiguousarray(array)
        digest.update(str((array.shape, array.dtype.str)).encode())
        digest.update(array.tobytes())
    return digest.hexdigest()


def multimodal_support(modality, q_a=0.70, q_b=0.75):
    """Return raw X[outcomes,12], P[outcome|y][2,outcomes] for oracle enumeration.

    A outcomes: sign -1,+1. B: (-1,-1),(-1,+1),(+1,-1),(+1,+1),
    where each pair is (noisy signal sign, independent nuisance sign).
    This function does not reveal the realized outcome of an unread observation.
    """
    if not (0.5 <= q_a < 1 and 0.5 <= q_b < 1):
        raise ValueError("evidence reliabilities must lie in [0.5,1)")
    if modality in ("A", 0):
        x = np.zeros((2, 12))
        x[0, 0], x[1, 1], x[:, 10] = 1, 1, 1
        prob = np.array([[q_a, 1 - q_a], [1 - q_a, q_a]])
    elif modality in ("B", 1):
        template = np.array([1, 1, -1, -1, 1, 1, -1, -1], dtype=float) * 0.7
        nuisance = np.array([1, -1, 1, -1, 1, -1, 1, -1], dtype=float) * 0.4
        x = np.zeros((4, 12))
        for i, (sign, noise) in enumerate(((-1, -1), (-1, 1), (1, -1), (1, 1))):
            x[i, 2:10] = sign * template + noise * nuisance
        x[:, 11] = 1
        prob = np.array([[q_b, q_b, 1 - q_b, 1 - q_b],
                         [1 - q_b, 1 - q_b, q_b, q_b]]) * 0.5
    else:
        raise ValueError("modality must be A/B or 0/1")
    return x, prob


@lru_cache(maxsize=1)
def digits_data():
    """Load installed sklearn data and fix disjoint stratified split identities."""
    from sklearn.datasets import load_digits
    data = load_digits()
    images = np.asarray(data.images, dtype=np.uint8)
    labels = np.asarray(data.target, dtype=np.int64)
    rng = np.random.default_rng(20261031)
    parts = {"train": [], "dev": [], "test": []}
    for label in range(10):
        indices = rng.permutation(np.flatnonzero(labels == label))
        n_train, n_dev = int(0.6 * len(indices)), int(0.2 * len(indices))
        parts["train"].extend(indices[:n_train])
        parts["dev"].extend(indices[n_train:n_train + n_dev])
        parts["test"].extend(indices[n_train + n_dev:])
    parts = {key: np.sort(value).astype(np.int64) for key, value in parts.items()}
    identity = array_hash(images, labels)
    return images, labels, parts, identity


def save_dataset_identity(directory):
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    images, labels, indices, digest = digits_data()
    np.savez_compressed(directory / "digits_split_indices.npz", **indices)
    info = {"dataset": "sklearn.datasets.load_digits", "raw_shape": list(images.shape),
            "dataset_sha256": digest, "split_seed": 20261031,
            "split_counts": {key: len(value) for key, value in indices.items()},
            "split_sha256": {key: array_hash(value) for key, value in indices.items()},
            "normalization": "fixed pixel / 16; no fitted feature transform",
            "split_rule": "per class floor(.6*n),floor(.2*n),remainder; sorted IDs",
            "test_usage": "dataset identity only before checkpoint freeze; no test loss or accuracy"}
    (directory / "digits_dataset_identity.json").write_text(json.dumps(info, indent=2) + "\n")
    return info


def sample_batch(task, rng, batch, variant="iid", split="train", indices=None):
    if task not in TASKS or variant not in ("iid", "long_delay", "clock_shift"):
        raise ValueError("unknown task or variant")
    if task == "associative_recall":
        delay = 12 if variant == "long_delay" else 4
        token = np.empty((8 + delay, batch), dtype=np.int64)
        y = np.empty(batch, dtype=np.int64)
        for b in range(batch):
            keys = rng.permutation(3)
            values = rng.integers(0, 3, 3)
            token[:6:2, b], token[1:6:2, b] = keys, values + 3
            token[6:6 + delay, b] = rng.integers(7, 9, delay)
            query = rng.integers(0, 3)
            token[-2, b], token[-1, b] = 6, query
            y[b] = values[np.flatnonzero(keys == query)[0]]
        x = np.eye(9)[token]
        ids = np.empty(0, dtype=np.int64)
    elif task == "multimodal_evidence":
        steps = 16 if variant == "long_delay" else 8
        y = rng.integers(0, 2, batch)
        x = np.empty((steps, batch, 12))
        for t in range(steps):
            for b in range(batch):
                modality = int(rng.integers(0, 2))
                support, prob = multimodal_support(modality)
                outcome = rng.choice(len(support), p=prob[y[b]])
                x[t, b] = support[outcome]
        ids = np.empty(0, dtype=np.int64)
    else:
        images, labels, partition, _ = digits_data()
        ids = rng.choice(partition[split], size=batch) if indices is None else np.asarray(indices)
        if not np.all(np.isin(ids, partition[split])):
            raise ValueError("digit indices do not belong to requested split")
        y = labels[ids].copy()
        x = images[ids].astype(np.float64).transpose(1, 0, 2) / 16.0
        if variant == "long_delay":
            x = np.concatenate((x, np.zeros_like(x)), axis=0)
    dt = np.ones(x.shape[:2])
    if variant == "clock_shift":
        dt[::2] = 0.5
        dt[1::2] = 1.5
    return {"x": x, "y": y, "dt": dt, "ids": ids}


def task_protocol():
    return {
        "tasks": TASKS, "recall_keys_values": [3, 3], "recall_train_delay": 4,
        "recall_long_delay": 12, "multimodal_train_steps": 8, "multimodal_long_steps": 16,
        "multimodal_reliabilities": {"A": 0.70, "B": 0.75},
        "multimodal_support_order": {"A": [-1, 1], "B": [[-1, -1], [-1, 1], [1, -1], [1, 1]]},
        "digits_split_seed": 20261031, "digits_long_delay": "8 zero rows after 8 image rows",
        "clock_shift": "alternating dt=.5,1.5; raw observations unchanged",
        "semantics": "raw one-hot tokens, raw finite-noise wave, or raw 8x8 digit rows; no posterior input",
    }
