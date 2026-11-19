"""Serial, checkpoint-based CPU inference measurements and operator audits.

Run this only after parallel training has finished. Profiler runs, checkpoint
reload, data preparation, validation and warmup are outside latency samples.
FLOP counts cover profiler-supported formulas, not all arithmetic operations.
"""

import gzip
import json
from pathlib import Path
import tempfile
import time

import numpy as np
import torch

from .data import load_data
from .models import SequenceClassifier
from .records import checkpoint_load, digest_bytes, environment, source_seal


def _canonical_hash(value):
    return digest_bytes(
        json.dumps(
            value, sort_keys=True, separators=(",", ":"), allow_nan=False
        ).encode()
    )


def _tensor_hash(tensor):
    array = tensor.detach().cpu().contiguous().numpy()
    header = json.dumps(
        {"shape": list(array.shape), "dtype": array.dtype.str}, sort_keys=True
    ).encode()
    return digest_bytes(header + array.tobytes())


def _audit_run_spec(run_dir, recorded_data, task):
    if recorded_data.get("task") != task:
        raise ValueError("requested task differs from the saved DATA.json task")
    record_path = run_dir / "RESULT.json"
    if not record_path.exists():
        record_path = run_dir / "START.json"
    if not record_path.exists():
        return {"status": "no run record; checkpoint and DATA.json still verified"}
    record = json.loads(record_path.read_text())
    spec = record.get("spec", {})
    expected = {
        "task": spec.get("task"),
        "seed": spec.get("data_seed", 7123),
        "context_length": spec.get("length"),
        "sizes": {
            "train": spec.get("train_size"),
            "val": spec.get("val_size", 512),
            "test": spec.get("test_size", 1024),
        },
    }
    actual = {key: recorded_data.get(key) for key in expected}
    if expected != actual:
        raise ValueError("saved run specification disagrees with DATA.json")
    seal = record.get("source_seal")
    if seal and seal != "unsealed-development":
        current = source_seal(Path(__file__).parent)
        if current != seal:
            raise ValueError("checkpoint run source seal differs from current source")
    return {
        "status": "verified",
        "record": record_path.name,
        "source_seal": seal or "not recorded",
    }


def _quantiles(values):
    return {
        "median": float(np.median(values)),
        "p95": float(np.quantile(values, 0.95)),
        "p05": float(np.quantile(values, 0.05)),
        "min": float(np.min(values)),
        "max": float(np.max(values)),
        "sum": float(np.sum(values)),
    }


def _run_forward_samples(model, x, dt, count):
    wall, cpu, reference = [], [], None
    max_difference = 0.0
    with torch.no_grad():
        for _ in range(count):
            start_cpu, start_wall = time.process_time(), time.perf_counter()
            logits, aux = model(x, dt)
            wall.append(time.perf_counter() - start_wall)
            cpu.append(time.process_time() - start_cpu)
            # Validation, copying and output release are deliberately outside timing.
            if not torch.isfinite(logits).all():
                raise FloatingPointError(
                    "profiled checkpoint produced nonfinite logits"
                )
            if reference is None:
                reference = logits.detach().clone()
            else:
                max_difference = max(
                    max_difference, float((logits - reference).abs().max())
                )
            del logits, aux
    return wall, cpu, reference, max_difference


def _allocation_timeline(trace):
    """Read profiler-managed allocation events, including unknown categories.

    CPU tensor allocations are not process RSS, allocator reserved memory or
    hardware energy. Under no_grad, many tensors have category UNKNOWN.
    """
    try:
        from torch.profiler._memory_profiler import _ACTION_TO_INDEX, _CATEGORY_TO_INDEX

        actions = {value: key.name for key, value in _ACTION_TO_INDEX.items()}
        categories = {
            value: key.name if key is not None else "UNKNOWN"
            for key, value in _CATEGORY_TO_INDEX.items()
        }
        with tempfile.TemporaryDirectory(prefix="hcsn-profile-") as temporary:
            path = Path(temporary) / "memory.raw.json.gz"
            trace.export_memory_timeline(str(path), device="cpu")
            with gzip.open(path, "rt") as handle:
                events = json.load(handle)
        created = {name: 0 for name in categories.values()}
        preexisting = sum(
            int(size)
            for _, action, size, _ in events
            if actions[action] == "PREEXISTING"
        )
        live, peak, released = 0, 0, 0
        for _, action, size, category in events:
            action_name = actions[action]
            if action_name == "CREATE":
                created[categories[category]] += int(size)
            elif action_name == "DESTROY":
                released += abs(int(size))
            # INCREMENT_VERSION consists of equal negative/positive transfers.
            live += int(size)
            peak = max(peak, live)
        return {
            "status": "available",
            "events": len(events),
            "forward_created_bytes": sum(created.values()),
            "created_bytes_by_category": created,
            "activation_labelled_created_bytes": created.get("ACTIVATION", 0),
            "unclassified_created_bytes": created.get("UNKNOWN", 0),
            "released_bytes": released,
            "preexisting_managed_bytes": preexisting,
            "peak_managed_bytes": peak,
            "peak_increment_over_preexisting_bytes": max(0, peak - preexisting),
            "scope": "PyTorch CPU tensor allocation timeline; not RSS or allocator-reserved memory",
            "classification_limit": "No-grad intermediates may be UNKNOWN; activation-labelled bytes are not all activations",
        }
    except Exception as error:
        return {
            "status": "unavailable",
            "error": f"{type(error).__name__}: {error}",
            "scope": "No activation/RSS estimate substituted for unavailable allocation data",
        }


