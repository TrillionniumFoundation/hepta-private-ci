"""Independent retained-result accounting, without importing replay/model code."""

import argparse
from collections import defaultdict
import csv
import hashlib
import json
import math
from pathlib import Path
import statistics
import time

import numpy as np


REPO = Path(__file__).resolve().parents[3]
HISTORY = REPO / "experiments/hcsn_validation_r12_20261031/content/results/formal001"


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def read(path):
    return json.loads(Path(path).read_text())


def require(value, message):
    if not value:
        raise ValueError(message)


def close(actual, expected, message):
    require(math.isclose(float(actual), float(expected), rel_tol=1e-12, abs_tol=1e-10), message)


def csv_rows(path):
    with path.open(newline="") as stream:
        return list(csv.DictReader(stream))


def audit(output):
    started = time.process_time()
    require(not (output / "INDEPENDENT_AUDIT.json").exists(), "Do not overwrite an audit")
    plan, frozen = read(output / "PROTOCOL.json"), read(output / "SOURCE_FREEZE.json")
    require(digest(output / "PROTOCOL.json") == frozen["protocol_sha256"], "Protocol hash")
    require(digest(output / "INPUT_MANIFEST.json") == frozen["input_manifest_sha256"], "Input manifest hash")
    for name, sha in frozen["files"].items():
        require(digest(REPO / name) == sha, "Scientific source identity: " + name)
    for name, sha in read(output / "INPUT_MANIFEST.json")["files"].items():
        require(digest(REPO / name) == sha, "Historical input identity: " + name)
    expected = {(j["id"], d) for j in read(HISTORY / "PROTOCOL.json")["jobs"] if j["kind"] == "fit"
                for d in read(HISTORY / "PROTOCOL.json")["domains"][j["task"]]}
    require({(j["id"], j["domain"]) for j in plan["jobs"]} == expected and len(plan["jobs"]) == len(expected),
            "Full historical matrix coverage")
    training = defaultdict(float)
    for path in (HISTORY / "process_receipts/worker").glob("*.json"):
        receipt = read(path)
        require(digest(path.with_suffix(".log")) == receipt["log_sha256"], "Historical receipt log")
        argv = receipt["command"]
        training[argv[argv.index("--job") + 1]] += receipt["cpu_seconds"]
    indexed, totals, max_difference, observations = {}, [], 0., 0
    for job in plan["jobs"]:
        result_path = output / "workers" / job["worker_id"] / "RESULT.json"
        record = read(result_path)
        receipt_path = output / "receipts" / (job["worker_id"] + ".json")
        receipt = read(receipt_path)
        require(receipt["returncode"] == 0 and digest(result_path) == receipt["result_sha256"], "Worker result identity")
        require(digest(receipt_path.with_suffix(".log")) == receipt["log_sha256"], "Worker log identity")
        require(record["job"] == job, "Worker job")
        require(record["runtime"]["threads"] == 1 and record["runtime"]["compute_device"] == "cpu", "CPU configuration")
        require(receipt["energy_joules"] is None and record["energy_joules"] is None, "Unknown energy must not become zero")
        prediction_path = result_path.parent / "predictions.npz"
        require(digest(prediction_path) == record["predictions_sha256"], "Prediction identity")
        with np.load(prediction_path, allow_pickle=False) as prediction, np.load(
                HISTORY / "heldout" / job["id"] / (job["domain"] + ".npz"), allow_pickle=False) as original:
            x, y, reference = prediction["logits"], prediction["labels"], original["logits"]
            require(np.isfinite(x).all() and np.array_equal(y, original["labels"]), "Prediction finiteness/labels")
            require(np.allclose(x, reference, atol=1e-6, rtol=1e-5), "Historical logits")
            require(np.array_equal(x.argmax(1), reference.argmax(1)), "Historical classes")
            require(str(prediction["input_sha256"]) == str(original["input_sha256"]) == record["input_sha256"], "Input identity")
            accuracy = float(np.mean(np.argmax(x, axis=1) == y))
            close(accuracy, record["accuracy"], "Accuracy recomputation")
            difference = float(np.max(np.abs(x - reference)))
            close(difference, record["historical_max_abs_logit_difference"], "Logit difference")
            max_difference = max(max_difference, difference)
            observations += len(y)
        totals.append(receipt)
        require({r["batch"] for r in record["measurements"]} == {1, 32}, "Batch coverage")
        for metric in record["measurements"]:
            batch = metric["batch"]
            require(len(metric["warm"]) == plan["repetitions"], "Repeat count")
            require(all(r["cpu_ns"] > 0 and r["wall_ns"] > 0 for r in metric["warm"]), "Nonpositive timing")
            require(metric["first_call"]["process_first_model_call"] == (batch == 1), "Cold label")
            require(metric["full_survival_distribution_bytes"] is None and metric["native_working_memory_peak_bytes"] is None,
                    "Unsupported memory claim")
            require(metric["returned_state_history_bytes"] == batch * record["steps"] * 16 * 4, "Actual returned state tensor size")
            calls = metric["selected_function_calls"]["log_ndtr"]
            expected_calls = record["steps"] * (2 if job["family"] == "analytic" else 1 if job["family"] == "probit" else 0)
            require(calls["calls"] == expected_calls, "Observed log_ndtr count")
            key = (job["task"], job["mode"], job["family"], job["seed"], job["domain"], batch)
            indexed[key] = dict(accuracy=accuracy,
                cpu=statistics.median(r["cpu_ns"] for r in metric["warm"]) / 1e9 / batch,
                wall=statistics.median(r["wall_ns"] for r in metric["warm"]) / 1e9 / batch,
                train=training[job["id"]] + training[job["donor"]])
    rows = csv_rows(output / "per_seed_quality_cost.csv")
    require(len(rows) == len(indexed), "Per-seed CSV count")
    require({(r["task"], r["mode"], r["family"], int(r["seed"]), r["domain"], int(r["batch"])) for r in rows}
            == set(indexed), "Per-seed unique coverage")
    for row in rows:
        key = (row["task"], row["mode"], row["family"], int(row["seed"]), row["domain"], int(row["batch"]))
        data = indexed[key]
        for field, reference in (("accuracy", "accuracy"), ("warm_cpu_s_per_sample", "cpu"),
                                 ("warm_wall_s_per_sample", "wall"), ("historical_pipeline_training_cpu_s", "train")):
            close(row[field], data[reference], "Per-seed aggregation: " + field)
    grouped = defaultdict(list)
    for key, row in indexed.items():
        grouped[(key[0], key[1], key[4], key[5], key[2])].append(row)
    aggregate = read(output / "aggregate_quality_cost.json")
    require(len(aggregate) == len(grouped), "Aggregate count")
    require({(r["task"], r["mode"], r["domain"], r["batch"], r["family"]) for r in aggregate} == set(grouped),
            "Aggregate unique coverage")
    for row in aggregate:
        group = grouped[(row["task"], row["mode"], row["domain"], row["batch"], row["family"])]
        require(len(group) == 3, "Exactly three historical fitting seeds")
        for field, reference in (("mean_accuracy", "accuracy"), ("mean_cpu_s_per_sample", "cpu"), ("mean_wall_s_per_sample", "wall")):
            close(row[field], statistics.mean(r[reference] for r in group), "Aggregate mean")
        peers = [p for p in aggregate if all(p[k] == row[k] for k in ("task", "mode", "domain", "batch"))]
        dominated = any(p["mean_accuracy"] >= row["mean_accuracy"] and p["mean_cpu_s_per_sample"] <= row["mean_cpu_s_per_sample"]
                        and (p["mean_accuracy"] > row["mean_accuracy"] or p["mean_cpu_s_per_sample"] < row["mean_cpu_s_per_sample"])
                        for p in peers)
        require(row["descriptive_pareto"] == (not dominated), "Descriptive Pareto arithmetic")
    paired = csv_rows(output / "paired_analytic_ordinary.csv")
    require(len(paired) == sum(key[2] == "analytic" for key in indexed), "Paired coverage")
    require({(r["task"], r["mode"], "analytic", int(r["seed"]), r["domain"], int(r["batch"])) for r in paired}
            == {k for k in indexed if k[2] == "analytic"}, "Paired unique coverage")
    for row in paired:
        prefix = (row["task"], row["mode"])
        suffix = (int(row["seed"]), row["domain"], int(row["batch"]))
        analytic = indexed[prefix + ("analytic",) + suffix]
        ordinary = indexed[prefix + ("ordinary_dual",) + suffix]
        close(row["analytic_minus_ordinary_accuracy"], analytic["accuracy"] - ordinary["accuracy"], "Paired quality")
        close(row["analytic_over_ordinary_cpu"], analytic["cpu"] / ordinary["cpu"], "Paired CPU")
        close(row["analytic_over_ordinary_wall"], analytic["wall"] / ordinary["wall"], "Paired wall")
    amort = csv_rows(output / "training_amortization.csv")
    require(len(amort) == sum(sum(n >= key[-1] and n % key[-1] == 0 for n in plan["requests"]) for key in indexed), "Amortization coverage")
    require({(r["task"], r["mode"], r["family"], int(r["seed"]), r["domain"], int(r["batch"]), int(r["requests"])) for r in amort}
            == {k + (n,) for k in indexed for n in plan["requests"] if n >= k[-1] and n % k[-1] == 0},
            "Amortization unique coverage")
    for row in amort:
        key = (row["task"], row["mode"], row["family"], int(row["seed"]), row["domain"], int(row["batch"]))
        n, batch = int(row["requests"]), int(row["batch"])
        require(n >= batch and n % batch == 0 and int(row["complete_batches"]) == n // batch, "Incomplete-batch amortization")
        close(row["cpu_s_per_request"], indexed[key]["train"] / n + indexed[key]["cpu"], "Amortized actual cost")
    summary = read(output / "SUMMARY.json")
    for field, reference in (("complete_worker_cpu_seconds", "cpu_seconds"), ("complete_worker_wall_seconds", "wall_seconds")):
        close(summary[field], sum(r[reference] for r in totals), "Complete process sum")
    require(summary["historical_predictions_reexecuted"] == observations and summary["new_fits"] == 0, "Replay scope")
    development = {}
    for directory in sorted(output.parent.glob("development_*")):
        development[directory.name] = sum(read(p)["cpu_seconds"] for p in (directory / "receipts").glob("*.json"))
    result = dict(passed=True, scientific_workers=len(totals), prediction_rows=observations,
        per_seed_cells=len(indexed), aggregate_cells=len(grouped), amortization_cells=len(amort),
        maximum_logit_replay_difference=max_difference, development_cpu_seconds=development,
        formal_complete_worker_cpu_seconds=summary["complete_worker_cpu_seconds"],
        audit_body_cpu_seconds=time.process_time() - started, auditor_sha256=digest(__file__),
        protocol_sha256=digest(output / "PROTOCOL.json"),
        scope="Independent retained-data arithmetic and identity audit; no model/replay module imported. Does not establish new quality, representative service latency, device energy, or optimized GPU performance.",
        timing_scope="Warm repeats use the fixed first 1/32 inputs per domain; shape/dt is identical across that domain and models have no input-dependent early exit. The 256 prediction rows are quality replay, not 256 separately timed requests.",
        amortization_scope="Historical training plus current inference is a cross-period ledger scenario. Original training was not rerun, and identical CPU/host conditions are not pinned by the original receipts. Matching tensor-runtime versions does not establish same-hardware from-scratch end-to-end training/deployment cost.",
        full_cost_scope="Formal-worker total excludes development, this audit, plots, packaging, parent overhead and environment installation. These are not silently folded into request-level deployment cost.")
    with (output / "INDEPENDENT_AUDIT.json").open("x") as stream:
        json.dump(result, stream, indent=2, sort_keys=True)
        stream.write("\n")
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True, type=Path)
    print(json.dumps(audit(parser.parse_args().output.resolve()), sort_keys=True))
