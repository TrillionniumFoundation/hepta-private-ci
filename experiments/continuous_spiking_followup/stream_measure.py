"""Serial CPU measurement of the same checkpoint as batch and actual stream.

Fixed tolerance: rtol=3e-5, atol=3e-6. Numerical or class disagreements are
retained as failed parity, never hidden by changing the tolerance after scores.
"""

import argparse
import json
from pathlib import Path
import time
import traceback

import numpy as np
import torch

from experiments.continuous_spiking_network import records
from experiments.continuous_spiking_network.data import load_data
from experiments.continuous_spiking_network.models import SequenceClassifier
from experiments.continuous_spiking_network.performance import (
    _canonical_hash,
    _tensor_hash,
    _quantiles,
)

from .budget_io import load_arrays, source_arrays, write_arrays
from .streaming import StreamingClassifier, model_digest


RTOL, ATOL = 3e-5, 3e-6


def _cost(cpu, wall):
    return {
        "cpu_seconds": time.process_time() - cpu,
        "wall_seconds": time.perf_counter() - wall,
    }


def _load_run(run, cache_dir, batch_size):
    raw_result = (run / "RESULT.json").read_bytes()
    result = json.loads(raw_result)
    spec = result["spec"]
    relative = Path(result["selected_checkpoint"])
    if (
        relative.is_absolute()
        or ".." in relative.parts
        or result["selection"]["selected_checkpoint"] != str(relative)
    ):
        raise ValueError("invalid or inconsistent selected checkpoint path")
    checkpoint = run / relative
    selected = result["candidates"][result["selection"]["candidate_index"]]
    manifest_raw = (checkpoint / "manifest.json").read_bytes()
    if records.digest_bytes(manifest_raw) != selected["checkpoint_manifest_sha256"]:
        raise ValueError("selected checkpoint manifest hash mismatch")
    manifest = json.loads(manifest_raw)
    for key in ("architecture", "width", "seed"):
        if manifest["config"][key] != spec[key]:
            raise ValueError(f"checkpoint/specification mismatch: {key}")
    if manifest["config"]["depth"] != spec.get("depth", 1) or manifest["config"][
        "match_cell_budget"
    ] != spec.get("match_cell_budget", False):
        raise ValueError("checkpoint/specification depth or matching mismatch")
    seals = {}
    for name, package in (
        ("base", Path(records.__file__).parent),
        ("followup", Path(__file__).parent),
    ):
        expected = result["source_seals"][name]
        seals[name] = (
            expected
            if expected == "unsealed-development"
            else records.source_seal(package)
        )
        if seals[name] != expected:
            raise ValueError("saved scientific source seal differs from current source")
    cpu, wall = time.process_time(), time.perf_counter()
    model = SequenceClassifier(**manifest["config"])
    loaded = records.checkpoint_load(model, checkpoint)
    if (
        loaded != manifest
        or (checkpoint / "manifest.json").read_bytes() != manifest_raw
    ):
        raise ValueError("checkpoint identity changed while loading")
    for row in manifest["tensors"]:
        value = model.state_dict()[row["name"]].detach().cpu().numpy()
        if (
            value.dtype.str != row["dtype"]
            or records.digest_bytes(value.tobytes()) != row["sha256"]
        ):
            raise ValueError("strict checkpoint reload altered tensor bytes or dtype")
    model.eval()
    reload_cost = _cost(cpu, wall)
    cpu, wall = time.process_time(), time.perf_counter()
    saved_data = json.loads((run / "DATA.json").read_text())
    bundle = load_data(
        spec["task"],
        train_size=spec["train_size"],
        val_size=spec.get("val_size", 256),
        test_size=spec.get("test_size", 512),
        context_length=spec["length"],
        seed=spec["data_seed"],
        cache_dir=cache_dir,
    )
    if _canonical_hash(saved_data) != _canonical_hash(bundle.manifest):
        raise ValueError("reconstructed data/source manifest differs from training")
    for folder, key in (
        ("sources", "sources_manifest_sha256"),
        ("predictions", "predictions_manifest_sha256"),
    ):
        if (
            records.digest_bytes((run / folder / "manifest.json").read_bytes())
            != result[key]
        ):
            raise ValueError(f"saved {folder} manifest hash mismatch")
    saved_sources, rebuilt_sources = load_arrays(run / "sources"), source_arrays(bundle)
    if set(saved_sources) != set(rebuilt_sources) or any(
        not np.array_equal(saved_sources[k], v) for k, v in rebuilt_sources.items()
    ):
        raise ValueError("reconstructed episode/source identities changed")
    predictions = load_arrays(run / "predictions")
    if not np.array_equal(
        predictions["sample_ids"], bundle.test.sample_ids
    ) or not np.array_equal(predictions["labels"], bundle.test.y):
        raise ValueError("saved prediction source/label identity mismatch")
    if (bundle.input_dim, bundle.num_classes) != (
        model.config["input_dim"],
        model.config["classes"],
    ):
        raise ValueError("model and dataset dimensions differ")
    batch = min(batch_size, len(bundle.test))
    x = torch.from_numpy(bundle.test.x[:batch]).contiguous()
    dt = torch.from_numpy(bundle.test.dt[:batch]).contiguous()
    data_cost = _cost(cpu, wall)
    identity = {
        "run_result_sha256": records.digest_bytes(raw_result),
        "checkpoint_manifest_sha256": records.digest_bytes(manifest_raw),
        "data_manifest_sha256": _canonical_hash(saved_data),
        "source_seals": seals,
        "sources_manifest_sha256": result["sources_manifest_sha256"],
        "predictions_manifest_sha256": result["predictions_manifest_sha256"],
        "selected_checkpoint": str(relative),
        "spec": spec,
    }
    return (
        model,
        checkpoint,
        x,
        dt,
        bundle.test,
        predictions,
        identity,
        {"reload": reload_cost, "data": data_cost},
    )


