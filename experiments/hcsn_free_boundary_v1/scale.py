"""CPU-only size/timing probes and exact numeric mid-stream checkpoint recovery.

Inputs and labels are deterministic synthetic tensors; these probes make no
accuracy, energy, GPU, or trained-model scaling-law claim. Baselines are timed
through sequence interfaces, never described as streaming-cache measurements.
"""

import argparse
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import platform
import statistics
import subprocess
import sys
import time
from unittest.mock import patch

import numpy as np
import torch
from torch.nn import functional as F

from . import model as model_module
from . import oracle_torch
from .benchmark_models import BASELINE_NAMES, build_model
from .model import HCSNClassifier
from .training import load_weights, save_weights


def _json(path, value):
    Path(path).write_text(json.dumps(value, sort_keys=True, indent=2, allow_nan=False) + "\n")


def _rss():
    try:
        import resource
        value = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        return int(value if sys.platform == "darwin" else value * 1024)
    except ImportError:
        return None


def environment():
    cpu_name = platform.processor()
    cpuinfo = Path("/proc/cpuinfo")
    if cpuinfo.is_file():
        cpu_name = next((line.split(":", 1)[1].strip()
                         for line in cpuinfo.read_text().splitlines()
                         if line.startswith("model name")), cpu_name)
    return dict(platform=platform.platform(), architecture=platform.machine(),
                cpu_model=cpu_name, logical_cpus=os.cpu_count(),
                affinity_cpus=len(os.sched_getaffinity(0)) if hasattr(os, "sched_getaffinity") else None,
                python=sys.version, torch=torch.__version__, numpy=np.__version__,
                torch_threads=torch.get_num_threads(), torch_interop_threads=torch.get_num_interop_threads(),
                cuda_available=torch.cuda.is_available(), measured_device="cpu",
                energy_measured=False, peak_rss_bytes=_rss())


@contextmanager
def _boundary_timing():
    """Observe unchanged root/implicit-gradient implementations in this process."""
    original_forward = model_module.free_boundary
    original_backward = oracle_torch._ImplicitBoundary.backward
    elapsed = dict(forward_cpu_seconds=0.0, backward_cpu_seconds=0.0,
                   forward_calls=0, backward_calls=0)

    def forward(*args):
        started = time.process_time()
        result = original_forward(*args)
        elapsed["forward_cpu_seconds"] += time.process_time() - started
        elapsed["forward_calls"] += 1
        return result

    def backward(ctx, gradient):
        started = time.process_time()
        result = original_backward(ctx, gradient)
        elapsed["backward_cpu_seconds"] += time.process_time() - started
        elapsed["backward_calls"] += 1
        return result

    with patch.object(model_module, "free_boundary", forward), patch.object(
            oracle_torch._ImplicitBoundary, "backward", staticmethod(backward)):
        yield elapsed


def _aggregate(records):
    cpu = [item["cpu_seconds"] for item in records]
    root = sum(item["root"]["forward_cpu_seconds"] + item["root"]["backward_cpu_seconds"]
               for item in records)
    return dict(cpu_median_seconds=statistics.median(cpu), cpu_min_seconds=min(cpu),
                cpu_max_seconds=max(cpu), wall_median_seconds=statistics.median(
                    item["wall_seconds"] for item in records),
                root_forward_cpu_mean_seconds=statistics.mean(
                    item["root"]["forward_cpu_seconds"] for item in records),
                root_backward_cpu_mean_seconds=statistics.mean(
                    item["root"]["backward_cpu_seconds"] for item in records),
                root_fraction_of_measured_cpu=root / sum(cpu), repeats=records)


def measure_configuration(name, batch, length, width=32, depth=1, repeats=3):
    generator = torch.Generator().manual_seed(771 + batch + length * 3)
    x = torch.randn(batch, length, 12, generator=generator)
    dt = 0.5 + torch.rand(batch, length, generator=generator)
    labels = torch.randint(8, (batch, length), generator=generator)
    model = build_model(name, 12, 8, width=width, depth=depth, seed=552)
    optimizer = torch.optim.Adam(model.parameters(), lr=0.001)
    before_rss = _rss()

    def execute(train):
        model.train(train)
        process_start, wall_start = time.process_time(), time.perf_counter()
        with _boundary_timing() as root:
            if train:
                optimizer.zero_grad(set_to_none=True)
                logits = model(x, dt, return_sequence=True, return_aux=False)
                loss = F.cross_entropy(logits.flatten(0, 1), labels.flatten())
                loss.backward()
                optimizer.step()
            else:
                with torch.inference_mode():
                    logits = model(x, dt, return_sequence=True, return_aux=False)
            if not torch.isfinite(logits).all():
                raise FloatingPointError(f"Nonfinite timing output: {name}")
        return dict(cpu_seconds=time.process_time() - process_start,
                    wall_seconds=time.perf_counter() - wall_start, root=dict(root))

    warmup = dict(forward=execute(False), train_step=execute(True))
    forward = [execute(False) for _ in range(repeats)]
    train = [execute(True) for _ in range(repeats)]
    return dict(model=name, batch=batch, length=length, width=width, depth=depth,
                counts=model.counts(), forward=_aggregate(forward), train_step=_aggregate(train),
                warmup=warmup, process_peak_rss_before_bytes=before_rss,
                process_peak_rss_after_bytes=_rss(),
                interface="full_sequence", streaming_cache_measured=False,
                training_updates_for_timing=1 + repeats)


