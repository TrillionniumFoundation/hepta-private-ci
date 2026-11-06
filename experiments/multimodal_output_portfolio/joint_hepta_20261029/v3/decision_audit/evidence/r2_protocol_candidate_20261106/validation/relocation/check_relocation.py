"""Linux-only receipt for moving unchanged protocol tools; no study execution."""

import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import platform
import resource
import subprocess
import sys
import time

import numpy as np


ROOT = Path(__file__).resolve().parents[2]


def identity(path):
    raw = path.read_bytes()
    return {"bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--outputs", type=Path, required=True)
    parser.add_argument("--receipts", type=Path, required=True)
    args = parser.parse_args()
    args.outputs.mkdir(parents=True, exist_ok=False)
    args.receipts.mkdir(parents=True, exist_ok=False)
    started_wall, started_cpu = time.perf_counter(), time.process_time()
    preservation = json.loads((ROOT / "PRESERVATION.json").read_bytes())
    report = {"schema": "hepta.r2.protocol-relocation-check.v1",
              "started_at": datetime.now(timezone.utc).isoformat(),
              "purpose": "Unchanged-file relocation only; no model, labels or study execution",
              "python": sys.version, "numpy": np.__version__, "platform": platform.platform(),
              "launcher": identity(Path(__file__)), "preservation": identity(ROOT / "PRESERVATION.json"),
              "commands": [], "status": "failed", "model_calls": 0, "training_calls": 0,
              "real_evaluation_calls": 0, "bootstrap_replicates_executed": 0,
              "test_dispatch_allowed": False, "no_update": True}

    def verify_copies():
        for row in preservation["files"]:
            assert identity(ROOT / row["path"]) == {"bytes": row["bytes"], "sha256": row["sha256"]}, row["path"]

    def run(name, expected_exit):
        output = args.outputs / (name + ".json")
        argv = [sys.executable, "-B", str(ROOT / (name + ".py")), "--output", str(output)]
        before = resource.getrusage(resource.RUSAGE_CHILDREN)
        start = time.perf_counter()
        command = {"argv": argv, "cwd": str(args.outputs), "expected_exit": expected_exit}
        report["commands"].append(command)
        try:
            result = subprocess.run(argv, cwd=args.outputs, capture_output=True, timeout=30)
            command["exit_code"] = result.returncode
            for kind, data in (("stdout", result.stdout), ("stderr", result.stderr)):
                path = args.receipts / (name + "." + kind)
                with path.open("xb") as stream:
                    stream.write(data)
                command[kind] = {"path": path.name, **identity(path)}
            assert result.returncode == expected_exit, command
            command["output"] = {"path": str(output), **identity(output)}
            return json.loads(output.read_bytes())
        finally:
            after = resource.getrusage(resource.RUSAGE_CHILDREN)
            command["whole_child_wall_seconds"] = time.perf_counter() - start
            command["whole_child_cpu_seconds"] = after.ru_utime + after.ru_stime - before.ru_utime - before.ru_stime

    try:
        assert sys.platform == "linux", "This validation receipt uses Linux child accounting"
        verify_copies()
        plan = run("compile_contracts", 0)
        rows = plan["fit_arm_rows"]
        assert len(rows) == 128 and Counter(x["arm"] for x in rows) == {"00": 32, "10": 32, "01": 32, "11": 32}
        assert all(x["execution_state"] == "NOT_RUN" and x["training_callable"] is None and x["checkpoint_sha256"] is None for x in rows)
        assert plan["status"] == "PLAN_ONLY_NOT_RUN" and plan["dispatch_allowed"] is False
        report["plan_summary"] = {"fit_arm_rows": len(rows), "arm_counts": dict(Counter(x["arm"] for x in rows)),
                                  "all_not_run": True, "all_training_and_checkpoint_bindings_null": True,
                                  "methods": plan["methods"], "dispatch_allowed": False}
        readiness = run("check_readiness", 2)
        assert readiness["status"] == "BLOCKED" and len(readiness["open_gates"]) == 6
        assert all(readiness[k] is False for k in ("test_dispatch_allowed", "training_started", "model_update_allowed"))
        report["readiness"] = readiness
        verify_copies()
        report["all_preserved_files_unchanged_before_and_after"] = True
        report["status"] = "passed_relocation_only"
    except (Exception, KeyboardInterrupt) as exc:
        report["error"] = {"type": type(exc).__name__, "message": str(exc)}
    finally:
        report["finished_at"] = datetime.now(timezone.utc).isoformat()
        report["costs"] = {"nonoverlapping_child_cpu_seconds": sum(c["whole_child_cpu_seconds"] for c in report["commands"]),
                           "sequential_child_wall_seconds": sum(c["whole_child_wall_seconds"] for c in report["commands"]),
                           "wrapper_interval_wall_seconds": time.perf_counter() - started_wall,
                           "wrapper_own_interval_cpu_seconds": time.process_time() - started_cpu,
                           "scope": "Whole CLI children; wrapper interval excludes imports and final receipt write. Do not add nested wall intervals.",
                           "peak_rss_bytes": None, "energy_joules": None, "physical_io_bytes": None,
                           "network_bytes": None, "original_execution_cost": None, "authoring_and_publication_cost": None}
        with (args.receipts / "EXECUTION.json").open("x") as out:
            json.dump(report, out, indent=2, allow_nan=False)
            out.write("\n")
    print(json.dumps({"status": report["status"], "receipt": str(args.receipts / "EXECUTION.json"), "costs": report["costs"]}))
    return 0 if report["status"] == "passed_relocation_only" else 1


if __name__ == "__main__":
    raise SystemExit(main())