def _sample_modes(model, x, dt, repeats):
    cpu, wall = time.process_time(), time.perf_counter()
    stream = StreamingClassifier(model)
    construction = _cost(cpu, wall)
    cpu, wall = time.process_time(), time.perf_counter()
    identity = model_digest(model)
    hash_probe = _cost(cpu, wall)
    samples, references, repeated_error = [], {}, {"batch": 0.0, "stream": 0.0}
    with torch.inference_mode():
        for phase, count in (("warmup", 2), ("measurement", repeats)):
            for repeat in range(count):
                order = ("batch", "stream") if repeat % 2 == 0 else ("stream", "batch")
                for mode in order:
                    sequence_cpu, sequence_wall = (
                        time.process_time(),
                        time.perf_counter(),
                    )
                    reset = None
                    if mode == "stream":
                        cpu, wall = time.process_time(), time.perf_counter()
                        stream.reset(x.shape[0])
                        reset = _cost(cpu, wall)
                    cpu, wall = time.process_time(), time.perf_counter()
                    if mode == "batch":
                        logits, aux = model(x, dt)
                    else:
                        for index in range(x.shape[1]):
                            logits, aux = stream.step(x[:, index], dt[:, index])
                    forward = _cost(cpu, wall)
                    request_cost = _cost(sequence_cpu, sequence_wall)
                    # Comparisons, cloning and releasing outputs follow both timers.
                    if mode in references:
                        repeated_error[mode] = max(
                            repeated_error[mode],
                            float((logits - references[mode]).abs().max()),
                        )
                    else:
                        references[mode] = logits.clone()
                    samples.append(
                        {
                            "phase": phase,
                            "repeat": repeat,
                            "mode": mode,
                            "forward": forward,
                            "reset_with_identity_check": reset,
                            "reset_plus_forward_interval": request_cost,
                        }
                    )
                    del logits, aux
    summaries = {}
    for mode in ("batch", "stream"):
        rows = [
            row
            for row in samples
            if row["phase"] == "measurement" and row["mode"] == mode
        ]
        wall_values = [row["forward"]["wall_seconds"] for row in rows]
        cpu_values = [row["forward"]["cpu_seconds"] for row in rows]
        summaries[mode] = {
            "wall_seconds": wall_values,
            "process_cpu_seconds": cpu_values,
            "wall_latency_seconds": _quantiles(wall_values),
            "process_cpu_seconds_stats": _quantiles(cpu_values),
            "examples_per_second": _quantiles(
                [x.shape[0] / value for value in wall_values]
            ),
            "reset_plus_forward_wall_seconds": [
                row["reset_plus_forward_interval"]["wall_seconds"] for row in rows
            ],
            "repeat_output_max_abs_difference": repeated_error[mode],
        }
    return (
        samples,
        summaries,
        {
            "stream_construction": construction,
            "standalone_model_hash_probe": hash_probe,
        },
        identity,
    )