def _flatten_state(state):
    result = {"elapsed": state["elapsed"].detach().cpu().numpy().copy()}
    for index, layer in enumerate(state["layers"]):
        for key, value in layer.items():
            result[f"layer_{index}.{key}"] = value.detach().cpu().numpy().copy()
    return result


def _read_state(path, depth):
    with np.load(path, allow_pickle=False) as archive:
        state = dict(elapsed=torch.from_numpy(np.array(archive["elapsed"], copy=True)), layers=[])
        for index in range(depth):
            state["layers"].append({key: torch.from_numpy(np.array(
                archive[f"layer_{index}.{key}"], copy=True))
                for key in ("content", "voltage", "refractory", "event")})
    return state


def _state_size(state):
    tensors = [state["elapsed"]] + [value for layer in state["layers"] for value in layer.values()]
    storages = {}
    for value in tensors:
        storage = value.untyped_storage()
        storages[storage.data_ptr()] = storage.nbytes()
    return dict(tensor_elements=sum(value.numel() for value in tensors),
                tensor_bytes=sum(value.numel() * value.element_size() for value in tensors),
                unique_storage_bytes=sum(storages.values()),
                tensors=len(tensors), retains_autograd_graph=any(value.grad_fn is not None for value in tensors))


def streaming_probe(width=32, depth=2, batch=2, length=512):
    generator = torch.Generator().manual_seed(335)
    x = torch.randn(batch, length, 12, generator=generator)
    dt = 0.4 + torch.rand(batch, length, generator=generator)
    model = HCSNClassifier(12, 8, width=width, depth=depth, seed=552).eval()
    checkpoints = sorted(set([n for n in (32, 64, 128, 256) if n <= length] + [length]))
    samples, outputs, state = [], [], None
    started = time.process_time()
    with torch.inference_mode():
        expected, _ = model(x, dt, return_sequence=True)
        batch_cpu = time.process_time() - started
        started = time.process_time()
        for index in range(length):
            logits, state, _ = model.step(x[:, index], dt[:, index], state)
            outputs.append(logits)
            if index + 1 in checkpoints:
                samples.append(dict(length=index + 1, **_state_size(state)))
        streaming_cpu = time.process_time() - started
    actual = torch.stack(outputs, 1)
    error = (actual - expected).abs().max().item()
    torch.testing.assert_close(actual, expected, rtol=2e-5, atol=2e-6)
    if len({item["tensor_elements"] for item in samples}) != 1:
        raise AssertionError("Streaming tensor size grew with prefix length")
    if len({item["unique_storage_bytes"] for item in samples}) != 1:
        raise AssertionError("Streaming retained storage grew with prefix length")
    return dict(batch=batch, width=width, depth=depth, length=length, samples=samples,
                max_batch_vs_step_logit_error=error, passed=True,
                batch_cpu_seconds=batch_cpu, streaming_cpu_seconds=streaming_cpu,
                inference_mode=True, expected_tensor_elements=batch * (1 + 4 * width * depth),
                claim="only this HCSN step state is measured; baseline caches are unmeasured")


def resume_worker(directory):
    """CLI child entry: reconstruct only from numeric weights/state and JSON config."""
    directory = Path(directory)
    config = json.loads((directory / "config.json").read_text())
    model = HCSNClassifier(**config).eval()
    load_weights(directory / "weights.npz", model)
    state = _read_state(directory / "mid_state.npz", config["depth"])
    with np.load(directory / "remaining_inputs.npz", allow_pickle=False) as archive:
        x = torch.from_numpy(np.array(archive["x"], copy=True))
        dt = torch.from_numpy(np.array(archive["dt"], copy=True))
    outputs = []
    with torch.inference_mode():
        for index in range(x.shape[1]):
            logits, state, _ = model.step(x[:, index], dt[:, index], state)
            outputs.append(logits)
    np.savez_compressed(directory / "resumed_logits.npz", logits=torch.stack(outputs, 1).numpy())
    np.savez_compressed(directory / "resumed_final_state.npz", **_flatten_state(state))
    _json(directory / "child_environment.json", environment())
    print(json.dumps(dict(status="resumed", suffix_steps=x.shape[1], pid=os.getpid())))


