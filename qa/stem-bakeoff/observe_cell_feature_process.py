"""Linux wait4 observer for one pinned generic complete-source exporter process.

CPU is the sum of disjoint child user/system and parent process measurements.
The inclusive interval contains exporter startup, encoding, serialization and
final pin checks; observer startup and final cost-receipt serialization are out.
"""

import argparse
import datetime
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time


def file_sha(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def write_json(path, value):
    with path.open("x") as stream:
        json.dump(value, stream, sort_keys=True, indent=2)
        stream.write("\n")


def observe(plan_path, expected_plan_sha256):
    began_wall, began_cpu = time.perf_counter_ns(), time.process_time_ns()
    if sys.platform != "linux" or not hasattr(os, "wait4"):
        raise ValueError("this process-cost observer requires Linux wait4 accounting")
    plan_path = Path(plan_path)
    raw = plan_path.read_bytes()
    if len(raw) > 131072 or hashlib.sha256(raw).hexdigest() != expected_plan_sha256:
        raise ValueError("execution plan differs from its explicit pin")
    plan = json.loads(raw)
    command, code_root = plan["command"], Path(__file__).resolve().parent
    flags = {"--candidate", "--dataset", "--snapshot", "--acquisition", "--output",
             "--batch-size", "--threads"}
    if (not isinstance(command, list) or len(command) != 16
            or any(type(value) is not str or not value for value in command)
            or command[1] != "generic_dataset_features.py"
            or set(command[2::2]) != flags
            or Path(plan["cwd"]).resolve() != code_root
            or not Path(command[0]).is_absolute() or not Path(command[0]).is_file()):
        raise ValueError("only one explicitly pinned generic feature exporter is supported")
    args = dict(zip(command[2::2], command[3::2], strict=True))
    if (args["--candidate"] not in ("granite97m", "embeddinggemma2_740m")
            or args["--batch-size"] != str(plan["policy"]["batch_size"])
            or args["--threads"] != str(plan["policy"]["threads"])):
        raise ValueError("exporter command differs from declared resource policy")
    dataset, acquisition, output = map(Path, (args["--dataset"], args["--acquisition"], args["--output"]))
    prefix = output.parent / output.name
    paths = {name: Path(str(prefix) + suffix) for name, suffix in (
        ("cost", "-process-cost.json"), ("log", "-progress.log"), ("start", "-process-start.json"))}
    if output.exists() or any(path.exists() for path in paths.values()):
        raise ValueError("each observed acquisition requires fresh output and receipts")
    observer_sha = file_sha(__file__)
    pins = {dataset: plan["dataset_sha256"], acquisition: plan["acquisition_sha256"],
            plan_path: expected_plan_sha256, Path(__file__).resolve(): observer_sha}
    for name, expected in plan["source_code_sha256"].items():
        if Path(name).name != name or not name.endswith(".py"):
            raise ValueError("source pins must name sibling Python modules")
        pins[code_root / name] = expected
    for path, expected in pins.items():
        if file_sha(path) != expected:
            raise ValueError("input or source differs before launch: " + str(path))
    environment = plan["environment"]
    if environment != {"OMP_NUM_THREADS": "1", "MKL_NUM_THREADS": "1",
                       "OPENBLAS_NUM_THREADS": "1", "TOKENIZERS_PARALLELISM": "false"}:
        raise ValueError("explicit bounded process environment required")
    env = dict(os.environ)
    env.update(environment)
    launch_wall = time.perf_counter_ns()
    with paths["log"].open("xb") as log:
        process = subprocess.Popen(command, cwd=code_root, env=env, stdout=log, stderr=subprocess.STDOUT)
        write_json(paths["start"], {
            "schema": "hepta.feature-process-start.v1", "pid": process.pid, "parent_pid": os.getpid(),
            "started_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "launch_plan_sha256": expected_plan_sha256, "dataset_sha256": plan["dataset_sha256"],
            "observer_source_sha256": observer_sha, "output": str(output)})
        print(json.dumps({"child_pid": process.pid, "output": str(output),
                          "expected_forwards": plan["expected_forwards"]}), flush=True)
        _pid, status, usage = os.wait4(process.pid, 0)
        child_exit_wall = time.perf_counter_ns()
        process.returncode = os.waitstatus_to_exitcode(status)
    errors, actual = [], {}
    report_sha = manifest_sha = None
    if process.returncode != 0:
        errors.append("exporter exit status was nonzero")
    try:
        for path, expected in pins.items():
            if file_sha(path) != expected:
                errors.append("input or source changed: " + str(path))
        report_raw = (output / "report.json").read_bytes()
        manifest_raw = (output / "manifest.json").read_bytes()
        report_sha = hashlib.sha256(report_raw).hexdigest()
        manifest_sha = hashlib.sha256(manifest_raw).hexdigest()
        report, manifest = json.loads(report_raw), json.loads(manifest_raw)
        if manifest["report.json"] != {"sha256": report_sha, "bytes": len(report_raw)}:
            errors.append("final manifest does not bind the captured report bytes")
        actual = {"physical_forwards": report["encoding"]["physical_forward_calls"],
                  "chunks": report["encoding"]["chunks"], "documents": report["feature_shape"][0],
                  "feature_shape": report["feature_shape"], "feature_identity": report["feature_identity"]}
        if (actual["physical_forwards"] != plan["expected_forwards"]
                or actual["chunks"] != plan["expected_chunks"] or actual["documents"] != plan["rows"]
                or report["plan"]["dataset_sha256"] != plan["dataset_sha256"]):
            errors.append("final count or dataset binding differs from the frozen launch plan")
    except (OSError, ValueError, KeyError, TypeError) as error:
        errors.append(type(error).__name__ + ": " + str(error)[:500])
    log_sha, start_sha = file_sha(paths["log"]), file_sha(paths["start"])
    child_user, child_system = round(usage.ru_utime * 1e9), round(usage.ru_stime * 1e9)
    parent_cpu = time.process_time_ns() - began_cpu
    receipt = {"schema": "hepta.feature-inclusive-process-cost.v1",
        "launch_plan_sha256": expected_plan_sha256, "dataset_sha256": plan["dataset_sha256"],
        "observer_source_sha256": observer_sha,
        "feature_report_sha256": report_sha, "feature_manifest_sha256": manifest_sha,
        "progress_log_sha256": log_sha, "start_receipt_sha256": start_sha,
        "exit_code": process.returncode, "completed": not errors, "verification_errors": errors,
        "observed_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "child_wall_ns": child_exit_wall - launch_wall,
        "child_user_cpu_ns": child_user, "child_system_cpu_ns": child_system,
        "child_cpu_ns": child_user + child_system, "parent_cpu_ns": parent_cpu,
        "total_cpu_ns": child_user + child_system + parent_cpu,
        "inclusive_wall_ns": time.perf_counter_ns() - began_wall,
        "child_peak_rss_bytes": usage.ru_maxrss * 1024, "actual": actual,
        "cpu_measurement": "child wait4 user+system CPU plus disjoint parent process_time_ns",
        "scope": "parent preflight, exporter interpreter/model startup, all planning/encoding/serialization "
                 "through child exit and final input/source/report pin verification; excludes observer "
                 "interpreter initialization and final process-cost receipt serialization; "
                 "do not add nested load/planning/encoding observations"}
    write_json(paths["cost"], receipt)
    print(json.dumps(receipt, sort_keys=True), flush=True)
    return receipt


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", required=True)
    parser.add_argument("--expected-plan-sha256", required=True)
    options = parser.parse_args()
    result = observe(options.plan, options.expected_plan_sha256)
    sys.exit(0 if result["completed"] else 1)
