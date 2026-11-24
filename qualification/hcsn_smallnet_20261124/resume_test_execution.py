"""Resume only missing sealed test slots after a proven terminated finalizer."""
import time
_ENTRY = time.perf_counter()
import argparse
from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import resource
import subprocess
import sys
import torch
from . import train as t
from . import adaptation_suite as adaptation
from .cost import CostMeter

def read(path):
    return json.loads(Path(path).read_text())

def create(path, value):
    """Publish complete JSON atomically without replacing any existing name."""
    path = Path(path)
    temporary = path.with_name(path.name+".resume.tmp")
    with temporary.open("x") as handle:
        json.dump(value, handle, indent=2, sort_keys=True, allow_nan=False)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.link(temporary, path)
    temporary.unlink()

def existing(p, directory, record):
    path = directory/"test_result.json"
    if not path.exists():
        return None
    row, raw = read(path), read(directory/"test_predictions.json")
    expected = {"attempt": directory.name, "status": "evaluated", "neurons": record["neurons"],
                "arm": record["arm"]["id"], "seed": record["seed"], "selected_step": record["selected_step"]}
    if (any(row.get(k) != v for k, v in expected.items()) or record["status"] != "completed"
            or row["predictions_sha256"] != t.digest(directory/"test_predictions.json")
            or raw["protocol_sha256"] != t.protocol_digest(p) or raw["source_hashes"] != p["source_hashes"]
            or raw["data_sha256"] != row["data_sha256"]):
        raise ValueError("existing complete test identity/hash changed: "+directory.name)
    return row

def worker(args):
    status, error = "failed", None
    directory = args.training/args.attempt
    try:
        p, claim = t.load_protocol(args.manifest), read(args.training/"RESUME_CLAIM.json")
        if (args.attempt not in claim["resumed_names"] or t.protocol_digest(p) != claim["protocol_sha256"]
                or t.digest(__file__) != claim["resume_source_sha256"]
                or t.digest(args.training/"SEAL.json") != claim["training_seal_sha256"]
                or t.digest(args.adaptation_seal) != claim["adaptation_seal_sha256"]
                or t.digest(args.training/"FINAL_CLAIM") != claim["original_final_claim_sha256"]):
            raise ValueError("resume worker does not match its immutable plan")
        record = read(directory/"result.json")
        if (t.digest(directory/"result.json") != claim["training_records"][args.attempt]
                or t.digest(directory/"checkpoint.pt") != record["checkpoint_sha256"]
                or any((directory/name).exists() for name in ("test_result.json", "test_predictions.json"))):
            raise ValueError("worker target is changed or already evaluated")
        create(directory/"RESUME_WORKER_CLAIM.json", {"resume_claim_sha256": t.digest(args.training/"RESUME_CLAIM.json")})
        dtype = torch.float64 if p["precision"] == "float64" else torch.float32
        data = t.make_data("test", per_source=p["data"]["test_per_source"], length=p["data"]["length"], dtype=dtype)
        if data.digest() != claim["test_data_sha256"]:
            raise ValueError("resumed final dataset identity changed")
        meter = CostMeter(scope="one_selected_and_initial_test_evaluation")
        ckpt = torch.load(directory/"checkpoint.pt", map_location="cpu", weights_only=True)
        model = t.SmallHCSN(t.ModelConfig(**ckpt["config"]))
        model.load_state_dict(ckpt["selected_model"])
        metrics, logits, _ = t.evaluate(model, data)
        model.load_state_dict(ckpt["initial_model"])
        initial, initial_logits, _ = t.evaluate(model, data)
        raw = {"ids": data.ids, "labels": data.y.tolist(), "source": data.source.tolist(),
            "prefix_logits": logits.tolist(), "initial_prefix_logits": initial_logits.tolist(),
            "final_logits": logits[-1].tolist(), "initial_margin": data.initial_margin.tolist(),
            "late_step": data.late_step.tolist(), "source_hashes": p["source_hashes"],
            "protocol_sha256": t.protocol_digest(p), "data_sha256": data.digest()}
        create(directory/"test_predictions.json", raw)
        row = {"attempt": args.attempt, "status": "evaluated", "neurons": record["neurons"],
            "arm": record["arm"]["id"], "seed": record["seed"], "metrics": metrics, "initial_metrics": initial,
            "selected_step": record["selected_step"], "data_sha256": data.digest(),
            "predictions_sha256": t.digest(directory/"test_predictions.json"), "cost": meter.snapshot()}
        create(directory/"test_result.json", row)
        status = "completed"
    except Exception as exc:
        error = type(exc).__name__+": "+str(exc)
        raise
    finally:
        create(directory/"resume_worker_cost.json", {"status": status, "error": error,
            "worker_cpu_through_report_seconds": time.process_time(), "worker_wall_including_import_seconds": time.perf_counter()-_ENTRY,
            "process_peak_rss_kib_linux": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss, "energy_joules": None})

