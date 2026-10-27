"""A public encoder-state gate selects decoder work before any decoding."""
import hashlib
from pathlib import Path
import time

import numpy as np

from .common import save


def public_features(encoded, preparation):
    array = np.asarray(encoded, dtype=np.float32)
    mean = array.mean(axis=1).reshape(16, -1)
    spread = array.std(axis=1).reshape(16, -1)
    return np.r_[np.log1p(preparation["audio_samples"] / 16000), mean.mean(axis=1), mean.std(axis=1), spread.mean(axis=1)].astype(np.float64)


def fit(rows):
    x = np.asarray([r["features"] for r in rows])
    # Terminal entropic moment difference includes the measured decoder cost.
    y = np.asarray([np.exp(-2 * (1 - min(1., r["low"]["WER"]) - .01 * r["low"]["cpu_seconds"]))
        - np.exp(-2 * (1 - min(1., r["high"]["WER"]) - .01 * r["high"]["cpu_seconds"])) for r in rows])
    mean, scale = x.mean(0), np.maximum(.1, x.std(0))
    design = np.c_[np.ones(len(x)), (x - mean) / scale]
    penalty = np.eye(design.shape[1]) * 10.
    penalty[0, 0] = .001
    weights = np.linalg.solve(design.T @ design + penalty, design.T @ y)
    return {"mean": mean.tolist(), "scale": scale.tolist(), "weights": weights.tolist(),
        "regularization": 10., "training_examples": len(rows), "training_speakers": sorted({r["speaker_id"] for r in rows}),
        "target_moment_difference": y.tolist(), "trainable_coefficients": len(weights),
        "loss": float(np.mean((design @ weights - y) ** 2)),
        "features": "duration plus16 channel-block means,16 block spreads of encoder means,16 block means of temporal standard deviation"}


def predict(features, model):
    design = np.r_[1., (features - np.asarray(model["mean"])) / np.asarray(model["scale"])]
    return float(design @ np.asarray(model["weights"]))


def episode(engine, path, model, threshold, output):
    output.mkdir(parents=True, exist_ok=False)
    wall, cpu = time.perf_counter_ns(), time.process_time_ns()
    encoded, preparation = engine.prepare(path)
    feature_wall, feature_cpu = time.perf_counter_ns(), time.process_time_ns()
    features = public_features(encoded, preparation)
    predicted = predict(features, model)
    beam = 5 if predicted >= threshold else 1
    gate = {"features": features.tolist(), "predicted_moment_gain": predicted, "threshold": threshold,
        "selected_beam": beam, "decoder_outputs_before_gate": 0,
        "cpu_seconds": (time.process_time_ns() - feature_cpu) / 1e9,
        "wall_seconds": (time.perf_counter_ns() - feature_wall) / 1e9}
    generation = engine.generate(encoded, beam, output / "FIRST.txt")
    delivered = output / "DELIVERED.txt"
    delivered.write_text(generation["transcript"] + "\n", encoding="utf-8")
    transcript = delivered.read_text(encoding="utf-8").strip()
    public = {"arm": "encoder_gate", "transcript": transcript, "encodings": [preparation], "generations": [generation],
        "gate": gate, "encoder_calls": 1, "decoder_calls": 1, "output_path": str(delivered),
        "output_sha256": hashlib.sha256(delivered.read_bytes()).hexdigest(), "private_reference_received": False,
        "delivered_before_private_scoring_ns": time.time_ns()}
    save(output / "PUBLIC_RESULT.json", public)
    return {**public, "whole_cpu_seconds": (time.process_time_ns() - cpu) / 1e9,
        "whole_wall_seconds": (time.perf_counter_ns() - wall) / 1e9}
