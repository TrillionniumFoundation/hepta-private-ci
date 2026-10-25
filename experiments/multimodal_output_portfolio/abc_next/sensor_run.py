"""Train one public reader using only the pre-existing generator-training role."""

import argparse
import hashlib
import json
from pathlib import Path
import resource
import time

import torch
from torch.nn import functional as F

from ..abc_recovery.base_recovery import file_sha, write_json
from ..v6.neural import parameter_hash
from ..v7.sources import load_roles
from .observability import PublicDigitSensor


CONFIG = {"seed": 20261025, "steps": 1200, "batch_size": 128,
          "learning_rate": .002, "threads": 2, "training_individual_sources": 10000,
          "temperature_individual_sources": 2000,
          "temperature_grid": [.75, 1., 1.25, 1.5, 2.],
          "augmentation_views": ["original", "noisy", "occluded", "bernoulli"]}


def augment(pixels, kind, generator):
    pixels = pixels.detach().clone()
    mask = torch.ones_like(pixels)
    if kind == "noisy":
        pixels = (pixels + .22 * torch.randn(pixels.shape, generator=generator)).clamp(0, 1)
    elif kind == "occluded":
        rows = torch.randint(19, (len(pixels),), generator=generator)
        cols = torch.randint(19, (len(pixels),), generator=generator)
        for i, (row, col) in enumerate(zip(rows.tolist(), cols.tolist())):
            mask[i, :, row:row + 10, col:col + 10] = 0
        pixels = (pixels + .08 * torch.randn(pixels.shape, generator=generator)).clamp(0, 1) * mask
    elif kind == "bernoulli":
        pixels = torch.bernoulli(pixels, generator=generator)
    elif kind != "original":
        raise ValueError("Unregistered sensor augmentation")
    return pixels, mask


