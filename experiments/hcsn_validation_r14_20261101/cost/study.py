"""Measure all historical domains with fresh workers and an external cost ledger.

No weights, data generator, predictions, or scientific selection rules change.
The parent imports only the standard library; each timed worker imports Torch.
"""

import argparse
from collections import defaultdict
import csv
from datetime import datetime, timezone
import hashlib
import importlib.metadata
import importlib.util
import json
import os
from pathlib import Path
import platform
import random
import shutil
import statistics
import subprocess
import sys
import time


ROOT = Path(__file__).resolve().parents[3]
HERE = Path(__file__).resolve().parent
OLD = ROOT / "experiments/hcsn_validation_r12_20261031/content"
STUDY = OLD / "results/formal001"
MODULE = "experiments.hcsn_validation_r14_20261101.cost.study"
REQUESTS = (1, 10, 32, 100, 320, 1000, 3200, 10000, 32000, 100000, 320000, 1000000)


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def write(path, value):
    with Path(path).open("x", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2, sort_keys=True,
                  allow_nan=False)
        stream.write("\n")


def require(condition, message):
    if not condition:
        raise ValueError(message)


def table(path, rows):
    with Path(path).open("x", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def prepare(output):
    output.mkdir(parents=True, exist_ok=False)
    old_protocol = read(STUDY / "PROTOCOL.json")
    jobs = []
    candidates = read(STUDY / "CANDIDATE_FREEZE.json")["candidates"]
    inputs = {str((STUDY / name).relative_to(ROOT)): sha(STUDY / name)
              for name in ("PROTOCOL.json", "SOURCE_FREEZE.json", "CANDIDATE_FREEZE.json")}
    for job in old_protocol["jobs"]:
        if job["kind"] != "fit":
            continue
        checkpoint = STUDY / candidates[job["id"]]["path"] / "selected.pt"
        require(sha(checkpoint) == candidates[job["id"]]["sha256"],
                "Historical candidate hash mismatch")
        inputs[str(checkpoint.relative_to(ROOT))] = sha(checkpoint)
        for domain in old_protocol["domains"][job["task"]]:
            evidence = STUDY / "heldout" / job["id"] / (domain + ".npz")
            inputs[str(evidence.relative_to(ROOT))] = sha(evidence)
            jobs.append(dict(**job, domain=domain, worker_id=job["id"] + "__" + domain,
                             checkpoint_sha256=sha(checkpoint),
                             historical_prediction_sha256=sha(evidence)))
    for path in sorted((STUDY / "process_receipts/worker").glob("*")):
        if path.is_file():
            inputs[str(path.relative_to(ROOT))] = sha(path)
    random.Random(1401101).shuffle(jobs)
    protocol = dict(schema="hcsn-r14.stress-cost.v1",
        purpose="Historical frozen-weight/data hardware replay; not new fits or confirmation",
        historical_protocol_sha256=sha(STUDY / "PROTOCOL.json"),
        historical_candidate_freeze_sha256=sha(STUDY / "CANDIDATE_FREEZE.json"),
        jobs=jobs, batches=[1, 32], warmups=3, repetitions=12,
        measurement_order_seed=1401101,
        execution="Serial fresh process per model/task/domain; one CPU thread",
        cold="First complete batch-1 forward in each fresh worker, after model/data loading; cold process total is the entire worker and is not a cold single-request latency",
        batch32_first="First batch-32 shape call follows batch-1 measurements; not process-cold",
        warm="Raw NumPy input view to Torch tensors, encoder, all sequence steps, readout, CPU output copy; cached input excludes generation, external acquisition, network and service infrastructure",
        quality="Regenerate all 256 original test inputs; compare full predictions with retained NPZ at atol=1e-6, rtol=1e-5; retain all domains",
        instrumentation="Untimed full-model pass counts actual calls/elements to log_ndtr, logaddexp, expm1 and exp; wrapper output must be bit-identical; other operators are not claimed counted",
        memory="Exact parameter/buffer/input/returned-history/output bytes; fresh-process peak RSS externally measured; no native allocator peak or full survival-distribution storage claim",
        unavailable="Device joules, optimized GPU kernels, online queries, full distribution and free-boundary solve not implemented/measured; null is not zero",
        inference="Three historical fitting seeds conditional on fixed datasets; descriptive per-seed and paired summaries only; timing repetitions are not fits",
        amortization="(historical donor + historical candidate fit/selection)/N + newly measured warm request; N is the total sample requests and only N>=batch and N divisible by batch are emitted (complete batches, no unmeasured tail); full worker receipt already includes nested stages and is never added to them",
        requests=list(REQUESTS))
    write(output / "PROTOCOL.json", protocol)
    write(output / "INPUT_MANIFEST.json", dict(files=inputs))
    cpuinfo = Path("/proc/cpuinfo")
    model_lines = [line.split(":", 1)[1].strip() for line in cpuinfo.read_text().splitlines()
                   if line.startswith("model name") and ":" in line] if cpuinfo.exists() else []
    write(output / "EXECUTION_ENVIRONMENT.json", dict(
        observed_at_utc=datetime.now(timezone.utc).isoformat(),
        platform=platform.platform(), cpu_models=sorted(set(model_lines)),
        logical_cpu_count=os.cpu_count(),
        allowed_cpus=sorted(os.sched_getaffinity(0)) if hasattr(os, "sched_getaffinity") else None,
        telemetry_roots=[dict(path=path, exists=Path(path).exists()) for path in
                         ("/sys/class/powercap", "/sys/devices/virtual/powercap", "/sys/class/hwmon")],
        nvidia_smi_executable=shutil.which("nvidia-smi"), energy_joules=None,
        scope="Current container visibility and CPU identity; no energy integration or exclusive-host claim"))
    source = {str(p.relative_to(ROOT)): sha(p) for p in sorted(HERE.glob("*.py"))}
    for path, digest in read(STUDY / "SOURCE_FREEZE.json")["files"].items():
        require(sha(OLD / path) == digest, "Historical source changed: " + path)
        source[str((OLD / path).relative_to(ROOT))] = digest
    write(output / "SOURCE_FREEZE.json", dict(files=source,
        protocol_sha256=sha(output / "PROTOCOL.json"),
        input_manifest_sha256=sha(output / "INPUT_MANIFEST.json"),
        frozen_at_utc=datetime.now(timezone.utc).isoformat(),
        source_scope="Local bytes fixed before execution; no external preregistration claim"))
    snapshots = output / "SOURCE_SNAPSHOTS"
    snapshots.mkdir()
    for path, digest in source.items():
        destination = snapshots / path.replace("/", "__")
        destination.write_bytes((ROOT / path).read_bytes())
        require(sha(destination) == digest, "Snapshot copy changed bytes")
    return dict(workers=len(jobs), fit_models=sum(j["kind"] == "fit" for j in old_protocol["jobs"]),
                protocol_sha256=sha(output / "PROTOCOL.json"))


def verify(output):
    freeze = read(output / "SOURCE_FREEZE.json")
    require(sha(output / "PROTOCOL.json") == freeze["protocol_sha256"], "Protocol changed")
    require(sha(output / "INPUT_MANIFEST.json") == freeze["input_manifest_sha256"], "Input manifest changed")
    for path, digest in freeze["files"].items():
        require(sha(ROOT / path) == digest, "Frozen source changed: " + path)
    require(sha(STUDY / "CANDIDATE_FREEZE.json") ==
            read(output / "PROTOCOL.json")["historical_candidate_freeze_sha256"],
            "Candidate freeze changed")
    return read(output / "PROTOCOL.json")


def instrument(torch, function):
    """Count selected actual tensor calls without mixing instrumentation with timing."""
    counts, saved = {}, []
    try:
        for owner, name, label in ((torch.special, "log_ndtr", "log_ndtr"),
                                   (torch, "logaddexp", "logaddexp"),
                                   (torch, "expm1", "expm1"),
                                   (torch, "exp", "exp")):
            original = getattr(owner, name)
            saved.append((owner, name, original))
            counts[label] = dict(calls=0, input_elements=0, output_elements=0)

            def counted(*args, _original=original, _label=label, **kwargs):
                row = counts[_label]
                row["calls"] += 1
                row["input_elements"] += sum(x.numel() for x in args if torch.is_tensor(x))
                value = _original(*args, **kwargs)
                row["output_elements"] += value.numel()
                return value

            setattr(owner, name, counted)
        value = function()
    finally:
        for owner, name, original in saved:
            setattr(owner, name, original)
    return value, counts


def worker(output, worker_id):
    plan = verify(output)
    job = next(row for row in plan["jobs"] if row["worker_id"] == worker_id)
    destination = output / "workers" / worker_id
    destination.mkdir(parents=True, exist_ok=False)
    import numpy as np
    import torch
    from experiments.hcsn_validation_r12_20261031.content.study import configure, load_selected
    from experiments.hcsn_validation_r12_20261031.content.data import dataset
    configure()
    runtime = read(STUDY / "PROTOCOL.json")["runtime"]
    require(torch.__version__ == runtime["torch"] and np.__version__ == runtime["numpy"],
            "Replay runtime differs from frozen historical tensor runtime")
    require(importlib.metadata.version("ncps") == runtime["ncps"], "CfC package version differs")
    cfc = Path(importlib.util.find_spec("ncps").origin).parent / "torch/cfc_cell.py"
    require(sha(cfc) == runtime["cfc_cell_sha256"], "CfC source differs from historical pin")
    model, _, _, entry = load_selected(STUDY / "PROTOCOL.json", job["id"])
    model.eval()
    require(entry["sha256"] == job["checkpoint_sha256"], "Worker checkpoint identity")
    data = dataset(job["task"], "test", job["domain"])
    historical = STUDY / "heldout" / job["id"] / (job["domain"] + ".npz")
    require(sha(historical) == job["historical_prediction_sha256"], "Historical predictions changed")
    with np.load(historical, allow_pickle=False) as raw:
        require(str(raw["input_sha256"]) == data["sha256"], "Data identity changed")
        require(np.array_equal(raw["labels"], data["y"]), "Historical labels differ")
        original_logits = raw["logits"].copy()

    def forward(batch):
        x = torch.from_numpy(data["x"][:batch])
        dt = torch.from_numpy(data["dt"][:batch])
        return model(x, dt).numpy().copy()

    measurements = []
    with torch.inference_mode():
        for batch in plan["batches"]:
            first_cpu, first_wall = time.process_time_ns(), time.perf_counter_ns()
            baseline = forward(batch)
            first = dict(cpu_ns=time.process_time_ns() - first_cpu,
                         wall_ns=time.perf_counter_ns() - first_wall,
                         process_first_model_call=batch == plan["batches"][0])
            for _ in range(plan["warmups"]):
                forward(batch)
            repeats = []
            for iteration in range(plan["repetitions"]):
                began_cpu, began_wall = time.process_time_ns(), time.perf_counter_ns()
                actual = forward(batch)
                repeats.append(dict(iteration=iteration,
                    cpu_ns=time.process_time_ns() - began_cpu,
                    wall_ns=time.perf_counter_ns() - began_wall))
                require(np.array_equal(actual, baseline), "Repeated output changed")
            counted, operations = instrument(torch, lambda: forward(batch))
            require(np.array_equal(counted, baseline), "Instrumentation changed model output")
            logits, states = model(torch.from_numpy(data["x"][:batch]),
                                   torch.from_numpy(data["dt"][:batch]), return_states=True)
            require(np.array_equal(logits.numpy(), baseline), "State observation changed outputs")
            measurements.append(dict(batch=batch, first_call=first, warm=repeats,
                selected_function_calls=operations,
                input_tensor_bytes=int(data["x"][:batch].nbytes + data["dt"][:batch].nbytes),
                returned_state_history_bytes=states.numel() * states.element_size(),
                output_tensor_bytes=logits.numel() * logits.element_size(),
                native_working_memory_peak_bytes=None, full_survival_distribution_bytes=None,
                full_survival_distribution_status="not represented by this historical content model"))
        reproduced = []
        for begin in range(0, len(data["y"]), 32):
            x, dt = torch.from_numpy(data["x"][begin:begin + 32]), torch.from_numpy(data["dt"][begin:begin + 32])
            reproduced.append(model(x, dt).numpy().copy())
        reproduced = np.concatenate(reproduced)
    max_difference = float(np.max(np.abs(reproduced - original_logits)))
    require(np.allclose(reproduced, original_logits, rtol=1e-5, atol=1e-6),
            "Predictions disagree with historical evidence")
    require(np.array_equal(reproduced.argmax(-1), original_logits.argmax(-1)),
            "Historical class predictions changed")
    np.savez_compressed(destination / "predictions.npz", logits=reproduced, labels=data["y"],
                        input_sha256=data["sha256"])
    result = dict(job=job, checkpoint=entry, input_sha256=data["sha256"],
        samples=len(data["y"]), steps=int(data["x"].shape[1]),
        accuracy=float((reproduced.argmax(-1) == data["y"]).mean()),
        historical_max_abs_logit_difference=max_difference,
        predictions_sha256=sha(destination / "predictions.npz"),
        parameters=sum(p.numel() for p in model.parameters()),
        parameter_bytes=sum(p.numel() * p.element_size() for p in model.parameters()),
        buffer_bytes=sum(p.numel() * p.element_size() for p in model.buffers()),
        measurements=measurements, energy_joules=None, online_query_cost=None,
        free_boundary_solve_cost=None,
        unsupported="No free-boundary solve/full survival-distribution state/online acquisition in this historical content model",
        runtime=dict(torch=torch.__version__, numpy=np.__version__, python=platform.python_version(),
                     threads=torch.get_num_threads(), cuda_available=torch.cuda.is_available(),
                     compute_device="cpu"),
        source_freeze_sha256=sha(output / "SOURCE_FREEZE.json"))
    write(destination / "RESULT.json", result)
    return dict(worker=worker_id, accuracy=result["accuracy"], max_logit_difference=max_difference)


def run(output, limit=None, worker_ids=None):
    plan = verify(output)
    require(hasattr(os, "wait4"), "External per-child accounting requires POSIX wait4")
    selected = plan["jobs"]
    if worker_ids:
        selected = [j for j in selected if j["worker_id"] in worker_ids]
        require(len(selected) == len(set(worker_ids)), "Unknown worker ID")
    if limit is not None:
        selected = selected[:limit]
    receipts = output / "receipts"
    receipts.mkdir(exist_ok=True)
    for index, job in enumerate(selected):
        worker_id = job["worker_id"]
        receipt = receipts / (worker_id + ".json")
        if receipt.exists():
            record = read(receipt)
            require(record["returncode"] == 0, "Prior failed attempt retained; use a new output freeze")
            require(sha(output / "workers" / worker_id / "RESULT.json") == record["result_sha256"],
                    "Completed result hash mismatch")
            continue
        command = [sys.executable, "-m", MODULE, "worker", "--output", str(output), "--worker-id", worker_id]
        logpath = receipts / (worker_id + ".log")
        with logpath.open("x") as stream:
            started = time.perf_counter()
            process = subprocess.Popen(command, stdout=stream, stderr=subprocess.STDOUT,
                                       cwd=ROOT)
            _, status, usage = os.wait4(process.pid, 0)
            process.returncode = os.waitstatus_to_exitcode(status)
            elapsed = time.perf_counter() - started
        resultpath = output / "workers" / worker_id / "RESULT.json"
        write(receipt, dict(worker_id=worker_id, command=command,
            returncode=process.returncode, cpu_seconds=usage.ru_utime + usage.ru_stime,
            wall_seconds=elapsed, peak_rss_bytes=usage.ru_maxrss * (1 if sys.platform == "darwin" else 1024),
            energy_joules=None, log_sha256=sha(logpath),
            result_sha256=sha(resultpath) if resultpath.exists() else None,
            scope="Complete fresh worker, including imports, load/identity checks, data, first and warm forwards, instrumentation, replay and output writing; nested timings are included"))
        print(json.dumps(dict(done=index + 1, total=len(selected), worker=worker_id,
                              status=process.returncode)), flush=True)
        require(process.returncode == 0, "Worker failed; retained: " + worker_id)
    return dict(selected_workers=len(selected), complete_receipts=len(list(receipts.glob("*.json"))))


def training_costs():
    costs = defaultdict(float)
    for path in (STUDY / "process_receipts/worker").glob("*.json"):
        record = read(path)
        argv = record["command"]
        require(sha(path.with_suffix(".log")) == record["log_sha256"], "Historical training log changed")
        job = argv[argv.index("--job") + 1]
        costs[job] += record["cpu_seconds"]
    return costs


def summarize(output):
    plan = verify(output)
    for path, digest in read(output / "INPUT_MANIFEST.json")["files"].items():
        require(sha(ROOT / path) == digest, "Frozen replay input changed: " + path)
    training = training_costs()
    rows, ledger, amortization = [], [], []
    for job in plan["jobs"]:
        worker_id = job["worker_id"]
        receipt_path = output / "receipts" / (worker_id + ".json")
        require(receipt_path.exists(), "Missing worker: " + worker_id)
        receipt = read(receipt_path)
        result_path = output / "workers" / worker_id / "RESULT.json"
        require(receipt["returncode"] == 0 and sha(result_path) == receipt["result_sha256"],
                "Invalid worker result")
        require(sha(receipt_path.with_suffix(".log")) == receipt["log_sha256"], "Worker log changed")
        result = read(result_path)
        require(result["job"] == job and result["source_freeze_sha256"] == sha(output / "SOURCE_FREEZE.json"),
                "Result source/job identity mismatch")
        require(sha(result_path.parent / "predictions.npz") == result["predictions_sha256"], "Prediction file changed")
        ledger.append({k: receipt[k] for k in ("worker_id", "returncode", "cpu_seconds", "wall_seconds", "peak_rss_bytes", "energy_joules")})
        require(job["id"] in training and job["donor"] in training, "Missing historical training receipt")
        pipeline_training = training[job["id"]] + training[job["donor"]]
        for metric in result["measurements"]:
            batch = metric["batch"]
            cpu = statistics.median(x["cpu_ns"] for x in metric["warm"]) / 1e9 / batch
            wall = statistics.median(x["wall_ns"] for x in metric["warm"]) / 1e9 / batch
            row = dict(task=job["task"], mode=job["mode"], family=job["family"], seed=job["seed"],
                domain=job["domain"], batch=batch, steps=result["steps"], accuracy=result["accuracy"],
                warm_cpu_s_per_sample=cpu, warm_wall_s_per_sample=wall,
                warm_throughput_samples_s=1 / wall,
                first_call_cpu_s=metric["first_call"]["cpu_ns"] / 1e9,
                first_call_wall_s=metric["first_call"]["wall_ns"] / 1e9,
                process_first_model_call=metric["first_call"]["process_first_model_call"],
                parameter_bytes=result["parameter_bytes"], buffer_bytes=result["buffer_bytes"],
                input_tensor_bytes=metric["input_tensor_bytes"],
                returned_state_history_bytes=metric["returned_state_history_bytes"],
                worker_peak_rss_bytes=receipt["peak_rss_bytes"],
                historical_pipeline_training_cpu_s=pipeline_training,
                energy_joules=None, full_survival_distribution_bytes=None,
                log_ndtr_calls=metric["selected_function_calls"]["log_ndtr"]["calls"],
                log_ndtr_output_elements=metric["selected_function_calls"]["log_ndtr"]["output_elements"],
                historical_max_abs_logit_difference=result["historical_max_abs_logit_difference"],
                checkpoint_sha256=job["checkpoint_sha256"], input_sha256=result["input_sha256"])
            rows.append(row)
            for reuse in plan["requests"]:
                if reuse < batch or reuse % batch:
                    continue
                amortization.append(dict(task=job["task"], mode=job["mode"], family=job["family"],
                    seed=job["seed"], domain=job["domain"], batch=batch, requests=reuse,
                    complete_batches=reuse // batch,
                    cpu_s_per_request=pipeline_training / reuse + cpu))
    table(output / "per_seed_quality_cost.csv", rows)
    table(output / "process_ledger.csv", ledger)
    table(output / "training_amortization.csv", amortization)
    paired = []
    lookup = {(r["task"], r["mode"], r["seed"], r["domain"], r["batch"], r["family"]): r for r in rows}
    for row in rows:
        if row["family"] != "analytic":
            continue
        baseline = lookup[(row["task"], row["mode"], row["seed"], row["domain"], row["batch"], "ordinary_dual")]
        paired.append(dict(task=row["task"], mode=row["mode"], seed=row["seed"], domain=row["domain"], batch=row["batch"],
            analytic_minus_ordinary_accuracy=row["accuracy"] - baseline["accuracy"],
            analytic_over_ordinary_cpu=row["warm_cpu_s_per_sample"] / baseline["warm_cpu_s_per_sample"],
            analytic_over_ordinary_wall=row["warm_wall_s_per_sample"] / baseline["warm_wall_s_per_sample"]))
    table(output / "paired_analytic_ordinary.csv", paired)
    groups = defaultdict(list)
    for row in rows:
        groups[(row["task"], row["mode"], row["domain"], row["batch"], row["family"])].append(row)
    aggregate = []
    for key, members in sorted(groups.items()):
        require(len(members) == 3, "Each condition must retain all three fits")
        value = dict(zip(("task", "mode", "domain", "batch", "family"), key))
        value.update(fitting_seeds=sorted(r["seed"] for r in members),
            mean_accuracy=statistics.mean(r["accuracy"] for r in members),
            mean_cpu_s_per_sample=statistics.mean(r["warm_cpu_s_per_sample"] for r in members),
            mean_wall_s_per_sample=statistics.mean(r["warm_wall_s_per_sample"] for r in members))
        aggregate.append(value)
    for row in aggregate:
        peers = [p for p in aggregate if all(p[k] == row[k] for k in ("task", "mode", "domain", "batch"))]
        row["descriptive_pareto"] = not any(p["mean_accuracy"] >= row["mean_accuracy"] and
            p["mean_cpu_s_per_sample"] <= row["mean_cpu_s_per_sample"] and
            (p["mean_accuracy"] > row["mean_accuracy"] or p["mean_cpu_s_per_sample"] < row["mean_cpu_s_per_sample"])
            for p in peers)
    write(output / "aggregate_quality_cost.json", aggregate)
    summary = dict(workers=len(ledger), model_domain_batch_cells=len(rows),
        historical_predictions_reexecuted=sum(read(output / "workers" / j["worker_id"] / "RESULT.json")["samples"] for j in plan["jobs"]),
        model_fits_reused=96, new_fits=0,
        complete_worker_cpu_seconds=sum(r["cpu_seconds"] for r in ledger),
        complete_worker_wall_seconds=sum(r["wall_seconds"] for r in ledger),
        maximum_worker_rss_bytes=max(r["peak_rss_bytes"] for r in ledger),
        maximum_logit_replay_difference=max(r["historical_max_abs_logit_difference"] for r in rows),
        analytic_slower_cpu_pairs=sum(r["analytic_over_ordinary_cpu"] > 1 for r in paired),
        analytic_comparison_pairs=len(paired),
        energy_joules=None, source_freeze_sha256=sha(output / "SOURCE_FREEZE.json"),
        scope="Descriptive CPU replay of all historical domains and baseline families. No new training, independent quality confirmation, device energy, GPU performance, or unified action/content 2x2 claim.")
    write(output / "SUMMARY.json", summary)
    return summary


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("prepare", "worker", "run", "summarize", "verify"))
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--worker-id")
    parser.add_argument("--workers", nargs="*")
    parser.add_argument("--limit", type=int)
    args = parser.parse_args()
    output = args.output.resolve()
    if args.command == "prepare":
        result = prepare(output)
    elif args.command == "worker":
        result = worker(output, args.worker_id)
    elif args.command == "run":
        result = run(output, args.limit, args.workers)
    elif args.command == "summarize":
        result = summarize(output)
    else:
        result = dict(verified_workers=len(verify(output)["jobs"]))
    print(json.dumps(result, ensure_ascii=False, allow_nan=False), flush=True)


if __name__ == "__main__":
    main()
