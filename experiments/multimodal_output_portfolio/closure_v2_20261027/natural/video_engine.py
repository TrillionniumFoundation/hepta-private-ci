"""Endpoint-only natural frame reconstruction with bounded flow computation."""
from pathlib import Path
import time

import cv2
import numpy as np
from PIL import Image

from ...continuation_20261027.natural.video_generator import endpoints, motion
from .common import cpu_now, save, sha


def components(left, right, solver):
    """All features are derived from the two observed RGB endpoints."""
    if solver == "farneback_original":
        return motion(left, right)
    grays = [cv2.cvtColor(np.rint(image * 255).astype(np.uint8), cv2.COLOR_RGB2GRAY) for image in (left, right)]
    preset = {"dis_ultrafast": cv2.DISOPTICAL_FLOW_PRESET_ULTRAFAST,
        "dis_fast": cv2.DISOPTICAL_FLOW_PRESET_FAST, "dis_medium": cv2.DISOPTICAL_FLOW_PRESET_MEDIUM}[solver]
    model = cv2.DISOpticalFlow_create(preset)
    flows = [model.calc(grays[0], grays[1], None), model.calc(grays[1], grays[0], None)]
    y, x = np.indices(left.shape[:2], dtype=np.float32)
    warps = []
    for image, flow in zip((left, right), flows):
        mx, my = x - .5 * flow[:, :, 0], y - .5 * flow[:, :, 1]
        # Two inverse-map updates reduce the direct displacement approximation.
        for _ in range(2):
            local = cv2.remap(flow, mx, my, cv2.INTER_LINEAR, borderMode=cv2.BORDER_REFLECT)
            mx, my = x - .5 * local[:, :, 0], y - .5 * local[:, :, 1]
        warps.append(cv2.remap(image, mx, my, cv2.INTER_LINEAR, borderMode=cv2.BORDER_REFLECT))
    blend, warped = (left + right) / 2, (warps[0] + warps[1]) / 2
    features = np.stack((np.ones(left.shape[:2]), np.mean(np.abs(left - right), axis=2),
        np.mean(np.abs(warps[0] - warps[1]), axis=2), np.mean(np.abs(warped - blend), axis=2)), axis=2)
    return blend, warped, features


def fit(training, solver):
    """Learn one bounded interpolation coefficient from training pixels only."""
    numerator, denominator, baseline_error, target_values = 0., 0., 0., 0
    for row in training:
        left, right = endpoints(row["left"], row["right"])
        blend, warped, _ = components(left, right, solver)
        with Image.open(row["private_target"]) as image:
            target = np.asarray(image.convert("RGB"), dtype=np.float64) / 255
        delta = (warped - blend).astype(np.float64)
        numerator += float(np.sum((target - blend) * delta))
        denominator += float(np.sum(delta * delta))
        baseline_error += float(np.sum((target - (blend + .5 * delta)) ** 2))
        target_values += target.size
    alpha = float(np.clip(numerator / max(denominator, 1e-20), 0, 1))
    return {"solver": solver, "alpha": alpha, "initial_alpha": .5, "trainable_parameters": 1,
        "objective": "Exact training RGB least-squares minimizer over convex blend coefficient",
        "numerator": numerator, "denominator": denominator,
        "training_scalar_values": target_values, "initial_training_MSE": baseline_error / target_values,
        "training_sources": sorted({r["source"] for r in training}), "private_test_pixels_received": False}


def render(item, configuration, destination):
    destination.mkdir(parents=True, exist_ok=False)
    wall, cpu = time.perf_counter(), cpu_now()
    left, right = endpoints(item["left"], item["right"])
    if configuration["solver"] == "blend":
        result, expensive = (left + right) / 2, 0
    else:
        blend, warped, features = components(left, right, configuration["solver"])
        if "weights" in configuration:
            alpha = 1 / (1 + np.exp(-np.clip(features @ np.asarray(configuration["weights"]), -30, 30)))
            result = blend + alpha[:, :, None] * (warped - blend)
        else:
            result = blend + configuration["alpha"] * (warped - blend)
        expensive = 2
    pixels = np.rint(np.clip(result, 0, 1) * 255).astype(np.uint8)
    path = destination / "DELIVERED.png"
    Image.fromarray(pixels).save(path)
    with Image.open(path) as image:
        if not np.array_equal(np.asarray(image), pixels):
            raise ValueError("Delivered frame pixels changed")
    public = {"output_path": str(path), "output_sha256": sha(path), "configuration": configuration,
        "expensive_flow_calls": expensive, "private_target_received": False,
        "delivered_ns": time.time_ns(), "shape": list(pixels.shape)}
    save(destination / "PUBLIC_RESULT.json", public)
    return {**public, "cpu_seconds": cpu_now() - cpu, "wall_seconds": time.perf_counter() - wall}


def score(target, output):
    with Image.open(target) as image:
        truth = np.asarray(image.convert("RGB"), dtype=np.float64) / 255
    with Image.open(output) as image:
        observed = np.asarray(image.convert("RGB"), dtype=np.float64) / 255
    mse = float(np.mean((truth - observed) ** 2))
    return {"pixel_MSE": mse, "PSNR": float(-10 * np.log10(max(mse, 1e-12)))}
