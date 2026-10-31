"""Known-model risk task; the independent teacher uses a three-mode Bayes sum.

The queried Brownian path starts after the observed sensor history. Observed
increments measure a fixed latent drift; they are not a censored surviving path.
This distinction avoids silently discarding survival information.
"""

import argparse
import hashlib
import json
from pathlib import Path
import time

import numpy as np
from scipy.special import log_ndtr, softmax

HERE = Path(__file__).resolve().parent
MODES = np.array([-.8, 0., .8])
PRIOR = np.array([.3, .4, .3])


def teacher_components(query):
    distance, sigma, horizon, slope = query[:, :4].T
    mu = MODES[None, :] - slope[:, None]
    d, s, t = distance[:, None], sigma[:, None], horizon[:, None]
    denominator = s * np.sqrt(t)
    log_f = np.logaddexp(log_ndtr((mu * t - d) / denominator),
        2 * mu * d / s**2 + log_ndtr((-mu * t - d) / denominator))
    if np.max(log_f) > 1e-10:
        raise ArithmeticError("first-passage probability exceeds one")
    return np.exp(np.minimum(log_f, 0.))


def make_data(name, protocol):
    size = protocol["data_sizes"].get(name,
        protocol["data_sizes"]["confirmation_per_regime"])
    rng = np.random.default_rng(protocol["data_seeds"][name])
    lower, upper = protocol["history_lengths"][name]
    lengths = rng.integers(lower, upper + 1, size)
    mode = rng.choice(3, size, p=PRIOR)
    dt = rng.uniform(*protocol["history_dt"], (size, 32))
    sensor_sd = rng.uniform(*protocol["history_sensor_sd"], (size, 32))
    increments = MODES[mode, None] * dt + sensor_sd * np.sqrt(dt) * rng.normal(size=dt.shape)
    mask = np.arange(32)[None, :] < lengths[:, None]
    a = np.sum(np.where(mask, increments / sensor_sd**2, 0.), axis=1)
    b = np.sum(np.where(mask, dt / sensor_sd**2, 0.), axis=1)
    posterior = softmax(a[:, None] * MODES - .5 * b[:, None] * MODES**2 + np.log(PRIOR), axis=1)
    ranges = protocol["query"] | protocol["shifts"].get(name, {})
    query = np.column_stack([rng.uniform(*ranges[k], size)
        for k in ("distance", "sigma", "horizon", "slope", "protect_cost")])
    components = teacher_components(query)
    probability = np.sum(posterior * components, axis=1)
    event = rng.random(size) < components[np.arange(size), mode]
    history = np.stack([increments, dt, sensor_sd], axis=-1) * mask[:, :, None]
    return {"history": history, "lengths": lengths, "query": query,
        "probability": probability, "event": event.astype(np.int8),
        "teacher_components": components, "posterior": posterior,
        "latent_mode_for_audit_only": mode}


def generate(confirmation=False):
    protocol = json.loads((HERE / "protocol.json").read_text())
    if confirmation and not (HERE / "FREEZE.json").exists():
        raise RuntimeError("freeze checkpoints before generating confirmation data")
    if confirmation:
        frozen = json.loads((HERE / "FREEZE.json").read_text())["source_and_checkpoint_sha256"]
        for relative, expected in frozen.items():
            if hashlib.sha256((HERE / relative).read_bytes()).hexdigest() != expected:
                raise RuntimeError("frozen input changed: " + relative)
    names = ["iid", "long_history", "low_noise", "moving_boundary"] if confirmation else ["train", "dev"]
    out = HERE / "evidence" / "data"
    out.mkdir(parents=True, exist_ok=True)
    metadata = {}
    for name in names:
        start, wall = time.process_time(), time.perf_counter()
        data = make_data(name, protocol)
        path = out / (name + ".npz")
        if path.exists():
            raise FileExistsError("refusing to overwrite frozen data: " + str(path))
        np.savez_compressed(path, **data)
        metadata[name] = {"cpu_seconds": time.process_time() - start,
            "wall_seconds": time.perf_counter() - wall, "samples": len(data["probability"]),
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
    (out / ("confirmation_generation.json" if confirmation else "training_generation.json")).write_text(
        json.dumps(metadata, indent=2) + "\n")
    print(json.dumps(metadata, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--confirmation", action="store_true")
    generate(parser.parse_args().confirmation)
