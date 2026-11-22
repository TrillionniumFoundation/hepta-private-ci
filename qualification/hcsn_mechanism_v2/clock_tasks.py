"""Nested partitions of identical held controls and physical event marks.

Labels use external hazard/filter/key-value laws, never HCSN outputs. Refinement
repeats already known held controls, adds no noise and preserves each real write
exactly once. These pairs test representation resolution, not the old protocol's
longer-horizon/new-trajectory distribution shift.
"""

import hashlib
import numpy as np


TASKS = ("held_hazard", "held_filter", "event_memory")
SPLITS = ("train", "dev", "final")


def generate_pair(namespace, seed, task, split, count, segments=8, refinement=4):
    if (
        task not in TASKS
        or split not in SPLITS
        or type(count) is not int
        or not 1 <= count <= 4096
        or type(segments) is not int
        or not 4 <= segments <= 32
        or type(refinement) is not int
        or not 2 <= refinement <= 8
        or segments * refinement > 256
        or not namespace
        or type(seed) is not int
        or seed < 0
    ):
        raise ValueError("bounded fresh paired-task identity required")
    identity = f"{namespace}/{seed}/{task}/{split}"
    rng = np.random.default_rng(
        int.from_bytes(hashlib.sha256(identity.encode()).digest()[:8], "little")
    )
    # Exact integer-microsecond subdivisions, with equal total physical time.
    micros = refinement * rng.integers(
        40_000 // refinement, 120_000 // refinement + 1, (count, segments)
    )
    dt = micros.astype(np.float64) / 1e6
    x = np.zeros((count, segments, 4), dtype=np.float64)
    write = np.ones((count, segments), dtype=np.float64)
    if task == "held_hazard":
        x[:, :, :2] = rng.uniform(-1, 1, (count, segments, 2))
        hazard = 0.15 + np.exp(0.6 * x[:, :, 0] - 0.3 * x[:, :, 1])
        y = -np.expm1(-(hazard * dt).sum(1))
    elif task == "held_filter":
        x[:, :, 0] = rng.uniform(-0.8, 0.8, (count, segments))
        x[:, :, 1] = rng.uniform(-0.4, 0.4, (count, segments))
        y = np.zeros(count)
        for t in range(segments):
            decay = np.exp(-0.8 * dt[:, t])
            y = decay * y + (1 - decay) * x[:, t, 0]
    else:
        values = rng.uniform(-0.8, 0.8, (count, 2))
        key, query = rng.choice([-1.0, 1.0], (2, count))
        x[:, :2, 0] = values
        x[:, 0, 1], x[:, 1, 1] = key * values[:, 0], -key * values[:, 1]
        x[:, :2, 2], x[:, -1, 3] = 1, query
        write[:, 2:] = 0  # query is known to the reader, not an extra memory write
        y = np.where(query == key, values[:, 0], values[:, 1])
    ids = np.array([f"{identity}/{i}" for i in range(count)])
    coarse = {"x": x, "dt": dt, "write_mask": write, "y": y[:, None], "ids": ids}
    fine_write = np.zeros((count, segments * refinement), dtype=np.float64)
    fine_write[:, ::refinement] = write
    refined = {
        "x": np.repeat(x, refinement, axis=1),
        "dt": np.repeat(micros / refinement / 1e6, refinement, axis=1),
        "write_mask": fine_write,
        "y": y[:, None].copy(),
        "ids": ids.copy(),
    }
    validate_pair(coarse, refined, refinement)
    return {
        "coarse": coarse,
        "refined": refined,
        "metadata": {
            "task": task,
            "split": split,
            "refinement": refinement,
            "semantics": "same held controls, physical events, latent IDs, label and horizon",
            "label_law": {
                "held_hazard": "1-exp(-integral(.15+exp(.6u-.3v)))",
                "held_filter": "dh/dt=.8*(u-h), h(0)=0",
                "event_memory": "query selects one of two physical key/value writes",
            }[task],
        },
    }


def validate_pair(coarse, refined, refinement):
    for data in (coarse, refined):
        x, dt, writes, y = (data[name] for name in ("x", "dt", "write_mask", "y"))
        if (
            x.ndim != 3
            or x.shape[-1] != 4
            or dt.shape != x.shape[:2]
            or writes.shape != dt.shape
            or y.shape != (len(x), 1)
            or any(
                value.dtype != np.float64 or not np.isfinite(value).all()
                for value in (x, dt, writes, y)
            )
            or (dt <= 0).any()
            or not np.isin(writes, (0.0, 1.0)).all()
            or not np.allclose(dt * 1e6, np.rint(dt * 1e6), rtol=0, atol=1e-6)
        ):
            raise ValueError("invalid finite paired stream")
    if (
        not np.array_equal(coarse["ids"], refined["ids"])
        or not np.array_equal(coarse["y"], refined["y"])
        or not np.array_equal(np.repeat(coarse["x"], refinement, axis=1), refined["x"])
        or not np.allclose(
            np.repeat(coarse["dt"] / refinement, refinement, axis=1),
            refined["dt"],
            rtol=0,
            atol=1e-15,
        )
        or not np.array_equal(
            refined["write_mask"][:, ::refinement], coarse["write_mask"]
        )
        or np.any(
            refined["write_mask"].reshape(len(coarse["x"]), -1, refinement)[:, :, 1:]
        )
        or not np.allclose(
            coarse["dt"].sum(1), refined["dt"].sum(1), rtol=0, atol=1e-14
        )
    ):
        raise ValueError(
            "refinement changed physical trajectory, information or events"
        )


def digest(data):
    result = hashlib.sha256()
    for name, value in sorted(data.items()):
        result.update(str((name, value.shape, value.dtype)).encode())
        result.update(value.tobytes())
    return result.hexdigest()
