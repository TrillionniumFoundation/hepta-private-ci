"""One bounded training or selected-evaluation process; never retries a fit."""

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import resource
import time
import traceback

import numpy as np

from .mechanism_contract import batch_order, digest, file_sha, load_contract, make_data, read_json, utc_now, validate_execution_environment, verify_sources, write_json
from .mechanism_model import DeviceEnergy, GradientAudit, benchmark, environment, make_model, memory_report, synchronize


def configure_torch(device):
    os.environ.setdefault("CUBLAS_WORKSPACE_CONFIG", ":4096:8")
    import torch
    torch.set_num_threads(1)
    torch.use_deterministic_algorithms(True)
    if str(device).startswith("cuda"):
        if not torch.cuda.is_available():
            raise RuntimeError("Requested CUDA is unavailable; no silent CPU substitution")
        torch.backends.cuda.matmul.allow_tf32 = False
        torch.backends.cudnn.allow_tf32 = False
        torch.backends.cudnn.benchmark = False
        torch.cuda.reset_peak_memory_stats(device)
    return torch


def tensors(data, torch):
    return {name: torch.from_numpy(value) for name, value in data.items()}


def merge_diagnostics(accumulator, current):
    for name in ("maximum_unconditioned_and_posterior_mass_defect", "maximum_negative_predicted_mass", "maximum_evidence"):
        accumulator[name] = max(accumulator.get(name, 0.), current[name])
    accumulator["minimum_evidence"] = min(accumulator.get("minimum_evidence", math.inf), current["minimum_evidence"])
    accumulator["mass_defect_columns"] = current["mass_defect_columns"]
    profile = current["mass_defects_by_time_step"]
    if "mass_defects_by_time_step" not in accumulator:
        accumulator["mass_defects_by_time_step"] = profile
    else:
        accumulator["mass_defects_by_time_step"] = np.maximum(accumulator["mass_defects_by_time_step"], profile).tolist()


def evaluate(model, data, plan, device, journal, phase, diagnostics):
    import torch
    squared_error, count = 0., 0
    start = time.monotonic()
    model.eval()
    with torch.inference_mode():
        for offset in range(0, len(data["x"]), plan["batch_size"]):
            sl = slice(offset, offset + plan["batch_size"])
            output, audit = model(data["x"][sl].to(device), data["dt_indices"][sl].to(device))
            loss_sum = (output - data["y"][sl].to(device)).square().sum().item()
            if not math.isfinite(loss_sum):
                raise FloatingPointError("Nonfinite evaluation loss")
            squared_error += loss_sum
            count += output.shape[0]
            merge_diagnostics(diagnostics, audit)
            journal(dict(event="evaluation_batch_completed", phase=phase, count=output.shape[0], cumulative_examples=count))
    return dict(mse=squared_error / count, squared_error_sum=squared_error, count=count,
                wall_seconds=time.monotonic() - start)


