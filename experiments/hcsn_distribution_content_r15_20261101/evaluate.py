"""Frozen-candidate confirmation, original stress domains and actual CPU work."""

import argparse
import json
import time
from pathlib import Path

import numpy as np
import torch

from experiments.hcsn_validation_r14_20261101.content.engine import (
    ValueController, all_logits, policy_values, replay, model_hash,
    READ_FEE, TIME_FEE, online_rollout, public_times,
)
from .campaign import configure, verified, write, digest, tensors
from .data import DOMAINS, dataset
from .models import restore, FAMILIES, traced_logits


def outcome(model, controller, values, execution):
    x, dt, y = tensors(values)
    logits, diagnostic = traced_logits(model, x, dt)
    if execution == "light":
        reads = torch.full((len(x),), dt.shape[1], dtype=torch.long)
        elapsed = dt.sum(1)
        selected = logits[:, -1]
        calibration = None
    else:
        stats = replay(logits, policy_values(controller, logits, dt), dt, y)
        reads = stats["read_count"]
        elapsed = public_times(dt)[0][torch.arange(len(x)), reads]
        selected = logits[torch.arange(len(x)), reads]
        calibration = {key: float(stats[key]) for key in ("occupied_mse", "root_mse", "occupied_hindsight_gap")}
    prediction = selected.argmax(-1)
    fee = READ_FEE * reads + TIME_FEE * elapsed
    utility = (prediction == y).float() - fee
    result = dict(prediction=prediction.numpy(), read_count=reads.numpy(), elapsed=elapsed.numpy(),
                fee=fee.numpy(), utility=utility.numpy(), labels=values["y"], group=values["group"],
                ids=values["ids"], context_ids=values["context_ids"], partition_ids=values["partition_ids"],
                dt=values["dt"], prob=selected.softmax(-1).numpy())
    if diagnostic is not None:
        result.update({key: value.numpy() for key, value in diagnostic.items()})
    return result, calibration


def actual_cost(model, controller, values, execution, batch_sizes=(1, 16)):
    records = []
    for count in batch_sizes:
        x, dt, y = tensors(values, slice(0, count))
        for phase in ("cold", "warm_1", "warm_2", "warm_3"):
            if phase == "cold" and hasattr(model.core, "clear_cache"):
                model.core.clear_cache()
            begin_cpu, begin_wall = time.process_time(), time.perf_counter()
            if execution == "value":
                result = online_rollout(model, controller, x, dt, y)
                prediction, reads = result["prediction"], result["reads"]
                processed, calls = result["processed_prefix_tokens"], result["model_calls"]
            else:
                prediction = model(x, dt).argmax(-1)
                reads = torch.full((count,), dt.shape[1], dtype=torch.long)
                processed, calls = count * dt.shape[1], 1
            records.append(dict(batch_size=count, phase=phase, cpu_seconds=time.process_time()-begin_cpu,
                                wall_seconds=time.perf_counter()-begin_wall, model_calls=calls,
                                processed_prefix_tokens=processed, reads=reads.tolist(), prediction=prediction.tolist()))
    return records