def run(cache, manifest, output):
    output.mkdir(parents=True, exist_ok=False)
    started_wall, started_cpu = time.perf_counter_ns(), time.process_time_ns()
    paths = [Path(__file__), Path(__file__).with_name("observability.py")]
    pins = {p.name: file_sha(p) for p in paths}
    write_json(output / "registration.json", {
        "schema": "hepta.abc-next.public-sensor-registration.v1", "registered_unix_ns": time.time_ns(),
        "config": CONFIG, "manifest_file_sha256": file_sha(manifest), "source_sha256": pins,
        "role_materialized": "train", "reward_or_audit_observers_used": False,
        "formal_neuron_or_test_sources_opened": False,
        "scope": "Public deployable feature extractor; training-role temperature selection is not independent outcome qualification"})
    try:
        torch.set_num_threads(CONFIG["threads"])
        corpus = load_roles(cache, manifest, roles=("train",))
        source = corpus.splits["train"]
        boundary = CONFIG["training_individual_sources"]
        if len(source) != boundary + CONFIG["temperature_individual_sources"]:
            raise ValueError("Training role source census differs")
        sensor = PublicDigitSensor(CONFIG["seed"])
        with torch.no_grad():
            counts = torch.bincount(source.labels[:boundary], minlength=10).float()
            sensor.prior.copy_(counts / counts.sum())
        pixels = source.images.float() / 255
        optimizer = torch.optim.Adam(sensor.parameters(), lr=CONFIG["learning_rate"])
        rng = torch.Generator().manual_seed(CONFIG["seed"] + 1)
        trace = []
        for step in range(CONFIG["steps"]):
            ids = torch.randint(boundary, (CONFIG["batch_size"],), generator=rng)
            kind = CONFIG["augmentation_views"][step % 4]
            observed, mask = augment(pixels[ids], kind, rng)
            optimizer.zero_grad(set_to_none=True)
            loss = F.cross_entropy(sensor(observed, mask), source.labels[ids])
            if not torch.isfinite(loss):
                raise ValueError("Nonfinite public sensor loss")
            loss.backward()
            optimizer.step()
            if step == 0 or (step + 1) % 100 == 0:
                row = {"step": step + 1, "augmentation": kind, "minibatch_loss": float(loss.detach())}
                trace.append(row)
                print(json.dumps(row), flush=True)
        sensor.eval().requires_grad_(False)
        labels = source.labels[boundary:]
        logits = {}
        with torch.inference_mode():
            for i, kind in enumerate(CONFIG["augmentation_views"]):
                observed, mask = augment(pixels[boundary:], kind, torch.Generator().manual_seed(CONFIG["seed"] + 100 + i))
                logits[kind] = torch.cat([sensor(x, m) for x, m in zip(observed.split(256), mask.split(256))])
        trials = []
        for temperature in CONFIG["temperature_grid"]:
            losses = {kind: float(F.cross_entropy(value / temperature, labels)) for kind, value in logits.items()}
            trials.append({"temperature": temperature, "mean_NLL": sum(losses.values()) / len(losses), "by_view_NLL": losses})
        chosen = min(trials, key=lambda row: (row["mean_NLL"], row["temperature"]))
        sensor.temperature.fill_(chosen["temperature"])
        by_view = {kind: {"correct": int((value.argmax(-1) == labels).sum()), "source_count": len(labels),
                          "accuracy": float((value.argmax(-1) == labels).float().mean())}
                   for kind, value in logits.items()}
        if pins != {p.name: file_sha(p) for p in paths}:
            raise ValueError("Public sensor source changed during training")
        record = {"schema": "hepta.abc-next.public-sensor.v1", "config": CONFIG,
                  "state_dict": sensor.state_dict(), "parameter_sha256": parameter_hash(sensor),
                  "source_sha256": pins, "manifest_sha256": corpus.manifest["manifest_sha256"]}
        with (output / "sensor.pt").open("xb") as stream:
            torch.save(record, stream)
        summary = {"status": "completed", "schema": "hepta.abc-next.public-sensor-result.v1",
                   "parameter_sha256": record["parameter_sha256"], "checkpoint_file_sha256": file_sha(output / "sensor.pt"),
                   "registration_sha256": file_sha(output / "registration.json"), "config": CONFIG,
                   "training_source_ids_sha256": hashlib.sha256("\n".join(source.ids[:boundary]).encode()).hexdigest(),
                   "temperature_source_ids_sha256": hashlib.sha256("\n".join(source.ids[boundary:]).encode()).hexdigest(),
                   "temperature_trials": trials, "selected_temperature": chosen["temperature"],
                   "training_role_tail_by_view": by_view, "trace": trace,
                   "independent_target_domain_qualification": False, "posterior_calibration_certificate": False,
                   "wall_ns": time.perf_counter_ns() - started_wall, "cpu_ns": time.process_time_ns() - started_cpu,
                   "maximum_rss_bytes": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024,
                   "timer_scope": "entry through fit, temperature selection, snapshot save and final identity check; process launch separately measured"}
        write_json(output / "result.json", summary)
        print(json.dumps({"status": "completed", "parameter_sha256": record["parameter_sha256"],
                          "selected_temperature": chosen["temperature"], "by_view": by_view}), flush=True)
    except BaseException as error:
        write_json(output / "failure.json", {"error": repr(error), "wall_ns": time.perf_counter_ns() - started_wall})
        raise


def load_sensor(path):
    record = torch.load(path, map_location="cpu", weights_only=True)
    if record["schema"] != "hepta.abc-next.public-sensor.v1":
        raise ValueError("Unknown public sensor snapshot")
    sensor = PublicDigitSensor(record["config"]["seed"])
    sensor.load_state_dict(record["state_dict"])
    sensor.eval().requires_grad_(False)
    if parameter_hash(sensor) != record["parameter_sha256"]:
        raise ValueError("Public sensor parameter identity differs")
    return sensor


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("cache", "manifest", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    args = parser.parse_args()
    run(args.cache, args.manifest, args.output)


if __name__ == "__main__":
    main()
