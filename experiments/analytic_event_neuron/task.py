"""Registered partially observed diffusion tasks; no policy reads latent targets."""

import hashlib
import numpy as np

HORIZONS = np.array([0.0, 0.5, 1.0, 2.0])
OFFSETS = np.array([0.0, 0.5, 1.0, 1.5, 2.0, 3.0])
LOWER, UPPER = -0.6, 0.6
STAGES = ("initial", "repair", "wait", "wait_repair")
PROCESS_VARIANCE = 0.18
OBSERVATION_VARIANCE = 0.64
REPAIR_VARIANCE = 0.04
WAIT_COST, REPAIR_COST = 0.07, 0.12


def _noise(rng, shape, law):
    if law in ("heavy_tail", "student_t"):
        return rng.standard_t(4, size=shape) / np.sqrt(2.0)
    return rng.standard_normal(shape)


def build_dataset(seed, n, split, law="gaussian"):
    """Every row is an independent trajectory, with shared future increments.

    The environment stores potential observations. They are exposed to a policy
    only through the selected action in evaluate_control. Future arrays are
    training labels or post-delivery scoring targets, never model features.
    """
    if law not in ("gaussian", "drift_shift", "heavy_tail", "student_t") or n <= 0:
        raise ValueError("Unknown task law or nonpositive trajectory count")
    rng = np.random.default_rng(seed)
    terms_rng = np.random.default_rng(np.random.SeedSequence([seed, 0xAE71]))
    cost_multiplier = terms_rng.choice([0.5, 1.0, 2.0, 4.0], size=n)
    drift = 0.12 if law != "drift_shift" else 0.32
    times = np.cumsum(rng.choice([0.2, 0.6, 1.1, 1.7], (n, 6)), axis=1)
    latent = rng.normal(size=n)
    observations = np.zeros((n, 6))
    last = np.zeros(n)
    for j in range(6):
        dt = times[:, j] - last
        latent += drift * dt + np.sqrt(PROCESS_VARIANCE * dt) * _noise(rng, n, law)
        observations[:, j] = latent + np.sqrt(OBSERVATION_VARIANCE) * _noise(rng, n, law)
        last = times[:, j]
    mask = rng.random((n, 6)) > 0.18
    mask[:, -1] = True
    observations = np.where(mask, observations, 0.0)
    future = np.empty((n, len(OFFSETS)))
    future[:, 0] = latent
    for j in range(1, len(OFFSETS)):
        dt = OFFSETS[j] - OFFSETS[j - 1]
        latent = latent + drift * dt + np.sqrt(PROCESS_VARIANCE * dt) * _noise(rng, n, law)
        future[:, j] = latent
    return {
        "obs": observations, "times": times, "mask": mask,
        "obs_var": np.full((n, 6), OBSERVATION_VARIANCE), "future": future,
        "repair_observation": future[:, 0] + np.sqrt(REPAIR_VARIANCE) * _noise(rng, n, law),
        "wait_observation": future[:, 2] + np.sqrt(OBSERVATION_VARIANCE) * _noise(rng, n, law),
        "wait_repair_observation": future[:, 2] + np.sqrt(REPAIR_VARIANCE) * _noise(rng, n, law),
        "cost_multiplier": cost_multiplier,
        "ids": np.array([f"{split}:{law}:{seed}:{i}" for i in range(n)]),
        "seed": int(seed), "split": split, "law": law, "drift": drift,
    }


def append_observation(h, observation, time, variance, suffix):
    """Append an actually acquired observation; simultaneous sensors are legal."""
    n = len(h["obs"])
    out = {k: np.array(v, copy=True) for k, v in h.items()}
    slots = np.sum(h["occupied"], axis=1).astype(int)
    if np.any(slots >= 8):
        raise ValueError("History capacity exhausted")
    row = np.arange(n)
    out["obs"][row, slots] = np.broadcast_to(observation, (n,))
    out["times"][row, slots] = np.broadcast_to(time, (n,))
    out["obs_var"][row, slots] = variance
    out["mask"][row, slots] = True
    out["occupied"][row, slots] = True
    out["ids"] = np.array([f"{x}/{suffix}" for x in h["ids"]])
    return out


def history(data, stage="initial"):
    """Extract public histories for training; evaluation acquires actions explicitly."""
    if stage not in STAGES:
        raise ValueError("Unknown stage")
    n = len(data["obs"])
    h = {"obs": np.zeros((n, 8)), "times": np.zeros((n, 8)),
         "mask": np.zeros((n, 8), dtype=bool), "occupied": np.zeros((n, 8), dtype=bool),
         "obs_var": np.ones((n, 8)), "ids": data["ids"].copy()}
    for key in ("obs", "times", "mask", "obs_var"):
        h[key][:, :6] = data[key]
    h["occupied"][:, :6] = True
    if stage == "repair":
        h = append_observation(h, data["repair_observation"], data["times"][:, -1], REPAIR_VARIANCE, stage)
    if stage.startswith("wait"):
        h = append_observation(h, data["wait_observation"], data["times"][:, -1] + 1.0, OBSERVATION_VARIANCE, "wait")
    if stage == "wait_repair":
        h = append_observation(h, data["wait_repair_observation"], data["times"][:, -1] + 1.0, REPAIR_VARIANCE, "repair")
    return h


def targets(data, stage="initial"):
    indices = [0, 1, 2, 4] if not stage.startswith("wait") else [2, 3, 4, 5]
    return data["future"][:, indices].copy()


def combine_training(data):
    contexts = [history(data, stage) for stage in STAGES]
    return ({key: np.concatenate([h[key] for h in contexts]) for key in contexts[0]},
            np.concatenate([targets(data, stage) for stage in STAGES]))


def subset(h, rows):
    return {key: np.atleast_1d(value[rows]) if value.ndim == 1 else np.atleast_2d(value[rows])
            for key, value in h.items()}


def latest_time(h):
    return np.max(np.where(h["occupied"], h["times"], 0.0), axis=1)


def event_labels(values):
    return np.where(values <= LOWER, 0, np.where(values > UPPER, 2, 1))


def dataset_digest(data):
    digest = hashlib.sha256()
    for key in sorted(data):
        digest.update(key.encode())
        value = data[key]
        digest.update(value.tobytes() if isinstance(value, np.ndarray) else str(value).encode())
    return digest.hexdigest()
