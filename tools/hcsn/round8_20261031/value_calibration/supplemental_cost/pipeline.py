"""Post-confirmation execution-cost audit; never retrains or selects a policy.

One worker processes the first 16 registered nominal seeds in each contract.
Every worker includes interpreter startup, imports, model loading, complete
inference, execution and gzip/report serialization. Original confirmation
timings and scientific comparisons remain untouched.
"""

import argparse
import gzip
import hashlib
import json
import os
from pathlib import Path
import resource
import subprocess
import sys
import time


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write(path, value):
    Path(path).write_text(json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n")


def worker(args):
    # process_time is cumulative from this process's beginning, including imports.
    from tools.hcsn.round8_20261031.value_calibration import finite
    from tools.hcsn.round8_20261031.value_calibration.frozen import FrozenR7
    from tools.hcsn.round8_20261031.value_calibration.head import CalibratedHead
    from tools.hcsn.round8_20261031.value_calibration.run import checkpoint, episode_run
    started = time.perf_counter()
    cases = json.loads(args.inputs.read_text())[f"{args.mode}/{args.seed}"]
    model = FrozenR7(checkpoint(args.mode, args.seed))
    head = CalibratedHead.load(args.prepared / f"{args.mode}_{args.seed}.json") if args.version == "new" else None
    setup_cpu = time.process_time()
    inference_cpu = 0.
    identities = []
    with gzip.open(args.output, "wt", compresslevel=6) as stream:
        for case in cases:
            episode = finite.task.generate_episode(case["episode_seed"], finite.configurations()[case["contract"]])
            result = episode_run(model, head, episode, case["episode_seed"] + 10000000)
            observed = {k: result[k] for k in ("utility", "task_return", "correct", "decisions", "events")}
            observed["actions"] = [r["action"] for r in result["steps"]]
            if observed != case["expected"][args.version]:
                raise AssertionError("cost replay changed a frozen confirmation result")
            inference_cpu += result["cpu_seconds"]
            identities.append(case["episode_seed"])
            stream.write(json.dumps({"episode_seed": case["episode_seed"], "result": result}, separators=(",", ":")) + "\n")
    report = {"mode": args.mode, "seed": args.seed, "version": args.version,
        "sessions": len(cases), "matches_original_confirmation": True,
        "interpreter_import_load_cpu_seconds": setup_cpu,
        "warm_episode_cpu_seconds": inference_cpu,
        "worker_cpu_before_report_seconds": time.process_time(),
        "worker_wall_after_import_seconds": time.perf_counter() - started,
        "raw_sha256": sha(args.output), "episode_seeds": identities}
    write(args.output.with_suffix(".json"), report)


def interval(values):
    import numpy as np
    from scipy.stats import t as student_t
    values = np.asarray(values)
    half = student_t.ppf(1 - .05 / 6, len(values) - 1) * values.std(ddof=1) / len(values) ** .5
    return {"mean": float(values.mean()), "interval": [float(values.mean() - half), float(values.mean() + half)]}


def campaign(args):
    args.output.mkdir(parents=True, exist_ok=False)
    started, parent_cpu = time.perf_counter(), time.process_time()
    prepared = json.loads((args.prepared / "PREPARE.json").read_text())
    design = prepared["protocol"]["confirmation"]
    inputs = {}
    with gzip.open(args.confirmation / "RAW.jsonl.gz", "rt") as stream:
        for line in stream:
            row = json.loads(line)
            if row["regime"] != "nominal" or row["episode_seed"] % 1000 >= 16:
                continue
            expected = {}
            for version in ("old", "new"):
                result = row["runs"][version]
                expected[version] = {k: result[k] for k in ("utility", "task_return", "correct", "decisions", "events")}
                expected[version]["actions"] = [r["action"] for r in result["steps"]]
            inputs.setdefault(f"{row['mode']}/{row['seed']}", []).append({"contract": row["contract"],
                "episode_seed": row["episode_seed"], "expected": expected})
    if len(inputs) != 15 or any(len(cases) != 128 for cases in inputs.values()):
        raise AssertionError("supplemental timing selection differs")
    input_path = args.output / "REPLAY_INPUTS.json"
    write(input_path, inputs)
    workers = []
    for fit in prepared["fits"]:
        mode, seed = fit["mode"], fit["seed"]
        for version in (("old", "new") if seed % 2 else ("new", "old")):
            output = args.output / f"{mode}_{seed}_{version}.jsonl.gz"
            command = [sys.executable, "-m", __spec__.name, "--worker", "--prepared", str(args.prepared),
                "--inputs", str(input_path), "--mode", mode, "--seed", str(seed), "--version", version,
                "--output", str(output)]
            env = dict(os.environ, OPENBLAS_NUM_THREADS="1", OMP_NUM_THREADS="1", PYTHONDONTWRITEBYTECODE="1")
            before = resource.getrusage(resource.RUSAGE_CHILDREN)
            wall = time.perf_counter()
            result = subprocess.run(command, env=env, check=True)
            after = resource.getrusage(resource.RUSAGE_CHILDREN)
            measurement = json.loads(output.with_suffix(".json").read_text())
            measurement.update({"exit_code": result.returncode,
                "complete_worker_cpu_seconds": after.ru_utime + after.ru_stime - before.ru_utime - before.ru_stime,
                "complete_worker_wall_seconds": time.perf_counter() - wall})
            workers.append(measurement)
            print(json.dumps({k: measurement[k] for k in ("mode", "seed", "version", "complete_worker_cpu_seconds")}), flush=True)
    costs = {(x["mode"], x["seed"], x["version"]): x["complete_worker_cpu_seconds"] / x["sessions"] for x in workers}
    offline = {(x["mode"], x["seed"]): x["standalone_new_preparation_cpu_seconds"] for x in prepared["fits"]}
    confirmed = json.loads((args.confirmation / "SUMMARY.json").read_text())
    utilities = {(x["mode"], x["seed"]): x["differences"]["utility"] for x in confirmed["fits"] if x["regime"] == "nominal"}
    audit = json.loads(args.audit.read_text())
    absolute = {(x["mode"], x["seed"], x["version"]): x["means"]["utility"]
        for x in audit["absolute_means"] if x["regime"] == "nominal"}
    comparisons = []
    contrasts = [(mode, "old") for mode in prepared["protocol"]["modes"]] + [(mode, "new") for mode in ("clocked", "direct")]
    for comparison, comparator in contrasts:
        label = f"new {comparison} minus old {comparison}" if comparator == "old" else f"new first_passage minus new {comparison}"
        u, dc, do = [], [], []
        for seed in prepared["protocol"]["core_seeds"]:
            if comparator == "old":
                u.append(utilities[comparison, seed])
                dc.append(costs[comparison, seed, "new"] - costs[comparison, seed, "old"])
                do.append(offline[comparison, seed])
            else:
                u.append(absolute["first_passage", seed, "new"] - absolute[comparison, seed, "new"])
                dc.append(costs["first_passage", seed, "new"] - costs[comparison, seed, "new"])
                do.append(offline["first_passage", seed] - offline[comparison, seed])
        sensitivity = [{"cpu_price": price, "deployment_sessions": sessions,
            **interval([v - price * (c + o / sessions) for v, c, o in zip(u, dc, do)])}
            for price in design["cpu_price_sensitivity"] for sessions in design["deployment_sessions_sensitivity"]]
        comparisons.append({"contrast": label, "utility": interval(u), "complete_pipeline_cpu_delta_per_session": interval(dc),
            "primary_pricing_net_utility": next(row for row in sensitivity if row["cpu_price"] == design["primary_compute_price_cpu"]
                and row["deployment_sessions"] == design["primary_training_amortization_sessions"]), "cost_sensitivity": sensitivity})
    write(args.output / "PIPELINE_COST.json", {"schema": "hepta.r8.value.pipeline-cost.v1",
        "classification": "post-confirmation supplemental cost audit; no policy or original confirmation change",
        "source_sha256": sha(__file__), "original_raw_sha256": sha(args.confirmation / "RAW.jsonl.gz"),
        "freeze_sha256": sha(args.prepared / "FREEZE.json"), "workers": workers,
        "replay_sessions": sum(x["sessions"] for x in workers), "comparisons": comparisons,
        "campaign_child_cpu_seconds": sum(x["complete_worker_cpu_seconds"] for x in workers),
        "campaign_parent_cpu_seconds": time.process_time() - parent_cpu,
        "campaign_wall_seconds": time.perf_counter() - started,
        "cost_model": "One new worker per 128-session batch, including startup/import/load/inference/task/gzip/report/exit; head preparation amortized separately over H sessions. The timing subset is fixed stratified 16 of 128 seeds per contract; estimates are supplemental, not the preregistered primary timing.",
        "unmeasured_costs": ["physical energy and money", "developer and assistant time", "setup CPU of explicitly retained failed early attempts", "original R7 common training cost"]})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--worker", action="store_true")
    parser.add_argument("--prepared", type=Path, required=True)
    parser.add_argument("--confirmation", type=Path)
    parser.add_argument("--audit", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--inputs", type=Path)
    parser.add_argument("--mode")
    parser.add_argument("--seed", type=int)
    parser.add_argument("--version", choices=("old", "new"))
    args = parser.parse_args()
    if args.worker:
        worker(args)
    else:
        campaign(args)


if __name__ == "__main__":
    main()