def _verify_prefixes(model, x, dt, saved_logits, output, sample_ids, labels):
    cpu, wall = time.process_time(), time.perf_counter()
    with torch.inference_mode():
        full, _ = model(x, dt, return_sequence=True)
        stream = StreamingClassifier(model).reset(x.shape[0])
        state_bytes, outputs = [stream.state_bytes], []
        for index in range(x.shape[1]):
            logits, _ = stream.step(x[:, index], dt[:, index])
            outputs.append(logits)
            state_bytes.append(stream.state_bytes)
        incremental = torch.stack(outputs, dim=1)
    close = torch.isclose(incremental, full, rtol=RTOL, atol=ATOL)
    changed = incremental.argmax(-1) != full.argmax(-1)
    archive_sha = write_arrays(
        output / "parity_arrays",
        {
            "full_sequence_prefix_logits": full.numpy(),
            "incremental_prefix_logits": incremental.numpy(),
            "sample_ids": np.asarray(sample_ids),
            "labels": np.asarray(labels),
        },
    )
    saved = torch.from_numpy(saved_logits)
    saved_close = bool(torch.allclose(full[:, -1], saved, rtol=RTOL, atol=ATOL))
    result = {
        "rtol": RTOL,
        "atol": ATOL,
        "all_prefixes_within_tolerance": bool(close.all()),
        "tensor_entries_outside_tolerance": int((~close).sum()),
        "max_abs_logit_error": float((incremental - full).abs().max()),
        "final_max_abs_logit_error": float(
            (incremental[:, -1] - full[:, -1]).abs().max()
        ),
        "prefix_predicted_class_changes": int(changed.sum()),
        "final_predicted_class_changes": int(changed[:, -1].sum()),
        "saved_training_predictions_within_tolerance": saved_close,
        "saved_training_prediction_max_abs_error": float(
            (full[:, -1] - saved).abs().max()
        ),
        "state_payload_bytes_initial_and_after_each_step": state_bytes,
        "final_state_payload_bytes": stream.state_bytes,
        "processed_rows": stream.processed_rows,
        "steps": stream.steps,
        "arrays_manifest_sha256": archive_sha,
        "passed": bool(close.all()) and not bool(changed.any()) and saved_close,
        "cost": _cost(cpu, wall),
    }
    return result


