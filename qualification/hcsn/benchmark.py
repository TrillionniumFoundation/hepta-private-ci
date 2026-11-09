"""Reproducible synthetic sequence experiments with explicit missing measurements.

Run from the repository root: python -m qualification.hcsn.benchmark \
  --config qualification/hcsn/configs/smoke.json --output /tmp/hcsn-smoke.json
This is a correctness/small-task harness, not a language-model scaling result.
"""

import argparse
import hashlib
from importlib import metadata
import json
import math
import os
import platform
from pathlib import Path
import shlex
import statistics
import sys
import time
import threading
import tempfile

import numpy as np

from . import attempts
from .execution import (canonical_gpu_uuid, close_energy_interval, configure_cuda, execution_policy,
                        implementation_record, training_memory_peak)


def atomic_json(path, value, *, replace=True):
    """Publish one complete receipt, retaining the previous file on interruption."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(dir=path.parent, prefix=path.name+".", suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as stream:
            json.dump(value, stream, indent=2, allow_nan=False)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        if replace:
            os.replace(temporary, path)
        else:
            os.link(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def receipt_key(report, task, model, seed):
    provenance = {key: report[key] for key in ("config", "source_sha256", "hardware", "software", "datasets")}
    provenance["datasets"] = report["datasets"][task]
    provenance.update(task=task, model=model, seed=seed)
    return hashlib.sha256(json.dumps(provenance, sort_keys=True).encode()).hexdigest()


def make_dataset(task, count, length, seed):
    """Independent splits; examples contain no label-derived inputs."""
    if count <= 0 or length < 4:
        raise ValueError("count must be positive and length at least four")
    rng = np.random.default_rng(seed)
    x = np.zeros((count, length, 2), dtype=np.float32)
    if task == "delayed_recall":
        x[..., 0] = rng.uniform(-1, 1, (count, length))
        x[:, 0, 1] = 1
        y = x[:, 0, 0:1].copy()
    elif task == "adding":
        x[..., 0] = rng.uniform(0, 1, (count, length))
        first = rng.integers(0, length//2, count)
        second = rng.integers(length//2, length, count)
        x[np.arange(count), first, 1] = 1
        x[np.arange(count), second, 1] = 1
        y = (x[np.arange(count), first, 0]+x[np.arange(count), second, 0])[:, None].copy()
    else:
        raise ValueError(f"unknown task {task!r}")
    return x, y.astype(np.float32)


class EnergyCounter:
    """Read physical counters if accessible; never infer energy from runtime/TDP.

    RAPL package and NVML GPU counters cover the wall-clock training interval,
    which includes other processes using the same device. They are not process
    attribution or whole-machine measurements. Missing counters remain null.
    """
    def __init__(self, device="cpu"):
        self.sources, self.reason, self.nvml = [], [], None
        self.gpu_device_identity = None
        powercap = Path("/sys/class/powercap")
        for path in sorted(powercap.glob("intel-rapl:*/energy_uj")):
            if path.parent.name.count(":") == 1:
                try:
                    bound = float((path.parent/"max_energy_range_uj").read_text())
                    float(path.read_text())
                    self.sources.append((path.parent.name, lambda p=path: float(p.read_text())/1e6,
                                         bound/1e6))
                except (OSError, ValueError) as exc:
                    self.reason.append(f"RAPL inaccessible: {type(exc).__name__}")
        if str(device).startswith("cuda"):
            self.gpu_device_identity = dict(cuda_uuid_raw=None, cuda_uuid=None,
                                            nvml_uuid_raw=None, nvml_uuid=None, mapping_verified=False)
            try:
                import pynvml
                pynvml.nvmlInit()
                self.nvml = pynvml
                import torch
                # Logical CUDA indices can be remapped by CUDA_VISIBLE_DEVICES.
                value = getattr(torch.cuda.get_device_properties(torch.device(device)), "uuid", None)
                self.gpu_device_identity["cuda_uuid_raw"] = str(value) if value is not None else None
                uuid = canonical_gpu_uuid(self.gpu_device_identity["cuda_uuid_raw"])
                self.gpu_device_identity["cuda_uuid"] = uuid
                handle = pynvml.nvmlDeviceGetHandleByUUID(uuid)
                nvml_uuid = pynvml.nvmlDeviceGetUUID(handle)
                self.gpu_device_identity["nvml_uuid_raw"] = (nvml_uuid if isinstance(nvml_uuid, (str, type(None)))
                                                             else repr(nvml_uuid))
                actual = canonical_gpu_uuid(nvml_uuid)
                self.gpu_device_identity["nvml_uuid"] = actual
                if actual != uuid:
                    raise ValueError("NVML handle UUID differs from the requested CUDA UUID")
                self.gpu_device_identity["mapping_verified"] = True
                pynvml.nvmlDeviceGetTotalEnergyConsumption(handle)
                self.sources.append((f"nvml_{uuid}",
                                     lambda: pynvml.nvmlDeviceGetTotalEnergyConsumption(handle)/1000,
                                     None))
            except Exception as exc:
                # NVML reports device/driver-specific exception classes.
                self.reason.append(f"NVML unavailable: {type(exc).__name__}: {exc}")
        self.before, self.measured, self.invalid = {}, {}, set()
        self.stop_event, self.thread = threading.Event(), None

    def _sample(self):
        for name, read, wrap in self.sources:
            if name in self.invalid:
                continue
            try:
                current = read()
                if name in self.before:
                    delta = current-self.before[name]
                    if delta < 0 and wrap is not None:
                        delta += wrap
                    if not math.isfinite(delta) or delta < 0:
                        raise ValueError("counter reset or invalid reading")
                    self.measured[name] = self.measured.get(name, 0.0)+delta
                self.before[name] = current
            except Exception as exc:
                self.invalid.add(name)
                self.measured.pop(name, None)
                self.reason.append(f"{name}: {type(exc).__name__}")

    def start(self):
        self._sample()
        if self.sources:
            def sample_loop():
                while not self.stop_event.wait(1.0):
                    self._sample()
            self.thread = threading.Thread(target=sample_loop, daemon=True)
            self.thread.start()

    def stop(self):
        self.stop_event.set()
        if self.thread is not None:
            self.thread.join(timeout=5.0)
            if self.thread.is_alive():
                return {"joules_by_physical_counter": None, "scope": "training wall interval",
                        "gpu_device_identity": self.gpu_device_identity,
                        "missing_reason": "hardware energy read did not finish"}
        self._sample()
        if self.nvml is not None:
            try:
                self.nvml.nvmlShutdown()
            except Exception as exc:
                self.reason.append(f"NVML shutdown: {type(exc).__name__}")
        return {"joules_by_physical_counter": self.measured or None,
                "gpu_device_identity": self.gpu_device_identity,
                "scope": "training wall interval; device/package, not process attribution",
                "sampling_interval_seconds": 1.0,
                "partial_unavailable_reasons": self.reason,
                "missing_reason": None if self.measured else "; ".join(self.reason) or
                "no accessible RAPL package or NVML device energy counter"}


def validate_config(config):
    execution_policy(config)
    for key in ("train_count", "validation_count", "test_count", "length", "hidden_size",
                "batch_size", "train_steps", "latency_repeats", "cpu_threads"):
        if not isinstance(config.get(key), int) or config[key] <= 0:
            raise ValueError(f"{key} must be a positive integer")
    if config["length"] < 4 or config["hidden_size"] % 2:
        raise ValueError("length>=4 and even hidden_size are required")
    seeds = config.get("seeds")
    if (not isinstance(seeds, list) or not seeds or
            any(not isinstance(seed, int) or seed < 0 for seed in seeds) or len(set(seeds)) != len(seeds)):
        raise ValueError("seeds must be a nonempty list of distinct nonnegative integers")
    if not config.get("models") or not config.get("tasks"):
        raise ValueError("models and tasks must be nonempty")
    for key in ("models", "tasks"):
        if len(set(config[key])) != len(config[key]):
            raise ValueError(f"{key} must contain distinct entries")
    if any(not isinstance(config.get(key), (int, float)) or not math.isfinite(config[key]) or
           config[key] <= 0 for key in ("dt", "learning_rate")):
        raise ValueError("dt and learning_rate must be finite and positive")


def aggregate(runs):
    """Count failures only among attempted runs; retain unavailable separately."""
    output = []
    for task, model in sorted({(r["task"], r["model"]) for r in runs}):
        records = [r for r in runs if (r["task"], r["model"]) == (task, model)]
        good = [r for r in records if r["status"] == "completed"]
        failed = [r for r in records if r["status"] == "failed"]
        item = {"task": task, "model": model, "completed_seeds": len(good),
                "failed_seeds": len(failed),
                "unavailable_seeds": sum(r["status"] == "unavailable" for r in records),
                "execution_failure_rate": len(failed)/(len(failed)+len(good)) if failed or good else None}
        all_attempts = [a for r in records for a in r.get("attempts", [{"result": r}])]
        item["attempt_accounting"] = attempts.accounting(all_attempts)
        item["failure_rate_scope"] = "top-level rates are final seed outcomes; attempt_accounting retains every retry"
        trained = [r for r in records if r.get("training_status") in {"completed", "failed"}]
        item["training_failure_rate"] = (sum(r["training_status"] == "failed" for r in trained)/len(trained)
                                         if trained else None)
        for metric in ("test_mse", "training_examples_per_second", "inference_examples_per_second",
                       "latency_p50_ms", "latency_p95_ms"):
            vals = [r[metric] for r in good]
            item[metric+"_mean"] = statistics.mean(vals) if vals else None
            item[metric+"_seed_std"] = statistics.stdev(vals) if len(vals) > 1 else None
        output.append(item)
    return output


def _run_one(config, task, name, seed, datasets, device, torch, checkpoint_path=None):
    from .baselines import UnavailableBaseline, make_encoder
    from torch import nn

    policy = execution_policy(config)
    record = {"task": task, "model": name, "seed": seed, "status": "failed",
              "execution_policy": policy, "encoder_class": None, "implementation": None,
              "training_status": "not_started", "training_examples_seen": 0,
              "training_tokens_seen": 0, "training_steps_completed": 0,
              "budget_measurement_scope": "examples/tokens submitted to training forward; optimizer steps counted separately",
              "energy": {"joules_by_physical_counter": None,
                         "interval_complete": False, "interval_completion": "not_started",
                         "missing_reason": "attempt did not reach physical energy measurement"}}
    stage = "construction"
    meter = None
    energy_started, peak_reset, peak_captured = False, False, False
    try:
        torch.manual_seed(seed)
        if device.type == "cuda":
            torch.cuda.manual_seed_all(seed)
        encoder = make_encoder(name, 2, config["hidden_size"], device=device, dt=config["dt"],
                               population_checkpoint_steps=policy["population_checkpoint_steps"])
        record["encoder_class"] = type(encoder).__name__
        record["implementation"] = implementation_record(encoder)
        if hasattr(encoder, "population"):
            from dataclasses import asdict
            cfg = encoder.population.config
            record["population_discretization"] = dict(asdict(cfg), refractory_steps=cfg.refractory_steps,
                                                        effective_refractory_time=cfg.refractory_steps*cfg.dt)
        class Regressor(nn.Module):
            def __init__(self):
                super().__init__()
                self.encoder = encoder
                self.readout = nn.Linear(config["hidden_size"], 1)
            def forward(self, x):
                return self.readout(self.encoder(x, dt=config["dt"])[:, -1])
        model = Regressor().to(device)
        record["parameters"] = sum(p.numel() for p in model.parameters())
        record["trainable_parameters"] = sum(p.numel() for p in model.parameters() if p.requires_grad)
        optimizer = torch.optim.Adam(model.parameters(), lr=config["learning_rate"])
        train_x, train_y, val_x, val_y, test_x, test_y = [torch.from_numpy(v).to(device) for v in datasets]
        def sync():
            if device.type == "cuda":
                torch.cuda.synchronize(device)
        def evaluate_mse(inputs, targets):
            total = inputs.new_zeros(())
            with torch.no_grad():
                for offset in range(0, len(inputs), config["batch_size"]):
                    batch = slice(offset, offset+config["batch_size"])
                    total = total+(model(inputs[batch])-targets[batch]).square().sum()
            return float(total/targets.numel())
        if device.type == "cuda":
            torch.cuda.reset_peak_memory_stats(device)
            peak_reset = True
        model.train()
        batch_rng = np.random.default_rng(seed+1729)
        losses, best_val, best_state = [], math.inf, None
        val_interval = max(1, config["train_steps"]//4)
        sync()
        meter = EnergyCounter(str(device))
        meter.start()
        energy_started = True
        start = time.perf_counter()
        stage, record["training_status"] = "training", "running"
        for step in range(config["train_steps"]):
            indices = torch.as_tensor(batch_rng.integers(0, len(train_x), config["batch_size"]), device=device)
            optimizer.zero_grad(set_to_none=True)
            record["training_examples_seen"] += config["batch_size"]
            record["training_tokens_seen"] += config["batch_size"]*config["length"]
            prediction = model(train_x[indices])
            loss = (prediction-train_y[indices]).square().mean()
            if not bool(torch.isfinite(loss)):
                raise FloatingPointError(f"nonfinite loss at optimizer step {step}")
            loss.backward()
            missing = [n for n, p in model.named_parameters() if p.requires_grad and p.grad is None]
            if missing:
                record["missing_trainable_gradients"] = missing
                raise FloatingPointError(f"missing trainable gradients at optimizer step {step}: {missing}")
            if any(p.grad is not None and not bool(torch.isfinite(p.grad).all()) for p in model.parameters()):
                raise FloatingPointError(f"nonfinite gradient at optimizer step {step}")
            norm = torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            if not bool(torch.isfinite(norm)):
                raise FloatingPointError(f"nonfinite gradient norm at optimizer step {step}")
            optimizer.step()
            record["training_steps_completed"] = step+1
            if any(not bool(torch.isfinite(p).all()) for p in model.parameters()):
                raise FloatingPointError(f"nonfinite updated parameter at optimizer step {step}")
            losses.append(float(loss.detach()))
            if (step+1) % val_interval == 0 or step+1 == config["train_steps"]:
                model.eval()
                validation = evaluate_mse(val_x, val_y)
                if not math.isfinite(validation):
                    raise FloatingPointError("nonfinite validation loss")
                if validation < best_val:
                    best_val = validation
                    best_state = {k: v.detach().clone() for k, v in model.state_dict().items()}
                model.train()
        sync()
        elapsed = time.perf_counter()-start
        stage, record["training_status"] = "evaluation", "completed"
        record["energy"] = close_energy_interval(meter, torch, device, started=energy_started)
        meter = None
        if not record["energy"]["interval_complete"]:
            raise RuntimeError("CUDA training energy interval did not synchronize completely")
        record.update(training_memory_peak(torch, device, reset_completed=peak_reset))
        record["peak_gpu_interval_complete"] = (
            record["peak_gpu_measurement_status"] == "measured" if device.type == "cuda" else None)
        peak_captured = True
        record["training_wall_seconds_including_validation"] = elapsed
        record["training_examples_seen"] = config["train_steps"]*config["batch_size"]
        record["training_tokens_seen"] = record["training_examples_seen"]*config["length"]
        record["training_examples_per_second"] = record["training_examples_seen"]/elapsed
        if checkpoint_path is not None:
            checkpoint_path = Path(checkpoint_path)
            temporary = checkpoint_path.with_suffix(".tmp")
            torch.save({"state_dict": best_state, "best_validation_mse": best_val,
                        "config": config, "task": task, "model": name, "seed": seed,
                        "training_steps_completed": len(losses)}, temporary)
            os.replace(temporary, checkpoint_path)
            record["best_checkpoint"] = str(checkpoint_path)
            record["best_checkpoint_sha256"] = hashlib.sha256(checkpoint_path.read_bytes()).hexdigest()
        model.load_state_dict(best_state)
        model.eval()
        with torch.no_grad():
            record["test_mse"] = evaluate_mse(test_x, test_y)
            if not math.isfinite(record["test_mse"]):
                raise FloatingPointError("nonfinite held-out test loss")
            batch = test_x[:config["batch_size"]]
            for _ in range(2):
                model(batch)
            sync()
            latencies = []
            for _ in range(config["latency_repeats"]):
                start = time.perf_counter()
                model(batch)
                sync()
                latencies.append(time.perf_counter()-start)
        record.update(status="completed", best_validation_mse=best_val,
                      initial_training_mse=losses[0], final_training_mse=losses[-1],
                      inference_batch_size=len(batch), inference_examples_per_second=len(batch)/statistics.mean(latencies),
                      latency_p50_ms=float(np.percentile(latencies, 50)*1000),
                      latency_p95_ms=float(np.percentile(latencies, 95)*1000))
    except UnavailableBaseline as exc:
        record.update(status="unavailable", reason=str(exc))
    except Exception as exc:
        record.update(status="failed", failure_stage=stage, reason=f"{type(exc).__name__}: {exc}")
        if record["training_status"] == "running":
            record["training_status"] = "failed"
    finally:
        if meter is not None:
            record["energy"] = close_energy_interval(meter, torch, device, started=energy_started)
            record["terminal_cuda_synchronized"] = record["energy"]["terminal_cuda_synchronized"]
            record["terminal_cuda_sync_error"] = record["energy"]["terminal_cuda_sync_error"]
        elif device.type == "cuda":
            try:
                torch.cuda.synchronize(device)
                record["terminal_cuda_synchronized"] = True
            except Exception as exc:
                record["terminal_cuda_synchronized"] = False
                record["terminal_cuda_sync_error"] = f"{type(exc).__name__}: {exc}"
                if record["status"] == "completed":
                    record.update(status="failed", failure_stage="terminal_synchronization",
                                  reason=record["terminal_cuda_sync_error"])
        if not peak_captured:
            record.update(training_memory_peak(torch, device, reset_completed=peak_reset))
            record["peak_gpu_interval_complete"] = False if device.type == "cuda" else None
    return record


def run(config, checkpoint_dir=None):
    validate_config(config)
    root = Path(__file__).parent
    source = hashlib.sha256()
    source_files = attempts.source_snapshot(root)
    for path in sorted(root.rglob("*.py")):
        source.update(str(path.relative_to(root)).encode()+b"\0"+path.read_bytes())
    cpu_name = platform.processor()
    if not cpu_name and Path("/proc/cpuinfo").exists():
        cpu_name = next((line.partition(":")[2].strip() for line in Path("/proc/cpuinfo").read_text().splitlines()
                         if line.startswith("model name")), "unknown CPU")
    report = {"schema_version": 2, "purpose": "synthetic research qualification", "config": config,
              "execution_policy": execution_policy(config),
              "source_sha256": source.hexdigest(), "source_files_sha256": source_files, "hardware": {"platform": platform.platform(),
              "machine": platform.machine(), "cpu_model": cpu_name, "logical_cpu_count": os.cpu_count(),
              "python": sys.version.split()[0], "numpy": np.__version__},
              "protocol": {"data_budget": "same steps, batch size, length and splits for every model",
              "data_seed": config.get("data_seed", 271828), "selection": "validation only; one held-out test evaluation",
              "parameter_matching": "same hidden width; actual parameter counts reported, not parameter matched",
              "latency": "batch forward; two warmups; synchronize CUDA after each measurement",
              "quality_scope": "synthetic tasks only; smoke scores do not establish learning superiority",
              "optimization": "PyTorch eager; Transformer uses native SDPA dispatch",
              "energy": "physical counters only; null when inaccessible; no TDP estimate"}, "runs": [], "datasets": {}}
    try:
        import torch
    except ImportError:
        for task in config["tasks"]:
            for name in config["models"]:
                for seed in config["seeds"]:
                    report["runs"].append({"task": task, "model": name, "seed": seed,
                                           "implementation": None, "execution_policy": report["execution_policy"],
                                           "status": "unavailable", "reason": "PyTorch is not installed"})
        report.update(status="unavailable", summary=aggregate(report["runs"]))
        return report
    device = torch.device(config.get("device", "cpu"))
    cuda_execution = configure_cuda(torch, device, config.get("cuda_memory_fraction"))
    cuda_unavailable_reason = cuda_execution["setup_error"]
    torch.set_num_threads(config["cpu_threads"])
    torch.use_deterministic_algorithms(True, warn_only=True)
    report["software"] = {}
    for package in ("numpy", "scipy", "torch", "ncps", "mamba-ssm", "triton", "causal-conv1d", "nvidia-ml-py"):
        try:
            report["software"][package] = metadata.version(package)
        except metadata.PackageNotFoundError:
            report["software"][package] = None
    report["hardware"].update(torch=torch.__version__, device=str(device),
                              device_name=(cuda_execution["name"] or "unavailable CUDA device")
                              if device.type == "cuda" else cpu_name,
                              cuda_execution=cuda_execution,
                              cpu_threads=torch.get_num_threads(), deterministic_requested=True)
    report["hardware"].update(cuda_runtime=torch.version.cuda, cuda_available=torch.cuda.is_available())
    for task in config["tasks"]:
        splits = []
        for offset, key in enumerate(("train_count", "validation_count", "test_count")):
            splits.extend(make_dataset(task, config[key], config["length"], config.get("data_seed", 271828)+offset))
        report["datasets"][task] = {"split_sha256": [hashlib.sha256(a.tobytes()+b.tobytes()).hexdigest()
                                                    for a, b in zip(splits[::2], splits[1::2])],
                                      "constant_predictor_test_mse": float(np.mean((splits[5]-np.mean(splits[1]))**2))}
        for name in config["models"]:
            for seed in config["seeds"]:
                key = receipt_key(report, task, name, seed)
                saved = None
                prior_attempts = []
                if checkpoint_dir is not None:
                    directory = Path(checkpoint_dir)
                    directory.mkdir(parents=True, exist_ok=True)
                    saved = directory/(key+".json")
                    prior_attempts = attempts.history(directory, key)
                result = None
                if attempts.source_snapshot(root) != source_files:
                    raise RuntimeError("source changed before attempt; no cache published")
                if saved is not None and saved.exists():
                    prior = json.loads(saved.read_text())
                    candidate = prior["result"]
                    if prior["key"] != key:
                        raise ValueError("checkpoint provenance mismatch")
                    terminal = next((a for a in prior_attempts if a['attempt_id'] == prior['attempt_id']), None)
                    if terminal is None or terminal['result'] != candidate:
                        raise ValueError("cache has no matching immutable attempt receipt")
                    if candidate["status"] == "completed":
                        weights = attempts.resolve_weights(directory, candidate)
                        if (not weights.exists() or hashlib.sha256(weights.read_bytes()).hexdigest()
                                != candidate.get("best_checkpoint_sha256")):
                            raise ValueError("missing or corrupted best validation checkpoint")
                        result = candidate.copy()
                        result['best_checkpoint'] = str(weights)
                        prior['verified_weights'] = str(weights)
                        atomic_json(saved, prior)
                if result is None:
                    def operation(weights):
                        if cuda_unavailable_reason:
                            return dict(task=task, model=name, seed=seed, status="unavailable",
                                        training_status="not_started", training_examples_seen=0,
                                        training_tokens_seen=0, training_steps_completed=0,
                                        energy={"joules_by_physical_counter": None,
                                                "interval_complete": False, "interval_completion": "not_started",
                                                "missing_reason": "CUDA execution setup unavailable; training not started"},
                                        implementation=None,
                                        execution_policy=report["execution_policy"],
                                        reason=cuda_unavailable_reason)
                        return _run_one(config, task, name, seed, splits, device, torch, weights)
                    provenance = dict(key=key, source_sha256=report["source_sha256"],
                                      config=config, dataset=report["datasets"][task],
                                      hardware=report["hardware"], software=report["software"],
                                      task=task, model=name, seed=seed)
                    if saved is not None:
                        result, attempt_id = attempts.execute(
                            directory, key, provenance, operation,
                            lambda: attempts.source_snapshot(root) == source_files, atomic_json)
                        # Only source-verified outcomes enter this replaceable index.
                        # Terminal attempts and their weights are never overwritten.
                        atomic_json(saved, dict(provenance, attempt_id=attempt_id, result=result))
                        prior_attempts = attempts.history(directory, key)
                    else:
                        result = operation(None)
                        if attempts.source_snapshot(root) != source_files:
                            raise RuntimeError("source changed during benchmark; no receipt published")
                        prior_attempts = [dict(provenance, result=result.copy())]
                if saved is not None and result.get('best_checkpoint_relative'):
                    result = dict(result, best_checkpoint=str(attempts.resolve_weights(directory, result)))
                result = dict(result, attempts=prior_attempts,
                              attempt_accounting=attempts.accounting(prior_attempts))
                report["runs"].append(result)
                print(f"{task} {name} seed={seed}: {result['status']}", file=sys.stderr, flush=True)
    expected = {(t, m, s) for t in config["tasks"] for m in config["models"] for s in config["seeds"]}
    observed = [(r["task"], r["model"], r["seed"]) for r in report["runs"]]
    if len(observed) != len(expected) or set(observed) != expected:
        raise ValueError("run matrix has missing or duplicate combinations")
    report["accounting"] = dict(requested=len(expected), unique_records=len(set(observed)),
                               completed=sum(r["status"] == "completed" for r in report["runs"]),
                               failed=sum(r["status"] == "failed" for r in report["runs"]),
                               unavailable=sum(r["status"] == "unavailable" for r in report["runs"]))
    report["attempt_accounting"] = attempts.accounting([a for r in report["runs"] for a in r["attempts"]])
    report["summary"] = aggregate(report["runs"])
    statuses = {r["status"] for r in report["runs"]}
    report["status"] = "completed" if statuses == {"completed"} else "partial"
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    config = json.loads(args.config.read_text())
    report = run(config, args.output.with_suffix(".runs"))
    report["command"] = shlex.join([sys.executable, "-m", "qualification.hcsn.benchmark", *sys.argv[1:]])
    args.output.parent.mkdir(parents=True, exist_ok=True)
    atomic_json(args.output, report)
    print(json.dumps({"output": str(args.output), "status": report["status"],
                      "runs": len(report["runs"])}, indent=2))
    if any(r["status"] == "failed" for r in report["runs"]):
        return 1
    return 0 if any(r["status"] == "completed" for r in report["runs"]) else 2


if __name__ == "__main__":
    raise SystemExit(main())