def recovery_probe(directory, width=32, depth=2, batch=3, length=256, split_at=113):
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=False)
    generator = torch.Generator().manual_seed(723)
    x = torch.randn(batch, length, 12, generator=generator)
    dt = 0.4 + torch.rand(batch, length, generator=generator)
    model = HCSNClassifier(12, 8, width=width, depth=depth, seed=552).eval()
    _json(directory / "config.json", model.config)
    weights_hash = save_weights(directory / "weights.npz", model)
    np.savez_compressed(directory / "remaining_inputs.npz", x=x[:, split_at:].numpy(), dt=dt[:, split_at:].numpy())
    state, outputs, middle = None, [], None
    with torch.inference_mode():
        for index in range(length):
            logits, state, _ = model.step(x[:, index], dt[:, index], state)
            if index + 1 == split_at:
                middle = _flatten_state(state)
                np.savez_compressed(directory / "mid_state.npz", **middle)
            if index >= split_at:
                outputs.append(logits)
    expected = torch.stack(outputs, 1).numpy()
    final = _flatten_state(state)
    np.savez_compressed(directory / "uninterrupted_logits.npz", logits=expected)
    np.savez_compressed(directory / "uninterrupted_final_state.npz", **final)
    command = [sys.executable, "-m", "experiments.hcsn_free_boundary_v1.scale",
               "--resume-worker", str(directory)]
    process = subprocess.run(command, cwd=Path(__file__).resolve().parents[2],
                              check=True, text=True, capture_output=True)
    (directory / "child_stdout.txt").write_text(process.stdout)
    (directory / "child_stderr.txt").write_text(process.stderr)
    with np.load(directory / "resumed_logits.npz", allow_pickle=False) as archive:
        resumed = np.array(archive["logits"])
    with np.load(directory / "resumed_final_state.npz", allow_pickle=False) as archive:
        state_errors = {key: float(np.max(np.abs(final[key] - archive[key]))) for key in final}
    logit_error = float(np.max(np.abs(expected - resumed)))
    refractory_max = max(float(middle[f"layer_{index}.refractory"].max()) for index in range(depth))
    passed = logit_error == 0 and max(state_errors.values()) == 0 and refractory_max > 0
    if not passed:
        raise AssertionError("Fresh-process state continuation did not match exactly")
    result = dict(passed=passed, length=length, split_at=split_at, batch=batch,
                   width=width, depth=depth, weights_sha256=weights_hash,
                   restored_components=["elapsed", "content", "voltage", "refractory", "event"],
                   mid_refractory_max=refractory_max, max_logit_error=logit_error,
                   final_state_max_errors=state_errors, child=json.loads(process.stdout),
                   parent_pid=os.getpid(), numeric_checkpoint_only=True)
    _json(directory / "receipt.json", result)
    return result


def run(output, repeats=3):
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    started_cpu, started_wall = time.process_time(), time.perf_counter()
    initial_environment = environment()
    source_files = ("scale.py", "model.py", "oracle_torch.py", "benchmark_models.py", "training.py")
    hashes = {name: hashlib.sha256((Path(__file__).parent / name).read_bytes()).hexdigest() for name in source_files}
    _json(output / "environment.json", initial_environment)
    records = []
    for name in ("free_dual",) + BASELINE_NAMES:
        for batch in (1, 16):
            for length in (32, 64, 128):
                record = measure_configuration(name, batch, length, repeats=repeats)
                records.append(record)
                _json(output / "performance.json", records)
                print(json.dumps(dict(completed=len(records), model=name, batch=batch,
                                      length=length, train_cpu=record["train_step"]["cpu_median_seconds"])), flush=True)
    size_records = []
    for width in (16, 32, 64):
        for depth in (1, 2):
            record = measure_configuration("free_dual", 16, 64, width, depth, repeats)
            probe_model = HCSNClassifier(12, 8, width=width, depth=depth)
            record["initial_stream_state"] = _state_size(probe_model.initial_state(16))
            size_records.append(record)
            _json(output / "width_depth.json", size_records)
    streaming = streaming_probe()
    _json(output / "streaming.json", streaming)
    recovery = recovery_probe(output / "recovery")
    final_environment = environment()
    summary = dict(status="completed", source_sha256=hashes, environment=initial_environment,
                    final_environment=final_environment, performance_configurations=len(records),
                    width_depth_configurations=len(size_records), warmups_per_phase=1,
                    repeats_per_phase=repeats, streaming=streaming, recovery=recovery,
                    total_parent_cpu_seconds=time.process_time() - started_cpu,
                    total_wall_seconds=time.perf_counter() - started_wall,
                    rss_scope="cumulative whole-process high-water mark, not isolated model memory",
                    energy_measured=False, quality_measured=False,
                    timing_scope="instrumented CPU sequence forward and full Adam training step")
    _json(output / "summary.json", summary)
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", default=str(Path(__file__).parent / "results" / "scaling001"))
    parser.add_argument("--resume-worker")
    parser.add_argument("--repeats", type=int, default=3)
    args = parser.parse_args()
    torch.set_num_threads(1)
    torch.set_num_interop_threads(1)
    if args.resume_worker:
        resume_worker(args.resume_worker)
    else:
        run(args.output, args.repeats)


if __name__ == "__main__":
    main()