def evaluate_group(output, task, seed, mode):
    protocol = verified(output)
    name = f"{task}_s{seed}_{mode}"
    fit_dir, dest = output / "fits" / name, output / "evaluation" / name
    dest.mkdir(parents=True, exist_ok=False)
    summary = json.loads((fit_dir / "SUMMARY.json").read_text())
    if summary["development"] or digest(fit_dir / "selected.pt") != summary["checkpoint_sha256"]:
        raise ValueError("Unfrozen or development checkpoint")
    candidate = torch.load(fit_dir / "selected.pt", weights_only=False)
    controller = ValueController(); controller.load_state_dict(candidate["controller"]); controller.eval()
    controller_identity = model_hash(controller)
    records, costs, ablations, alignment = [], [], [], []
    start_cpu, start_wall = time.process_time(), time.perf_counter()
    with torch.no_grad():
        for family in FAMILIES:
            model = restore(candidate, family)
            identity = model_hash(model)
            if identity != summary["model_hashes"][family]:
                raise ValueError("Selected backend identity changed")
            for domain in DOMAINS[task]:
                values = dataset(task, "test", domain)
                for execution in (["light", "value"] if mode == "value" else ["light"]):
                    arrays, calibration = outcome(model, controller, values, execution)
                    filename = f"{family}_{domain}_{execution}.npz"
                    np.savez_compressed(dest / filename, **arrays)
                    row = dict(path=str((dest / filename).relative_to(output)), task=task, seed=seed,
                               family=family, train_mode=mode, exec_mode=execution, domain=domain,
                               model_hash=identity, controller_hash=controller_identity if execution == "value" else None,
                               train_controller_hash=controller_identity if mode == "value" else None,
                               sha256=digest(dest / filename), data_sha256=values["sha256"], calibration=calibration)
                    records.append(row)
                    if "upper_loss_prefix" in arrays:
                        occupied = np.arange(arrays["upper_loss_prefix"].shape[1])[None] <= arrays["read_count"][:, None]
                        row["posterior_qualification"] = dict(
                            all_prefix_maximum_upper_loss=float(arrays["upper_loss_prefix"].max()),
                            occupied_maximum_upper_loss=float(arrays["upper_loss_prefix"][occupied].max()),
                            maximum_mass_error=float(arrays["mass_error_prefix"].max()),
                            minimum_probability=float(arrays["minimum_probability_prefix"].min()),
                            all_prefix_upper_loss_pass=bool(arrays["upper_loss_prefix"].max() <= 1e-7))
                    # Charge a real causal actor on each original non-missing stress domain.
                    if not domain.startswith("missing"):
                        observed = actual_cost(model, controller, values, execution)
                        for receipt in observed:
                            count = receipt["batch_size"]
                            bad_reads = int(np.count_nonzero(np.asarray(receipt["reads"]) != arrays["read_count"][:count]))
                            bad_prediction = int(np.count_nonzero(np.asarray(receipt["prediction"]) != arrays["prediction"][:count]))
                            alignment.append(dict(task=task, seed=seed, family=family, mode=mode, domain=domain,
                                                  execution=execution, phase=receipt["phase"], batch=count,
                                                  read_mismatch=bad_reads, prediction_mismatch=bad_prediction))
                            if bad_reads or bad_prediction:
                                raise AssertionError("Confirmation/actual online mismatch")
                        costs.append(dict(task=task, seed=seed, family=family, train_mode=mode,
                                          exec_mode=execution, domain=domain, measurements=observed))
                if mode == "value" and family == "analytic_distribution":
                    for ablation in ("content_independence", "mean_position", "readout_independence"):
                        model.core.ablation = ablation
                        arrays, calibration = outcome(model, controller, values, "value")
                        filename = f"{family}_{domain}_{ablation}.npz"
                        np.savez_compressed(dest / filename, **arrays)
                        ablations.append(dict(path=str((dest / filename).relative_to(output)), task=task, seed=seed,
                                              family=family, train_mode=mode, exec_mode="value", domain=domain,
                                              ablation=ablation, model_hash=identity, controller_hash=controller_identity,
                                              sha256=digest(dest / filename), calibration=calibration))
                    model.core.ablation = "none"
    write(dest / "INDEX.json", dict(records=records))
    write(dest / "ABLATIONS.json", dict(records=ablations))
    write(dest / "COST.json", dict(records=costs, total_cpu_seconds=time.process_time()-start_cpu,
                                   total_wall_seconds=time.perf_counter()-start_wall,
                                   note="Total confirmation work is not added to deployment actor timers. Cold/warm costs include actual prefix recomputation and controller calls."))
    write(dest / "ALIGNMENT.json", dict(records=alignment, mismatches=0))
    return dict(group=name, records=len(records), cpu_seconds=time.process_time()-start_cpu)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=["group", "index"])
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--task")
    parser.add_argument("--seed", type=int)
    parser.add_argument("--mode", choices=["light", "value"])
    args = parser.parse_args(); configure()
    if args.action == "group":
        print(json.dumps(evaluate_group(args.output, args.task, args.seed, args.mode)))
    else:
        for source, target in [("INDEX.json", "EVALUATION_INDEX.json"), ("ABLATIONS.json", "ABLATION_INDEX.json"), ("COST.json", "COST_INDEX.json")]:
            records = []
            for path in sorted(args.output.glob("evaluation/*/" + source)):
                records += json.loads(path.read_text())["records"]
            write(args.output / target, dict(records=records))


if __name__ == "__main__":
    main()
