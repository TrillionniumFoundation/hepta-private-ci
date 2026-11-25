"""New-process forward replay of sealed, already evaluated SmallHCSN models."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import resource
import subprocess
import sys
import time


def encode(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write_new(path, value):
    path = Path(path)
    raw = encode(value) + b"\n"
    with path.open("xb") as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())
    if path.read_bytes() != raw:
        raise ValueError("Replay receipt readback differs")
    return hashlib.sha256(raw).hexdigest()


def common_inputs(args):
    checked = {"protocol": (args.protocol, args.protocol_sha), "seal": (args.seal, args.seal_sha),
               "evaluation": (str(Path(args.evaluation) / "RESULT.json"), args.result_sha),
               "open_receipt": (str(Path(args.evaluation) / "OPEN_RECEIPT.json"), args.open_sha)}
    values = {}
    for name, (path, expected) in checked.items():
        if sha(path) != expected:
            raise ValueError("Frozen replay input changed: " + name)
        values[name] = json.loads(Path(path).read_text())
    protocol, seal, evaluation, opened = (values[k] for k in ("protocol", "seal", "evaluation", "open_receipt"))
    if (seal["protocol_sha256"] != args.protocol_sha or evaluation["protocol_sha256"] != args.protocol_sha
            or opened["protocol_sha256"] != args.protocol_sha or opened["candidate_seal_sha256"] != args.seal_sha
            or evaluation["candidate_freeze_commit"] != args.candidate_commit
            or opened["candidate_freeze_commit"] != args.candidate_commit):
        raise ValueError("Replay is not bound to the published candidate and test opening")
    expected = {(n, s) for n in protocol["widths"] for s in protocol["seeds"]}
    for rows in (seal["rows"], evaluation["rows"]):
        if len(rows) != len(expected) or {(r["width"], r["seed"]) for r in rows} != expected:
            raise ValueError("Frozen replay roster is incomplete")
    return values


def worker(args):
    started = time.perf_counter()
    cpu_start = time.process_time()
    values = common_inputs(args)
    protocol = values["protocol"]
    row = next(r for r in values["evaluation"]["rows"] if (r["width"], r["seed"]) == (args.width, args.seed))
    sealed = next(r for r in values["seal"]["rows"] if (r["width"], r["seed"]) == (args.width, args.seed))
    results = Path(args.results).resolve()
    result_path = (results / sealed["result_relative_path"]).resolve()
    if not result_path.is_relative_to(results) or sha(result_path) != sealed["result_sha256"]:
        raise ValueError("Candidate result changed after sealing")
    result = json.loads(result_path.read_text())
    if (result["solution"]["candidate_sha256"] != row["candidate_sha256"]
            or row["candidate_sha256"] != sealed["candidate_sha256"]
            or hashlib.sha256(encode(result["solution"]["candidate"])).hexdigest() != row["candidate_sha256"]):
        raise ValueError("Candidate content or publication binding differs")
    import_started = time.perf_counter()
    provider = Path(args.provider).resolve()
    sys.path.insert(0, str(provider))
    import features
    import prepare
    if not Path(features.__file__).resolve().is_relative_to(provider) or not Path(prepare.__file__).resolve().is_relative_to(provider):
        raise ValueError("Replay imported a different provider")
    prepare.verify_protocol(args.protocol)
    np, torch = features.np, features.torch
    import_seconds = time.perf_counter() - import_started
    basis_path = Path(args.basis) / f"basis_n{args.width}_s{args.seed}.json"
    outer = json.loads(basis_path.read_text())
    basis = outer["basis"]
    if features.digest(basis) != outer["coordinates_sha256"] or result["header"]["coordinates"] != outer["coordinates_sha256"]:
        raise ValueError("Replay uses different frozen feature coordinates")
    model_started = time.perf_counter()
    model, physical = features.load_model(args.capsule, args.width, args.seed)
    if physical != basis["physical_model"]:
        raise ValueError("Physical initialization differs from the sealed basis")
    protected = {name: value.clone() for name, value in model.state_dict().items() if not name.startswith("readout.")}
    checkpoint_path = Path(args.evaluation) / f"adopted_n{args.width}_s{args.seed}.pt"
    if sha(checkpoint_path) != row["saved_model_sha256"] or checkpoint_path.stat().st_size != row["saved_model_bytes"]:
        raise ValueError("Evaluated model file changed")
    checkpoint = torch.load(checkpoint_path, map_location="cpu", weights_only=True)
    if checkpoint["candidate_sha256"] != row["candidate_sha256"] or checkpoint["config"] != physical["config"]:
        raise ValueError("Saved model metadata differs")
    model.load_state_dict(checkpoint["state_dict"], strict=True)
    if any(not torch.equal(value, model.state_dict()[name]) for name, value in protected.items()):
        raise ValueError("Saved readout model changed the frozen physical field")
    candidate = np.asarray(result["solution"]["candidate"])
    raw_weight = candidate[:-1] / np.asarray(basis["scale"])
    raw_bias = candidate[-1] - np.asarray(basis["mean"]) @ raw_weight
    expected_weight = torch.tensor(np.stack((-raw_weight / 2, raw_weight / 2)), dtype=torch.float64)
    expected_bias = torch.tensor([-raw_bias / 2, raw_bias / 2], dtype=torch.float64)
    head_exact = torch.equal(model.readout.weight, expected_weight) and torch.equal(model.readout.bias, expected_bias)
    if not head_exact:
        raise ValueError("Saved readout is not the sealed candidate installation")
    load_seconds = time.perf_counter() - model_started
    test_rows = []
    for node, original in zip(features.NODES, row["test"]):
        tick = time.perf_counter()
        batch = features.corpus("test", node, args.seed, 0, protocol["test_per_node"])
        test_sha = features.array_hash(batch["x"], batch["margin"], batch["y"])
        if test_sha != original["test_sha256"] or batch["source"] != original["test_source"]:
            raise ValueError("Recreated test is not the previously opened test")
        values, diagnostic = features.extract(model, batch)
        prediction = np.asarray(diagnostic["model_logit_margin"])
        prediction_path = Path(args.evaluation) / f"predictions_n{args.width}_s{args.seed}_{node}.npz"
        with np.load(prediction_path, allow_pickle=False) as saved:
            prediction_exact = np.array_equal(prediction, saved["prediction"])
            labels_exact = np.array_equal(batch["y"], saved["target"])
            expected = features.coordinates(values, basis) @ candidate
            expected_exact = np.array_equal(expected, saved["expected"])
            difference = float(np.max(np.abs(prediction - saved["prediction"])))
            realization_error = float(np.max(np.abs(prediction - expected)))
        if not prediction_exact or not labels_exact or not expected_exact or realization_error > protocol["head_realization_tolerance"]:
            raise ValueError("Fresh-process predictions differ from evaluated artifacts")
        test_rows.append({"node_partition": node, "test_sha256": test_sha, "source": batch["source"],
                          "prediction_file_sha256": sha(prediction_path), "predictions_exact": prediction_exact,
                          "labels_exact": labels_exact, "coordinate_predictions_exact": expected_exact,
                          "prediction_max_abs_difference": difference, "head_realization_max_abs_error": realization_error,
                          "count": len(prediction), "wall_seconds": time.perf_counter() - tick,
                          "forward_seconds": diagnostic["wall_s"], "mass_error": diagnostic["mass_error"],
                          "mark_excess": diagnostic["mark_excess"]})
    if len(test_rows) != 2 or any(not torch.equal(value, model.state_dict()[name]) for name, value in protected.items()):
        raise ValueError("Replay changed physical parameters or omitted a partition")
    usage = resource.getrusage(resource.RUSAGE_SELF)
    report = {"record_kind": "actual_hcsn_fresh_process_forward_replay", "schema_version": 1,
              "width": args.width, "seed": args.seed, "pid": os.getpid(), "parent_pid": os.getppid(),
              "source_sha256": sha(__file__), "source_freeze_commit": args.source_commit,
              "protocol_sha256": args.protocol_sha, "candidate_freeze_commit": args.candidate_commit,
              "evaluation_result_sha256": args.result_sha, "open_receipt_sha256": args.open_sha,
              "candidate_seal_sha256": args.seal_sha, "candidate_sha256": row["candidate_sha256"],
              "model_file_sha256": sha(checkpoint_path), "basis_file_sha256": sha(basis_path),
              "physical_parent_state_sha256": physical["state_sha256"], "physical_parameters_exact_before_and_after": True,
              "protected_tensor_count": len(protected), "installed_head_exact": head_exact, "test": test_rows,
              "provider_import_seconds": import_seconds, "model_create_and_load_seconds": load_seconds,
              "worker_wall_seconds": time.perf_counter() - started, "worker_cpu_seconds": time.process_time() - cpu_start,
              "process_cpu_user_seconds": usage.ru_utime, "process_cpu_system_seconds": usage.ru_stime,
              "max_rss_kib": usage.ru_maxrss, "passed": True, "training_or_parameter_tuning": False,
              "native_daemon_or_real_user_adoption": False}
    write_new(Path(args.output) / f"replay_n{args.width}_s{args.seed}.json", report)
    print(json.dumps({"width": args.width, "seed": args.seed, "pid": os.getpid(), "passed": True}), flush=True)


def supervise(args):
    started = time.perf_counter()
    values = common_inputs(args)
    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=False)
    private = output / "private"
    private.mkdir()
    rows = []
    for row in values["evaluation"]["rows"]:
        argv = [sys.executable, str(Path(__file__).resolve()), *sys.argv[1:], "--worker", "--width", str(row["width"]), "--seed", str(row["seed"])]
        tick = time.perf_counter()
        cpu = resource.getrusage(resource.RUSAGE_CHILDREN)
        completed = subprocess.run(argv, capture_output=True, text=True, timeout=180)
        elapsed = time.perf_counter() - tick
        after = resource.getrusage(resource.RUSAGE_CHILDREN)
        log = private / f"worker_n{row['width']}_s{row['seed']}.json"
        write_new(log, {"exit_code": completed.returncode, "stdout": completed.stdout, "stderr": completed.stderr})
        if completed.returncode != 0:
            write_new(output / "failure.json", {"width": row["width"], "seed": row["seed"], "exit_code": completed.returncode,
                      "source_sha256": sha(__file__), "log_sha256": sha(log), "completed": len(rows)})
            raise RuntimeError("Fresh-process replay failed; exact private logs retained")
        path = output / f"replay_n{row['width']}_s{row['seed']}.json"
        record = json.loads(path.read_text())
        if not record["passed"] or record["pid"] == os.getpid() or record["source_sha256"] != sha(__file__):
            raise ValueError("Invalid fresh-process receipt")
        rows.append({"width": row["width"], "seed": row["seed"], "pid": record["pid"],
                     "receipt_sha256": sha(path), "receipt_bytes": path.stat().st_size, "exit_code": completed.returncode,
                     "complete_process_wall_seconds": elapsed, "complete_process_cpu_seconds": after.ru_utime + after.ru_stime - cpu.ru_utime - cpu.ru_stime})
        print(json.dumps(rows[-1]), flush=True)
    if len({row["pid"] for row in rows}) != len(rows):
        raise ValueError("Expected a different fresh process for every model")
    report = {"record_kind": "actual_hcsn_fresh_process_replay_supervisor", "schema_version": 1,
              "source_sha256": sha(__file__), "source_freeze_commit": args.source_commit, "pid": os.getpid(),
              "candidate_freeze_commit": args.candidate_commit, "candidate_seal_sha256": args.seal_sha,
              "evaluation_result_sha256": args.result_sha, "open_receipt_sha256": args.open_sha,
              "protocol_sha256": args.protocol_sha, "fresh_processes": len(rows), "test_partitions": 2 * len(rows),
              "rows": rows, "all_passed": True, "total_wall_seconds": time.perf_counter() - started,
              "total_child_cpu_seconds": sum(row["complete_process_cpu_seconds"] for row in rows),
              "scope": "Read-only fresh-process reload and forward replay of already opened test inputs; no training, tuning, native daemon, or real-user adoption."}
    write_new(output / "RESULT.json", report)
    print(json.dumps({"fresh_processes": len(rows), "all_passed": True, "total_wall_seconds": report["total_wall_seconds"], "result_sha256": sha(output / "RESULT.json")}), flush=True)


def arguments():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("provider", "capsule", "basis", "protocol", "seal", "results", "evaluation", "output", "source-commit", "candidate-commit", "protocol-sha", "seal-sha", "result-sha", "open-sha"):
        parser.add_argument("--" + name, required=True)
    parser.add_argument("--worker", action="store_true")
    parser.add_argument("--width", type=int)
    parser.add_argument("--seed", type=int)
    return parser.parse_args()


if __name__ == "__main__":
    args = arguments()
    worker(args) if args.worker else supervise(args)
