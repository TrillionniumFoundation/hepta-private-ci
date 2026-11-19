"""Post-seal independent numeric readers and finite-grid stopping reference."""

import gzip
import hashlib
import json
from pathlib import Path

import numpy as np
from scipy.special import expit, ndtr


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def canonical(value, compact=False):
    options = {"sort_keys": True, "allow_nan": False}
    if compact:
        options["separators"] = (",", ":")
    return hashlib.sha256(json.dumps(value, **options).encode()).hexdigest()


def check(condition, message):
    if not condition:
        raise ValueError(message)


def close(actual, expected, message, atol=1e-10, rtol=1e-8):
    check(np.allclose(actual, expected, atol=atol, rtol=rtol), message)


def read_arrays(directory):
    """Independent decoding of the declared concatenated numeric evidence."""
    directory = Path(directory)
    manifest = json.loads((directory / "manifest.json").read_text())
    check(manifest["format"] == "hcsn_followup_arrays_v1", "array format")
    parts = []
    for part in manifest["parts"]:
        check(Path(part["file"]).name == part["file"], "array shard path")
        path = directory / part["file"]
        check(sha(path) == part["sha256"], "array shard SHA")
        with np.load(path, allow_pickle=False) as archive:
            check(archive["bytes"].dtype == np.uint8, "packed array byte dtype")
            parts.append(archive["bytes"].tobytes())
    raw, offset, arrays = b"".join(parts), 0, {}
    check(len(raw) == manifest["nbytes"], "array packed length")
    for name, row in sorted(manifest["arrays"].items()):
        dtype = np.dtype(row["dtype"])
        check(not dtype.hasobject and row["offset"] == offset, "array dtype/range")
        check(
            int(np.prod(row["shape"], dtype=np.int64)) * dtype.itemsize
            == row["nbytes"],
            "array shape bytes",
        )
        value = raw[offset : offset + row["nbytes"]]
        check(hashlib.sha256(value).hexdigest() == row["sha256"], "array tensor SHA")
        arrays[name] = np.frombuffer(value, dtype=dtype).reshape(row["shape"]).copy()
        offset += row["nbytes"]
    check(offset == len(raw), "unassigned packed bytes")
    return arrays


def read_traces(directory, receipt):
    path = Path(directory) / receipt["path"]
    check(sha(path) == receipt["sha256"], "trace compressed SHA")
    raw = gzip.decompress(path.read_bytes())
    check(
        hashlib.sha256(raw).hexdigest() == receipt["uncompressed_sha256"],
        "trace uncompressed SHA",
    )
    values = [json.loads(line) for line in raw.splitlines()]
    check(len(values) == receipt["records"], "trace record count")
    return values


def regenerate_episodes(count, horizon, snrs, costs, seed, split):
    """NumPy reimplementation; no call to the production episode generator."""
    rng = np.random.default_rng(seed)
    contexts = np.array([(s, c) for s in snrs for c in costs], dtype=np.float32)
    selection = np.arange(count) % len(contexts)
    rng.shuffle(selection)
    snr, cost = (contexts[selection, i].copy() for i in (0, 1))
    labels = np.arange(count) % 2
    rng.shuffle(labels)
    observations = rng.normal(size=(count, horizon)).astype(np.float32)
    observations += (2 * labels - 1).astype(np.float32)[:, None] * snr[:, None]
    remaining = np.broadcast_to(
        np.arange(horizon - 1, -1, -1), observations.shape
    ).copy()
    x = np.stack(
        (
            observations,
            np.broadcast_to(snr[:, None], observations.shape),
            np.broadcast_to(cost[:, None], observations.shape),
            remaining.astype(np.float32) / np.float32(24),
        ),
        axis=-1,
    )
    increments = np.float32(2) * snr[:, None] * observations
    return {
        "x": x,
        "dt": np.ones((count, horizon), np.float32),
        "label": labels.astype(np.int64),
        "snr": snr,
        "cost": cost,
        "remaining_steps": remaining,
        "observations": observations,
        "bayes_log_odds": increments.cumsum(1, dtype=np.float64).astype(np.float32),
        "episode_id": np.array([f"study002.{split}:{seed}:{i}" for i in range(count)]),
    }


def gaussian_weights(grid, means, sigma):
    """SciPy Gaussian integration of clipped linear interpolation basis functions."""
    z = (grid[None, :] - means[:, None]) / sigma
    cdf = ndtr(z)
    density = np.exp(-0.5 * z * z) / np.sqrt(2 * np.pi)
    mass = np.diff(cdf, axis=1)
    moment = means[:, None] * mass + sigma * (density[:, :-1] - density[:, 1:])
    spacing = np.diff(grid)
    result = np.zeros((len(grid), len(grid)))
    result[:, :-1] += (grid[1:] * mass - moment) / spacing
    result[:, 1:] += (moment - grid[:-1] * mass) / spacing
    result[:, 0] += cdf[:, 0]
    result[:, -1] += 1 - cdf[:, -1]
    result = np.maximum(result, 0)
    return result / result.sum(axis=1, keepdims=True)


def reference_waits(snr, cost, horizon):
    """Independent NumPy/SciPy evaluation on the SAME approximate 257 grid.

    This checks the finite-grid values, not continuum optimality or whether a
    calibrated neural score really obeys Bayesian log-odds transitions.
    """
    grid = np.linspace(-12, 12, 257)
    prior, value = expit(grid), expit(np.abs(grid))
    transition = prior[:, None] * gaussian_weights(grid, grid + 2 * snr**2, 2 * snr)
    transition += (1 - prior[:, None]) * gaussian_weights(
        grid, grid - 2 * snr**2, 2 * snr
    )
    waits = [np.full_like(grid, -np.inf)]
    for _ in range(horizon - 1):
        wait = transition @ value - cost
        waits.append(wait)
        value = np.maximum(expit(np.abs(grid)), wait)
    return grid, np.stack(waits)
