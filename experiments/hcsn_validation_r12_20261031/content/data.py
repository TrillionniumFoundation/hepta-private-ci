"""Two causal raw-input tasks and paired, prespecified stress transformations."""

import hashlib
import numpy as np

from .upstream.content_tasks import sample_batch, multimodal_support


TASKS = {"recall": (9, 3), "binding": (17, 2)}
DOMAINS = {
    "recall": ("iid", "long_distractors", "blank_retention", "irregular_dt", "clock4x", "query_swap", "missing_payload"),
    "binding": ("iid", "long_distractors", "blank_retention", "irregular_dt", "clock4x", "query_swap", "missing_a", "missing_b"),
}
SPLITS = {"train": (512, 81101), "val": (128, 81102), "test": (256, 81103)}


def digest(*arrays):
    result = hashlib.sha256()
    for value in arrays:
        value = np.ascontiguousarray(value)
        result.update(str((value.shape, value.dtype.str)).encode())
        result.update(value.tobytes())
    return result.hexdigest()


def dataset(task, split, domain="iid"):
    if task not in TASKS or split not in SPLITS or domain not in DOMAINS[task]:
        raise ValueError("Unknown task/split/domain")
    count, seed = SPLITS[split]
    rng = np.random.default_rng(seed + 100 * (task == "binding"))
    if task == "recall":
        original = sample_batch("associative_recall", rng, count)
        x, y = original["x"].transpose(1, 0, 2).copy(), original["y"].copy()
        groups = np.arange(count)
        query = x[:, -1].argmax(-1)
        keys = x[:, :6:2].argmax(-1)
        values = x[:, 1:6:2].argmax(-1) - 3
        if domain == "query_swap":
            query = (query + 1) % 3
            x[:, -1] = np.eye(9)[query]
            y = values[np.arange(count), (keys == query[:, None]).argmax(-1)]
        if domain == "missing_payload":
            x[:, 1:6:2] = 0
        if domain == "long_distractors":
            noise = np.eye(9)[rng.integers(7, 9, size=(count, 12))]
            x = np.concatenate((x[:, :-2], noise, x[:, -2:]), axis=1)
    else:
        # Four combinations per context make either modality alone exactly
        # label-balanced, including timing, order, nuisance, keys and query.
        x = np.zeros((count, 9, 17))
        y = np.zeros(count, dtype=np.int64)
        groups = np.repeat(np.arange(count // 4), 4)
        for group in range(count // 4):
            query = int(rng.integers(2))
            other = rng.integers(0, 2, size=2)
            nuisance = rng.integers(0, 2, size=2)
            order = rng.permutation(4)
            for combo, (a, b) in enumerate(((0, 0), (0, 1), (1, 0), (1, 1))):
                row = group * 4 + combo
                signs_a = np.empty(2, dtype=int)
                signs_b = np.empty(2, dtype=int)
                signs_a[query], signs_b[query] = a, b
                signs_a[1-query], signs_b[1-query] = other
                for position, event in enumerate(order):
                    modality, key = divmod(int(event), 2)
                    support, _ = multimodal_support(modality)
                    index = signs_a[key] if modality == 0 else 2 * signs_b[key] + nuisance[key]
                    x[row, position, :12] = support[index]
                    x[row, position, 12 + key] = 1
                    x[row, position, 14] = 1
                x[row, 4:8, 16] = 1  # explicit empty slots, no payload
                selected = 1-query if domain == "query_swap" else query
                x[row, -1, 12+selected] = 1
                x[row, -1, 15] = 1
                y[row] = int(signs_a[selected] == signs_b[selected])
        if domain in ("missing_a", "missing_b"):
            missing = x[..., 10 if domain == "missing_a" else 11] > 0
            x[missing] = 0
        if domain == "long_distractors":
            noise = np.zeros((count, 12, 17))
            noise[..., 16] = 1
            x = np.concatenate((x[:, :-1], noise, x[:, -1:]), axis=1)
    if domain == "blank_retention":
        x = np.concatenate((x, np.zeros((count, 8, x.shape[-1]))), axis=1)
    dt = np.ones(x.shape[:2])
    if domain == "irregular_dt":
        dt[:, ::2], dt[:, 1::2] = .25, 1.75
    if domain == "clock4x":
        dt *= 4
    x, dt = x.astype(np.float32), dt.astype(np.float32)
    y, groups = y.astype(np.int64), groups.astype(np.int64)
    return dict(x=x, dt=dt, y=y, group=groups, ids=np.arange(count),
                sha256=digest(x, dt, y, groups), task=task, split=split, domain=domain)


def twin_balance(values):
    """Check the class counts attached to identical complete observations."""
    buckets = {}
    for x, dt, target in zip(values["x"], values["dt"], values["y"]):
        buckets.setdefault(digest(x, dt), []).append(int(target))
    return all(sum(labels) * 2 == len(labels) for labels in buckets.values())