def run_job(job_path):
    job = read_json(job_path)
    output = Path(job["attempt_path"])
    started, cpu_start = time.monotonic(), time.process_time()
    terminal = dict(schema="hcsn-mechanism-attempt-terminal-v1", identity=job["identity"],
                    fit=job["fit"], phase=job["phase"], started_at=utc_now(), status="FAILED",
                    optimizer_updates_attempted=0, optimizer_updates_completed=0,
                    training_examples_completed=0, evaluation_examples_completed={},
                    validation=None, test=[], diagnostics={}, full_physical_energy_joules=None)
    torch = model = optimizer = energy = gradients = None
    log = (output / "journal.jsonl").open("x", buffering=1)

    def journal(event):
        if event.get("event") == "optimizer_update_completed":
            terminal["training_examples_completed"] += event["examples"]
        if event.get("event") == "evaluation_batch_completed":
            terminal["evaluation_examples_completed"][event["phase"]] = event["cumulative_examples"]
        event.update(at=utc_now(), worker_wall_seconds=time.monotonic() - started,
                     worker_cpu_seconds=time.process_time() - cpu_start)
        log.write(json.dumps(event, allow_nan=False, sort_keys=True) + "\n")
        log.flush()

    try:
        plan, metadata, arrays, roster, identity = load_contract(job["bundle"], job["plan"])
        if identity != job["identity"]:
            raise ValueError("Worker identity differs from supervisor")
        matches = [fit for fit in roster if fit["fit_id"] == job["fit"].get("fit_id")]
        if len(matches) != 1 or matches[0] != job["fit"]:
            raise ValueError("Worker fit is not the exact frozen roster row")
        torch = configure_torch(job["device"])
        terminal["environment"] = environment(job["device"])
        terminal["frozen_environment_check"] = validate_execution_environment(plan, terminal["environment"], metadata)
        energy = DeviceEnergy(job["device"])
        fit = job["fit"]
        model = make_model(arrays, fit["arm"], metadata["arms"][fit["arm"]]["channel"], fit["training_seed"], job["device"], plan["mass_tolerance"])
        terminal["initial_parameter_sha256"] = hashlib.sha256(b"".join(p.detach().cpu().numpy().tobytes() for p in model.parameters())).hexdigest()
        if job["phase"] == "fit":
            raw_train, train_receipt = make_data(plan, fit["task"], "train")
            raw_val, val_receipt = make_data(plan, fit["task"], "validation")
            train, validation = tensors(raw_train, torch), tensors(raw_val, torch)
            terminal["data"] = dict(train=train_receipt, validation=val_receipt)
            optimizer = torch.optim.Adam(model.parameters(), lr=fit["learning_rate"])
            gradients = GradientAudit(model)
            train_started = time.monotonic()
            order_hash = hashlib.sha256()
            model.train()
            for step, index in enumerate(batch_order(plan, fit), 1):
                if time.monotonic() - started >= plan["max_fit_wall_seconds"]:
                    raise TimeoutError("Fit exceeded its frozen per-fit wall budget")
                terminal["optimizer_updates_attempted"] = step
                order_hash.update(index.tobytes())
                journal(dict(event="optimizer_update_started", update=step, batch_index_sha256=hashlib.sha256(index.tobytes()).hexdigest()))
                optimizer.zero_grad(set_to_none=True)
                output_value, audit = model(train["x"][index].to(job["device"]), train["dt_indices"][index].to(job["device"]))
                loss = (output_value - train["y"][index].to(job["device"])).square().mean()
                if not bool(torch.isfinite(loss).item()):
                    raise FloatingPointError("Nonfinite training loss")
                loss.backward()
                gradients.observe(model)
                optimizer.step()
                synchronize(job["device"])
                terminal["optimizer_updates_completed"] = step
                merge_diagnostics(terminal["diagnostics"], audit)
                journal(dict(event="optimizer_update_completed", update=step, examples=len(index), mse=float(loss.item())))
            terminal["training_wall_seconds"] = time.monotonic() - train_started
            terminal["batch_order_sha256"] = order_hash.hexdigest()
            terminal["training_time_steps_completed"] = terminal["training_examples_completed"] * plan["sequence_length"]
            terminal["validation"] = evaluate(model, validation, plan, job["device"], journal, "validation", terminal["diagnostics"])
            checkpoint = dict(schema="hcsn-mechanism-checkpoint-v1", identity=identity, fit=fit, model=model.state_dict(),
                              optimizer=optimizer.state_dict(), optimizer_updates_completed=terminal["optimizer_updates_completed"],
                              data=terminal["data"], torch_rng_state=torch.get_rng_state(),
                              cuda_rng_state=torch.cuda.get_rng_state_all() if str(job["device"]).startswith("cuda") else [])
            with (output / "checkpoint.pt").open("xb") as stream:
                torch.save(checkpoint, stream)
            terminal["checkpoint_sha256"] = file_sha(output / "checkpoint.pt")
        elif job["phase"] == "selected_test":
            lock_path = Path(job["selection_lock"])
            if file_sha(lock_path) != job["selection_lock_sha256"]:
                raise ValueError("Selection lock drift")
            lock = read_json(lock_path)
            selected = lock["selected"].get(fit["arm"])
            if lock["identity"] != identity or not selected or selected["fit_id"] != fit["fit_id"]:
                raise ValueError("Checkpoint was not selected before test")
            checkpoint_path = Path(job["checkpoint_path"])
            if file_sha(checkpoint_path) != selected["checkpoint_sha256"]:
                raise ValueError("Selected checkpoint bytes drifted")
            checkpoint = torch.load(checkpoint_path, map_location="cpu", weights_only=True)
            if checkpoint["identity"] != identity or checkpoint["fit"] != fit or checkpoint["optimizer_updates_completed"] != plan["train_updates"]:
                raise ValueError("Checkpoint training identity mismatch")
            model.load_state_dict(checkpoint["model"], strict=True)
            terminal["checkpoint_sha256"] = selected["checkpoint_sha256"]
            terminal["selection_lock_sha256"] = job["selection_lock_sha256"]
            for episode_seed in plan["test_episode_seeds"]:
                raw, receipt = make_data(plan, fit["task"], "test", episode_seed)
                test_data = tensors(raw, torch)
                result = evaluate(model, test_data, plan, job["device"], journal, "test-" + str(episode_seed), terminal["diagnostics"])
                result.update(episode_seed=episode_seed, data=receipt)
                terminal["test"].append(result)
            terminal["same_fit_aggregated_test_mse"] = sum(row["squared_error_sum"] for row in terminal["test"]) / sum(row["count"] for row in terminal["test"])
            terminal["independent_training_replicates_represented"] = 1
            terminal["evaluation_episode_seeds_are_training_replicates"] = False
            terminal["performance"] = benchmark(model, test_data["x"], test_data["dt_indices"], plan, job["device"])
        else:
            raise ValueError("Unknown worker phase")
        verify_sources(plan["source_pins"])
        if file_sha(job["plan"]) != identity["plan_sha256"] or file_sha(job["bundle"]) != identity["bundle_sha256"]:
            raise ValueError("Plan or operator bundle changed during the attempt")
        terminal["source_and_input_pins_unchanged_at_completion"] = True
        terminal["status"] = "COMPLETED"
    except Exception as error:
        terminal["status"] = "TIMEOUT" if isinstance(error, TimeoutError) else "FAILED"
        terminal["error"] = dict(type=type(error).__name__, message=str(error))
        (output / "error.txt").write_text(traceback.format_exc())
        if model is not None and torch is not None and not (output / "checkpoint.pt").exists():
            try:
                with (output / "failure-checkpoint.pt").open("xb") as stream:
                    torch.save(dict(identity=job["identity"], fit=job["fit"], model=model.state_dict(),
                                    optimizer_updates_completed=terminal["optimizer_updates_completed"],
                                    partial=True, eligible_for_selection=False), stream)
                terminal["failure_checkpoint_sha256"] = file_sha(output / "failure-checkpoint.pt")
            except Exception as checkpoint_error:
                terminal["failure_checkpoint_error"] = str(checkpoint_error)
    finally:
        if model is not None:
            terminal["memory"] = memory_report(model, optimizer)
        if gradients is not None:
            terminal["observed_gradients"] = gradients.report()
        if torch is not None and str(job["device"]).startswith("cuda") and torch.cuda.is_available():
            terminal["gpu_peak_allocated_bytes"] = torch.cuda.max_memory_allocated(job["device"])
            terminal["gpu_peak_reserved_bytes"] = torch.cuda.max_memory_reserved(job["device"])
        terminal["energy"] = energy.finish() if energy else dict(device_interval_joules=None, full_physical_energy_joules=None)
        terminal["finished_at"] = utc_now()
        terminal["worker_wall_seconds"] = time.monotonic() - started
        terminal["worker_process_cpu_seconds"] = time.process_time() - cpu_start
        terminal["worker_peak_rss_bytes"] = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024
        terminal["cost_scope"] = "Worker process including setup, data creation, its named phase, checkpoint and diagnostics. Supervisor child CPU must not be added again."
        journal(dict(event="worker_terminal", status=terminal["status"]))
        log.close()
        write_json(output / "terminal.json", terminal)
    return terminal


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--job", required=True, type=Path)
    args = parser.parse_args()
    result = run_job(args.job)
    print(json.dumps({key: result[key] for key in ("fit", "phase", "status", "optimizer_updates_completed")}))
    return 0 if result["status"] == "COMPLETED" else 1


if __name__ == "__main__":
    raise SystemExit(main())