def _operator_audit(model, x, dt):
    start_cpu, start_wall = time.process_time(), time.perf_counter()
    try:
        with (
            torch.no_grad(),
            torch.profiler.profile(
                activities=[torch.profiler.ProfilerActivity.CPU],
                with_flops=True,
                record_shapes=True,
                profile_memory=True,
                with_stack=True,
            ) as trace,
        ):
            logits, aux = model(x, dt)
        del logits, aux
        events = trace.key_averages(group_by_input_shape=True)
        supported, unsupported, attention = [], set(), set()
        for event in events:
            if event.flops and event.flops > 0:
                supported.append(
                    {
                        "operator": event.key,
                        "calls": int(event.count),
                        "formula_flops": int(event.flops),
                        "input_shapes": event.input_shapes,
                    }
                )
            elif event.key.startswith("aten::"):
                unsupported.add(event.key)
            if "scaled_dot_product" in event.key or "flash_attention" in event.key:
                attention.add(event.key)
        memory = _allocation_timeline(trace)
        result = {
            "status": "available",
            "forward_calls": 1,
            "observed_formula_flops": sum(item["formula_flops"] for item in supported),
            "flop_scope": "Profiler shape-based formulas for supported operators only; not total model FLOPs",
            "supported_operator_formulas": supported,
            "unsupported_ops": sorted(unsupported),
            "unsupported_scope": "Operators without assigned FLOPs, including special/fused functions and bookkeeping",
            "attention_operators": sorted(attention),
            "memory": memory,
        }
    except Exception as error:
        result = {
            "status": "unavailable",
            "error": f"{type(error).__name__}: {error}",
            "forward_calls": None,
            "observed_formula_flops": None,
            "unsupported_ops": ["profiling unavailable: no complete FLOP estimate"],
            "attention_operators": [],
            "memory": {"status": "unavailable"},
        }
    result["cpu_seconds"] = time.process_time() - start_cpu
    result["wall_seconds"] = time.perf_counter() - start_wall
    return result