def measure_run(
    run_directory, cache_dir, output, batch_size=16, repeats=7, cross_process=False
):
    """Measure a fresh output directory; preserve failed or discrepant evidence."""
    if (
        type(batch_size) is not int
        or batch_size < 1
        or type(repeats) is not int
        or repeats < 1
    ):
        raise ValueError("batch_size and repeats must be positive integers")
    run, output = Path(run_directory).resolve(), Path(output)
    output.mkdir(parents=True, exist_ok=False)
    cpu_start, wall_start = time.process_time(), time.perf_counter()
    torch.set_num_threads(1)
    try:
        model, checkpoint, x, dt, test, predictions, identity, costs = _load_run(
            run, cache_dir, batch_size
        )
        if x.device.type != "cpu" or x.dtype != torch.float32:
            raise ValueError("this measurement contract requires CPU float32")
        samples, summaries, setup, digest = _sample_modes(model, x, dt, repeats)
        batch = x.shape[0]
        parity = _verify_prefixes(
            model,
            x,
            dt,
            predictions["logits"][:batch],
            output,
            test.sample_ids[:batch],
            test.y[:batch],
        )
        replay = {
            "status": "not_selected",
            "reason": "cross-process cases are preselected, not score-dependent",
        }
        if cross_process:
            from .stream_replay import replay_in_subprocess

            replay = replay_in_subprocess(
                model, checkpoint, x, dt, output / "cold_replay"
            )
        for name, package in (
            ("base", Path(records.__file__).parent),
            ("followup", Path(__file__).parent),
        ):
            if (
                identity["source_seals"][name] != "unsealed-development"
                and records.source_seal(package) != identity["source_seals"][name]
            ):
                raise ValueError("scientific source changed during measurement")
        result = {
            "schema": "hcsn-batch-stream-measurement-v1",
            "run_directory": str(run),
            "identity": identity,
            "model_sha256": digest,
            "strict_reload": True,
            "fixed_batch": {
                "selection": "first test episodes in saved dataset order",
                "requested_batch_size": batch_size,
                "batch_size": batch,
                "sequence_length": x.shape[1],
                "feature_width": x.shape[2],
                "sample_ids": test.sample_ids[:batch].tolist(),
                "x_sha256": _tensor_hash(x),
                "dt_sha256": _tensor_hash(dt),
            },
            "warmup_repetitions_per_mode": 2,
            "measurement_repetitions_per_mode": repeats,
            "raw_samples": samples,
            "measurement": summaries,
            "setup_costs": setup,
            "preparation_costs": costs,
            "parity": parity,
            "cross_process_replay": replay,
            "environment": records.environment(),
            "timing_scope": "batch: complete final-logit model forward including auxiliary creation; stream: all one-token forwards including input checks, Python iteration and per-step auxiliary creation. Reset/model hash, warmup, state tracing, output comparison, replay and serialization excluded from forward timers and separately recorded; reset-plus-forward intervals also retained.",
            "memory_scope": "persistent tensor payload only, excluding weights, Python metadata and transient work; not RSS, peak allocation or energy",
            "quantile_scope": "descriptive repeats on shared CPU host, not confidence intervals",
            "execution_policy": "invoke serially after all training; no host exclusivity inferred",
            "total_parent_cpu_seconds": time.process_time() - cpu_start,
            "total_wall_seconds": time.perf_counter() - wall_start,
            "accounting": "nested phases are included in totals; child CPU is separate; timers exclude imports and final MEASUREMENT write",
        }
        records.write_json(output / "MEASUREMENT.json", result)
        return result
    except Exception:
        records.write_json(
            output / "FAILED.json",
            {"traceback": traceback.format_exc(), "time": time.time()},
        )
        raise


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--run", required=True)
    parser.add_argument("--cache-dir", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--batch-size", type=int, default=16)
    parser.add_argument("--repeats", type=int, default=7)
    parser.add_argument("--cross-process", action="store_true")
    args = parser.parse_args()
    torch.set_num_interop_threads(1)
    result = measure_run(
        args.run,
        args.cache_dir,
        args.output,
        args.batch_size,
        args.repeats,
        args.cross_process,
    )
    print(
        json.dumps(
            {
                "output": args.output,
                "parity_passed": result["parity"]["passed"],
                "cross_process": result["cross_process_replay"]["status"],
            }
        ),
        flush=True,
    )
