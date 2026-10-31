"""Prepare fresh training data and baselines; never generate confirmation data."""

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import shutil
import time

from .. import task, train
from ..native_adapter import Native
from ..run import digest, load_data, save_data, write_json


PROJECT = Path(__file__).resolve().parent


def base_training(run_dir, native_dir, protocol):
    run_dir, native_dir = Path(run_dir), Path(native_dir)
    run_dir.mkdir(parents=True, exist_ok=True)
    if (run_dir / "FREEZE.json").exists():
        raise ValueError("A frozen run cannot be refitted")
    destination = run_dir / "native"
    destination.mkdir(exist_ok=False)
    for name in ("analytic_event", "BUILD_RECEIPT.json"):
        shutil.copy2(native_dir / name, destination / name)
    write_json(destination / "REUSE_RECEIPT.json", {
        "binary_sha256": digest(destination / "analytic_event"),
        "source_round": 1,
        "current_round_fresh_build": False,
        "fresh_rust_builds": 0,
        "prior_build_receipt_preserved": True,
    })
    started, cpu = time.perf_counter_ns(), time.process_time_ns()
    receipts = []
    with Native(destination / "analytic_event", destination / "BUILD_RECEIPT.json") as native:
        for seed in protocol["training_seeds"]:
            directory = run_dir / "training" / f"seed_{seed}"
            directory.mkdir(parents=True, exist_ok=False)
            training = task.build_dataset(protocol["data_offsets"]["train"] + seed,
                                          protocol["rows"]["train"], "train")
            development = task.build_dataset(protocol["data_offsets"]["development"] + seed,
                                             protocol["rows"]["development"], "development")
            save_data(directory / "TRAIN.npz", training)
            save_data(directory / "DEVELOPMENT.npz", development)
            before_calls, before_ticks = native.calls, native.original_sparse_ticks
            before, before_cpu = time.perf_counter_ns(), time.process_time_ns()
            models, receipt = train.fit_models(training, development, seed, native)
            receipt.update({"wall_ns": time.perf_counter_ns() - before,
                            "cpu_ns": time.process_time_ns() - before_cpu,
                            "native_requests": native.calls - before_calls,
                            "original_sparse_ticks": native.original_sparse_ticks - before_ticks,
                            "fit_completed_utc": datetime.now(timezone.utc).isoformat()})
            write_json(directory / "BASE_MODELS.json", models)
            write_json(directory / "BASE_TRAINING.json", receipt)
            receipts.append({"seed": seed, "model_sha256": digest(directory / "BASE_MODELS.json"),
                             "optimizer_success": receipt["optimizer_success"],
                             "filter_parameter_l2_change": receipt["filter_parameter_l2_change"],
                             "wall_ns": receipt["wall_ns"], "cpu_ns": receipt["cpu_ns"]})
            print(json.dumps({"phase": "base_training", **receipts[-1]}), flush=True)
        accounting = {"native_requests": native.calls, "original_sparse_ticks": native.original_sparse_ticks,
                      "native_ipc_wall_ns": native.wall_ns}
    summary = {"schema": "hepta.analytic-event.round3.base-training.v1", "seeds": receipts,
               "wall_ns": time.perf_counter_ns() - started, "cpu_ns": time.process_time_ns() - cpu,
               "confirmation_generated": False, **accounting}
    write_json(run_dir / "BASE_PREPARATION.json", summary)
    return summary


def event_training(run_dir, protocol):
    from .event_study import prepare

    run_dir = Path(run_dir)
    if (run_dir / "FREEZE.json").exists():
        raise ValueError("A frozen run cannot be refitted")
    started, cpu = time.perf_counter_ns(), time.process_time_ns()
    receipts = []
    for seed in protocol["training_seeds"]:
        directory = run_dir / "training" / f"seed_{seed}"
        if (directory / "MODELS.json").exists():
            raise ValueError("A completed event selection cannot be silently replaced")
        models = json.loads((directory / "BASE_MODELS.json").read_text())
        receipt = json.loads((directory / "BASE_TRAINING.json").read_text())
        development = load_data(directory / "DEVELOPMENT.npz")
        selected, selection = prepare(models, development, directory, driver_receipt=receipt)
        receipts.append({"seed": seed, "model_sha256": digest(directory / "MODELS.json"),
                         "arms": list(selected)})
        print(json.dumps({"phase": "event_selection", **receipts[-1]}), flush=True)
    result = {"schema": "hepta.analytic-event.round3.event-preparation.v1", "seeds": receipts,
              "wall_ns": time.perf_counter_ns() - started, "cpu_ns": time.process_time_ns() - cpu,
              "confirmation_generated": False}
    write_json(run_dir / "EVENT_PREPARATION.json", result)
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("phase", choices=("base", "events"))
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--native-dir", type=Path)
    parser.add_argument("--protocol", type=Path, default=PROJECT / "PROTOCOL.json")
    arguments = parser.parse_args()
    registered = json.loads(arguments.protocol.read_text())
    if arguments.phase == "base":
        if arguments.native_dir is None:
            parser.error("base training requires --native-dir")
        base_training(arguments.run_dir, arguments.native_dir, registered)
    else:
        event_training(arguments.run_dir, registered)