def profile_checkpoint(checkpoint_dir, task, cache_dir, batch_size=16, repeats=5):
    """Strictly reload a checkpoint and measure one fixed held-out test batch.

    DATA.json must be beside the checkpoint directory, as written by train.fit.
    Loading does not download or train. Existing RESULT/START and source seals
    are verified when present. The caller must serialize this function after
    training jobs terminate; process_cpu and wall clocks do not prove isolation.
    """
    if (
        not isinstance(batch_size, int)
        or batch_size < 1
        or not isinstance(repeats, int)
        or repeats < 1
    ):
        raise ValueError("batch_size and repeats must be positive integers")
    total_cpu, total_wall = time.process_time(), time.perf_counter()
    checkpoint_dir = Path(checkpoint_dir)
    manifest_path = checkpoint_dir / "manifest.json"
    manifest_bytes = manifest_path.read_bytes()
    manifest = json.loads(manifest_bytes)
    run_dir = checkpoint_dir.parent
    recorded_data = json.loads((run_dir / "DATA.json").read_text())
    source_audit = _audit_run_spec(run_dir, recorded_data, task)

    start_cpu, start_wall = time.process_time(), time.perf_counter()
    model = SequenceClassifier(**manifest["config"])
    loaded = checkpoint_load(model, checkpoint_dir)
    if loaded != manifest or manifest_path.read_bytes() != manifest_bytes:
        raise ValueError("checkpoint manifest changed during reload")
    if model.config != manifest["config"]:
        raise ValueError("constructed model configuration differs from checkpoint")
    target_state = model.state_dict()
    for item in manifest["tensors"]:
        actual = target_state[item["name"]].detach().cpu().contiguous().numpy()
        if (
            actual.dtype.str != item["dtype"]
            or digest_bytes(actual.tobytes()) != item["sha256"]
        ):
            raise ValueError(
                "strict checkpoint reload changed a state dtype or tensor value"
            )
    model.eval()
    reload_work = {
        "cpu_seconds": time.process_time() - start_cpu,
        "wall_seconds": time.perf_counter() - start_wall,
    }

    start_cpu, start_wall = time.process_time(), time.perf_counter()
    sizes = recorded_data["sizes"]
    bundle = load_data(
        task,
        train_size=sizes["train"],
        val_size=sizes["val"],
        test_size=sizes["test"],
        context_length=recorded_data["context_length"],
        seed=recorded_data["seed"],
        cache_dir=cache_dir,
    )
    if _canonical_hash(bundle.manifest) != _canonical_hash(recorded_data):
        raise ValueError(
            "reloaded data/source manifest differs from the training data manifest"
        )
    if (
        bundle.input_dim != model.config["input_dim"]
        or bundle.num_classes != model.config["classes"]
    ):
        raise ValueError("checkpoint input/classes disagree with the saved dataset")
    actual_batch = min(batch_size, len(bundle.test))
    x = torch.from_numpy(bundle.test.x[:actual_batch]).contiguous()
    dt = torch.from_numpy(bundle.test.dt[:actual_batch]).contiguous()
    sample_ids = bundle.test.sample_ids[:actual_batch].tolist()
    batch_hash = _canonical_hash(
        {"x": _tensor_hash(x), "dt": _tensor_hash(dt), "sample_ids": sample_ids}
    )
    data_work = {
        "cpu_seconds": time.process_time() - start_cpu,
        "wall_seconds": time.perf_counter() - start_wall,
    }

    warm_wall, warm_cpu, warm_logits, warm_difference = _run_forward_samples(
        model, x, dt, 2
    )
    walls, cpus, logits, repeat_difference = _run_forward_samples(model, x, dt, repeats)
    warm_repeat_difference = float((warm_logits - logits).abs().max())
    positions = actual_batch * x.shape[1]
    operator_audit = _operator_audit(model, x, dt)
    result = {
        "schema": "hcsn-performance-v1",
        "task": task,
        "config": model.config,
        "checkpoint_manifest_sha256": digest_bytes(manifest_bytes),
        "source_audit": source_audit,
        "data_manifest_sha256": _canonical_hash(recorded_data),
        "fixed_batch": {
            "selection": "first held-out test examples in saved dataset order",
            "requested_batch_size": batch_size,
            "batch_size": actual_batch,
            "sequence_length": x.shape[1],
            "feature_width": x.shape[2],
            "sample_ids": sample_ids,
            "sha256": batch_hash,
        },
        "strict_reload": True,
        "reload_work": reload_work,
        "data_work": data_work,
        "warmup": {
            "forward_calls": 2,
            "examples": 2 * actual_batch,
            "sequence_positions": 2 * positions,
            "wall_seconds": warm_wall,
            "process_cpu_seconds": warm_cpu,
            "included_in_latency_samples": False,
        },
        "measurement": {
            "forward_calls": repeats,
            "examples": repeats * actual_batch,
            "sequence_positions": repeats * positions,
            "wall_seconds": walls,
            "process_cpu_seconds": cpus,
            "wall_latency_seconds": _quantiles(walls),
            "process_cpu_seconds_stats": _quantiles(cpus),
            "examples_per_second": _quantiles(
                [actual_batch / value for value in walls]
            ),
            "sequence_positions_per_second": _quantiles(
                [positions / value for value in walls]
            ),
            "timing_scope": "full no-grad model forward including auxiliary tensor creation; excludes output release/validation, reload, data, warmup and profiler",
            "quantile_scope": "descriptive repeat quantiles, not confidence intervals; throughput p05 is the slow tail",
        },
        "logits_sha256": _tensor_hash(logits),
        "repeat_output_max_abs_difference": max(
            warm_difference, repeat_difference, warm_repeat_difference
        ),
        "parameter_bytes": sum(
            p.numel() * p.element_size() for p in model.parameters()
        ),
        "trainable_parameter_bytes": sum(
            p.numel() * p.element_size() for p in model.parameters() if p.requires_grad
        ),
        "buffer_bytes": sum(b.numel() * b.element_size() for b in model.buffers()),
        "parameter_counts": model.counts(),
        "operator_audit": operator_audit,
        "environment": environment(),
        "execution_policy": "CPU; invoke serially after training completes; no concurrency/isolation guarantee inferred from clocks",
        "total_cpu_seconds": time.process_time() - total_cpu,
        "total_wall_seconds": time.perf_counter() - total_wall,
    }
    return result
