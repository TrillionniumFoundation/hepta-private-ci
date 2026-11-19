"""Frozen experiment inventory, bounded workers and durable failure records."""

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import json
from pathlib import Path
import random
import subprocess
import sys
import time

from .records import digest_bytes, source_seal, write_json


def build_inventory(protocol):
    runs = []
    common = protocol["common"]
    for stage in ("mechanism", "representation"):
        config = protocol[stage]
        for task in config["tasks"]:
            for architecture in config["architectures"]:
                for seed in protocol[f"{stage}_seeds"]:
                    spec = {
                        key: config[key]
                        for key in ("train_size", "width", "depth", "length", "updates")
                    }
                    spec.update(
                        stage=stage,
                        task=task,
                        architecture=architecture,
                        seed=seed,
                        data_seed=protocol["data_seed"],
                        val_size=common["val_size"],
                        test_size=common["test_size"],
                        batch_size=common["batch_size"],
                        lr=common["learning_rate"],
                        match_cell_budget=stage == "mechanism"
                        and architecture == "continuous_rnn",
                    )
                    runs.append(
                        {
                            "run_id": f"{stage}/{task}/{architecture}/seed{seed}",
                            "spec": spec,
                        }
                    )
    for index, config in enumerate(protocol["scaling"]["configurations"]):
        for architecture in protocol["scaling"]["architectures"]:
            for seed in protocol["scaling_seeds"]:
                spec = dict(
                    config,
                    stage="scaling",
                    architecture=architecture,
                    seed=seed,
                    data_seed=protocol["data_seed"],
                    updates=protocol["scaling"]["updates"],
                    val_size=common["val_size"],
                    test_size=common["test_size"],
                    batch_size=common["batch_size"],
                    lr=common["learning_rate"],
                )
                runs.append(
                    {
                        "run_id": f"scaling/config{index:02d}/{architecture}/seed{seed}",
                        "spec": spec,
                    }
                )
    for seed in protocol["boundary_seeds"]:
        runs.append(
            {
                "run_id": f"boundary/seed{seed}",
                "spec": {"stage": "boundary", "seed": seed},
            }
        )
    return runs


def execute_run(run, output, cache_dir):
    directory = output / run["run_id"]
    directory.mkdir(parents=True, exist_ok=True)
    if (directory / "RESULT.json").exists():
        return {"run_id": run["run_id"], "status": "existing"}
    write_json(directory / "SPEC.json", run["spec"])
    module = "boundary_study" if run["spec"]["stage"] == "boundary" else "train"
    command = [
        sys.executable,
        "-m",
        f"experiments.continuous_spiking_network.{module}",
        "--output",
        str(directory),
    ]
    if module == "train":
        command.extend(
            ["--spec", str(directory / "SPEC.json"), "--cache-dir", str(cache_dir)]
        )
    else:
        command.extend(["--seed", str(run["spec"]["seed"])])
    attempt = len(list(directory.glob("execution_*.log"))) + 1
    start = time.time()
    with (directory / f"execution_{attempt:02d}.log").open("w") as log:
        process = subprocess.run(
            command, stdout=log, stderr=subprocess.STDOUT, check=False
        )
    receipt = {
        "run_id": run["run_id"],
        "exit_code": process.returncode,
        "elapsed_seconds": time.time() - start,
        "command": command,
        "status": "completed"
        if process.returncode == 0 and (directory / "RESULT.json").exists()
        else "failed",
    }
    write_json(directory / f"EXECUTION_{attempt:02d}.json", receipt)
    return receipt


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True)
    parser.add_argument("--cache-dir", required=True)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument(
        "--stage",
        choices=["all", "mechanism", "representation", "scaling", "boundary"],
        default="all",
    )
    parser.add_argument("--inventory-only", action="store_true")
    args = parser.parse_args()
    package = Path(__file__).parent
    seal = source_seal(package)
    protocol = json.loads((package / "PROTOCOL.json").read_text())
    output = Path(args.output).resolve()
    inventory = {"source_seal": seal, "runs": build_inventory(protocol)}
    inventory_digest = digest_bytes(
        json.dumps(inventory["runs"], sort_keys=True, separators=(",", ":")).encode()
    )
    if protocol.get("runs_sha256") != inventory_digest:
        raise ValueError("run inventory differs from the frozen protocol digest")
    path = output / "RUNS.json"
    if path.exists() and json.loads(path.read_text()) != inventory:
        raise ValueError("cannot alter a registered run inventory")
    write_json(path, inventory)
    if args.inventory_only:
        print(
            json.dumps({"runs": len(inventory["runs"]), "source_seal": seal}),
            flush=True,
        )
        return
    selected = [
        run
        for run in inventory["runs"]
        if args.stage == "all" or run["spec"]["stage"] == args.stage
    ]
    random.Random(20261028).shuffle(selected)
    receipts = []
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        pending = {
            pool.submit(execute_run, run, output, Path(args.cache_dir).resolve()): run
            for run in selected
        }
        for future in as_completed(pending):
            receipt = future.result()
            receipts.append(receipt)
            print(json.dumps(receipt), flush=True)
            write_json(output / f"PROGRESS_{args.stage}.json", receipts)
    failed = [r for r in receipts if r["status"] == "failed"]
    if failed:
        raise SystemExit(f"{len(failed)} failed runs retained")


if __name__ == "__main__":
    main()
