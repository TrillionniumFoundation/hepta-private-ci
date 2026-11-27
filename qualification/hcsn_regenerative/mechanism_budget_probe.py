"""A priori runtime probe: 400 updates on independent non-task random arrays."""

import argparse
import hashlib
from pathlib import Path
import resource
import time
import traceback

import numpy as np

from .mechanism_contract import ARMS, DT, EXPECTED_PARAMETERS, RUNNER_FILES, STATE_COUNT, file_sha, read_json, utc_now, verify_sources, write_json
from .mechanism_model import DeviceEnergy, GradientAudit, environment, make_model, memory_report, synchronize
from .mechanism_worker import configure_torch, evaluate, merge_diagnostics, tensors


def run_probe(bundle, device, output):
    bundle, output = Path(bundle), Path(output)
    if output.exists():
        raise FileExistsError("Use a new runtime-probe output directory")
    output.mkdir(parents=True)
    started, cpu = time.monotonic(), time.process_time()
    directory = Path(__file__).parent
    names = list(RUNNER_FILES) + ["mechanism_qualify.py", "mechanism_budget_probe.py", "tests/test_mechanism_training.py"]
    pins = {str((directory / name).relative_to(directory.parents[1])): file_sha(directory / name) for name in names}
    result = dict(schema="hcsn-mechanism-nontask-budget-probe-v1", at=utc_now(), status="failed",
                  bundle_sha256=file_sha(bundle), bundle_metadata_sha256=file_sha(bundle.with_suffix(".json")),
                  source_pins=pins, state_count=STATE_COUNT, expected_parameter_count=EXPECTED_PARAMETERS,
                  arm="regenerative_dual", device=device, data_seed=931117, initialization_seed=931119,
                  validation_seed=931123, batch_order_seed=931127, sequence_length=64, batch_size=64,
                  updates_registered=400, optimizer_updates_completed=0, learning_rate=.003,
                  formal_training_fits=0, task_datasets_read=False, task_gain_established=False,
                  full_physical_energy_joules=None, diagnostics={},
                  purpose="Runtime/peak-memory feasibility only; independent random observations and random labels, no task reward or selection")
    energy = model = optimizer = gradients = None
    log = (output / "journal.jsonl").open("x", buffering=1)

    def journal(event):
        import json
        event.update(at=utc_now(), probe_wall_seconds=time.monotonic() - started)
        log.write(json.dumps(event, allow_nan=False) + "\n")

    def random_arrays(seed, count):
        rng = np.random.default_rng(seed)
        x = rng.uniform(-1, 1, (count, 64, 3)).astype(np.float32)
        x[..., 1] = rng.integers(0, 2, (count, 64))
        indices = rng.integers(0, 4, (count, 64), dtype=np.int64)
        x[..., 2] = np.asarray(DT, dtype=np.float32)[indices]
        return dict(x=x, dt_indices=indices, y=rng.uniform(-1, 1, (count, 1)).astype(np.float32))

    try:
        metadata = read_json(bundle.with_suffix(".json"))
        if metadata["bundle_sha256"] != result["bundle_sha256"] or metadata["state_count"] != STATE_COUNT or set(metadata["arms"]) != set(ARMS):
            raise ValueError("Exact S81 ten-arm bundle required")
        verify_sources(metadata["source_pins"])
        with np.load(bundle, allow_pickle=False) as archive:
            arrays = {name: archive[name].copy() for name in archive.files}
        for name, value in arrays.items():
            if hashlib.sha256(value.tobytes()).hexdigest() != metadata["array_sha256"][name]:
                raise ValueError("Unbound operator array")
        torch = configure_torch(device)
        result["environment"] = environment(device)
        energy = DeviceEnergy(device)
        model = make_model(arrays, "regenerative_dual", "dual", result["initialization_seed"], device)
        if sum(p.numel() for p in model.parameters()) != EXPECTED_PARAMETERS:
            raise ValueError("Incorrect state/parameter capacity")
        train_raw, validation_raw = random_arrays(931117, 2048), random_arrays(931123, 512)
        result["data_array_sha256"] = {split: {name: hashlib.sha256(value.tobytes()).hexdigest() for name, value in data.items()}
                                       for split, data in (("probe_train", train_raw), ("probe_validation", validation_raw))}
        train, validation = tensors(train_raw, torch), tensors(validation_raw, torch)
        optimizer = torch.optim.Adam(model.parameters(), lr=.003)
        gradients = GradientAudit(model)
        rng = np.random.default_rng(931127)
        remaining = np.empty(0, dtype=np.int64)
        update_durations = []
        training_started = time.monotonic()
        for step in range(1, 401):
            if time.monotonic() - started >= 480:
                raise TimeoutError("Probe exhausted the predeclared 480-second fit window")
            if len(remaining) < 64:
                remaining = np.concatenate((remaining, rng.permutation(2048)))
            index, remaining = remaining[:64], remaining[64:]
            tick = time.monotonic()
            optimizer.zero_grad(set_to_none=True)
            prediction, audit = model(train["x"][index].to(device), train["dt_indices"][index].to(device))
            loss = (prediction - train["y"][index].to(device)).square().mean()
            if not bool(torch.isfinite(loss).item()):
                raise FloatingPointError("Nonfinite non-task loss")
            loss.backward()
            gradients.observe(model)
            optimizer.step()
            synchronize(device)
            result["optimizer_updates_completed"] = step
            update_durations.append(time.monotonic() - tick)
            merge_diagnostics(result["diagnostics"], audit)
            journal(dict(event="non_task_optimizer_update_completed", update=step, examples=64))
        result["training_wall_seconds"] = time.monotonic() - training_started
        result["update_seconds"] = {key: float(value) for key, value in zip(("p50", "p95", "p99", "max"),
                                                   np.r_[np.quantile(update_durations, [.5, .95, .99]), max(update_durations)])}
        result["validation"] = evaluate(model, validation, dict(batch_size=64), device, journal, "non_task_validation", result["diagnostics"])
        checkpoint_start = time.monotonic()
        with (output / "probe-checkpoint.pt").open("xb") as stream:
            torch.save(dict(model=model.state_dict(), optimizer=optimizer.state_dict(), non_task_probe_only=True,
                            optimizer_updates_completed=400), stream)
        result["checkpoint_wall_seconds"] = time.monotonic() - checkpoint_start
        result["checkpoint_sha256"] = file_sha(output / "probe-checkpoint.pt")
        verify_sources(pins)
        result["status"] = "completed"
    except Exception as error:
        result["error"] = dict(type=type(error).__name__, message=str(error), traceback=traceback.format_exc())
    finally:
        if model is not None:
            result["memory"] = memory_report(model, optimizer)
        if gradients is not None:
            result["observed_gradients"] = gradients.report()
        result["wall_seconds"] = time.monotonic() - started
        result["process_cpu_seconds"] = time.process_time() - cpu
        result["peak_process_rss_bytes"] = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024
        result["energy"] = energy.finish() if energy else dict(device_interval_joules=None, full_physical_energy_joules=None)
        result["within_480_second_probe_window"] = result["status"] == "completed" and result["wall_seconds"] < 480
        result["formal_fit_budget_guaranteed"] = False
        result["budget_inference_scope"] = "Empirical representative dual-arm graph on this device; reserve remaining time for import, input verification, process and artifact overhead. Failures still retained."
        if str(device).startswith("cuda"):
            try:
                import torch
                result["peak_gpu_allocated_bytes"] = torch.cuda.max_memory_allocated(device)
                result["peak_gpu_reserved_bytes"] = torch.cuda.max_memory_reserved(device)
            except Exception:
                result["peak_gpu_allocated_bytes"] = None
        journal(dict(event="non_task_probe_terminal", status=result["status"]))
        log.close()
        write_json(output / "result.json", result)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle", required=True, type=Path)
    parser.add_argument("--device", required=True, choices=("cpu", "cuda"))
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    result = run_probe(args.bundle, args.device, args.output)
    print(result["status"], result["optimizer_updates_completed"], result["wall_seconds"])
    return 0 if result["status"] == "completed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