def launch(args):
    meter = CostMeter(scope="resume_driver_body_only; child CPU and prior timeout are separate")
    p, ap = t.load_protocol(args.manifest), read(args.adaptation_manifest)
    adaptation.validate_adaptation_protocol(p, ap)
    seal, global_seal, prior = read(args.training/"SEAL.json"), read(args.adaptation_seal), read(args.timeout_receipt)
    if (prior.get("state") != "timed_out" or prior.get("exit_code") != 124
            or seal["protocol_sha256"] != t.protocol_digest(p) or seal["source_hashes"] != p["source_hashes"]
            or (args.training/"FINAL_CLAIM").read_text().strip() != t.digest(args.training/"SEAL.json")
            or (args.training/"FINAL_RESULTS.json").exists()):
        raise ValueError("prior termination, original claim or training seal is invalid")
    records = t.validate_attempts(p, args.training, expected_records=seal["attempts"])
    if (global_seal["adaptation_protocol_sha256"] != t.protocol_digest(ap)
            or set(global_seal["attempts"]) != set(adaptation._expected(p))):
        raise ValueError("global adaptation seal mismatch")
    for name, sha in global_seal["attempts"].items():
        directory = args.adaptation_seal.parent/name
        if t.digest(directory/"SEAL.json") != sha:
            raise ValueError("adaptation seal changed")
        bound = adaptation._validate_attempt(p, ap, directory)
        if records[name][0]["status"] != "completed" or bound["parent_checkpoint_sha256"] != records[name][0]["checkpoint_sha256"]:
            raise ValueError("adaptation parent differs from training selection")
        trained = torch.load(args.training/name/"checkpoint.pt", map_location="cpu", weights_only=True)
        if adaptation.tensor_digest(trained["selected_model"]) != bound["parent_tensor_sha256"]:
            raise ValueError("adaptation parent tensors differ from actual selected training state")
    completed, missing, partials, datasets = {}, [], {}, set()
    for name, (record, _) in records.items():
        directory = args.training/name
        row = existing(p, directory, record)
        if row is not None:
            completed[name] = {file: t.digest(directory/file) for file in ("test_result.json", "test_predictions.json")}
            datasets.add(row["data_sha256"])
        elif record["status"] == "completed":
            missing.append(name)
            partials[name] = {file: t.digest(directory/file) for file in
                ("test_predictions.json", "test_predictions.json.tmp", "test_result.json.tmp") if (directory/file).exists()}
    if len(datasets) != 1 or len(completed) != prior["completed_training_test_cases"] or len(missing) != prior["remaining_training_test_cases"]:
        raise ValueError("resume inventory differs from the terminated-writer receipt")
    plan = {"protocol_sha256": t.protocol_digest(p), "source_hashes": p["source_hashes"],
        "adaptation_source_hashes": ap["source_hashes"], "resume_source_sha256": t.digest(__file__),
        "training_seal_sha256": t.digest(args.training/"SEAL.json"), "adaptation_seal_sha256": t.digest(args.adaptation_seal),
        "original_final_claim_sha256": t.digest(args.training/"FINAL_CLAIM"), "timeout_receipt_sha256": t.digest(args.timeout_receipt),
        "prior_timeout": prior, "completed_before": completed, "completed_before_count": len(completed),
        "resumed_names": missing, "resumed_count": len(missing), "unsealed_partial_sha256": partials,
        "training_records": seal["attempts"], "test_data_sha256": next(iter(datasets)), "workers": args.workers}
    create(args.training/"RESUME_CLAIM.json", plan)
    for name, files in partials.items():
        if files:
            archive = args.training/"unsealed_partial"/name
            archive.mkdir(parents=True, exist_ok=False)
            for file, sha in files.items():
                source = args.training/name/file
                if t.digest(source) != sha:
                    raise ValueError("partial changed after recovery plan")
                source.rename(archive/file)
            create(archive/"PARTIAL_RECEIPT.json", {"original_sha256": files, "reason": "no complete test_result at recovery preflight"})
    def run(name):
        command = [sys.executable, "-m", __package__+".resume_test_execution", "worker", *sys.argv[2:], "--attempt", name]
        started = time.perf_counter()
        row = {"attempt": name, "returncode": None}
        env = dict(os.environ, OMP_NUM_THREADS="1", MKL_NUM_THREADS="1", OPENBLAS_NUM_THREADS="1")
        try:
            with (args.training/(name+".resume.worker.log")).open("x") as log:
                child = subprocess.run(command, env=env, stdout=log, stderr=subprocess.STDOUT, check=False)
            row["returncode"] = child.returncode
        except Exception as exc:
            row["error"] = type(exc).__name__+": "+str(exc)
        finally:
            row["parent_launch_exit_wall_seconds"] = time.perf_counter()-started
            create(args.training/name/"resume_parent_cost.json", row)
            print(json.dumps(row), flush=True)
        return row
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        workers = list(pool.map(run, missing))
    for name, files in completed.items():
        if any(t.digest(args.training/name/file) != sha for file, sha in files.items()):
            raise ValueError("previously completed case was modified")
    children = resource.getrusage(resource.RUSAGE_CHILDREN)
    receipt = {**plan, "workers_finished": workers, "resume_driver_cost": meter.snapshot(),
        "driver_cpu_through_report_seconds": time.process_time(), "child_cpu_including_shutdown_seconds": children.ru_utime+children.ru_stime,
        "driver_wall_including_import_seconds": time.perf_counter()-_ENTRY, "prior_interrupted_worker_complete_cpu_seconds": None,
        "prior_completed_case_costs": {name: read(args.training/name/"test_result.json")["cost"] for name in completed},
        "prior_cpu_note": "Original timeout CPU is incomplete; do not infer from wall or add overlapping adaptation costs.", "energy_joules": None}
    create(args.training/"RESUME_RECEIPT.json", receipt)
    if any(row["returncode"] != 0 for row in workers):
        raise RuntimeError("resumed worker failed; receipt retained, no FINAL_RESULTS published")
    rows = [existing(p, args.training/name, record) if record["status"] == "completed" else
            {"attempt": name, "status": "unavailable", "reason": record["error"]} for name, (record, _) in records.items()]
    if any(row is None or row.get("data_sha256", plan["test_data_sha256"]) != plan["test_data_sha256"] for row in rows):
        raise ValueError("final slot coverage or dataset identity differs")
    create(args.training/"FINAL_RESULTS.json", {"experiment_id": p["experiment_id"], "protocol_sha256": t.protocol_digest(p),
        "seal_sha256": t.digest(args.training/"SEAL.json"), "results": rows, "cost": meter.snapshot(),
        "resume_receipt": {"path": "RESUME_RECEIPT.json", "sha256": t.digest(args.training/"RESUME_RECEIPT.json"),
                           "original_execution": "timed_out exit124; completed rows retained byte-identically"}})
    print(json.dumps({"completed_before": len(completed), "resumed_names": missing, "final_rows": len(rows)}), flush=True)

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("launch", "worker"))
    for name in ("manifest", "training", "adaptation-manifest", "adaptation-seal", "timeout-receipt"):
        parser.add_argument("--"+name, type=Path, required=True)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--attempt")
    args = parser.parse_args()
    if not 1 <= args.workers <= 4:
        parser.error("1..4 fresh workers required")
    torch.set_num_threads(1)
    try:
        (worker if args.action == "worker" else launch)(args)
    except BaseException as exc:
        if args.action == "launch":
            usage = resource.getrusage(resource.RUSAGE_CHILDREN)
            create(args.training/"RESUME_FAILURE.json", {"error": type(exc).__name__+": "+str(exc),
                "source_sha256": t.digest(__file__), "driver_cpu_through_report_seconds": time.process_time(),
                "child_cpu_through_report_seconds": usage.ru_utime+usage.ru_stime,
                "driver_wall_including_import_seconds": time.perf_counter()-_ENTRY})
        raise

if __name__ == "__main__":
    main()
